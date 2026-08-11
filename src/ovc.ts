// Servicio OVC: la API oficial, la que se bloquea con volumen. Un 403 aislado no
// significa nada (lo da también una RC inventada); diagnóstico solo con catastro_estado.
import { pedirPermiso, registrarExito, registrarFallo } from "./limiter.js";

export const OVC_HOST = "ovc.catastro.meh.es";
const BASE = `http://${OVC_HOST}/ovcservweb/OVCSWLocalizacionRC`;

export const canario: { rc: string | null; provincia: string | null; municipio: string | null } =
  { rc: null, provincia: null, municipio: null };

export class OVCError extends Error {}

async function get(path: string, params: Record<string, string>): Promise<string> {
  await pedirPermiso(OVC_HOST);
  let texto: string;
  try {
    const r = await fetch(`${BASE}/${path}?` + new URLSearchParams(params));
    if (!r.ok) throw new OVCError(`HTTP ${r.status}`);
    texto = await r.text();
  } catch (e) {
    registrarFallo(OVC_HOST);
    throw e;
  }
  registrarExito(OVC_HOST);
  return texto;
}

function tag(xml: string, nombre: string): string | null {
  const m = new RegExp(`<(?:\\w+:)?${nombre}[^>]*>([^<]*)<`).exec(xml);
  return m?.[1]?.trim() || null;
}

function errores(xml: string): string | null {
  const m = /<(?:\w+:)?err[^>]*>([\s\S]*?)<\/(?:\w+:)?err>/.exec(xml);
  return m ? m[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim() : null;
}

function parsearDNP(xml: string) {
  const err = errores(xml);
  if (err) throw new OVCError(err);
  const pc1 = tag(xml, "pc1"), pc2 = tag(xml, "pc2");
  const car = tag(xml, "car"), cc1 = tag(xml, "cc1"), cc2 = tag(xml, "cc2");
  return {
    rc14: pc1 && pc2 ? pc1 + pc2 : null,
    rc20: pc1 && pc2 && car && cc1 && cc2 ? pc1 + pc2 + car + cc1 + cc2 : null,
    direccion: tag(xml, "ldt"),
    uso: tag(xml, "luso"),
    superficie_m2: tag(xml, "ssp") ?? tag(xml, "sfc"),
    paraje: tag(xml, "npa"),
    poligono: tag(xml, "cpo"),
    parcela: tag(xml, "cpa"),
  };
}

export async function consultaDNPRC(provincia: string, municipio: string, rc: string) {
  return parsearDNP(await get("OVCCallejero.asmx/Consulta_DNPRC",
    { Provincia: provincia, Municipio: municipio, RC: rc }));
}

export async function consultaDNPPP(provincia: string, municipio: string, poligono: string, parcela: string) {
  return parsearDNP(await get("OVCCallejero.asmx/Consulta_DNPPP",
    { Provincia: provincia, Municipio: municipio, Poligono: poligono, Parcela: parcela }));
}

export async function consultaRCCOOR(x: number, y: number, srs = "EPSG:25829") {
  const xml = await get("OVCCoordenadas.asmx/Consulta_RCCOOR",
    { SRS: srs, Coordenada_X: String(x), Coordenada_Y: String(y) });
  const err = errores(xml);
  if (err) throw new OVCError(err);
  const pc1 = tag(xml, "pc1"), pc2 = tag(xml, "pc2");
  return { rc14: pc1 && pc2 ? pc1 + pc2 : null, direccion: tag(xml, "ldt") };
}

export async function probar(rcOk: string | null, provincia: string, municipio: string) {
  const resultados: Record<string, string> = {};
  const casos: Array<[string, string | null]> = [["valida", rcOk], ["inventada", "99999Z999999ZZ"]];
  for (const [etiqueta, rc] of casos) {
    if (!rc) { resultados[etiqueta] = "sin_referencia"; continue; }
    try {
      await consultaDNPRC(provincia, municipio, rc);
      resultados[etiqueta] = "ok";
    } catch (e) {
      resultados[etiqueta] = e instanceof OVCError
        ? `error_datos: ${e.message}`
        : `error_red: ${(e as Error).message}`;
    }
  }
  return resultados;
}
