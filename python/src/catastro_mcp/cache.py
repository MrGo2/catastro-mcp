"""Caché SQLite: parcelas del GML INSPIRE + fichas de la sede + contador de peticiones."""
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".catastro-mcp" / "cache.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS parcelas (
    rc14 TEXT PRIMARY KEY,
    provincia TEXT NOT NULL,
    municipio TEXT NOT NULL,
    area_m2 REAL NOT NULL,          -- cp:areaValue del GML: fuente oficial, la única aceptada
    cx REAL NOT NULL,               -- centroide EPSG:25829
    cy REAL NOT NULL,
    wkt TEXT NOT NULL               -- geometría completa EPSG:25829
);
CREATE INDEX IF NOT EXISTS idx_parcelas_mun ON parcelas(provincia, municipio);

CREATE TABLE IF NOT EXISTS fichas (
    rc14 TEXT PRIMARY KEY REFERENCES parcelas(rc14),
    rc20 TEXT,
    paraje TEXT,
    localizacion TEXT,
    clase TEXT,
    uso TEXT,
    superficie_grafica_m2 REAL,     -- solo informativa; la superficie oficial es parcelas.area_m2
    consultada_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contador (
    host TEXT NOT NULL,
    fecha TEXT NOT NULL,            -- YYYY-MM-DD
    n INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (host, fecha)
);

CREATE TABLE IF NOT EXISTS municipios_descargados (
    provincia TEXT NOT NULL,
    municipio TEXT NOT NULL,
    n_parcelas INTEGER NOT NULL,
    descargado_en TEXT NOT NULL,
    PRIMARY KEY (provincia, municipio)
);
"""


def conectar() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
