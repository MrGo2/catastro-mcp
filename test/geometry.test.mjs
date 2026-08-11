import { test } from "node:test";
import assert from "node:assert";
import { centroide, distanciaAnillos, cardinal, dentro } from "../dist/geometry.js";

const cuadrado = (x, y, l) => [[x, y], [x + l, y], [x + l, y + l], [x, y + l], [x, y]];

test("centroide de cuadrado", () => {
  const [cx, cy] = centroide(cuadrado(0, 0, 10));
  assert.ok(Math.abs(cx - 5) < 1e-9 && Math.abs(cy - 5) < 1e-9);
});

test("anillos que se tocan → distancia 0", () => {
  assert.equal(distanciaAnillos(cuadrado(0, 0, 10), cuadrado(10, 0, 10)), 0);
});

test("anillos separados → distancia real", () => {
  assert.ok(Math.abs(distanciaAnillos(cuadrado(0, 0, 10), cuadrado(13, 0, 10)) - 3) < 1e-9);
});

test("uno dentro de otro → 0", () => {
  assert.equal(distanciaAnillos(cuadrado(2, 2, 2), cuadrado(0, 0, 10)), 0);
});

test("cardinal", () => {
  assert.equal(cardinal(0, 0, 0, 10), "N");
  assert.equal(cardinal(0, 0, 10, 0), "E");
  assert.equal(cardinal(0, 0, -7, -7), "SO");
});

test("dentro", () => {
  assert.ok(dentro([5, 5], cuadrado(0, 0, 10)));
  assert.ok(!dentro([15, 5], cuadrado(0, 0, 10)));
});
