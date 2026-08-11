// Limitador por host: techo diario ACUMULADO (no solo ritmo) + parada por fallos seguidos.
// El aprendizaje caro: 3,2 req/s era razonable y aun así ~32.000 acumuladas cortaron la IP.
import { conectar } from "./cache.js";

export const TECHO_DIARIO = 1000;
const FALLOS_MAX = 10;
const PAUSA_MS = 500;

const fallos = new Map<string, number>();
const ultima = new Map<string, number>();

export class TechoAlcanzadoError extends Error {}

export function usadosHoy(host: string): number {
  const row = conectar()
    .prepare("SELECT n FROM contador WHERE host=? AND fecha=?")
    .get(host, hoy()) as { n: number } | undefined;
  return row?.n ?? 0;
}

function hoy(): string {
  return new Date().toISOString().slice(0, 10);
}

export async function pedirPermiso(host: string): Promise<void> {
  if ((fallos.get(host) ?? 0) >= FALLOS_MAX) {
    throw new TechoAlcanzadoError(
      `${host}: ${FALLOS_MAX} fallos consecutivos. Parada automática. ` +
      `Ejecuta catastro_estado antes de reintentar.`);
  }
  const usados = usadosHoy(host);
  if (usados >= TECHO_DIARIO) {
    throw new TechoAlcanzadoError(
      `${host}: techo diario alcanzado (${usados}/${TECHO_DIARIO}). ` +
      `Se reanuda mañana. Para tandas grandes usa la descarga INSPIRE.`);
  }
  const delta = Date.now() - (ultima.get(host) ?? 0);
  if (delta < PAUSA_MS) await new Promise((r) => setTimeout(r, PAUSA_MS - delta));
  ultima.set(host, Date.now());
  conectar()
    .prepare("INSERT INTO contador(host,fecha,n) VALUES(?,?,1) " +
             "ON CONFLICT(host,fecha) DO UPDATE SET n=n+1")
    .run(host, hoy());
}

export function registrarExito(host: string): void { fallos.set(host, 0); }
export function registrarFallo(host: string): void { fallos.set(host, (fallos.get(host) ?? 0) + 1); }
