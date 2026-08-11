// Sede electrónica: la vía de rescate. Host distinto del OVC (sobrevive a su bloqueo),
// acepta RC de 14 chars y devuelve más campos que el SOAP básico.
import { conectar } from "./cache.js";
import { pedirPermiso, registrarExito, registrarFallo } from "./limiter.js";

export const SEDE_HOST = "www1.sedecatastro.gob.es";
const URL_FICHA = `https://${SEDE_HOST}/CYCBienInmueble/OVCConCiud.aspx`;

export class SedeError extends Error {}

function limpiar(s: string): string {
  return s.replace(/<[^>]+>/g, " ")
    .replace(/&aacute;/g, "á").replace(/&eacute;/g, "é").replace(/&iacute;/g, "í")
    .replace(/&oacute;/g, "ó").replace(/&uacute;/g, "ú").replace(/&ntilde;/g, "ñ")
    .replace(/&amp;/g, "&").replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ").trim();
}

export async function ficha(rc: string, provinciaDel: string, municipioMun: string, urbRus = "R") {
  await pedirPermiso(SEDE_HOST);
  let pagina: string;
  try {
    const r = await fetch(URL_FICHA + "?" + new URLSearchParams({
      del: provinciaDel, mun: municipioMun, UrbRus: urbRus,
      from: "nuevoVisor", ZV: "NO", RefC: rc,
    }), { headers: { "User-Agent": "Mozilla/5.0 (Macintosh) mcp-catastro/1.0" } });
    if (!r.ok) throw new SedeError(`HTTP ${r.status}`);
    pagina = await r.text();
  } catch (e) {
    registrarFallo(SEDE_HOST);
    throw e;
  }
  registrarExito(SEDE_HOST);
  return parsearFicha(pagina, rc);
}

function parsearFicha(pagina: string, rc: string) {
  const datos: Record<string, unknown> = { rc_consultada: rc };
  const etiquetados = new Map<string, string>();
  for (const m of pagina.matchAll(
    /<span[^>]*class="[^"]*control-label[^"]*"[^>]*>(.*?)<\/span>\s*(?:<\/div>\s*)?<div[^>]*>\s*(?:<label[^>]*>)?(.*?)(?:<\/label>)?\s*<\/div>/gis)) {
    etiquetados.set(limpiar(m[1]).toLowerCase(), limpiar(m[2]));
  }
  const campos: Array<[string, string]> = [
    ["clase", "clase"], ["uso principal", "uso"],
    ["superficie gráfica", "superficie_grafica"], ["superficie construida", "superficie_construida"],
  ];
  for (const [etq, clave] of campos) {
    for (const [k, v] of etiquetados) if (k.includes(etq) && v) { datos[clave] = v; break; }
  }
  // Localización: el paraje puede venir en celda propia o pegado en la misma celda
  // que "Polígono N Parcela M PARAJE. MUN (PROV)" (medido: llega todo en una celda).
  const locBloque = /Localizaci[oó]n([\s\S]*?)(?:Clase|Uso principal|Superficie)/i.exec(pagina);
  if (locBloque) {
    const partes = [...locBloque[1].matchAll(/<label[^>]*>([\s\S]*?)<\/label>/g)]
      .map((m) => limpiar(m[1])).filter(Boolean);
    if (partes.length) {
      const loc = partes.join(" | ");
      datos.localizacion = loc;
      datos.poligono = /Pol[ií]gono\s+(\d+)/i.exec(loc)?.[1] ?? null;
      datos.parcela = /Parcela\s+(\d+)/i.exec(loc)?.[1] ?? null;
      let paraje: string | null = null;
      for (const p of partes) {
        paraje = /Parcela\s+\d+\s+(.+?)\.\s*[A-ZÑ]/.exec(p)?.[1]?.trim() ?? null;
        if (paraje) break;
        if (!/^\s*Pol[ií]gono/i.test(p)) {
          paraje = /^([^.(]+)[.(]/.exec(p)?.[1]?.trim() ?? null;
          if (paraje) break;
        }
      }
      datos.paraje = paraje;
    }
  }
  // rc20: solo el token de 20 chars (la celda arrastra texto de UI)
  datos.rc20 = /\b([0-9A-Z]{14}[0-9A-Z]{4}[A-Z]{2})\b/.exec(pagina)?.[1] ?? null;
  for (const k of ["superficie_grafica", "superficie_construida"] as const) {
    const v = datos[k];
    if (typeof v === "string") {
      const m = /([\d.]+)/.exec(v.replace(/\./g, "").replace(",", "."));
      datos[k + "_m2"] = m ? Number(m[1]) : null;
    }
  }
  if (Object.keys(datos).length <= 2 && !datos.rc20) {
    throw new SedeError(
      "Ficha vacía. Puede ser parcela sin bien inmueble O bloqueo de acceso: " +
      "distínguelo con catastro_estado antes de concluir nada.");
  }
  return datos;
}

export function guardarFicha(rc14: string, datos: Record<string, unknown>): void {
  conectar().prepare(
    "INSERT OR REPLACE INTO fichas(rc14,rc20,paraje,localizacion,clase,uso,superficie_grafica_m2,consultada_en) " +
    "VALUES(?,?,?,?,?,?,?,?)")
    .run(rc14, (datos.rc20 as string) ?? null, (datos.paraje as string) ?? null,
         (datos.localizacion as string) ?? null, (datos.clase as string) ?? null,
         (datos.uso as string) ?? null, (datos.superficie_grafica_m2 as number) ?? null,
         new Date().toISOString());
}
