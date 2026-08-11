# mcp-catastro

[![npm](https://img.shields.io/npm/v/mcp-catastro)](https://www.npmjs.com/package/mcp-catastro)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![node](https://img.shields.io/badge/node-%E2%89%A522-brightgreen)](package.json)

Servidor MCP para el Catastro español. Descarga el parcelario oficial INSPIRE de
un municipio y responde en local (superficie, geometría, parcelas colindantes,
búsqueda por paraje), y consulta el OVC y la sede electrónica cuando hace falta
la red, con límites diarios que evitan que el Catastro te corte la IP.

Nació de un caso real: localizar las fincas de una herencia en Muxía (A Coruña).
Por el camino aprendimos a base de errores qué vía usar para cada cosa, y este
servidor encapsula esas decisiones para que nadie tenga que repetirlas.

## Instalación

Con Claude Code (Node 22 o superior):

```bash
claude mcp add catastro -- npx -y mcp-catastro
```

Con Claude Desktop o cualquier cliente MCP, en `claude_desktop_config.json`:

```json
{ "mcpServers": { "catastro": { "command": "npx", "args": ["-y", "mcp-catastro"] } } }
```

El servidor corre en tu máquina y consulta al Catastro con tu IP, así que la
cuota y los bloqueos son solo tuyos. La caché se crea en `~/.catastro-mcp/`.

¿Cliente sin soporte de MCP local (claude.ai web, app móvil, ChatGPT)? Hay una
instancia pública, sin registro:

```
https://catastro.mestria.es/mcp
```

Añádela como conector personalizado. Cuota anónima de 50 llamadas al día por
IP, con Muxía precargada en la caché. Todos los usuarios de esa instancia
comparten la IP de salida hacia el Catastro, así que para volumen serio instala
el paquete o monta tu propia instancia (abajo).

## Herramientas

Sin red, contra la caché local:

| Herramienta | Qué hace |
|---|---|
| `catastro_descargar_municipio` | Baja el parcelario INSPIRE completo del municipio y construye la caché. Es la operación fundacional: el resto la da por hecha |
| `catastro_parcela_local` | Superficie oficial, centroide y geometría de una parcela |
| `catastro_vecinas` | Parcelas colindantes, con distancia y orientación cardinal |
| `catastro_en_radio` | Parcelas cuyo centroide cae dentro de un círculo |
| `catastro_buscar_paraje` | Búsqueda difusa por nombre de paraje |

Con red, una petición por llamada y siempre con el limitador puesto:

| Herramienta | Qué hace |
|---|---|
| `catastro_ficha` | Ficha de la sede electrónica: paraje, clase, uso, superficie gráfica y referencia de 20 caracteres |
| `catastro_por_poligono_parcela` | Resuelve la referencia catastral desde la numeración polígono/parcela |
| `catastro_por_coordenada` | Qué parcela hay en un punto |

De control:

| Herramienta | Qué hace |
|---|---|
| `catastro_estado` | Diagnóstico de acceso: distingue "el dato no existe" de "me han cortado" |
| `catastro_completar_parajes` | Recorre una lista de referencias rellenando parajes, reanudable |

## Las tres vías del Catastro

El Catastro tiene tres formas de acceso que no se parecen en nada, y elegir mal
es lo que arruina el trabajo.

| Vía | Host | Para qué | Límite |
|---|---|---|---|
| Descarga INSPIRE (GML) | www.catastro.hacienda.gob.es | Más de ~20 parcelas, geometría, superficie oficial | Ninguno |
| OVC (SOAP) | ovc.catastro.meh.es | Resolver referencias por polígono/parcela o coordenada | Sin límite documentado, pero con ~32.000 peticiones acumuladas cortan la IP |
| Sede electrónica (HTML) | www1.sedecatastro.gob.es | Paraje, clase, uso, referencia de 20 caracteres | Host distinto del OVC: sobrevive a su bloqueo |

Tres detalles de la sede que no están documentados en ningún sitio: acepta la
referencia de 14 caracteres (sin dígitos de control, que es justo lo que da el
GML), vive en otro host (el bloqueo del OVC no le afecta) y devuelve más campos
que la consulta SOAP básica.

## Decisiones de diseño

La caché no es una optimización, es el diseño. El servidor responde desde disco
por defecto y sale a la red solo cuando el dato no está o se lo pides. De las
preguntas típicas sobre una finca (¿cuánto mide?, ¿quién linda?, ¿qué hay
cerca?), solo el nombre del paraje necesita red.

El limitador cuenta el total diario por host (techo de 1000 peticiones), no
solo el ritmo. Un ritmo razonable con un acumulado grande también corta la IP:
lo medimos a 3,2 peticiones por segundo. A 10 fallos consecutivos el servidor
para solo.

Una ficha vacía o un 403 no se interpretan solos. Una referencia inventada
devuelve el mismo 403 que una IP cortada, así que `catastro_estado` consulta a
la vez una referencia que funcionó y una inventada: si las dos fallan igual, el
problema es tu acceso, no los datos.

La superficie sale siempre del `areaValue` del GML, que es la fuente oficial.
La superficie gráfica de la sede se guarda como dato informativo, pero no pisa
a la del GML.

## Lo que no puede dar

El valor de referencia solo se consulta en la sede identificándose con
certificado digital o Cl@ve, y la titularidad es dato protegido. Ninguna API
pública los expone, y este servidor tampoco.

## Montar tu propia instancia remota

En `python/` hay una implementación equivalente en Python que además expone el
servidor por streamable HTTP, pensada para servir a varias personas:

```bash
cd python && uv sync
CATASTRO_MCP_PUBLIC_HOST=tu-dominio uv run python -m catastro_mcp.http
```

Cada persona recibe un token (`python -m catastro_mcp.http crear-token nombre`)
con cuota diaria propia de 2000 llamadas, y `CATASTRO_MCP_ANONIMO=1` abre
además el acceso sin token con cuota de 50 al día por IP de cliente. El token
puede ir en la cabecera `X-Auth-Token` o en la ruta
(`https://tu-dominio/t/<token>/mcp`) para clientes que solo aceptan una URL.
El access log va apagado a propósito, porque el token viaja en la ruta.

## Verificado en vivo

Todo lo de arriba está medido, no copiado de documentación (11/08/2026):

- Muxía (15053): 43.188 parcelas descargadas y cacheadas en 5 segundos.
- Polígono 9, parcela 1: referencia `15053A00900001`, 15.149 m², paraje FONTE SALGUEIRA.
- Prueba cruzada de fuentes: la superficie del GML y la superficie gráfica de la sede coinciden al metro.
- Control negativo de la búsqueda difusa: un paraje inventado devuelve cero resultados.
- `catastro_estado` diagnosticó un bloqueo real de IP en el OVC mientras la sede seguía operativa.

## Licencia

MIT. No afiliado a la Dirección General del Catastro. Los datos catastrales
son públicos y se sirven bajo las condiciones de la DGC.
