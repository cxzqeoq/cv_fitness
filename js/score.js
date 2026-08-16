// score.js — очки, тиры, комбо, повторы/фазы/удержания и графики углов.
import { TIERS, TIER_MAX, EXERCISES, FEATURES, STATIC_RANGE } from "./config.js";
import { $, fmtN, say2 } from "./utils.js";
import { cmp, s } from "./state.js";
import { featOn, rangeOf } from "./features.js";

// ── первичная фича (детектор упражнения) ──
function aAngleSeries(key){
  const out = [];
  for (const sm of cmp.samples){
    const v = sm.a[key];
    if (v != null) out.push([sm.tA, v]);
  }
  return out;
}
function rangeOfKey(key){
  const arr = aAngleSeries(key);
  return rangeOf(arr);
}

// Какая фича «ведёт» упражнение: по пресету (например knee → lKnee/rKnee)
// или по максимальному размаху среди включённых фич.
export function resolvePrimary(){
  const sel = ($("exSel").value) || "auto";
  const ex = EXERCISES[sel] || EXERCISES.auto;
  let cand;
  if (sel !== "auto" && ex.primary !== "top"){
    cand = FEATURES.filter(f => f.key.startsWith(ex.primary) && featOn(f));
  } else {
    cand = FEATURES.filter(f => featOn(f));
  }
  if (!cand.length) cand = FEATURES.filter(f => featOn(f));
  let best = null, br = -1;
  for (const f of cand){
    const r = rangeOfKey(f.key);
    if (r > br){ br = r; best = f.key; }
  }
  return best || (cand[0] ? cand[0].key : null);
}

// Тип упражнения: cycle (повторы) / flow (фазы) / hold (удержание).
// Авто-детект — по числу экстремумов первичной фичи A.
export function detectExerciseType(){
  const sel = ($("exSel").value) || "auto";
  if (sel !== "auto"){
    cmp.exType = (sel === "yogaHold" || sel === "plank") ? "hold" : (sel === "yogaFlow" ? "flow" : "cycle");
    return;
  }
  if (cmp.samples.length < 20) return;
  const key = cmp.primary || resolvePrimary();
  if (!key) return;
  const arr = aAngleSeries(key);
  // STATIC_RANGE=1.5° порог «застывшей» фичи; ×4 — минимум амплитуды, чтобы считаться циклом
  if (rangeOf(arr) < STATIC_RANGE * 4){ cmp.exType = "hold"; return; }
  let ext = 0, dir = 0, prev = null;
  for (const [t, v] of arr){
    if (prev == null){ prev = v; continue; }
    const d = v - prev;
    if (Math.abs(d) > 25){
      if (dir === 0 || (d > 0 && dir < 0) || (d < 0 && dir > 0)) ext++;
      dir = d > 0 ? 1 : -1;
    }
    prev = v;
  }
  cmp.exType = ext >= 3 ? "cycle" : "flow";
  if (cmp.tag !== cmp.exType){
    cmp.tag = cmp.exType;
    say2(`режим: ${cmp.exType === "cycle" ? "повторы" : cmp.exType === "flow" ? "поток (фазы)" : "удержание"}`);
  }
}

// ── повторы/фазы (live): детектор экстремумов первичной фичи B ──
// Каждый завершённый цикл (пик→впадина→пик) суммируется в scoreRep.
function repFeed(key, t, val){
  const d = (cmp.detB[key] = cmp.detB[key] || { ext: [], lastVal: null, lastType: null });
  const amp = Math.max(4, (Number($("repAmp").value) || cmp.amp || 25)) * 0.5;
  if (d.lastVal == null){ d.lastVal = val; return; }
  if (d.lastType == null){
    if (Math.abs(val - d.lastVal) >= amp){
      const type = val > d.lastVal ? "peak" : "valley";
      d.ext.push({ type, t, val });
      d.lastType = type; d.lastVal = val;
    }
    return;
  }
  const wantValley = d.lastType === "peak";
  const flip = wantValley ? (val <= d.lastVal - amp) : (val >= d.lastVal + amp);
  if (flip){
    const type = wantValley ? "valley" : "peak";
    d.ext.push({ type, t, val });
    d.lastType = type; d.lastVal = val;
    const x = d.ext;
    if (x.length >= 3){
      const e0 = x[x.length - 3], e2 = x[x.length - 1];
      if (e0.type === e2.type){
        scoreRep(e0.t, e2.t);
        x.splice(x.length - 3, 2);
      }
    }
  } else {
    if (wantValley && val > d.lastVal) d.lastVal = val;
    else if (!wantValley && val < d.lastVal) d.lastVal = val;
  }
}
function scoreRep(startB, endB){
  let s = 0, w = 0, has = false;
  for (const sm of cmp.samples){
    if (sm.tB >= startB && sm.tB <= endB){
      if (sm.sim != null && sm.sim >= 0){ s += sm.sim * (sm.wsum || 1); w += (sm.wsum || 1); has = true; }
    }
  }
  const pct = has ? s / w * 100 : null;
  cmp.repScores.push({ label: (cmp.exType === "flow" ? "Ф" : "R") + (cmp.repScores.length + 1), pct });
}

// Чипы повторов под счётом.
export function renderReps(winS, last){
  const el = $("repChips");
  if (!el) return;
  if (cmp.exType === "hold" || cmp.exType == null || !cmp.samples.length){
    el.hidden = true; return;
  }
  el.hidden = false;
  if (last && cmp.primary){
    const kb = last.b[cmp.primary];
    if (kb != null) repFeed(cmp.primary, last.tB, kb);
  }
  const pre = cmp.exType === "flow" ? "Ф" : "R";
  let html = "";
  for (let i = 0; i < cmp.repScores.length; i++){
    const r = cmp.repScores[i];
    html += `<span class="rp${r.pct == null ? " pend" : ""}">${r.label} ${r.pct == null ? "…" : Math.round(r.pct) + "%"}</span>`;
  }
  el.innerHTML = html + `<span class="rp act">${pre}${cmp.repScores.length + 1}…</span>`;
}

// Панель удержания: длительность, ошибка угла, дрожь.
export function renderHold(winS){
  const el = $("holdPanel");
  if (!el) return;
  if (cmp.exType !== "hold" || !winS.length){ el.hidden = true; return; }
  el.hidden = false;
  const last = winS[winS.length - 1] || {};
  const thr = Number($("thr").value);
  let es = 0, en = 0;
  for (const sm of winS){ if (sm.sim != null){ es += (1 - sm.sim) * thr; en++; } }
  const err = en ? es / en : null;
  let sum = 0, sum2 = 0, cn = 0;
  if (cmp.primary){
    for (const sm of winS){
      const b = sm.b[cmp.primary];
      if (b != null){ sum += b; sum2 += b * b; cn++; }
    }
  }
  const wob = cn > 1 ? Math.sqrt(Math.max(0, sum2 / cn - (sum / cn) * (sum / cn))) : 0;
  const mm = Math.floor((last.tA || 0) / 60), ss = Math.round((last.tA || 0) % 60);
  el.innerHTML = `длительность <b>${mm}:${(ss < 10 ? "0" : "") + ss}</b>` +
    (err != null ? ` · ошибка угла <b>${err.toFixed(1)}°</b>` : "") +
    (cn ? ` · дрожь <b>${wob.toFixed(1)}°</b>` : "");
}

// Число счёта / комбо / тир на странице.
export function renderScore(){
  const n = $("scoreNum"), mx = $("scoreMaxV"), c = $("combo"), t = $("tier");
  if (n) n.textContent = fmtN(cmp.score);
  if (mx) mx.textContent = "/" + fmtN(TIER_MAX);
  if (c) c.textContent = cmp.combo > 0 ? "Комбо ×" + cmp.combo : "";
  if (t){
    if (cmp.tier){
      t.textContent = cmp.tier.name;
      t.style.color = cmp.tier.col;
      t.style.borderColor = cmp.tier.col;
      t.classList.add("on");
    } else {
      t.textContent = "";
      t.classList.remove("on");
    }
  }
}

// ── графики углов по времени (A — зелёный, B — оранжевый) ──
export function buildCharts(){
  $("charts").innerHTML = "";
  s.chartCV = {};
  for (const f of FEATURES){
    if (!featOn(f)) continue;
    const box = document.createElement("div"); box.className = "chart";
    const t = document.createElement("div"); t.className = "ctitle";
    t.innerHTML = `<span>${f.name}</span><b id="chartv_${f.key}"></b>`;
    const ca = document.createElement("canvas"); ca.width = 320; ca.height = 56;
    box.appendChild(t); box.appendChild(ca);
    $("charts").appendChild(box);
    s.chartCV[f.key] = ca;
  }
}
export function drawCharts(){
  const n = cmp.samples.length; if (!n) return;
  const thr = Number($("thr").value);
  for (const f of FEATURES){
    const cvx = s.chartCV[f.key]; if (!cvx) continue;
    const cr = cvx.getContext("2d"); const W = cvx.width, H = cvx.height;
    cr.clearRect(0,0,W,H);
    const arrA = [], arrB = [];
    for (const sm of cmp.samples){
      arrA.push(sm.a[f.key] ?? null);
      arrB.push(sm.b[f.key] ?? null);
    }
    let lo = Infinity, hi = -Infinity;
    for (const x of arrA) if (x != null){ lo=Math.min(lo,x); hi=Math.max(hi,x); }
    for (const x of arrB) if (x != null){ lo=Math.min(lo,x); hi=Math.max(hi,x); }
    if (!isFinite(lo)){ lo = 0; hi = 180; }
    else { const pad=(hi-lo)*0.12 || 8; lo-=pad; hi+=pad; }
    const Y = val => H - ((val - lo)/(hi - lo)) * H;
    for (let i = 1; i < n; i++){
      const a=arrA[i], b=arrB[i];
      if (a == null || b == null) continue;
      const x0=(i-1)/(n-1)*W, x1=i/(n-1)*W;
      const y0=Y(a), y1=Y(b);
      cr.fillStyle = Math.abs(a-b) > thr ? "rgba(255,79,79,.28)" : "rgba(255,255,255,.06)";
      cr.fillRect(x0, Math.min(y0,y1), Math.max(x1-x0, 1), Math.max(Math.abs(y1-y0), 1));
    }
    const plot = (arr, col) => {
      cr.strokeStyle = col; cr.lineWidth = 1.5; cr.beginPath();
      arr.forEach((val,i) => {
        if (val == null) return;
        const x = i/(n-1)*W, y = Y(val);
        i ? cr.lineTo(x,y) : cr.moveTo(x,y);
      });
      cr.stroke();
    };
    plot(arrA, "#c6ff2e"); plot(arrB, "#ff9f1a");
    const lb = $("chartv_" + f.key);
    if (lb) lb.textContent = arrA[n-1] != null ? arrA[n-1].toFixed(0)+"°" : "";
  }
}