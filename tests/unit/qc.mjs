// Юнит-тесты qc.js: med, medianTail, sigmaRobust, gaussSim (Node ESM).
// Запуск: node tests/unit/qc.mjs
import assert from "node:assert/strict";
import { med, medianTail, sigmaRobust, gaussSim } from "../../js/qc.js";

// ── med ──
assert.equal(med([]), 0);
assert.equal(med([5]), 5);
assert.equal(med([1, 3, 2]), 2);
assert.equal(med([4, 1, 3, 2]), 2.5);
assert.equal(med([1, 1, 1, 100]), 1); // выброс не двигает медиану
assert.equal(med([100, 1, 1, 1]), 1);

// ── medianTail ──
const h = [[0, 10], [1, 20], [2, 30], [3, 40]];
assert.equal(medianTail(h, 3), 30);       // последние 3: 20,30,40 → 30
assert.equal(medianTail(h, 4), 25);       // 10,20,30,40 → 25
assert.equal(medianTail(h, 5), null);     // не хватает
assert.equal(medianTail([], 3), null);

// ── sigmaRobust: N(0, σ) → σ ≈ 1.4826·MAD ≈ σ ──
// Детерминированный «нормальный» шум (sum of uniforms, Box–Muller).
function gauss(seed, n){
  const out = [];
  let s = seed >>> 0;
  const rnd = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  while (out.length < n){
    const u1 = rnd() || 1e-9, u2 = rnd();
    out.push(Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2));
  }
  return out;
}
const g5 = gauss(42, 2000).map(x => x * 5);          // N(0, 5°)
const s5 = sigmaRobust(g5);
assert.ok(Math.abs(s5 - 5) < 0.35, `σ по N(0,5) ≈ ${s5.toFixed(2)} (ожидаем ~5)`);

const constArr = new Array(50).fill(37.0);
assert.ok(sigmaRobust(constArr) < 1e-9);

// Устойчивость: 5% выбросов не должны сильно испортить оценку.
const gWithOut = [...g5];
for (let i = 0; i < 50; i++) gWithOut[i * 40] = 500;
assert.ok(Math.abs(sigmaRobust(gWithOut) - 5) < 1.5, `σ с выбросами ≈ ${sigmaRobust(gWithOut).toFixed(2)}`);

// Малый объём данных (как на старте сессии) — не падает.
assert.equal(sigmaRobust([1, 2]), 0);

// ── gaussSim: exp(−err²/2σ²) ──
assert.ok(Math.abs(gaussSim(0, 5) - 1) < 1e-12, "0° → 1");
assert.ok(Math.abs(gaussSim(5, 5) - Math.exp(-0.5)) < 1e-12, "err==σ → 0.607");
assert.ok(Math.abs(gaussSim(10, 5) - Math.exp(-2)) < 1e-12, "err==2σ → 0.135");
assert.equal(gaussSim(null, 5), 0);
assert.equal(gaussSim(3, 0), 0);
assert.equal(gaussSim(3, -1), 0);

console.log("все тесты прошли");