"""Limitador por host: techo diario acumulado (no solo ritmo) + parada por fallos consecutivos.

El aprendizaje caro: 3,2 req/s fue un ritmo razonable y aun así ~32.000 peticiones
acumuladas cortaron la IP. Lo que hay que contar es el TOTAL diario.
"""
import time
from datetime import date

from .cache import conectar

TECHO_DIARIO = 1000          # por host y día
FALLOS_MAX = 10              # fallos consecutivos → parada
PAUSA_S = 0.5                # pausa mínima entre peticiones con red


class TechoAlcanzadoError(Exception):
    pass


class Limitador:
    def __init__(self):
        self._fallos: dict[str, int] = {}
        self._ultima: dict[str, float] = {}

    def usados_hoy(self, host: str) -> int:
        con = conectar()
        try:
            row = con.execute(
                "SELECT n FROM contador WHERE host=? AND fecha=?",
                (host, date.today().isoformat()),
            ).fetchone()
            return row["n"] if row else 0
        finally:
            con.close()

    def pedir_permiso(self, host: str) -> None:
        """Llamar ANTES de cada petición. Lanza TechoAlcanzadoError si no procede."""
        if self._fallos.get(host, 0) >= FALLOS_MAX:
            raise TechoAlcanzadoError(
                f"{host}: {FALLOS_MAX} fallos consecutivos. Parada automática. "
                f"Ejecuta catastro_estado() para diagnosticar antes de reintentar."
            )
        usados = self.usados_hoy(host)
        if usados >= TECHO_DIARIO:
            raise TechoAlcanzadoError(
                f"{host}: techo diario alcanzado ({usados}/{TECHO_DIARIO}). "
                f"Se reanuda mañana. Para tandas grandes usa la descarga INSPIRE."
            )
        transcurrido = time.monotonic() - self._ultima.get(host, 0.0)
        if transcurrido < PAUSA_S:
            time.sleep(PAUSA_S - transcurrido)
        self._ultima[host] = time.monotonic()
        con = conectar()
        try:
            con.execute(
                "INSERT INTO contador(host, fecha, n) VALUES(?,?,1) "
                "ON CONFLICT(host, fecha) DO UPDATE SET n = n + 1",
                (host, date.today().isoformat()),
            )
            con.commit()
        finally:
            con.close()

    def registrar_exito(self, host: str) -> None:
        self._fallos[host] = 0

    def registrar_fallo(self, host: str) -> None:
        self._fallos[host] = self._fallos.get(host, 0) + 1


LIMITADOR = Limitador()
