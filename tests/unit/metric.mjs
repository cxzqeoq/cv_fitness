// Юнит-тесты «честной шкалы» (Фаза 3): simReported на реальных числах.
// Запуск: node tests/unit/metric.mjs
import assert from "node:assert/strict";
import { simReported, ceilFrom, sigmaEffFrom } from "../../js/qc.js";
import { SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR } from "../../js/config.js";

const near = (a, b, eps = 1e-3) => assert.ok(Math.abs(a - b) < eps, `${a.toFixed(4)} ≈ ${b.toFixed(4)}`);

// Реальные числа с телефона: локоть L σn = 5.37°, tight-допуск yogaHold (tol=8).
const tol = 8, sn = 5.37;
const se = sigmaEffFrom(tol, sn, SIGMA_TOL_FACTOR);           // hypot(8/1.5, 5.37) ≈ 7.568
near(se, Math.hypot(tol / SIGMA_TOL_FACTOR, sn));
const ceil = ceilFrom(tol, sn, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR);
near(ceil, Math.exp(-((CEIL_ERR_K * sn) ** 2) / (2 * se * se)));

// Идеальный повтор (ошибка ≈ √2·σn — разность двух независимых измерений) → 100% (кламп).
assert.equal(simReported(CEIL_ERR_K * sn, tol, sn, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR), 1);
// 0° — тоже 100%.
assert.equal(simReported(0, tol, sn, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR), 1);
// err=10° → ~69% (при идеале на ~69% было бы 100% от твоего максимума).
near(simReported(10, tol, sn, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR), 0.691);

// Свободное упражнение (tol=40), почти без шума (σn=0.5): почти не отличается от классического.
const tol40 = 40, snLow = 0.5;
near(simReported(5, tol40, snLow, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR), 0.983);
near(simReported(40, tol40, snLow, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR), 0.325);

// Нет шума: потолок = 1, итог = голый гауссиан σ=tol/1.5.
const se0 = tol40 / SIGMA_TOL_FACTOR;
near(simReported(40, tol40, 0, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR), Math.exp(-1600 / (2 * se0 * se0)));
near(simReported(20, tol40, 0, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR), Math.exp(-400 / (2 * se0 * se0)));

// Сильный шум + tight-допуск: потолок опускается, идеал всё равно 100% от своего максимума.
const snBig = 10;
assert.equal(simReported(0, 8, snBig, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR), 1);
near(simReported(15, 8, snBig, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR), 0.907);

// Безопасность: экстремальный шум не даёт NaN/Inf, потолок не ниже CEIL_FLOOR.
assert.ok(ceilFrom(8, 1000, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR) >= CEIL_FLOOR - 1e-12);
assert.ok(Number.isFinite(simReported(300, 8, 1000, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR)));
assert.ok(simReported(300, 8, 1000, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR) >= 0);

console.log("все тесты прошли");