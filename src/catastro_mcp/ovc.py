"""Servicio OVC (ovc.catastro.meh.es): la API oficial, la que se bloquea con volumen.

Todas las llamadas pasan por el limitador. Un 403 aislado no significa nada:
lo devuelve también una RC inventada. Diagnóstico solo con el control de tres puntas
(catastro_estado)."""
import xml.etree.ElementTree as ET

import httpx

from .limiter import LIMITADOR

HOST = "ovc.catastro.meh.es"
BASE = f"http://{HOST}/ovcservweb"

# Referencia canario: una RC que sabemos que funciona (se fija tras la primera
# consulta con éxito; configurable).
CANARIO_RC = {"rc": None, "provincia": None, "municipio": None}


class OVCError(Exception):
    pass


def _get(path: str, params: dict) -> ET.Element:
    LIMITADOR.pedir_permiso(HOST)
    try:
        r = httpx.get(f"{BASE}/{path}", params=params, timeout=30, follow_redirects=True)
        r.raise_for_status()
    except Exception:
        LIMITADOR.registrar_fallo(HOST)
        raise
    LIMITADOR.registrar_exito(HOST)
    texto = r.text
    # quitar namespaces para parsear cómodo
    import re
    texto = re.sub(r'\sxmlns(:\w+)?="[^"]+"', "", texto, count=10)
    texto = re.sub(r"<(/?)\w+:", r"<\1", texto)
    return ET.fromstring(texto)


def _texto(root: ET.Element, tag: str) -> str | None:
    el = root.find(f".//{tag}")
    return el.text if el is not None and el.text else None


def _errores(root: ET.Element) -> str | None:
    err = root.find(".//err")
    if err is not None:
        return " ".join(x.text or "" for x in err.iter() if x.text)
    return None


def consulta_dnprc(provincia: str, municipio: str, rc: str) -> dict:
    root = _get(
        "OVCSWLocalizacionRC/OVCCallejero.asmx/Consulta_DNPRC",
        {"Provincia": provincia, "Municipio": municipio, "RC": rc},
    )
    return _parsear_dnp(root)


def consulta_dnppp(provincia: str, municipio: str, poligono: str, parcela: str) -> dict:
    root = _get(
        "OVCSWLocalizacionRC/OVCCallejero.asmx/Consulta_DNPPP",
        {"Provincia": provincia, "Municipio": municipio, "Poligono": poligono, "Parcela": parcela},
    )
    return _parsear_dnp(root)


def consulta_rccoor(x: float, y: float, srs: str = "EPSG:25829") -> dict:
    root = _get(
        "OVCSWLocalizacionRC/OVCCoordenadas.asmx/Consulta_RCCOOR",
        {"SRS": srs, "Coordenada_X": x, "Coordenada_Y": y},
    )
    err = _errores(root)
    if err:
        raise OVCError(err)
    pc1, pc2 = _texto(root, "pc1"), _texto(root, "pc2")
    return {
        "rc14": (pc1 or "") + (pc2 or "") or None,
        "direccion": _texto(root, "ldt"),
    }


def _parsear_dnp(root: ET.Element) -> dict:
    err = _errores(root)
    if err:
        raise OVCError(err)
    pc1, pc2 = _texto(root, "pc1"), _texto(root, "pc2")
    car, cc1, cc2 = _texto(root, "car"), _texto(root, "cc1"), _texto(root, "cc2")
    rc20 = None
    if pc1 and pc2 and car and cc1 and cc2:
        rc20 = pc1 + pc2 + car + cc1 + cc2
    return {
        "rc14": (pc1 or "") + (pc2 or "") or None,
        "rc20": rc20,
        "direccion": _texto(root, "ldt"),
        "uso": _texto(root, "luso"),
        "superficie_m2": _texto(root, "ssp") or _texto(root, "sfc"),
        "paraje": _texto(root, "npa"),
        "poligono": _texto(root, "cpp/cpo") or _texto(root, "cpo"),
        "parcela": _texto(root, "cpp/cpa") or _texto(root, "cpa"),
    }


def probar(rc_ok: str | None, provincia: str, municipio: str) -> dict:
    """Control de tres puntas contra OVC: RC buena, RC inventada. Devuelve estado."""
    resultados = {}
    rc_falsa = "99999Z999999ZZ"
    for etiqueta, rc in (("valida", rc_ok), ("inventada", rc_falsa)):
        if rc is None:
            resultados[etiqueta] = "sin_referencia"
            continue
        try:
            consulta_dnprc(provincia, municipio, rc)
            resultados[etiqueta] = "ok"
        except OVCError as e:
            resultados[etiqueta] = f"error_datos: {e}"
        except Exception as e:
            resultados[etiqueta] = f"error_red: {type(e).__name__}: {e}"
    return resultados
