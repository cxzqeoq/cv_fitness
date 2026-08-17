// signature.js — «подпись движения» для сегментации длинных видео.
// Эксперимент debug_seg: проверяем, видна ли смена упражнения как устойчивое
// изменение motion signature (а не «активность/отдых»).
//
// Чистый модуль без DOM: работает и в браузере, и в Node (юнит-тесты).
// Углы берутся из features.js.featAngle (единый источник истины), а геометрия —
// из raw worldLandmarks в тело-локальном фрейме (не зависит от ракурса камеры).
//
// Пайплайн:
//   frames (по кадрам 5 Гц, с реальными временами {time, desc})
//     → mirrorPad()              — зеркальное заполнение краёв
//     → buildWindows()           — окна 5 с / шаг 2 с
//     → madNormalize()           — z=(x−median)/MAD по всему видео
//     → contextDistance(t)       — сравнение левого/правого контекста
//       → changeDistance()       — {D_motion, D_pose, combined}

import { FEATURES } from "./config.js";
import { featAngle } from "./features.js";

// Параметры по умолчанию (переопределяются в debug_seg).
export const WINDOW = 5;   // секунд — контекст/окно подписи
export const STEP = 2;     // секунд — шаг окна
export const RATE_HZ = 5;  // сэмплирование кадров

// Веса групп (начальные, калибруются по размеченным видео):
//   углы 40 / геометрия 40 / темп 10 / поза 10
export const WEIGHTS = { angles: 0.4, geometry: 0.4, tempo: 0.1, pose: 0.1 };

// ── геометрия: списки ключей ──
// Полный набор геометрических дескрипторов (каждый — число на кадр).
export const GEOM_FEATURES = [
  "torsoTilt", "shoulderHipTwist",
  "lArmElev", "lArmAz", "lForElev", "lForAz", "lWristHt",
  "rArmElev", "rArmAz", "rForElev", "rForAz", "rWristHt",
  "lKneeHt", "rKneeHt", "lAnkleHt", "rAnkleHt", "legSpread"
];
// Поза/ориентация — подмножество геометрии (для отдельного сигнала D_pose).
export const POSE_FEATURES = ["torsoTilt", "shoulderHipTwist"];

// Группы для расстояний.
export const GROUPS = {
  angles: FEATURES.map(f => f.key),                       // угловая кинематика
  geometry: GEOM_FEATURES.filter(k => !POSE_FEATURES.includes(k)), // 3D-движение конечностей
  tempo: ["globalRate"],                                  // темп/цикличность
  pose: POSE_FEATURES,                                    // поза/ориентация корпуса
};

// ── мелкие помощники ──
const sub = (a, b) => ({ x: a.x - b.x, y: a.y - b.y, z: (a.z ?? 0) - (b.z ?? 0) });
const dot = (a, b) => a.x * b.x + a.y * b.y + (a.z ?? 0) * (b.z ?? 0);
function norm(a){
  const m = Math.hypot(a.x, a.y, a.z ?? 0);
  return m ? { x: a.x / m, y: a.y / m, z: (a.z ?? 0) / m } : null;
}
const cross = (a, b) => ({
  x: (a.y || 0) * (b.z || 0) - (a.z || 0) * (b.y || 0),
  y: (a.z || 0) * (b.x || 0) - (a.x || 0) * (b.z || 0),
  z: (a.x || 0) * (b.y || 0) - (a.y || 0) * (b.x || 0)
});
// Угол между векторами в градусах (0..180); null при вырождении.
const vang = (a, b) => {
  const n1 = norm(a), n2 = norm(b);
  if (!n1 || !n2) return null;
  const c = dot(n1, n2);
  return Math.acos(Math.max(-1, Math.min(1, c))) * 180 / Math.PI;
};
const pt = (g, i) => g[i] || { x: 0, y: 0, z: 0, v: 0 };
export function median(arr){
  if (!arr.length) return null;
  const a = [...arr].sort((x, y) => x - y);
  const n = a.length;
  return n % 2 ? a[(n - 1) / 2] : (a[n / 2 - 1] + a[n / 2]) / 2;
}
// Робастный размах p90−p10 (устойчив к одиночным «телепортам» точек).
export function robustSpread(arr){
  if (!arr.length) return 0;
  const a = [...arr].sort((x, y) => x - y);
  const p = i => a[Math.min(a.length - 1, Math.max(0, Math.round(i * (a.length - 1))))];
  return p(0.9) - p(0.1);
}

// ── дескрипторы одного кадра из worldLandmarks (33 точки {x,y,z,v}) ──
// Возвращает { valid, angles:{<9 фич>}, geom:{<геометрия>} } или null.
export function frameDescriptors(wmLm){
  if (!wmLm || wmLm.length < 33) return null;
  // Опорные точки: плечи и таз должны быть видны.
  const vis = i => pt(wmLm, i).v ?? 1;
  if (vis(11) < 0.5 || vis(12) < 0.5 || vis(23) < 0.5 || vis(24) < 0.5) return null;

  const lsh = pt(wmLm, 11), rsh = pt(wmLm, 12), lhip = pt(wmLm, 23), rhip = pt(wmLm, 24);
  const S = { x: (lsh.x + rsh.x) / 2, y: (lsh.y + rsh.y) / 2, z: ((lsh.z ?? 0) + (rsh.z ?? 0)) / 2 };
  const H = { x: (lhip.x + rhip.x) / 2, y: (lhip.y + rhip.y) / 2, z: ((lhip.z ?? 0) + (rhip.z ?? 0)) / 2 };

  // Тело-локальный фрейм: up = таз→плечи, lat = плечо-в-плечо, fwd = перпендикуляр.
  const up = norm(sub(S, H));
  const lat = norm(sub(rsh, lsh));
  const fwd = lat && up ? norm(cross(up, lat)) : null;
  if (!up || !lat || !fwd) return null;

  const geom = {};
  // Поза.
  geom.torsoTilt = vang(up, { x: 0, y: 1, z: 0 });                       // 0 стоя … 90 лёжа
  const sl = sub(rsh, lsh), hl = sub(rhip, lhip);
  const tw = vang(sl, hl);                                               // 3D-перекос плеч/таза
  geom.shoulderHipTwist = tw == null ? null : Math.min(tw, 180 - tw);

  // Руки (каждая): возвышение/азимут плеча и предплечья + высота кисти.
  for (const s of ["l", "r"]){
    const sh = s === "l" ? lsh : rsh;
    const el = pt(wmLm, s === "l" ? 13 : 14);
    const wr = pt(wmLm, s === "l" ? 15 : 16);
    const A = sub(el, sh), F = sub(wr, el);
    const elev = vang(A, up);
    geom[s + "ArmElev"] = elev;
    geom[s + "ForElev"] = vang(F, up);
    // Азимут в плоскости (lat, fwd) относительно lat.
    const proj = v => { const upc = dot(v, up); return sub(v, { x: up.x * upc, y: up.y * upc, z: up.z * upc }); };
    const Ap = proj(A);
    const az = (() => {
      if (!fwd) return null;
      const m = Math.hypot(Ap.x, Ap.y, Ap.z ?? 0);
      if (m < 1e-4) return null;
      return Math.atan2(dot(Ap, fwd), dot(Ap, lat)) * 180 / Math.PI;
    })();
    geom[s + "ArmAz"] = az;
    const Fp = proj(F);
    const faz = (() => {
      if (!fwd) return null;
      const m = Math.hypot(Fp.x, Fp.y, Fp.z ?? 0);
      if (m < 1e-4) return null;
      return Math.atan2(dot(Fp, fwd), dot(Fp, lat)) * 180 / Math.PI;
    })();
    geom[s + "ForAz"] = faz;
    geom[s + "WristHt"] = dot(sub(wr, sh), up);                           // м, + вверх
  }

  // Ноги: высоты колена/стопы относительно таза и размах стоп.
  const lkn = pt(wmLm, 25), rkn = pt(wmLm, 26), lan = pt(wmLm, 27), ran = pt(wmLm, 28);
  geom.lKneeHt = dot(sub(lkn, H), up);
  geom.rKneeHt = dot(sub(rkn, H), up);
  geom.lAnkleHt = dot(sub(lan, H), up);
  geom.rAnkleHt = dot(sub(ran, H), up);
  geom.legSpread = Math.hypot(lan.x - ran.x, lan.y - ran.y, (lan.z ?? 0) - (ran.z ?? 0));

  // Углы-фичи (единый источник истины — features.js).
  const angles = {};
  for (const f of FEATURES) angles[f.key] = featAngle(wmLm, f);

  return { valid: true, angles, geom };
}

// ── окно подписи ──
// frames: [{time, desc}] в окне [t0, t1]. Возвращает подпись окна или null.
// Подпись угловых фич: {vel (RMS скорости, °/с), amp (размах), dir (направленность),
// rate (пересечения нуля/с)}; геометрии/позы: {med, rng}.
export function windowSignature(frames, winSec = WINDOW){
  if (!frames || frames.length < 3) return null;
  const sig = {};
  const rates = [];
  for (const f of FEATURES){
    const key = f.key;
    const vals = [], ts = [];
    for (const fr of frames){
      const v = fr.desc && fr.desc.angles[key];
      if (v != null && isFinite(v)){ vals.push(v); ts.push(fr.time); }
    }
    if (vals.length < 3){ sig[key] = null; continue; }
    const amp = robustSpread(vals);
    let velS = 0, velN = 0;
    for (let i = 1; i < vals.length; i++){
      const dt = ts[i] - ts[i - 1];
      if (dt > 0 && isFinite(dt)){ velS += Math.abs((vals[i] - vals[i - 1]) / dt); velN++; }
    }
    const mn = Math.min(...vals), mx = Math.max(...vals);
    const mid = (mn + mx) / 2;
    let zc = 0;
    for (let i = 1; i < vals.length; i++){
      if ((vals[i - 1] - mid) * (vals[i] - mid) < 0) zc++;
    }
    sig[key] = {
      vel: velN ? velS / velN : 0,
      amp,
      dir: amp > 1e-3 ? Math.min(1, Math.abs(vals[vals.length - 1] - vals[0]) / amp) : 0,
      rate: winSec > 0 ? zc / winSec : 0
    };
    rates.push(winSec > 0 ? zc / winSec : 0);
  }
  for (const key of GEOM_FEATURES){
    const vals = [];
    for (const fr of frames){
      const v = fr.desc && fr.desc.geom[key];
      if (v != null && isFinite(v)) vals.push(v);
    }
    if (vals.length < 2){ sig[key] = null; continue; }
    sig[key] = { med: median(vals), rng: robustSpread(vals) };
  }
  const rs = rates.filter(r => isFinite(r));
  sig.globalRate = { med: rs.length ? median(rs) : 0 };
  return sig;
}

// ── постройка окон с зеркальным паддингом краёв ──
export function mirrorPad(frames, winSec = WINDOW, rateHz = RATE_HZ){
  if (!frames.length) return frames;
  const t0 = frames[0].time, t1 = frames[frames.length - 1].time;
  const dt = 1 / rateHz;
  const margin = Math.min(winSec, (t1 - t0) / 2);
  const out = [];
  const nearest = t => {
    let best = frames[0], bd = Infinity;
    for (const fr of frames){ const d = Math.abs(fr.time - t); if (d < bd){ bd = d; best = fr; } }
    return best;
  };
  for (let s = t0 - margin; s < t0 - 1e-6; s += dt) out.push({ time: s, desc: nearest(2 * t0 - s).desc });
  for (const fr of frames) out.push(fr);
  for (let s = t1 + dt; s <= t1 + margin + 1e-6; s += dt) out.push({ time: s, desc: nearest(2 * t1 - s).desc });
  return out;
}

// Окна: [{t0, t1, tMid, sig}].
export function buildWindows(frames, winSec = WINDOW, step = STEP){
  const out = [];
  if (!frames.length) return out;
  const t0 = frames[0].time, t1 = frames[frames.length - 1].time;
  for (let s = t0; s + winSec <= t1 + 1e-6; s += step){
    const sel = frames.filter(f => f.time >= s - 1e-9 && f.time <= s + winSec);
    const sig = windowSignature(sel, winSec);
    if (sig) out.push({ t0: s, t1: s + winSec, tMid: s + winSec / 2, sig });
  }
  return out;
}

// ── нормализация MAD по всем окнам видео ──
// Возвращает norms: {"feature.comp" → {med, mad}}. mad=0 → признак не меняется (неинформативен).
export function madNormalize(windows){
  const norms = {};
  const byComp = {};
  for (const w of windows){
    const sig = w.sig;
    for (const [key, val] of Object.entries(sig)){
      if (!val) continue;
      for (const [c, v] of Object.entries(val)){
        if (!isFinite(v)) continue;
        (byComp[key + "." + c] = byComp[key + "." + c] || []).push(v);
      }
    }
  }
  for (const [ck, arr] of Object.entries(byComp)){
    const med = median(arr);
    const mad = median(arr.map(v => Math.abs(v - med))) * 1.4826;
    norms[ck] = { med, mad };
  }
  return norms;
}

// ── расстояния ──
// Разность по одному признаку (RMS по компонентам, в нормализованном виде).
export function compDiff(key, a, b, norms){
  if (!a || !b) return null;
  let s = 0, n = 0;
  for (const [c, av] of Object.entries(a)){
    const bv = b[c];
    if (!isFinite(av) || !isFinite(bv)) continue;
    const nm = norms[key + "." + c];
    if (!nm || !(nm.mad > 0)) continue;   // константный признак — неинформативен
    const za = (av - nm.med) / nm.mad;
    const zb = (bv - nm.med) / nm.mad;
    s += (za - zb) ** 2; n++;
  }
  return n ? Math.sqrt(s / n) : null;
}
function groupDist(keyList, a, b, norms){
  let s = 0, n = 0;
  for (const k of keyList){
    const d = compDiff(k, a[k], b[k], norms);
    if (d != null){ s += d; n++; }
  }
  return n ? s / n : null;
}

// Расстояние между двумя подписями (сигнатурами окна/контекста).
export function changeDistance(sigL, sigR, norms){
  const dA = groupDist(GROUPS.angles, sigL, sigR, norms);
  const dG = groupDist(GROUPS.geometry, sigL, sigR, norms);
  const dT = groupDist(GROUPS.tempo, sigL, sigR, norms);
  const dP = groupDist(GROUPS.pose, sigL, sigR, norms);
  const w = WEIGHTS;
  const motion = (dA != null || dT != null)
    ? ((dA ?? 0) * w.angles + (dT ?? 0) * w.tempo) / (w.angles + w.tempo) : null;
  const posep = (dG != null || dP != null)
    ? ((dG ?? 0) * w.geometry + (dP ?? 0) * w.pose) / (w.geometry + w.pose) : null;
  const combined = (motion != null && posep != null)
    ? motion * 0.5 + posep * 0.5 : (motion ?? posep);
  return { D_motion: motion, D_pose: posep, combined };
}

// Медиана подписей (покомпонентно) — представитель контекста.
export function medianWin(list){
  if (!list.length) return null;
  const sigs = list.map(w => w.sig).filter(Boolean);
  if (!sigs.length) return null;
  const keys = new Set();
  for (const sg of sigs) for (const k of Object.keys(sg)) keys.add(k);
  const out = {};
  for (const k of keys){
    const comps = new Set();
    for (const sg of sigs) if (sg[k]) for (const c of Object.keys(sg[k])) comps.add(c);
    out[k] = {};
    for (const c of comps){
      const vals = [];
      for (const sg of sigs) if (sg[k] && sg[k][c] != null && isFinite(sg[k][c])) vals.push(sg[k][c]);
      if (vals.length) out[k][c] = median(vals);
    }
    if (!Object.keys(out[k]).length) out[k] = null;
  }
  return out;
}

// Расстояние контекстов вокруг момента t: левое окно [t−ctx, t], правое [t, t+ctx].
// Возвращает {D_motion, D_pose, combined} или null (нечем сравнить).
export function contextDistance(windows, t, norms, ctxSec = WINDOW){
  const left = windows.filter(w => w.tMid >= t - ctxSec && w.tMid < t);
  const right = windows.filter(w => w.tMid >= t && w.tMid <= t + ctxSec);
  const ml = medianWin(left), mr = medianWin(right);
  if (!ml || !mr) return null;
  return changeDistance(ml, mr, norms);
}

// ── кандидаты и сегменты (чистые функции, юнит-тестируются) ──

// Автопорог из перцентилей сигнала: high = pctHigh, low = pctLow.
// Возвращает {high, low} или null, если сигнал слишком мал/вырожден.
export function autothreshold(sig, pctHigh = 0.95, pctLow = 0.7){
  const vals = sig.map(s => s.comb).filter(v => v != null && isFinite(v));
  if (vals.length < 10) return null;
  const p = q => {
    const a = [...vals].sort((x, y) => x - y);
    const pos = q * (a.length - 1);
    const lo = Math.floor(pos), hi = Math.ceil(pos);
    return a[lo] + (a[hi] - a[lo]) * (pos - lo);
  };
  const high = p(pctHigh), low = p(pctLow);
  if (!(high > low)) return null;
  return { high, low };
}

// Кандидаты-интервалы с гистерезисом: вход > high, выход < low.
// sig: [{t, comb, Dm, Dp}]. Возвращает [{startT, endT, peak, peakT, boundary, conf, Dm, Dp}].
// boundary — первый образец на нарастании ≥ base + frac·(peak−base) (frac≈0.7);
// conf — высота подъёма peak−base.
export function detectCandidates(sig, high, low, frac = 0.7){
  const out = [];
  const N = sig.length;
  let state = 0, start = -1;
  for (let i = 0; i < N; i++){
    const c = sig[i].comb;
    if (state === 0){
      if (c != null && c > high){ state = 1; start = i; }
    } else {
      if (c == null || c < low){
        out.push(finish(sig, start, i - 1, frac));
        state = 0; start = -1;
      }
    }
  }
  if (state === 1) out.push(finish(sig, start, N - 1, frac));
  return out;
}

function finish(sig, a, b, frac){
  let base = Infinity;
  for (let i = Math.max(0, a - 3); i <= a; i++)
    if (sig[i].comb != null) base = Math.min(base, sig[i].comb);
  if (!isFinite(base)) base = 0;
  let peak = -Infinity, peakI = a;
  for (let i = a; i <= b; i++){
    const c = sig[i].comb;
    if (c != null && c > peak){ peak = c; peakI = i; }
  }
  if (!isFinite(peak) || peak <= base){
    return { startT: sig[a].t, endT: sig[b].t, peak: peak, peakT: sig[peakI].t,
             boundary: sig[a].t, conf: 0, Dm: null, Dp: null };
  }
  let bi = -1;
  for (let i = a; i <= peakI; i++){
    const c = sig[i].comb;
    if (c != null && c >= base + frac * (peak - base)){ bi = i; break; }
  }
  const boundary = bi < 0 ? sig[a].t : sig[bi].t;
  const p = sig[peakI];
  return { startT: sig[a].t, endT: sig[b].t, peak, peakT: sig[peakI].t,
           boundary, conf: peak - base, Dm: p.Dm, Dp: p.Dp };
}

// Сегменты из кандидатов: границы делят [t0, duration] на интервалы.
// Каждый сегмент заканчивается границей (transition к следующему упражнению),
// последний тянется до конца видео. Возвращает [{n, start, end, boundary, conf, dom}].
export function segmentsFromCandidates(cands, duration, t0 = 0){
  const segs = [];
  let prev = t0;
  let n = 1;
  for (const c of cands){
    if (c.boundary <= prev + 0.05) continue;
    segs.push({ n: n++, start: prev, end: c.boundary, boundary: c.boundary,
                conf: c.conf, dom: dominant(c) });
    prev = c.boundary;
  }
  if (duration - prev > 0.05 || !segs.length){
    segs.push({ n: n++, start: prev, end: duration, boundary: null, conf: null, dom: null });
  }
  return segs;
}

function dominant(c){
  const dm = c.Dm, dp = c.Dp;
  if (dm == null && dp == null) return "—";
  if (dm == null) return "D_pose";
  if (dp == null) return "D_motion";
  if (Math.abs(dm - dp) < 0.05) return "оба";
  return dm > dp ? "D_motion" : "D_pose";
}