// Caché SQLite (node:sqlite, sin deps nativas): parcelas INSPIRE + fichas + contador.
import { DatabaseSync } from "node:sqlite";
import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export const DB_DIR = join(homedir(), ".catastro-mcp");
export const DB_PATH = join(DB_DIR, "cache-ts.db");

const SCHEMA = `
CREATE TABLE IF NOT EXISTS parcelas (
  rc14 TEXT PRIMARY KEY,
  provincia TEXT NOT NULL,
  municipio TEXT NOT NULL,
  area_m2 REAL NOT NULL,      -- cp:areaValue del GML: la superficie oficial, la única aceptada
  cx REAL NOT NULL,           -- centroide EPSG:25829
  cy REAL NOT NULL,
  minx REAL NOT NULL, miny REAL NOT NULL, maxx REAL NOT NULL, maxy REAL NOT NULL,
  anillo TEXT NOT NULL        -- anillo exterior [[x,y],...] EPSG:25829
);
CREATE INDEX IF NOT EXISTS idx_parcelas_mun ON parcelas(provincia, municipio);
CREATE TABLE IF NOT EXISTS fichas (
  rc14 TEXT PRIMARY KEY,
  rc20 TEXT, paraje TEXT, localizacion TEXT, clase TEXT, uso TEXT,
  superficie_grafica_m2 REAL,  -- informativa; la oficial es parcelas.area_m2
  consultada_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contador (
  host TEXT NOT NULL, fecha TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (host, fecha)
);
CREATE TABLE IF NOT EXISTS municipios_descargados (
  provincia TEXT NOT NULL, municipio TEXT NOT NULL,
  n_parcelas INTEGER NOT NULL, descargado_en TEXT NOT NULL,
  PRIMARY KEY (provincia, municipio)
);`;

let db: DatabaseSync | null = null;

export function conectar(): DatabaseSync {
  if (db) return db;
  mkdirSync(DB_DIR, { recursive: true });
  db = new DatabaseSync(DB_PATH);
  db.exec(SCHEMA);
  return db;
}
