// qc.js — «качество измерения»: робастная оценка шума угла и утилиты.
// Чистый модуль без DOM: только числа и массивы, юнитится в Node.
// σ_noise — разброс оценки угла фичи на этом устройстве/освещении: из
// остатков val − median3 по коротким окнам (кривизна движения мизерна) через
// MAD/0.6745. Используется (в Фазе 3) как шум-осведомлённое расширение допуска
// и «потолок честности» — чтобы один и тот же результат читался одинаково
// на разных камерах.

// Медиана массива чисел (пустой → 0).
export function med(xs){
  if (!xs || !xs.length) return 0;
  const s = xs.slice().sort((a, b) => a - b);
  const n = s.length;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}

// Медиана последних `k` значений истории [[t, val], …]. null, если их меньше k.
export function medianTail(h, k){
  if (!h || h.length < k) return null;
  const vals = [];
  for (let i = h.length - k; i < h.length; i++) vals.push(h[i][1]);
  return med(vals);
}

// Робастное σ из остатков: 1.4826 · MAD (медиана |x − медиана|).
// Устойчиво к одиночным выбросам, в отличие от обычного std.
export function sigmaRobust(residuals){
  if (!residuals || residuals.length < 3) return 0;
  const m = med(residuals);
  const devs = residuals.map(x => Math.abs(x - m));
  return 1.4826 * med(devs);
}

// ── Фаза 3: честная шкала (гауссиан + потолок от σ_noise) ──
// Базовая форма: строгий гауссиан σ = tol/1.5 (ошибка == tol даёт ~32%).
// Шум камеры расширяет эффективный допуск: σ_eff² = (tol/1.5)² + σn².
// «Потолок» — сходство идеального повтора при этом шуме (|Δ| ≈ √2·σn, разность
// двух независимых измерений) → итог = sim/потолок (0..1): 100% = твой максимум
// при этом устройстве/освещении, один и тот же результат на разных камерах.

// exp(−err²/2σ²): 0→1, err==σ→0.607, err==2σ→0.135; σ≤0 → 0.
export function gaussSim(err, sigma){
  if (err == null || !(sigma > 0)) return 0;
  return Math.exp(-(err * err) / (2 * sigma * sigma));
}

// Эффективный допуск фичи: шум-расширенный базовый σ.
export function sigmaEffFrom(thr, sigma, factor){
  return Math.hypot(thr / factor, sigma);
}

// Потолок честности: simGauss при ошибке идеального повтора √2·σn.
// Кламп снизу CEIL_FLOOR — чтобы нормировка не взрывалась при экстремальном шуме.
export function ceilFrom(thr, sigma, factor, errK, floor){
  const se = sigmaEffFrom(thr, sigma, factor);
  return Math.max(floor, gaussSim(errK * sigma, se));
}

// Итоговая оценка фичи: sim/потолок, 0..1.
export function simReported(err, thr, sigma, factor, errK, floor){
  const se = sigmaEffFrom(thr, sigma, factor);
  const ceil = ceilFrom(thr, sigma, factor, errK, floor);
  if (ceil <= 0) return 0;
  return Math.min(1, gaussSim(err, se) / ceil);
}