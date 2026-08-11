"""catastro-mcp: servidor MCP para el Catastro español.

Diseño (medido en la sesión de la herencia, 11/08/2026):
- La caché es el diseño, no una optimización: responde desde disco por defecto.
- El limitador cuenta el TOTAL diario por host, no solo el ritmo.
- "No existe" y "no puedo" se distinguen con canario (catastro_estado).
- La superficie manda desde el areaValue del GML; ninguna otra fuente la pisa.
"""
import difflib
import math

from mcp.server import MCPServer
from shapely import wkt as shapely_wkt
from shapely.geometry import Point
from shapely.strtree import STRtree

from . import inspire, ovc, sede
from .cache import conectar
from .limiter import LIMITADOR, TECHO_DIARIO

mcp = MCPServer("catastro")


def _rc14(rc: str) -> str:
    rc = rc.strip().upper()
    return rc[:14]


def _fila_parcela(rc: str):
    con = conectar()
    try:
        return con.execute("SELECT * FROM parcelas WHERE rc14=?", (_rc14(rc),)).fetchone()
    finally:
        con.close()


# ---------- Sin red (caché local) ----------

@mcp.tool()
def catastro_descargar_municipio(provincia: str, municipio: str) -> dict:
    """Baja el parcelario INSPIRE completo del municipio (GML oficial, sin límite) y
    construye la caché local. Operación fundacional: el resto de herramientas la dan
    por hecha. provincia y municipio son códigos numéricos (ej. '15', '15053' o el
    código que use el feed; para Muxía: provincia='15', municipio='15053').
    Cualquier operación sobre más de ~20 parcelas se resuelve aquí, nunca una a una."""
    return inspire.descargar_municipio(provincia, municipio)


@mcp.tool()
def catastro_parcela_local(rc: str) -> dict:
    """Superficie oficial (areaValue del GML), centroide y geometría de una parcela,
    desde la caché local, sin red. rc: referencia de 14 o 20 caracteres."""
    row = _fila_parcela(rc)
    if row is None:
        return {"error": f"RC {_rc14(rc)} no está en la caché. "
                         "Ejecuta antes catastro_descargar_municipio."}
    con = conectar()
    try:
        ficha = con.execute("SELECT * FROM fichas WHERE rc14=?", (row["rc14"],)).fetchone()
    finally:
        con.close()
    out = {
        "rc14": row["rc14"],
        "superficie_m2": row["area_m2"],   # fuente: GML INSPIRE. Ninguna otra la pisa.
        "centroide_25829": [row["cx"], row["cy"]],
        "wkt": row["wkt"],
    }
    if ficha:
        out["paraje"] = ficha["paraje"]
        out["clase"] = ficha["clase"]
        out["uso"] = ficha["uso"]
        out["rc20"] = ficha["rc20"]
    return out


@mcp.tool()
def catastro_vecinas(rc: str, contacto_max: float = 3.0) -> list[dict]:
    """Parcelas que tocan (o quedan a menos de contacto_max metros de) una dada, con la
    orientación cardinal de cada vecina respecto al centroide. Local, sin red."""
    row = _fila_parcela(rc)
    if row is None:
        return [{"error": f"RC {_rc14(rc)} no está en la caché."}]
    geom = shapely_wkt.loads(row["wkt"])
    con = conectar()
    try:
        filas = con.execute(
            "SELECT rc14, area_m2, cx, cy, wkt FROM parcelas WHERE provincia=? AND municipio=? AND rc14<>?",
            (row["provincia"], row["municipio"], row["rc14"]),
        ).fetchall()
    finally:
        con.close()
    geoms = [shapely_wkt.loads(f["wkt"]) for f in filas]
    arbol = STRtree(geoms)
    idxs = arbol.query(geom.buffer(contacto_max))
    out = []
    for i in idxs:
        if geom.distance(geoms[i]) <= contacto_max:
            f = filas[i]
            out.append({
                "rc14": f["rc14"],
                "superficie_m2": f["area_m2"],
                "distancia_m": round(geom.distance(geoms[i]), 2),
                "orientacion": _cardinal(row["cx"], row["cy"], f["cx"], f["cy"]),
            })
    return sorted(out, key=lambda p: p["distancia_m"])


def _cardinal(x0: float, y0: float, x1: float, y1: float) -> str:
    ang = math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360
    sectores = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
    return sectores[int((ang + 22.5) // 45) % 8]


@mcp.tool()
def catastro_en_radio(x: float, y: float, radio: float, srs: str = "EPSG:25829") -> list[dict]:
    """Parcelas cuyo centroide cae dentro de un círculo (x, y, radio en metros).
    Local, sin red. Solo EPSG:25829 (el SRS de la caché INSPIRE de Galicia)."""
    if srs != "EPSG:25829":
        return [{"error": "v1 solo soporta EPSG:25829 (el SRS de la caché)."}]
    con = conectar()
    try:
        filas = con.execute(
            "SELECT rc14, area_m2, cx, cy FROM parcelas "
            "WHERE cx BETWEEN ? AND ? AND cy BETWEEN ? AND ?",
            (x - radio, x + radio, y - radio, y + radio),
        ).fetchall()
    finally:
        con.close()
    centro = Point(x, y)
    out = [
        {"rc14": f["rc14"], "superficie_m2": f["area_m2"],
         "distancia_m": round(centro.distance(Point(f["cx"], f["cy"])), 1)}
        for f in filas if centro.distance(Point(f["cx"], f["cy"])) <= radio
    ]
    return sorted(out, key=lambda p: p["distancia_m"])


@mcp.tool()
def catastro_buscar_paraje(municipio: str, texto: str, umbral: float = 0.85) -> list[dict]:
    """Busca por nombre de paraje con similitud difusa sobre los parajes ya cacheados
    (los rellena catastro_ficha / catastro_completar_parajes). Local, sin red.
    Un nombre inventado debe quedar por debajo del umbral: si cuela, baja el umbral."""
    con = conectar()
    try:
        filas = con.execute(
            "SELECT f.rc14, f.paraje, p.area_m2 FROM fichas f JOIN parcelas p USING(rc14) "
            "WHERE p.municipio=? AND f.paraje IS NOT NULL",
            (municipio,),
        ).fetchall()
    finally:
        con.close()
    objetivo = texto.strip().upper()
    out = []
    for f in filas:
        ratio = difflib.SequenceMatcher(None, objetivo, f["paraje"].upper()).ratio()
        if ratio >= umbral:
            out.append({"rc14": f["rc14"], "paraje": f["paraje"],
                        "superficie_m2": f["area_m2"], "similitud": round(ratio, 3)})
    return sorted(out, key=lambda p: -p["similitud"])


# ---------- Con red (una petición por llamada) ----------

@mcp.tool()
def catastro_ficha(rc: str, provincia_del: str, municipio_mun: str) -> dict:
    """Consulta la sede electrónica (host www1, distinto del OVC — sobrevive a sus
    bloqueos) y devuelve paraje, clase, uso, superficie gráfica y RC de 20 chars.
    Acepta RC de 14 (sin dígitos de control). provincia_del/municipio_mun: códigos
    numéricos de la sede (Muxía: del='15', mun='53'). Guarda el resultado en caché.
    Nota: la superficie gráfica es informativa; la oficial es la del GML.
    NO disponible por ninguna vía pública: valor de referencia (requiere certificado
    digital o Cl@ve en la sede) y titularidad (dato protegido)."""
    datos = sede.ficha(_rc14(rc), provincia_del, municipio_mun)
    if _fila_parcela(rc) is not None:
        sede.guardar_ficha(_rc14(rc), datos)
        datos["cacheada"] = True
    return datos


@mcp.tool()
def catastro_por_poligono_parcela(provincia: str, municipio: str, poligono: str, parcela: str) -> dict:
    """Resuelve la RC desde la numeración polígono/parcela vía OVC (Consulta_DNPPP).
    provincia/municipio en texto oficial OVC (ej. 'A CORUÑA', 'MUXIA')."""
    datos = ovc.consulta_dnppp(provincia, municipio, poligono, parcela)
    if datos.get("rc14") and ovc.CANARIO_RC["rc"] is None:
        ovc.CANARIO_RC.update({"rc": datos["rc14"], "provincia": provincia, "municipio": municipio})
    return datos


@mcp.tool()
def catastro_por_coordenada(x: float, y: float, srs: str = "EPSG:25829") -> dict:
    """Resuelve qué parcela hay en un punto vía OVC (Consulta_RCCOOR). Prefiere
    catastro_en_radio si el municipio ya está cacheado (sin red y sin cuota)."""
    return ovc.consulta_rccoor(x, y, srs)


# ---------- Control ----------

@mcp.tool()
def catastro_estado(provincia: str = "A CORUÑA", municipio: str = "MUXIA") -> dict:
    """Control de tres puntas contra ambos hosts: RC que funcionó, RC inventada.
    Distingue 'no existe' (error de datos con canario OK) de 'no puedo' (todo falla
    igual → bloqueo de IP). Llamar ANTES de cualquier tanda y cuando algo devuelva
    vacío. Nota: un 403 aislado no dice nada — lo da también una RC inventada."""
    estado = {
        "cuota_ovc_hoy": f"{LIMITADOR.usados_hoy(ovc.HOST)}/{TECHO_DIARIO}",
        "cuota_sede_hoy": f"{LIMITADOR.usados_hoy(sede.HOST)}/{TECHO_DIARIO}",
    }
    canario = ovc.CANARIO_RC["rc"]
    if canario is None:
        con = conectar()
        try:
            row = con.execute("SELECT rc14 FROM fichas LIMIT 1").fetchone() or \
                  con.execute("SELECT rc14 FROM parcelas LIMIT 1").fetchone()
        finally:
            con.close()
        canario = row["rc14"] if row else None
    estado["ovc"] = ovc.probar(canario, provincia, municipio)
    if canario:
        try:
            sede.ficha(canario, "15", "53")
            estado["sede"] = "operativa"
        except Exception as e:
            estado["sede"] = f"fallo: {type(e).__name__}: {e}"
    else:
        estado["sede"] = "sin_canario (descarga un municipio o consulta una ficha primero)"
    v = estado["ovc"]
    if isinstance(v, dict) and str(v.get("valida", "")).startswith("error") \
            and v.get("valida") == v.get("inventada"):
        estado["diagnostico"] = "OVC BLOQUEADO: la RC válida y la inventada fallan igual → es la IP, no los datos."
    return estado


@mcp.tool()
def catastro_completar_parajes(municipio: str, rcs: list[str], provincia_del: str = "15",
                               municipio_mun: str = "53") -> dict:
    """Recorre una lista de RCs rellenando el paraje que falte vía la sede, con el
    limitador puesto. Reanudable: se salta las que ya tienen ficha; si el techo diario
    corta, se relanza otro día con la misma lista."""
    hechas, saltadas, fallos = 0, 0, []
    con = conectar()
    try:
        ya = {r["rc14"] for r in con.execute(
            "SELECT rc14 FROM fichas WHERE paraje IS NOT NULL").fetchall()}
    finally:
        con.close()
    for rc in rcs:
        rc = _rc14(rc)
        if rc in ya:
            saltadas += 1
            continue
        try:
            datos = sede.ficha(rc, provincia_del, municipio_mun)
            sede.guardar_ficha(rc, datos)
            hechas += 1
        except Exception as e:
            fallos.append({"rc": rc, "error": f"{type(e).__name__}: {e}"})
            if len(fallos) >= 10:
                return {"hechas": hechas, "saltadas": saltadas, "fallos": fallos,
                        "parada": "10 fallos: ejecuta catastro_estado() antes de seguir."}
    return {"hechas": hechas, "saltadas": saltadas, "fallos": fallos}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
