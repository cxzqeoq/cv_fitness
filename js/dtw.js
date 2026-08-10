// dtw.js — выравнивание временных рядов (Dynamic Time Warping).
// Чистый модуль: только [t, значение]-массивы на входе, никакого DOM.
// Обе функции с полосой Сакоэ–Чибы ±K (ограничивает «рассинхрон» пути).
import { softSim } from "./utils.js";

// Оффлайн-выравнивание двух равночастотных рядов углов:
//   a, b — plain-массивы значений по возрастанию времени (време/шаг одинаковый),
//   thr — допуск для softSim.
// Возвращает { meanSim, coverage, meanAbs } или null при недостатке данных.
export function dtwAlign(a, b, thr){
  const n = a.length, m = b.length;
  if (n < 2 || m < 2) return null;
  const K = Math.max(4, Math.round(Math.max(n, m) * 0.12));
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
    if (pd === 0) { if (i > 0) i--; else j--; }
    else if (pd === 1) { if (j > 0) j--; else i--; }
    else { if (i > 0) i--; if (j > 0) j--; }
  }
  sum += Math.abs(a[0] - b[0]); pairs++;
  const meanAbs = sum / pairs;
  const meanSim = softSim(meanAbs, thr);
  const coverage = Math.min(1, pairs / Math.max(n, m));
  return { meanSim, coverage, meanAbs };
}

// Живое совпадение с предсказанием лага: лучший softSim по окну эталона.
// Работает в двух режимах:
//   acq=true  — захват лага: ищем по всему окну (в начале эталона соседнего
//               цикла ещё нет, «алиаса» фазы нет) — сходство и tAt честные.
//   acq=false — стейди-стейт: полоса ±band вокруг предсказанного времени
//               (tA - curLag), не даёт «перескочить» в соседний цикл на
//               периодичных движениях и держит % плавным.
// Возвращает { sim, tAt } или null, если в полосе не нашлось кандидатов
// (резкий выход из ритма — вызывающий код расширяет поиск на всё окно).
export function liveMatch(aWin, bVal, tA, curLag, acq, win, thr){
  if (!aWin || !aWin.length) return null;
  const band = Math.min(0.6, win / 2);
  const ref = (curLag == null || acq) ? tA : tA - curLag;
  const lo = acq ? (tA - win) : ref - band;
  const hi = acq ? tA : (ref + band);
  let m = -Infinity, bestT = null, bestD = Infinity;
  for (const [ta, av] of aWin){
    if (ta < lo || ta > hi) continue;
    const d = Math.abs(av - bVal);
    const s2 = softSim(d, thr);
    // tie-break на плато softSim (=1): предпочитаем меньшую дельту угла
    // (точнее фаза), при равной дельте — ближе к центру полосы
    if (s2 > m ||
        (s2 === m && bestT != null && (d < bestD || (d === bestD && Math.abs(ta - ref) < Math.abs(bestT - ref))))){
      m = s2; bestT = ta; bestD = d;
    }
  }
  if (!isFinite(m)) return null;
  return { sim: m, tAt: bestT };
}