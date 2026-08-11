"""Descarga masiva INSPIRE: GML de parcelas por municipio, sin auth ni límite.

Resuelve el 90% de los casos sin tocar la red después de la descarga inicial.
Cualquier operación sobre >20 parcelas se hace aquí, nunca consultando una a una.
"""
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone

import httpx
from shapely import wkt as shapely_wkt
from shapely.geometry import Polygon, MultiPolygon

from .cache import conectar

HOST = "www.catastro.hacienda.gob.es"
BASE = f"https://{HOST}/INSPIRE/CadastralParcels"

NS = {
    "gml": "http://www.opengis.net/gml/3.2",
    "cp": "http://inspire.ec.europa.eu/schemas/cp/4.0",
}


def _url_atom_provincia(provincia: str) -> str:
    # Feed ATOM por provincia: lista los ZIP de todos sus municipios.
    return f"{BASE}/{provincia}/ES.SDGC.CP.atom_{provincia}.xml"


def localizar_zip(provincia: str, municipio: str) -> str:
    """Encuentra la URL del ZIP del municipio vía el feed ATOM de la provincia."""
    r = httpx.get(_url_atom_provincia(provincia), timeout=60, follow_redirects=True)
    r.raise_for_status()
    # Los <link>/<id> del feed llevan las URLs de los ZIP; buscamos por código de municipio.
    urls = re.findall(r"https?://[^\s<>\"']+\.zip", r.text)
    candidatas = [u for u in urls if f".{municipio}." in u or f".{municipio}-" in u]
    if not candidatas:
        raise ValueError(
            f"Municipio {municipio} no encontrado en el feed de la provincia {provincia}. "
            f"URLs de ejemplo del feed: {urls[:3]}"
        )
    return candidatas[0]


def _parsear_posiciones(texto: str) -> list[tuple[float, float]]:
    vals = texto.split()
    return [(float(vals[i]), float(vals[i + 1])) for i in range(0, len(vals) - 1, 2)]


def _geometria_de_parcela(elem: ET.Element):
    exterior = None
    interiores = []
    for surf in elem.iter(f"{{{NS['gml']}}}exterior"):
        pos = surf.find(f".//{{{NS['gml']}}}posList")
        if pos is not None and pos.text:
            exterior = _parsear_posiciones(pos.text)
            break
    for interior in elem.iter(f"{{{NS['gml']}}}interior"):
        pos = interior.find(f".//{{{NS['gml']}}}posList")
        if pos is not None and pos.text:
            interiores.append(_parsear_posiciones(pos.text))
    if not exterior or len(exterior) < 3:
        return None
    try:
        return Polygon(exterior, interiores)
    except Exception:
        return None


def descargar_municipio(provincia: str, municipio: str) -> dict:
    """Baja el GML INSPIRE del municipio y construye la caché. Operación fundacional."""
    url = localizar_zip(provincia, municipio)
    r = httpx.get(url, timeout=300, follow_redirects=True)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    gml_names = [n for n in zf.namelist() if n.lower().endswith(".gml")]
    if not gml_names:
        raise ValueError(f"El ZIP {url} no contiene ningún .gml: {zf.namelist()}")

    con = conectar()
    n = 0
    try:
        for name in gml_names:
            with zf.open(name) as f:
                for _, elem in _iter_parcelas(f):
                    rc14 = _rc_de_gml_id(elem)
                    if not rc14:
                        continue
                    area_el = elem.find(f"{{{NS['cp']}}}areaValue")
                    geom = _geometria_de_parcela(elem)
                    if area_el is None or area_el.text is None or geom is None:
                        continue
                    c = geom.centroid
                    con.execute(
                        "INSERT OR REPLACE INTO parcelas(rc14, provincia, municipio, area_m2, cx, cy, wkt) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (rc14, provincia, municipio, float(area_el.text), c.x, c.y, geom.wkt),
                    )
                    n += 1
                    elem.clear()
        con.execute(
            "INSERT OR REPLACE INTO municipios_descargados VALUES(?,?,?,?)",
            (provincia, municipio, n, datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
    finally:
        con.close()
    return {"provincia": provincia, "municipio": municipio, "parcelas": n, "url": url}


def _iter_parcelas(f):
    for event, elem in ET.iterparse(f, events=("end",)):
        if elem.tag == f"{{{NS['cp']}}}CadastralParcel":
            yield event, elem


def _rc_de_gml_id(elem: ET.Element) -> str | None:
    gml_id = elem.get(f"{{{NS['gml']}}}id", "")
    # gml:id tipo "ES.SDGC.CP.15053A009000010000..." — la RC de 14 chars es el último tramo.
    m = re.search(r"CP\.([0-9A-Z]{14})", gml_id)
    if m:
        return m.group(1)
    # fallback: cp:nationalCadastralReference
    ref = elem.find(f"{{{NS['cp']}}}nationalCadastralReference")
    if ref is not None and ref.text and len(ref.text) == 14:
        return ref.text
    return None


def cargar_geometria(row) -> Polygon | MultiPolygon:
    return shapely_wkt.loads(row["wkt"])
