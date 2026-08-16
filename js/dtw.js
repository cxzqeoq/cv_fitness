// dtw.js — выравнивание временных рядов (Dynamic Time Warping).
// Чистый модуль: только [t, значение]-массивы на входе, никакого DOM.
// Обе функции с полосой Сакоэ–Чибы ±K (ограничивает «рассинхрон» пути).
import { softSim } from "./utils.js";

// Оффлайн-выравнивание двух равночастотных рядов углов:
//   a, b — plain-массивы значений по возрастанию времени (време/шаг одинаковый),
//   thr — допуск для softSim,
//   band — кап полосы Сакоэ–Чибы в сэмплах (необязательно): если задан,
//          K = max(4, min(12%·max(n,m), band)) — не даёт пути «простить» больше
//          заданного времени (по умолчанию без band K = 12%·max(n,m)).
// Возвращает { meanSim, coverage, meanAbs } или null при недостатке данных.
export function dtwAlign(a, b, thr, band){
  const n = a.length, m = b.length;
  if (n < 2 || m < 2) return null;
  const k12 = Math.round(Math.max(n, m) * 0.12);
  const K = Math.max(4, band == null ? k12 : Math.min(k12, band));
  const INF = 1e18;
  // 2-row DP: храним только текущую и предыдущую строки полосы (стоимость + длина
  // пути). Полная матрица n×m на длинных сессиях (finalDTW по 40-мин видео)
  // укладывала гигабайты — здесь память O(m), время O(n·K).
  let dp = new Array(m), len = new Array(m);   // текущая строка
  let dP = new Array(m), lP = new Array(m);    // предыдущая
  for (let j = 0; j < m; j++){ dp[j] = INF; len[j] = 0; }
  // строка 0: только полоса вправо
  const b1 = Math.min(K, m - 1);
  dp[0] = Math.abs(a[0] - b[0]); len[0] = 1;
  for (let j = 1; j <= b1; j++){ dp[j] = dp[j-1] + Math.abs(a[0] - b[j]); len[j] = j + 1; }
  for (let i = 1; i < n; i++){
    const t = dP; dP = dp; dp = t;
    const tl = lP; lP = len; len = tl;
    const j0 = Math.max(0, i - K), j1 = Math.min(m - 1, i + K);
    const p0 = Math.max(0, i - 1 - K), p1 = Math.min(m - 1, i - 1 + K);
    for (let j = Math.max(0, j0 - 1); j <= j1; j++){ dp[j] = INF; len[j] = 0; }
    for (let j = j0; j <= j1; j++){
      let best = INF, blen = 0;
      const cost = Math.abs(a[i] - b[j]);
      if (j > j0 && dp[j-1] < INF){ best = dp[j-1]; blen = len[j-1]; }
      if (j >= p0 && j <= p1 && dP[j] < INF && dP[j] < best){ best = dP[j]; blen = lP[j]; }
      if (j - 1 >= p0 && j - 1 <= p1 && dP[j-1] < INF && dP[j-1] < best){ best = dP[j-1]; blen = lP[j-1]; }
      if (best < INF){ dp[j] = best + cost; len[j] = blen + 1; }
    }
  }
  // Финальная ячейка (n-1, m-1) достижима в полосе только если |n-1-(m-1)| <= K.
  // Проверка обязательна: при выходе за полосу dp[m-1] держал бы устаревшее
  // значение прошлой строки (ряды переиспользуются), а не INF, как в полной матрице.
  if (Math.abs(n - 1 - (m - 1)) > K || dp[m-1] >= INF) return null;
  const meanAbs = dp[m-1] / len[m-1];
  const meanSim = softSim(meanAbs, thr);
  const coverage = Math.min(1, len[m-1] / Math.max(n, m));
  return { meanSim, coverage, meanAbs };
}

// Лучшее совпадение в окне эталона: поиск по всем [t, val] с единым tie-break.
// Приоритет: выше softSim → меньше дельта угла (точнее фаза) → ближе к ref по времени.
// tie-break на плато softSim (=1) важен: без него первый в окне (самый старый)
// кандидат побеждал бы только за счёт порядка, и при быстрых движениях на
// независимых декодах «лучшая» ошибка раздувалась до 25-39°, хотя рядом лежало
// совпадение с ошибкой в 1-5°.
// Возвращает { m, bestT, bestD } (bestD — |Δ| в ° на лучшем совпадении) или null.
export function bestInWindow(aWin, bVal, thr, ref){
  let m = -Infinity, bestT = null, bestD = Infinity;
  for (const [ta, av] of aWin){
    const d = Math.abs(av - bVal);
    const s2 = softSim(d, thr);
    if (s2 > m ||
        (s2 === m && bestT != null && (d < bestD || (d === bestD && Math.abs(ta - ref) < Math.abs(bestT - ref))))){
      m = s2; bestT = ta; bestD = d;
    }
  }
  if (!isFinite(m)) return null;
  return { m, bestT, bestD };
}

// Живое совпадение с предсказанием лага: лучший softSim по окну эталона.
// Работает в двух режимах:
//   acq=true  — захват лага: ищем по всему окну (в начале эталона соседнего
//               цикла ещё нет, «алиаса» фазы нет) — сходство и tAt честные.
//   acq=false — стейди-стейт: полоса ±band вокруг предсказанного времени
//               (tA - curLag), не даёт «перескочить» в соседний цикл на
//               периодичных движениях и держит % плавным.
// Возвращает { sim, tAt, err } (err — |Δ| в ° на лучшем совпадении) или null,
// если в полосе не нашлось кандидатов (резкий выход из ритма — вызывающий код
// расширяет поиск на всё окно).
export function liveMatch(aWin, bVal, tA, curLag, acq, win, thr){
  if (!aWin || !aWin.length) return null;
  const band = Math.min(0.6, win / 2);
  const ref = (curLag == null || acq) ? tA : tA - curLag;
  const lo = acq ? (tA - win) : ref - band;
  const hi = acq ? tA : (ref + band);
  const inBand = [];
  for (const [ta, av] of aWin) if (ta >= lo && ta <= hi) inBand.push([ta, av]);
  const best = bestInWindow(inBand, bVal, thr, ref);
  if (!best) return null;
  return { sim: best.m, tAt: best.bestT, err: best.bestD };
}