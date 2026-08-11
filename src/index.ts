#!/usr/bin/env node
// mcp-catastro: servidor MCP para el Catastro español.
// Diseño (medido 11/08/2026): la caché es el diseño; el limitador cuenta el TOTAL
// diario; "no existe" ≠ "no puedo" (canario); la superficie manda desde el GML.
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { conectar } from "./cache.js";
import { cardinal, distanciaAnillos, type Anillo } from "./geometry.js";
import { descargarMunicipio } from "./inspire.js";
import * as ovc from "./ovc.js";
import * as sede from "./sede.js";
import { TECHO_DIARIO, usadosHoy } from "./limiter.js";

const server = new McpServer({ name: "catastro", version: "1.0.0" });

const rc14 = (rc: string) => rc.trim().toUpperCase().slice(0, 14);
const json = (v: unknown) => ({ content: [{ type: "text" as const, text: JSON.stringify(v, null, 1) }] });

interface FilaParcela {
  rc14: string; provincia: string; municipio: string; area_m2: number;
  cx: number; cy: number; minx: number; miny: number; maxx: number; maxy: number; anillo: string;
}

const filaParcela = (rc: string): FilaParcela | undefined =>
  conectar().prepare("SELECT * FROM parcelas WHERE rc14=?").get(rc14(rc)) as FilaParcela | undefined;

function similitud(a: string, b: string): number {
  // ratio Levenshtein normalizado (equivalente práctico al de difflib)
  const m = a.length, n = b.length;
  if (!m || !n) return 0;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return 1 - prev[n] / Math.max(m, n);
}

// ---------- Sin red (caché local) ----------

server.tool(
  "catastro_descargar_municipio",
  "Baja el parcelario INSPIRE completo del municipio (GML oficial, sin límite) y construye la caché local. " +
  "Operación fundacional: el resto la da por hecha. Códigos numéricos (Muxía: provincia '15', municipio '15053'). " +
  "Cualquier operación sobre más de ~20 parcelas se resuelve aquí, nunca una a una.",
  { provincia: z.string(), municipio: z.string() },
  async ({ provincia, municipio }) => json(await descargarMunicipio(provincia, municipio)),
);

server.tool(
  "catastro_parcela_local",
  "Superficie oficial (areaValue del GML — la única fuente aceptada), centroide y geometría, desde caché, sin red.",
  { rc: z.string().describe("referencia catastral de 14 o 20 caracteres") },
  async ({ rc }) => {
    const row = filaParcela(rc);
    if (!row) return json({ error: `RC ${rc14(rc)} no está en la caché. Ejecuta antes catastro_descargar_municipio.` });
    const ficha = conectar().prepare("SELECT * FROM fichas WHERE rc14=?").get(row.rc14) as Record<string, unknown> | undefined;
    return json({
      rc14: row.rc14, superficie_m2: row.area_m2, centroide_25829: [row.cx, row.cy],
      anillo_25829: JSON.parse(row.anillo),
      ...(ficha ? { paraje: ficha.paraje, clase: ficha.clase, uso: ficha.uso, rc20: ficha.rc20 } : {}),
    });
  },
);

server.tool(
  "catastro_vecinas",
  "Parcelas que tocan (o quedan a menos de contacto_max metros de) una dada, con orientación cardinal. Local, sin red.",
  { rc: z.string(), contacto_max: z.number().default(3.0) },
  async ({ rc, contacto_max }) => {
    const row = filaParcela(rc);
    if (!row) return json({ error: `RC ${rc14(rc)} no está en la caché.` });
    const anillo: Anillo = JSON.parse(row.anillo);
    const candidatas = conectar().prepare(
      "SELECT * FROM parcelas WHERE provincia=? AND municipio=? AND rc14<>? " +
      "AND maxx>=? AND minx<=? AND maxy>=? AND miny<=?").all(
      row.provincia, row.municipio, row.rc14,
      row.minx - contacto_max, row.maxx + contacto_max,
      row.miny - contacto_max, row.maxy + contacto_max) as unknown as FilaParcela[];
    const out = [];
    for (const f of candidatas) {
      const d = distanciaAnillos(anillo, JSON.parse(f.anillo));
      if (d <= contacto_max) {
        out.push({ rc14: f.rc14, superficie_m2: f.area_m2, distancia_m: Math.round(d * 100) / 100,
                   orientacion: cardinal(row.cx, row.cy, f.cx, f.cy) });
      }
    }
    return json(out.sort((a, b) => a.distancia_m - b.distancia_m));
  },
);

server.tool(
  "catastro_en_radio",
  "Parcelas cuyo centroide cae dentro de un círculo (x, y en EPSG:25829, radio en metros). Local, sin red.",
  { x: z.number(), y: z.number(), radio: z.number(), srs: z.string().default("EPSG:25829") },
  async ({ x, y, radio, srs }) => {
    if (srs !== "EPSG:25829") return json({ error: "v1 solo soporta EPSG:25829 (el SRS de la caché)." });
    const filas = conectar().prepare(
      "SELECT rc14, area_m2, cx, cy FROM parcelas WHERE cx BETWEEN ? AND ? AND cy BETWEEN ? AND ?")
      .all(x - radio, x + radio, y - radio, y + radio) as unknown as FilaParcela[];
    const out = filas
      .map((f) => ({ rc14: f.rc14, superficie_m2: f.area_m2,
                     distancia_m: Math.round(Math.hypot(f.cx - x, f.cy - y) * 10) / 10 }))
      .filter((f) => f.distancia_m <= radio)
      .sort((a, b) => a.distancia_m - b.distancia_m);
    return json(out);
  },
);

server.tool(
  "catastro_buscar_paraje",
  "Búsqueda difusa por nombre de paraje sobre los ya cacheados (los rellena catastro_ficha / " +
  "catastro_completar_parajes). Local, sin red. Un nombre inventado debe quedar bajo el umbral.",
  { municipio: z.string(), texto: z.string(), umbral: z.number().default(0.75) },
  async ({ municipio, texto, umbral }) => {
    const filas = conectar().prepare(
      "SELECT f.rc14, f.paraje, p.area_m2 FROM fichas f JOIN parcelas p USING(rc14) " +
      "WHERE p.municipio=? AND f.paraje IS NOT NULL").all(municipio) as Array<{ rc14: string; paraje: string; area_m2: number }>;
    const objetivo = texto.trim().toUpperCase();
    return json(filas
      .map((f) => ({ rc14: f.rc14, paraje: f.paraje, superficie_m2: f.area_m2,
                     similitud: Math.round(similitud(objetivo, f.paraje.toUpperCase()) * 1000) / 1000 }))
      .filter((f) => f.similitud >= umbral)
      .sort((a, b) => b.similitud - a.similitud));
  },
);

// ---------- Con red (una petición por llamada) ----------

server.tool(
  "catastro_ficha",
  "Consulta la sede electrónica (host www1, distinto del OVC — sobrevive a sus bloqueos): paraje, clase, uso, " +
  "superficie gráfica (informativa; la oficial es la del GML) y RC de 20. Acepta RC de 14. " +
  "provincia_del/municipio_mun: códigos de la sede (Muxía: del '15', mun '53'). " +
  "NO existe por vía pública: valor de referencia (pide certificado/Cl@ve) ni titularidad (dato protegido).",
  { rc: z.string(), provincia_del: z.string(), municipio_mun: z.string() },
  async ({ rc, provincia_del, municipio_mun }) => {
    const datos = await sede.ficha(rc14(rc), provincia_del, municipio_mun);
    if (filaParcela(rc)) { sede.guardarFicha(rc14(rc), datos); datos.cacheada = true; }
    return json(datos);
  },
);

server.tool(
  "catastro_por_poligono_parcela",
  "Resuelve la RC desde polígono/parcela vía OVC (Consulta_DNPPP). provincia/municipio en texto OVC ('A CORUÑA', 'MUXIA').",
  { provincia: z.string(), municipio: z.string(), poligono: z.string(), parcela: z.string() },
  async ({ provincia, municipio, poligono, parcela }) => {
    const datos = await ovc.consultaDNPPP(provincia, municipio, poligono, parcela);
    if (datos.rc14 && !ovc.canario.rc) Object.assign(ovc.canario, { rc: datos.rc14, provincia, municipio });
    return json(datos);
  },
);

server.tool(
  "catastro_por_coordenada",
  "Resuelve qué parcela hay en un punto vía OVC (Consulta_RCCOOR). Prefiere catastro_en_radio si el municipio está cacheado.",
  { x: z.number(), y: z.number(), srs: z.string().default("EPSG:25829") },
  async ({ x, y, srs }) => json(await ovc.consultaRCCOOR(x, y, srs)),
);

// ---------- Control ----------

server.tool(
  "catastro_estado",
  "Control de tres puntas contra ambos hosts (RC que funcionó + RC inventada): distingue 'no existe' " +
  "(error de datos con canario OK) de 'no puedo' (todo falla igual → bloqueo de IP). Llamar antes de una tanda " +
  "y cuando algo devuelva vacío. Un 403 aislado no dice nada.",
  { provincia: z.string().default("A CORUÑA"), municipio: z.string().default("MUXIA") },
  async ({ provincia, municipio }) => {
    let rcCanario = ovc.canario.rc;
    if (!rcCanario) {
      const row = (conectar().prepare("SELECT rc14 FROM fichas LIMIT 1").get() ??
                   conectar().prepare("SELECT rc14 FROM parcelas LIMIT 1").get()) as { rc14: string } | undefined;
      rcCanario = row?.rc14 ?? null;
    }
    const estado: Record<string, unknown> = {
      cuota_ovc_hoy: `${usadosHoy(ovc.OVC_HOST)}/${TECHO_DIARIO}`,
      cuota_sede_hoy: `${usadosHoy(sede.SEDE_HOST)}/${TECHO_DIARIO}`,
      ovc: await ovc.probar(rcCanario, provincia, municipio),
    };
    if (rcCanario) {
      try { await sede.ficha(rcCanario, "15", "53"); estado.sede = "operativa"; }
      catch (e) { estado.sede = `fallo: ${(e as Error).message}`; }
    } else {
      estado.sede = "sin_canario (descarga un municipio o consulta una ficha primero)";
    }
    const v = estado.ovc as Record<string, string>;
    if (v.valida?.startsWith("error") && v.valida === v.inventada) {
      estado.diagnostico = "OVC BLOQUEADO: la RC válida y la inventada fallan igual → es la IP, no los datos.";
    }
    return json(estado);
  },
);

server.tool(
  "catastro_completar_parajes",
  "Recorre una lista de RCs rellenando el paraje que falte vía la sede, con limitador. Reanudable: " +
  "se salta las que ya tienen ficha; si el techo diario corta, se relanza otro día con la misma lista.",
  { municipio: z.string(), rcs: z.array(z.string()), provincia_del: z.string().default("15"), municipio_mun: z.string().default("53") },
  async ({ rcs, provincia_del, municipio_mun }) => {
    const ya = new Set((conectar().prepare("SELECT rc14 FROM fichas WHERE paraje IS NOT NULL").all() as Array<{ rc14: string }>).map((r) => r.rc14));
    let hechas = 0, saltadas = 0;
    const fallos: Array<{ rc: string; error: string }> = [];
    for (const rcRaw of rcs) {
      const rc = rc14(rcRaw);
      if (ya.has(rc)) { saltadas++; continue; }
      try {
        const datos = await sede.ficha(rc, provincia_del, municipio_mun);
        sede.guardarFicha(rc, datos);
        hechas++;
      } catch (e) {
        fallos.push({ rc, error: (e as Error).message });
        if (fallos.length >= 10) {
          return json({ hechas, saltadas, fallos, parada: "10 fallos: ejecuta catastro_estado antes de seguir." });
        }
      }
    }
    return json({ hechas, saltadas, fallos });
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);
