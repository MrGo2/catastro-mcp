"""Sede electrónica (www1.sedecatastro.gob.es): la vía de rescate.

Tres hechos medidos que la justifican:
- Acepta la RC de 14 chars (sin dígitos de control) — clave, porque el GML da 14.
- Host distinto: el bloqueo del OVC no le afecta.
- Devuelve más campos que el SOAP básico: RC de 20, paraje, clase, uso, sup. gráfica.
"""
import html
import re
from datetime import datetime, timezone

import httpx

from .cache import conectar
from .limiter import LIMITADOR

HOST = "www1.sedecatastro.gob.es"
URL = f"https://{HOST}/CYCBienInmueble/OVCConCiud.aspx"

UA = "Mozilla/5.0 (Macintosh) catastro-mcp/1.0"


class SedeError(Exception):
    pass


def _limpiar(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def ficha(rc: str, provincia_del: str, municipio_mun: str, urb_rus: str = "R") -> dict:
    """Consulta la ficha del bien inmueble. rc: 14 o 20 chars. del/mun: códigos numéricos."""
    LIMITADOR.pedir_permiso(HOST)
    try:
        r = httpx.get(
            URL,
            params={"del": provincia_del, "mun": municipio_mun, "UrbRus": urb_rus,
                    "from": "nuevoVisor", "ZV": "NO", "RefC": rc},
            headers={"User-Agent": UA},
            timeout=30,
            follow_redirects=True,
        )
        r.raise_for_status()
    except Exception:
        LIMITADOR.registrar_fallo(HOST)
        raise
    LIMITADOR.registrar_exito(HOST)
    return _parsear_ficha(r.text, rc)


def _parsear_ficha(pagina: str, rc: str) -> dict:
    datos: dict = {"rc_consultada": rc}

    # La ficha viene como pares etiqueta/valor en divs/spans. Extraemos por etiqueta.
    # El campo Localización queda partido en DOS celdas consecutivas:
    #   Polígono 9 Parcela 1 | FONTE SALGUEIRA. MUXIA (A CORUÑA)
    # El paraje está en la SEGUNDA — un corte en el primer separador lo pierde.
    campos = {
        "referencia catastral": "rc20",
        "clase": "clase",
        "uso principal": "uso",
        "superficie gráfica": "superficie_grafica",
        "superficie construida": "superficie_construida",
    }
    bloques = re.findall(
        r'<span[^>]*class="[^"]*control-label[^"]*"[^>]*>(.*?)</span>\s*'
        r'(?:</div>\s*)?<div[^>]*>\s*(?:<label[^>]*>)?(.*?)(?:</label>)?\s*</div>',
        pagina, re.S | re.I,
    )
    etiquetados: dict[str, str] = {}
    for etiqueta, valor in bloques:
        etiquetados[_limpiar(etiqueta).lower()] = _limpiar(valor)

    for etq, clave in campos.items():
        for k, v in etiquetados.items():
            if etq in k and v:
                datos[clave] = v
                break

    # Localización: juntar TODAS las celdas del bloque, no solo la primera.
    loc_partes = []
    m = re.search(r"Localizaci[oó]n(.*?)(?:Clase|Uso principal|Superficie)", pagina, re.S | re.I)
    if m:
        for celda in re.findall(r"<label[^>]*>(.*?)</label>", m.group(1), re.S):
            t = _limpiar(celda)
            if t:
                loc_partes.append(t)
    if loc_partes:
        datos["localizacion"] = " | ".join(loc_partes)
        datos["poligono"], datos["parcela"] = _pol_par(datos["localizacion"])
        datos["paraje"] = _paraje(loc_partes)

    # rc20: quedarnos solo con el token de 20 chars (la celda arrastra texto de UI
    # tipo "copiar código de barras").
    m = re.search(r"\b([0-9A-Z]{14}[0-9A-Z]{4}[A-Z]{2})\b", datos.get("rc20", "") or pagina)
    datos["rc20"] = m.group(1) if m else None

    # superficie a número
    for k in ("superficie_grafica", "superficie_construida"):
        if k in datos:
            m = re.search(r"([\d.]+)", datos[k].replace(".", "").replace(",", "."))
            datos[k + "_m2"] = float(m.group(1)) if m else None

    if len(datos) <= 1:
        raise SedeError(
            "Ficha vacía. Puede ser parcela sin bien inmueble O bloqueo de acceso: "
            "distínguelo con catastro_estado() antes de concluir nada."
        )
    return datos


def _pol_par(loc: str) -> tuple[str | None, str | None]:
    mp = re.search(r"Pol[ií]gono\s+(\d+)", loc, re.I)
    mr = re.search(r"Parcela\s+(\d+)", loc, re.I)
    return (mp.group(1) if mp else None, mr.group(1) if mr else None)


def _paraje(partes: list[str]) -> str | None:
    # El paraje va en "PARAJE. MUNICIPIO (PROVINCIA)". Puede llegar en celda propia
    # o pegado en la misma celda que "Polígono N Parcela M PARAJE. MUN (PROV)":
    # medido en vivo 11/08/2026, llega TODO en una celda. Cubrimos ambos casos.
    for p in partes:
        m = re.search(r"Parcela\s+\d+\s+(.+?)\.\s*[A-ZÑ]", p)
        if m:
            return m.group(1).strip()
        if not re.match(r"\s*Pol[ií]gono", p, re.I):
            m = re.match(r"([^.(]+)[.(]", p)
            if m:
                return m.group(1).strip()
    return None


def guardar_ficha(rc14: str, datos: dict) -> None:
    con = conectar()
    try:
        con.execute(
            "INSERT OR REPLACE INTO fichas(rc14, rc20, paraje, localizacion, clase, uso, "
            "superficie_grafica_m2, consultada_en) VALUES(?,?,?,?,?,?,?,?)",
            (rc14, datos.get("rc20"), datos.get("paraje"), datos.get("localizacion"),
             datos.get("clase"), datos.get("uso"), datos.get("superficie_grafica_m2"),
             datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
    finally:
        con.close()
