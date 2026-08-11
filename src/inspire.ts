// Descarga masiva INSPIRE: GML por municipio, sin auth ni límite. La vía para >20 parcelas.
import { unzipSync } from "fflate";
import { conectar } from "./cache.js";
import { bbox, centroide, type Anillo } from "./geometry.js";

const BASE = "https://www.catastro.hacienda.gob.es/INSPIRE/CadastralParcels";

export async function localizarZip(provincia: string, municipio: string): Promise<string> {
  const url = `${BASE}/${provincia}/ES.SDGC.CP.atom_${provincia}.xml`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`Feed ATOM de la provincia ${provincia}: HTTP ${r.status}`);
  const texto = await r.text();
  const urls = texto.match(/https?:\/\/[^\s<>"']+\.zip/g) ?? [];
  const zip = urls.find((u) => u.includes(`.${municipio}.`) || u.includes(`.${municipio}-`));
  if (!zip) throw new Error(
    `Municipio ${municipio} no está en el feed de la provincia ${provincia}. Ejemplos: ${urls.slice(0, 3).join(", ")}`);
  return zip;
}

export async function descargarMunicipio(provincia: string, municipio: string) {
  const url = await localizarZip(provincia, municipio);
  const r = await fetch(url);
  if (!r.ok) throw new Error(`Descarga ${url}: HTTP ${r.status}`);
  const zip = unzipSync(new Uint8Array(await r.arrayBuffer()));
  const db = conectar();
  const ins = db.prepare(
    "INSERT OR REPLACE INTO parcelas(rc14,provincia,municipio,area_m2,cx,cy,minx,miny,maxx,maxy,anillo) " +
    "VALUES(?,?,?,?,?,?,?,?,?,?,?)");
  let n = 0;
  db.exec("BEGIN");
  try {
    for (const [nombre, datos] of Object.entries(zip)) {
      if (!nombre.toLowerCase().endsWith(".gml")) continue;
      const gml = new TextDecoder("utf-8").decode(datos);
      // parcelas delimitadas por el elemento cp:CadastralParcel; regex por bloque
      const bloques = gml.split(/<cp:CadastralParcel[\s>]/).slice(1);
      for (const bloque of bloques) {
        const fin = bloque.indexOf("</cp:CadastralParcel>");
        const p = fin === -1 ? bloque : bloque.slice(0, fin);
        const rc = /CP\.([0-9A-Z]{14})/.exec(p)?.[1] ??
                   /<cp:nationalCadastralReference>([0-9A-Z]{14})</.exec(p)?.[1];
        const area = /<cp:areaValue[^>]*>([\d.]+)</.exec(p)?.[1];
        // primer posList = anillo exterior (gml:exterior precede a los interiores)
        const pos = /<gml:posList[^>]*>([\s\d.\-]+)</.exec(p)?.[1];
        if (!rc || !area || !pos) continue;
        const vals = pos.trim().split(/\s+/).map(Number);
        const anillo: Anillo = [];
        for (let i = 0; i + 1 < vals.length; i += 2) anillo.push([vals[i], vals[i + 1]]);
        if (anillo.length < 3) continue;
        const [cx, cy] = centroide(anillo);
        const [minx, miny, maxx, maxy] = bbox(anillo);
        ins.run(rc, provincia, municipio, Number(area), cx, cy, minx, miny, maxx, maxy,
                JSON.stringify(anillo));
        n++;
      }
    }
    db.prepare("INSERT OR REPLACE INTO municipios_descargados VALUES(?,?,?,?)")
      .run(provincia, municipio, n, new Date().toISOString());
    db.exec("COMMIT");
  } catch (e) {
    db.exec("ROLLBACK");
    throw e;
  }
  return { provincia, municipio, parcelas: n, url };
}
