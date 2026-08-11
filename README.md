# catastro-mcp

Servidor MCP para el Catastro español. Encapsula las tres vías de acceso y las
decisiones que arruinan el trabajo si se toman mal (medido en la sesión de la
herencia, 11/08/2026).

## Las tres vías

| Vía | Host | Cuándo | Límite |
|---|---|---|---|
| INSPIRE GML | www.catastro.hacienda.gob.es | >20 parcelas, geometría, superficie oficial | ninguno |
| OVC (SOAP) | ovc.catastro.meh.es | resolver RC por polígono/parcela o coordenada | ~32k acumuladas → IP cortada |
| Sede (HTML) | www1.sedecatastro.gob.es | paraje, clase, uso, RC de 20 | host distinto: sobrevive al bloqueo del OVC |

## Herramientas (10)

Sin red (caché SQLite en `~/.catastro-mcp/cache.db`):
- `catastro_descargar_municipio(provincia, municipio)` — fundacional; baja el GML
- `catastro_parcela_local(rc)` — superficie oficial (areaValue), centroide, WKT
- `catastro_vecinas(rc, contacto_max)` — colindantes con orientación cardinal
- `catastro_en_radio(x, y, radio)` — parcelas por centroide en un círculo
- `catastro_buscar_paraje(municipio, texto, umbral)` — búsqueda difusa

Con red (una petición por llamada, limitador puesto):
- `catastro_ficha(rc, provincia_del, municipio_mun)` — sede; acepta RC de 14
- `catastro_por_poligono_parcela(provincia, municipio, poligono, parcela)` — OVC
- `catastro_por_coordenada(x, y, srs)` — OVC

Control:
- `catastro_estado()` — control de tres puntas: distingue "no existe" de "no puedo"
- `catastro_completar_parajes(municipio, rcs)` — tanda reanudable con limitador

## Reglas de diseño (no negociables)

1. La superficie manda desde el `areaValue` del GML. El servidor no acepta
   superficies de otro origen.
2. El limitador cuenta el TOTAL diario por host (techo 1000), no solo el ritmo.
   A 10 fallos consecutivos, parada automática.
3. Un 403 o una ficha vacía no se interpretan solos: `catastro_estado()` primero.
4. No hay valor de referencia (requiere certificado/Cl@ve) ni titularidad
   (dato protegido) por ninguna vía pública.

## Instalación

```bash
cd ~/Edelwyss/infrastructure/catastro-mcp
uv sync
claude mcp add catastro -- uv run --directory ~/Edelwyss/infrastructure/catastro-mcp catastro-mcp
```

## Verificado en vivo (11/08/2026)

- Muxía (15053): 43.188 parcelas descargadas y cacheadas en 10 s.
- Polígono 9 parcela 1 → RC `15053A00900001`, 15.149 m², paraje FONTE SALGUEIRA.
- Prueba cruzada: superficie GML (15149) == superficie gráfica de la sede (15.149 m²).
- Control negativo difuso: "PRADO DO INVENTADO" → 0 resultados.
- `catastro_estado()` diagnosticó correctamente el bloqueo real del OVC
  (RC válida e inventada fallan igual → IP) con la sede operativa.

## Instancia pública — sin instalar nada

```
https://catastro.mestria.es/mcp
```

Añádela como conector MCP en claude.ai (Ajustes → Conectores → personalizado),
en la app móvil de Claude o en ChatGPT (developer mode). Sin registro: cuota
anónima de 200 llamadas/día por IP. La caché trae Muxía (A Coruña) precargada;
pide otro municipio con `catastro_descargar_municipio`.

## Montar tu propia instancia

El modo HTTP (`python -m catastro_mcp.http`) expone el servidor por streamable
HTTP con token por persona y cuota diaria por token (2000 llamadas).

```bash
# alta de una persona (imprime su token)
python -m catastro_mcp.http crear-token nombre
```

Acceso anónimo: exporta `CATASTRO_MCP_ANONIMO=1` (cuota por IP de cliente).
Conexión con token desde clientes que solo aceptan URL:

```
https://tu-dominio/t/<token>/mcp
```

Con cabeceras: `X-Auth-Token: <token>` sobre `https://tu-dominio/mcp` (preferido).

Variables: `CATASTRO_MCP_PORT` (8765) y `CATASTRO_MCP_PUBLIC_HOST` (el hostname
público, para la protección anti DNS-rebinding). El access log va apagado a
propósito: el token viaja en la ruta.

Nota de convivencia: todos los usuarios de una instancia comparten la IP de
salida, y el bloqueo del Catastro es por IP. El techo diario por host (1000)
protege a todos; si necesitas más volumen, monta tu propia instancia.
