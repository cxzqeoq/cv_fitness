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

// Живое скользящее DTW: последний кадр B кладём на A-траекторию локальным путём.
// Прощает дрейф темпа («иногда вместе, иногда с опозданием»).
//   aHist/bHist — [t, val] по возрастанию t, thr — допуск.
// Возвращает { sim, tAt } (медиана по хвосту пути ~0.3с) или null.
export function liveDTWMap(aHist, bHist, thr){
  if (!aHist || !bHist) return null;
  const n0 = aHist.length, m0 = bHist.length;
  if (n0 < 3 || m0 < 3) return null;
  const L = Math.min(n0, m0); // равные длины → путь точно достигает конца при любой полосе K
  const A = aHist.slice(-L), B = bHist.slice(-L);
  const n = L, m = L;
  const K = L; // полная свобода дрейфа внутри окна сравнения (±lagWin) — само окно ограничивает рассинхрон
  const INF = 1e18;
  let dp = [], prev = [];
  for (let i = 0; i < n; i++){ dp.push(new Array(m).fill(INF)); prev.push(new Array(m).fill(-1)); }
  dp[0][0] = Math.abs(A[0][1] - B[0][1]);
  for (let j = 1; j <= K && j < m; j++){ dp[0][j] = dp[0][j-1] + Math.abs(A[0][1] - B[j][1]); prev[0][j] = 1; }
  for (let i = 1; i < n; i++){
    const j0 = Math.max(0, i - K), j1 = Math.min(m - 1, i + K);
    for (let j = j0; j <= j1; j++){
      let best = INF, bp = -1;
      if (j - 1 >= j0 && dp[i][j-1] < best){ best = dp[i][j-1]; bp = 1; }
      if (dp[i-1][j] < best){ best = dp[i-1][j]; bp = 0; }
      if (j - 1 >= 0 && dp[i-1][j-1] < best){ best = dp[i-1][j-1]; bp = 2; }
      if (bp >= 0){ dp[i][j] = best + Math.abs(A[i][1] - B[j][1]); prev[i][j] = bp; }
    }
  }
  if (prev[n-1][m-1] < 0) return null;
  let i = n - 1, j = m - 1;
  while (i > 0 && prev[i][j] === 0) i--; // b[последний] накрыл несколько A → берём верхний
  if (dp[i][j] >= INF) return null;
  // сходство — медиана по хвосту пути (~0.3с): не точка-в-точку, а окрестность гасит джиттер камеры
  const tEnd = B[m-1][0];
  const sims = [];
  let si = i, sj = j;
  while (si >= 0 && sj >= 0 && tEnd - B[sj][0] <= 0.3){
    sims.push(softSim(Math.abs(A[si][1] - B[sj][1]), thr));
    const p = prev[si][sj];
    if (p === 1) sj--;
    else if (p === 0) si--;
    else { si--; sj--; }
  }
  if (!sims.length) return null;
  sims.sort((x, y) => x - y);
  return { sim: sims[Math.floor(sims.length/2)], tAt: A[i][0] };
}