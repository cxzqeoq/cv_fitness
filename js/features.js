// features.js — математика сравнения движений: углы-фичи, видимость,
// корреляция «формы движения» (форма-гейт), веса по размаху эталона, сессия.
import { FEATURES, I, SYNC_MIN, STATIC_RANGE, ANGLE_Z_W } from "./config.js";
import { $, fadeA, mid, pair, ang3w } from "./utils.js";
import { cmp, s } from "./state.js";

// Включена ли фича на форме (чекбокс chk_<key>).
export function featOn(f){ return $("chk_" + f.key).checked; }

// Точки скелета, от которых считается фича.
export function featCoords(f){
  if (f.tilt)  return [I.LSH, I.RSH, I.LHIP, I.RHIP];
  if (f.spread) return [I.LSH, I.RSH, I.LWR, I.RWR];
  if (f.twist) return [I.LSH, I.RSH, I.LHIP, I.RHIP];
  return [f.a, f.b, f.c];
}

// Видимость фичи в позе (минимальная по её точкам; минимум 0.05).
export function covOf(g, f){
  let mn = 1;
  for (const i of featCoords(f)){
    const p = pair(g, i);
    const a = fadeA(p.v ?? 1);
    if (a <= 0) return 0;
    mn = Math.min(mn, a);
  }
  return Math.max(mn, 0.05);
}

// Размах ряда [t, val] и среднее.
export function rangeOf(arr){
  if (!arr || arr.length < 2) return 0;
  let mn = 1e9, mx = -1e9;
  for (const [, v] of arr){ if (v < mn) mn = v; if (v > mx) mx = v; }
  return mx - mn;
}
export function meanOf(arr){
  if (!arr || !arr.length) return null;
  let s = 0;
  for (const [, v] of arr) s += v;
  return s / arr.length;
}

// Пирсон между двумя рядами; 0-дисперсия → 1 (сигнала нет — не «шумная» фича).
export function pearson(pa, pb){
  const n = pa.length; if (n < 3) return 1;
  let ma = 0, mb = 0;
  for (let i = 0; i < n; i++){ ma += pa[i]; mb += pb[i]; }
  ma /= n; mb /= n;
  let sxx = 0, syy = 0, sxy = 0;
  for (let i = 0; i < n; i++){
    const dx = pa[i] - ma, dy = pb[i] - mb;
    sxx += dx*dx; syy += dy*dy; sxy += dx*dy;
  }
  const den = Math.sqrt(sxx * syy);
  if (!den) return 1;
  return sxy / den;
}

// «Пытается ли человек повторять» по форме движения: макс. скрелированность B с A
// на лучшем лаге (в сэмплах — и файл со сдвигом, и камера с латентностью
// укладываются в lag search). Возвращает 2, если сигнала нет (мало точек / эталон
// почти статичен) — тогда фичу не гейтим.
export function syncGate(fkey, winSec){
  const sels = cmp.samples.slice(-80);
  const arrA = [], arrB = [], dts = [];
  for (let i = 0; i < sels.length; i++){
    const sm = sels[i];
    const a = sm.a[fkey], b = sm.b[fkey];
    if (a != null && b != null){ arrA.push(a); arrB.push(b); }
    if (i > 0){
      const d = sm.tA - sels[i-1].tA;
      if (d > 0 && d < 1) dts.push(d);
    }
  }
  const dbg = { n: sels.length, len: arrA.length, win: winSec };
  if (arrA.length < 16) return 2;
  let mx = -Infinity, mn = Infinity;
  for (const x of arrA){ if (x > mx) mx = x; if (x < mn) mn = x; }
  if (mx - mn < 8) return 2; // удержание/полу-статичная фича — не по форме судить
  if (!dts.length) return 2;
  dts.sort((x, y) => x - y);
  const dt = dts[Math.floor(dts.length / 2)];
  // лаг-поиск должен покрывать ту задержку, которую прощает DTW/выравнивание
  // (файл со сдвигом 1с, камера с латентностью ~0.5с) — иначе гейт «не видит»
  // правильного лага и зануляет честные сэмплы.
  const wSec = Math.max(winSec || 2, 2);
  const W = Math.min(Math.floor(arrA.length / 2), Math.max(4, Math.round(wSec / dt)));
  let best = -2, bestLag = null;
  for (let lag = -W; lag <= W; lag++){
    const pa = [], pb = [];
    for (let i = 0; i < arrA.length; i++){
      const j = i + lag;
      if (j < 0 || j >= arrB.length) continue;
      pa.push(arrA[i]); pb.push(arrB[j]);
    }
    if (pa.length < 12) continue;
    const c = pearson(pa, pb);
    if (c > best){ best = c; bestLag = lag; }
  }
  dbg.dt = +dt.toFixed(4); dbg.W = W; dbg.best = best === -2 ? null : +best.toFixed(3); dbg.lag = bestLag;
  return best;
}

// Угол одной фичи в позе (по индексам точек фичи).
export function featAngle(g, f){
  if (f.tilt){
    const neck = mid(pair(g,I.LSH), pair(g,I.RSH));
    const pelv = mid(pair(g,I.LHIP), pair(g,I.RHIP));
    const dx=neck.x-pelv.x, dy=neck.y-pelv.y, dz=(neck.z??0)-(pelv.z??0);
    const m=Math.hypot(dx,dy,dz);
    if (!m) return null;
    return Math.acos(Math.max(-1, Math.min(1, (-dy)/m))) * 180/Math.PI;
  }
  if (f.spread){
    const sh = mid(pair(g,I.LSH), pair(g,I.RSH));
    return ang3w(pair(g,I.LWR), sh, pair(g,I.RWR), ANGLE_Z_W);
  }
  if (f.twist){
    // Кручение корпуса: угол между плечевой и тазовой линиями в горизонтальной
    // плоскости (world XZ). Работает только в метровом world-фрейме: в проекции
    // камеры эта же величина зависела бы от ракурса.
    const ls=pair(g,I.LSH), rs=pair(g,I.RSH), lh=pair(g,I.LHIP), rh=pair(g,I.RHIP);
    const sx=rs.x-ls.x, sz=(rs.z??0)-(ls.z??0);
    const hx=rh.x-lh.x, hz=(rh.z??0)-(lh.z??0);
    const ms=Math.hypot(sx,sz), mh=Math.hypot(hx,hz);
    if (!ms || !mh) return null;
    const cos=(sx*hx+sz*hz)/(ms*mh);
    return Math.acos(Math.max(-1, Math.min(1, cos))) * 180/Math.PI;
  }
  const ok = [f.a,f.b,f.c].every(i => fadeA(pair(g,i).v ?? 1) > 0);
  if (!ok) return null;
  return ang3w(pair(g,f.a), pair(g,f.b), pair(g,f.c), ANGLE_Z_W);
}

// Все активные фичи позы.
export function cmpFeatures(g){
  const out = {};
  for (const f of FEATURES) out[f.key] = featOn(f) ? featAngle(g, f) : null;
  return out;
}

// Окно сравнения (с): камера — минимум 1 с (латентность скелета ~0.5с),
// файл — как ползунок (по умолчанию 0.5 с).
export function currentWin(){
  const el = $("lagWin");
  let v = (el && el.value != null) ? Number(el.value) : (s.camOn ? 2 : 0.5);
  if (s.camOn && v < 1) v = 1;
  return v;
}

// Вес фичи по реальному размаху эталона (профиль анализа):
// нерабочие/почти-статические углы меньше шумят.
export function refW(f){
  const p = cmp.aProf && cmp.aProf.per ? cmp.aProf.per[f.key] : null;
  if (!p || p.rng == null || !cmp.aProf.maxRng) return 1;
  return Math.max(0.15, p.rng / cmp.aProf.maxRng);
}
export function featWeights(){
  const out = {};
  for (const f of FEATURES) out[f.key] = featOn(f) ? refW(f) : 0;
  return out;
}

// Среднее сходство за сессию по фичам (в процентах).
export function computeSession(){
  if (!cmp.framesTotal) return null;
  let sSum = 0, sN = 0;
  for (const f of FEATURES){
    if (!featOn(f) || cmp.featSum[f.key] == null) continue;
    sSum += cmp.featSum[f.key] / cmp.framesTotal * 100;
    sN++;
  }
  return sN ? sSum / sN : null;
}