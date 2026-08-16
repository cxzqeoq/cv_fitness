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