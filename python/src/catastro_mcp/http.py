"""Modo remoto: streamable HTTP con token por persona y cuota diaria por token.

Auth: token en cabecera X-Auth-Token (preferida) o como primer tramo de la ruta
(/t/<token>/mcp) para clientes que solo aceptan una URL (claude.ai, ChatGPT).
El access log va APAGADO: un token en la ruta acabaría en el journal.

Tokens en el fichero ~/.catastro-mcp/tokens (una línea "nombre:token" por persona).
Cuota diaria por token reutilizando la tabla contador (host = "token:<nombre>").
"""
import os
import secrets
from pathlib import Path

import uvicorn
from starlette.responses import JSONResponse

from .limiter import LIMITADOR
from .server import mcp

TOKENS_PATH = Path.home() / ".catastro-mcp" / "tokens"
CUOTA_DIARIA_TOKEN = 2000    # llamadas MCP por persona y día (la mayoría son locales)
CUOTA_DIARIA_ANONIMA = 50    # sin token, por IP de cliente
ANONIMO_OK = os.environ.get("CATASTRO_MCP_ANONIMO", "") == "1"


def _cargar_tokens() -> dict[str, str]:
    """token -> nombre"""
    if not TOKENS_PATH.exists():
        return {}
    out = {}
    for linea in TOKENS_PATH.read_text().splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and ":" in linea:
            nombre, token = linea.split(":", 1)
            out[token.strip()] = nombre.strip()
    return out


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        tokens = _cargar_tokens()  # releído por petición: alta/baja sin reiniciar
        token = None
        for k, v in scope.get("headers", []):
            if k == b"x-auth-token":
                token = v.decode()
        path = scope["path"]
        if token is None and path.startswith("/t/"):
            resto = path[3:]
            token, _, subpath = resto.partition("/")
            scope = dict(scope)
            scope["path"] = "/" + subpath
        nombre = tokens.get(token or "")
        if nombre is not None:
            clave, cuota = f"token:{nombre}", CUOTA_DIARIA_TOKEN
        elif ANONIMO_OK:
            # acceso público sin token: cuota por IP de cliente (tras Cloudflare,
            # la IP real viene en CF-Connecting-IP)
            ip = "?"
            for k, v in scope.get("headers", []):
                if k == b"cf-connecting-ip":
                    ip = v.decode()
            if ip == "?" and scope.get("client"):
                ip = scope["client"][0]
            clave, cuota = f"ip:{ip}", CUOTA_DIARIA_ANONIMA
        else:
            resp = JSONResponse({"error": "no autorizado"}, status_code=401)
            return await resp(scope, receive, send)
        usados = LIMITADOR.usados_hoy(clave)
        if usados >= cuota:
            resp = JSONResponse(
                {"error": f"cuota diaria agotada ({usados}/{cuota})"},
                status_code=429)
            return await resp(scope, receive, send)
        _contar(clave)
        return await self.app(scope, receive, send)


def _contar(clave: str) -> None:
    from datetime import date
    from .cache import conectar
    con = conectar()
    try:
        con.execute(
            "INSERT INTO contador(host, fecha, n) VALUES(?,?,1) "
            "ON CONFLICT(host, fecha) DO UPDATE SET n = n + 1",
            (clave, date.today().isoformat()))
        con.commit()
    finally:
        con.close()


def crear_token(nombre: str) -> str:
    token = secrets.token_urlsafe(24)
    TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKENS_PATH, "a") as f:
        f.write(f"{nombre}:{token}\n")
    return token


def main():
    from mcp.server.transport_security import TransportSecuritySettings
    puerto = int(os.environ.get("CATASTRO_MCP_PORT", "8765"))
    hosts = ["127.0.0.1", f"127.0.0.1:{puerto}", "localhost", f"localhost:{puerto}"]
    publico = os.environ.get("CATASTRO_MCP_PUBLIC_HOST")  # ej. catastro.mestria.es
    if publico:
        hosts += [publico, f"{publico}:443"]
    app = mcp.streamable_http_app(
        transport_security=TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=["*"]),
        stateless_http=True,  # clientes móviles: sin sesión pegajosa
    )
    # ponytail: access_log=False es deliberado — el token viaja en la ruta
    uvicorn.run(AuthMiddleware(app), host="127.0.0.1", port=puerto, access_log=False)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "crear-token":
        print(crear_token(sys.argv[2]))
    else:
        main()
