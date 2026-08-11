// Geometría planar mínima para EPSG:25829 (metros). Turf no vale aquí: asume grados.
export type Punto = [number, number];
export type Anillo = Punto[];

export function centroide(anillo: Anillo): Punto {
  // centroide de polígono por área firmada; cae a media de vértices si degenerado
  let a = 0, cx = 0, cy = 0;
  for (let i = 0; i < anillo.length - 1; i++) {
    const [x0, y0] = anillo[i], [x1, y1] = anillo[i + 1];
    const f = x0 * y1 - x1 * y0;
    a += f; cx += (x0 + x1) * f; cy += (y0 + y1) * f;
  }
  if (Math.abs(a) < 1e-9) {
    const n = anillo.length;
    return [anillo.reduce((s, p) => s + p[0], 0) / n, anillo.reduce((s, p) => s + p[1], 0) / n];
  }
  return [cx / (3 * a), cy / (3 * a)];
}

export function bbox(anillo: Anillo): [number, number, number, number] {
  let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
  for (const [x, y] of anillo) {
    if (x < minx) minx = x; if (y < miny) miny = y;
    if (x > maxx) maxx = x; if (y > maxy) maxy = y;
  }
  return [minx, miny, maxx, maxy];
}

function distSegSeg(a: Punto, b: Punto, c: Punto, d: Punto): number {
  if (segCruzan(a, b, c, d)) return 0;
  return Math.min(distPuntoSeg(a, c, d), distPuntoSeg(b, c, d),
                  distPuntoSeg(c, a, b), distPuntoSeg(d, a, b));
}

function distPuntoSeg(p: Punto, a: Punto, b: Punto): number {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const l2 = dx * dx + dy * dy;
  let t = l2 === 0 ? 0 : ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

function orient(a: Punto, b: Punto, c: Punto): number {
  return Math.sign((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]));
}

function segCruzan(a: Punto, b: Punto, c: Punto, d: Punto): boolean {
  const o1 = orient(a, b, c), o2 = orient(a, b, d), o3 = orient(c, d, a), o4 = orient(c, d, b);
  return o1 !== o2 && o3 !== o4;
}

export function dentro(p: Punto, anillo: Anillo): boolean {
  let dentro_ = false;
  for (let i = 0, j = anillo.length - 1; i < anillo.length; j = i++) {
    const [xi, yi] = anillo[i], [xj, yj] = anillo[j];
    if (yi > p[1] !== yj > p[1] &&
        p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) dentro_ = !dentro_;
  }
  return dentro_;
}

export function distanciaAnillos(a: Anillo, b: Anillo): number {
  // 0 si se tocan/solapan; si no, mínima distancia borde a borde
  if (dentro(a[0], b) || dentro(b[0], a)) return 0;
  let min = Infinity;
  for (let i = 0; i < a.length - 1; i++) {
    for (let j = 0; j < b.length - 1; j++) {
      const d = distSegSeg(a[i], a[i + 1], b[j], b[j + 1]);
      if (d < min) min = d;
      if (min === 0) return 0;
    }
  }
  return min;
}

export function cardinal(x0: number, y0: number, x1: number, y1: number): string {
  const ang = ((Math.atan2(x1 - x0, y1 - y0) * 180) / Math.PI + 360) % 360;
  const sectores = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];
  return sectores[Math.floor(((ang + 22.5) % 360) / 45)];
}
