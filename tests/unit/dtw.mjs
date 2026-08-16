// Юнит-тесты dtwAlign (Node ESM).
// Запуск: node tests/unit/dtw.mjs
// Сверяем 2-row banded DP с эталонной полной матрицей (старый код) и проверяем
// полосу-кап, покрытие и отсутствие OOM на больших входах.
import assert from "node:assert/strict";
import { dtwAlign, bestInWindow } from "../../js/dtw.js";
import { softSim } from "../../js/utils.js";

// Эталонная реализация (копия старого кода: полная матрица + бэктрекинг).
function refAlign(a, b, band){
  const n = a.length, m = b.length;
  const k12 = Math.round(Math.max(n, m) * 0.12);
  const K = Math.max(4, band == null ? k12 : Math.min(k12, band));
  const INF = 1e18;
  const dp = new Array(n), prev = new Array(n);
  for (let i = 0; i < n; i++){ dp[i] = new Array(m).fill(INF); prev[i] = new Array(m).fill(-1); }
  dp[0][0] = Math.abs(a[0] - b[0]);
  for (let j = 1; j <= K && j < m; j++){ dp[0][j] = dp[0][j-1] + Math.abs(a[0] - b[j]); prev[0][j] = 0; }
  for (let i = 1; i < n; i++){
    const j0 = Math.max(0, i - K), j1 = Math.min(m - 1, i + K);
    for (let j = j0; j <= j1; j++){
      let best = INF, bp = -1;
      if (j - 1 >= 0 && Math.abs(i - (j - 1)) <= K && dp[i][j-1] < best){ best = dp[i][j-1]; bp = 1; }
      if (dp[i-1][j] < best){ best = dp[i-1][j]; bp = 0; }
      if (j - 1 >= 0 && dp[i-1][j-1] < best){ best = dp[i-1][j-1]; bp = 2; }
      if (bp >= 0) dp[i][j] = best + Math.abs(a[i] - b[j]);
      prev[i][j] = bp;
    }
  }
  if (dp[n-1][m-1] >= INF) return null;
  let i = n - 1, j = m - 1, sum = 0, pairs = 0;
  while (i > 0 || j > 0){
    sum += Math.abs(a[i] - b[j]); pairs++;
    const pd = prev[i][j];
    if (pd === 0){ if (i > 0) i--; else j--; }
    else if (pd === 1){ if (j > 0) j--; else i--; }
    else { if (i > 0) i--; if (j > 0) j--; }
  }
  sum += Math.abs(a[0] - b[0]); pairs++;
  return { meanAbs: sum / pairs, coverage: Math.min(1, pairs / Math.max(n, m)) };
}

function mkCos(n, shift, amp = 28, base = 120, period = 50){
  const out = new Array(n);
  for (let i = 0; i < n; i++) out[i] = base + amp * Math.cos(2 * Math.PI * (i - shift) / period);
  return out;
}

let failed = 0;
function check(name, fn){
  try { fn(); console.log("  ok  " + name); }
  catch (err){ failed++; console.log(" FAIL " + name + " — " + err.message); }
}

console.log("dtw.mjs");

// 1. identical: нулевая ошибка, sim=1, покрытие 1
check("identical", () => {
  const a = mkCos(300, 0);
  const r = dtwAlign(a, a, 20);
  assert.ok(r);
  assert.ok(Math.abs(r.meanAbs) < 1e-9, `meanAbs=${r.meanAbs}`);
  assert.equal(r.meanSim, 1);
  assert.equal(r.coverage, 1);
});

// 2. сдвиг внутри полосы 12% — прощается
check("shift within default band", () => {
  const a = mkCos(300, 0), b = mkCos(300, 20);
  const r = dtwAlign(a, b, 20);
  assert.ok(r);
  assert.ok(r.meanAbs < 5, `meanAbs=${r.meanAbs}`);
  assert.ok(r.coverage > 0.9, `cov=${r.coverage}`);
});

// 3. сдвиг больше полосы — путь существует, но дорогой (полоса не «прощает»)
//    используем рампу (не периодику: cos с периодом 50 «маскирует» сдвиг 60)
check("shift beyond band is expensive", () => {
  const n = 300;
  const a = new Array(n), b = new Array(n);
  for (let i = 0; i < n; i++){ a[i] = i; b[i] = Math.max(0, i - 60); }
  const r = dtwAlign(a, b, 20);
  assert.ok(r);
  assert.ok(r.meanAbs > 8, `meanAbs=${r.meanAbs}`);
});

// 4. разница длин больше полосы → null; в полосе → работает
check("length diff beyond band => null", () => {
  const a = mkCos(100, 0), b = mkCos(60, 0);
  assert.equal(dtwAlign(a, b, 20), null);
});
check("length diff within band", () => {
  const a = mkCos(100, 0), b = mkCos(90, 0);
  const r = dtwAlign(a, b, 20);
  assert.ok(r);
  assert.ok(r.coverage >= 0.9, `cov=${r.coverage}`);
});

// 5. band-кап: малый band не прощает большой сдвиг
check("band cap limits forgiveness", () => {
  const a = mkCos(300, 0), b = mkCos(300, 25);
  const r = dtwAlign(a, b, 20, 8);
  assert.ok(r);
  assert.ok(r.meanAbs > 8, `meanAbs=${r.meanAbs}`);
});

// 6. эквивалентность эталонной полной матрице на случайных данных
check("equivalent to full-matrix reference (50 cases)", () => {
  let seed = 7;
  const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  for (let t = 0; t < 50; t++){
    const n = 10 + Math.floor(rnd() * 90);
    const m = 10 + Math.floor(rnd() * 90);
    const a = [], b = [];
    for (let i = 0; i < n; i++) a.push(Math.round(rnd() * 90));
    for (let i = 0; i < m; i++) b.push(Math.round(rnd() * 90));
    const band = [undefined, 4, 8, 20][t % 4];
    const got = dtwAlign(a, b, 20, band);
    const exp = refAlign(a, b, band);
    assert.deepEqual(
      got == null ? null : { meanAbs: got.meanAbs, coverage: got.coverage },
      exp == null ? null : { meanAbs: exp.meanAbs, coverage: exp.coverage },
      `t=${t} n=${n} m=${m} band=${band}`
    );
  }
});

// 7. большой вход с капом полосы — быстро и без падений
check("large input with band cap is fast", () => {
  const n = 50000;
  const a = mkCos(n, 0), b = mkCos(n, 10);
  const t0 = Date.now();
  const r = dtwAlign(a, b, 20, 60);
  const ms = Date.now() - t0;
  assert.ok(r, "null");
  assert.ok(ms < 5000, `слишком долго: ${ms}ms`);
});

// 8. bestInWindow — единый tie-break на плато softSim (Фаза 3.1):
//    при равном sim побеждает меньшая дельта угла (точнее фаза), иначе ближе к ref.
check("bestInWindow plateau: min delta wins", () => {
  const w = [[1, 100], [2, 105], [3, 110]];
  const r = bestInWindow(w, 104, 40, 3);
  assert.ok(r, "null");
  assert.equal(r.bestT, 2);      // |105-104|=1 — ближайший по углу, не первый в окне
  assert.equal(r.bestD, 1);
  assert.equal(r.m, 1);          // все кандидаты на плато (=1)
});
check("bestInWindow plateau: oldest-in-window no longer wins", () => {
  // регрессия исходного бага: первый (самый старый) кандидат на плато тоже sim=1,
  // но рядом лежит совпадение с ошибкой 1° — должен победить он
  const w = [[1, 140], [2, 106]];
  const r = bestInWindow(w, 105, 40, 2);
  assert.ok(r);
  assert.equal(r.bestT, 2);
  assert.equal(r.bestD, 1);      // не 35 (|140-105|), как было без tie-break
});
check("bestInWindow tie on delta: closer to ref", () => {
  const w = [[1, 104], [3, 104]];
  const r = bestInWindow(w, 104, 40, 2.5);
  assert.ok(r);
  assert.equal(r.bestT, 3);      // |3-2.5| < |1-2.5|
  assert.equal(r.bestD, 0);
});
check("bestInWindow sim is primary key", () => {
  // все вне допуска: побеждает max softSim (=min delta, монотонность)
  const w = [[1, 140], [2, 130]];
  const r = bestInWindow(w, 105, 20, 1);
  assert.ok(r);
  assert.equal(r.bestD, 25);                          // |130-105|
  assert.equal(r.m, softSim(25, 20));                 // (44-25)/24
  // внутри допуска кандидат бьёт более дальний вне допуска
  const w2 = [[1, 145], [2, 113]];
  const r2 = bestInWindow(w2, 105, 20, 1);
  assert.ok(r2);
  assert.equal(r2.bestT, 2);
  assert.equal(r2.bestD, 8);
  assert.equal(r2.m, 1);
});
check("bestInWindow empty window => null; beyond cap => worst match", () => {
  assert.equal(bestInWindow([], 104, 40, 3), null);
  // кандидат за пределом капа — валидное (худшее) совпадение с sim=0, не null
  const r = bestInWindow([[1, 200]], 105, 20, 1);
  assert.ok(r);
  assert.equal(r.m, 0);
  assert.equal(r.bestD, 95);
});

if (failed){ console.log(`\n${failed} тестов FAILED`); process.exit(1); }
console.log("\nвсе тесты прошли");
