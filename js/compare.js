// compare.js — режим «Сравнение»: эталон A против повтора B (файл или камера телефона).
// Сравнение идёт по 8 углам-фичам со скользящим окном (+ DTW), плюс игра-счёт,
// повторы/удержания, анализ эталона, просмотр и экспорт CSV.
import { TIER_MAX, FEATURES, EXERCISES, STATIC_RANGE, SYNC_MIN, SYNC_HARD, SYNC_REL_MIN_SPS, SMOOTH_TELEPORT, DEFAULT_SIGMA, SIGMA_WIN_S, SIGMA_MIN_RESID, SIGMA_FREEZE_S, SIGMA_SPIKE, SIGMA_EMA, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR } from "./config.js";
import { $, say2, diag, beep, fmtN, softSim, tierFor, mediaErrText, ensureMeta, playVideo } from "./utils.js";
import { makeLandmarker } from "./model.js";
import { s, cmp } from "./state.js";
import { featOn, cmpFeatures, covOf, syncGate, refW, currentWin, rangeOf, computeSession, pearson, featWeights } from "./features.js";
import { renderScore, renderReps, renderHold, buildCharts, drawCharts, detectExerciseType, resolvePrimary } from "./score.js";
import { drawSkelC, drawCmpBg } from "./render.js";
import { dtwAlign, liveMatch, bestInWindow } from "./dtw.js";
import { med, medianTail, sigmaRobust, simReported } from "./qc.js";

const vA = $("vA"), vB = $("vB"), cvA = $("cvA"), cvB = $("cvB");
const ctxA = cvA.getContext("2d", { alpha:true }), ctxB = cvB.getContext("2d", { alpha:true });

// Сглаживание позы: не доверяем резким скачкам (>0.22); raw — просто копия.
function cmpSmooth(prev, lm, a, raw){
  if (!prev || !prev.length || raw) return lm.map(p => ({ x:p.x, y:p.y, z:p.z, v: p.visibility ?? 1 }));
  return lm.map((p,j) => {
    const vn = p.visibility ?? 1;
    const o = prev[j];
    if (vn < VIS_LO) return o;
    if (o.v < VIS_LO) return { x:p.x, y:p.y, z:p.z, v: vn };
    if (Math.hypot(p.x - o.x, p.y - o.y) > SMOOTH_TELEPORT) return { x:p.x, y:p.y, z:p.z, v: vn };
    return { x:a*o.x+(1-a)*p.x, y:a*o.y+(1-a)*p.y, z:a*(o.z??0)+(1-a)*(p.z??0), v:Math.max(o.v, vn) };
  });
}
import { VIS_LO } from "./config.js";

// Мировые (метрические) точки фич с видимостью: у worldLandmarks visibility есть,
// но на всякий случай страхуемся значением из 2D-точки того же индекса.
function worldOf2(wm, lm){
  return wm.map((p, j) => ({
    x:p.x, y:p.y, z:p.z,
    v: p.visibility ?? (lm && lm[j] && lm[j].visibility) ?? 1
  }));
}
// Источник для расчёта фич: worldLandmarks (метры), если детектор их отдал,
// иначе 2D-ландмарки (деградация на нестандартном рантайме).
function featSource(wm, lm){ return (wm && wm.length) ? worldOf2(wm, lm) : lm; }

// Падение детекции канала: по кол-ву подряд — сигнал и переключение на CPU.
function noteFail(key, er, n){
  const msg = (er && (er.message || er.name)) || er || "ошибка";
  diag(`cmp ${key}: ${msg} (#${n})`, true);
  say2(`Канал ${key}: детекция падает (#${n})`, true);
  if (n >= 6 && !cmp["fb"+key]){
    cmp["fb"+key] = true;
    beep(440, 0.2);
    makeLandmarker("CPU").then(lm => {
      if (key === "A"){ if (s.lmA) s.lmA.close(); s.lmA = lm; cmp.failsA = 0; }
      else { if (s.lmB) s.lmB.close(); s.lmB = lm; cmp.failsB = 0; }
      say2(`Канал ${key} переключён на CPU.`);
    }).catch(err => say2(`CPU ${key}: ${err.message}`, true));
  }
}

// Один кадр живого сравнения: детект A и B, отрисовка, накопление сэмпла.
function cmpTick(){
  if (!cmp.running) return;
  let newA = false, newB = false;
  try {
    const style = $("styleC").value;
    const bg = style === "ghost" ? "ghost" : $("bgC").value;
    const smA = Number($("smC").value)/100;
    drawCmpBg(ctxA, cvA.width, cvA.height, vA, bg);
    drawCmpBg(ctxB, cvB.width, cvB.height, vB, bg);

    if (vA.readyState >= 2 && vA.currentTime !== cmp.lastTimeA){
      cmp.lastTimeA = vA.currentTime;
      let ts = cmp.tsA < 0 ? Math.round(vA.currentTime * 1000)
                           : Math.max(cmp.tsA + 1, Math.round(vA.currentTime * 1000));
      if (ts - cmp.tsA > 500 && cmp.tsA >= 0){ cmp.smoothA = []; cmp.smoothA3D = []; }
      cmp.tsA = ts;
      if (s.lmA) s.lmA._lastTs = ts;
      try {
        const fa = s.lmA.detectForVideo(vA, ts);
        if (fa?.landmarks?.length){
          cmp.smoothA = cmpSmooth(cmp.smoothA, fa.landmarks[0], smA);
          cmp.smoothA3D = cmpSmooth(cmp.smoothA3D, featSource(fa.worldLandmarks?.[0], fa.landmarks[0]), smA);
          newA = true; cmp.failsA = 0;
          if (cmp.audioPending){ cmp.audioPending = false; vA.muted = s.sound.muted; }
        }
      }
      catch(er){ cmp.failsA++; noteFail("A", er, cmp.failsA); }
    }

    let doB = false, tsB = 0;
    if (vB.readyState >= 2){
      if (s.camOn){
        if (cmp.bNew || cmp.bNoRVC){ // детект строго на новый кадр камеры (rVFC) — без лишнего инференса на каждый rAF
          cmp.bNew = false;
          tsB = ++cmp.camTS;
          if (s.lmB) s.lmB._lastTs = tsB;
          doB = true;
        }
      } else if (vB.currentTime !== cmp.lastTimeB){
        cmp.lastTimeB = vB.currentTime;
        tsB = cmp.tsB < 0 ? Math.round(vB.currentTime * 1000)
                          : Math.max(cmp.tsB + 1, Math.round(vB.currentTime * 1000));
        if (tsB - cmp.tsB > 500 && cmp.tsB >= 0){ cmp.smoothB = []; cmp.smoothB3D = []; }
        cmp.tsB = tsB;
        if (s.lmB) s.lmB._lastTs = tsB;
        doB = true;
      }
    }
    if (doB){
      try {
        const fb = s.lmB.detectForVideo(vB, tsB);
        if (fb?.landmarks?.length){
          const smB = s.camOn ? Math.max(0.35, smA) : smA;
          cmp.smoothB = cmpSmooth(cmp.smoothB, fb.landmarks[0], smB);
          cmp.smoothB3D = cmpSmooth(cmp.smoothB3D, featSource(fb.worldLandmarks?.[0], fb.landmarks[0]), smB);
          newB = true; cmp.failsB = 0;
        }
      }
      catch(er){ cmp.failsB++; noteFail("B", er, cmp.failsB); }
    }
    if (newA || newB) cmp.frames++;

    const colA = "#c6ff2e", colB = "#ff9f1a";
    const va = cmp.smoothA3D.length ? cmpFeatures(cmp.smoothA3D) : null;
    const vb = cmp.smoothB3D.length ? cmpFeatures(cmp.smoothB3D) : null;
    if (va) drawSkelC(ctxA, cvA.width, cvA.height, colA, cmp.smoothA, $("showA").checked, va);
    if (vb) drawSkelC(ctxB, cvB.width, cvB.height, colB, cmp.smoothB, $("showA").checked, vb);

    if (cmp.armed && newA && newB) cmpAddSample(va, vb);
    if (++cmp.everyN % 6 === 0){ cmpUpdateUI(); drawCharts(); }
  } catch(err){
    diag("cmp: " + ((err && err.message) || err), true);
  } finally {
    if (vA.ended || vB.ended){ cmpStop(); return; }
    requestAnimationFrame(cmpTick);
  }
}

// Накопление одного сэмпла сравнения: окно A, DTW/лаг, форма-гейт и веса.
function cmpAddSample(va, vb){
  if (!va && !vb) return;
  if (!s.camOn && performance.now() < cmp.warmUntil) return;
  va = va || {}; vb = vb || {};
  const thr = Number($("thr").value);
  const tA = vA.currentTime, tB = s.camOn ? performance.now()/1000 : vB.currentTime;
  const win = currentWin();
  const sm = { tA, tB, a:{}, b:{}, s:{}, w:{}, e:{}, tA_:{}, moved:false, sim:0, wsum:0 };
  // Удержание последнего валидного угла при кратковременной пропаже точки
  // (микропотери видимости) — дырки в данных не рвут DTW/поиск и не роняют покрытие.
  const heldB = {};
  const hB = (cmp.bHist = cmp.bHist || {});   // длинная история B по фичам (okno = win) — для liveMatch
  const hS = (cmp.bHistS = cmp.bHistS || {}); // короткая история B (~0.5c) — для проверки «застыл/двигается»
  for (const f of FEATURES){
    let kb = vb[f.key];
    if (kb == null){
      const lastB = (hB[f.key] || []).slice(-1)[0];
      if (lastB && tB - lastB[0] <= 0.25) kb = lastB[1]; // 0.25с — не дольше, иначе «заморозка» искажает живой счёт
    }
    heldB[f.key] = kb;
    if (kb == null) continue;
    (hB[f.key] = hB[f.key] || []).push([tB, kb]);
    const h = hB[f.key];
    while (h.length > 1 && h[h.length-1][0] - h[0][0] > win) h.shift();
    if (h.length > 120) h.shift(); // верхний кап: очень длинные окна/редкие фичи не должны копить память
    (hS[f.key] = hS[f.key] || []).push([tB, kb]);
    const hs = hS[f.key];
    while (hs.length > 1 && hs[hs.length-1][0] - hs[0][0] > 0.5) hs.shift();
    if (hs.length > 60) hs.shift();
    // σ_noise (Фаза 1): остаток val − median3 по короткому окну B. Окно ≤ SIGMA_WIN_S —
    // кривизна движения мизерна, остаток шум-доминирован → MAD/0.6745 даёт робастный
    // разброс оценки угла на этом устройстве. Спайки/телепорты не копим.
    if (!cmp.sigmaFrozen[f.key] && hs.length >= 4 && tB - hs[hs.length-3][0] <= SIGMA_WIN_S){
      const prevVal = hs[hs.length-2][1];
      if (Math.abs(kb - prevVal) <= SIGMA_SPIKE){
        const m3 = medianTail(hs, 3);
        if (m3 != null){
          const ring = (cmp.resid[f.key] = cmp.resid[f.key] || []);
          ring.push(kb - m3);
          if (ring.length > 400) ring.shift();
          if (ring.length >= SIGMA_MIN_RESID){
            const sig = sigmaRobust(ring);
            cmp.sigmaNoise[f.key] = cmp.sigmaNoise[f.key] == null
                ? sig
                : cmp.sigmaNoise[f.key] * (1 - SIGMA_EMA) + sig * SIGMA_EMA;
          }
        }
      }
    }
    if (tA >= SIGMA_FREEZE_S && !cmp.sigmaFrozen[f.key]){
      cmp.sigmaFrozen[f.key] = true;
      if (cmp.sigmaNoise[f.key] == null) cmp.sigmaNoise[f.key] = DEFAULT_SIGMA;
    }
  }
  // статичность B по фичам (за последние ~0.5с)
  const bStuck = {};
  let movedN = 0;
  for (const k in hS){
    const h = hS[k];
    if (h.length < 2) continue;
    if (rangeOf(h) < STATIC_RANGE) bStuck[k] = true;
    else movedN++;
  }
  const moved = movedN > 0;
  // форма-гейт: если человек НЕ повторяет траекторию A (делает другое упражнение), фича → 0,
  // даже если углы случайно близки. Мягкий допуск прощает неточность, но не «не то движение».
  const gates = {};
  for (const f of FEATURES){
    if (!featOn(f)) continue;
    const g = syncGate(f.key, win);
    gates[f.key] = g;
    cmp.gate[f.key] = g;
    // сессионный средний gate: только осмысленные корреляции (g===2 — «нет
    // сигнала/не судить» и не должен раздувать среднее до порога гейта)
    if (g !== 2){
      cmp.gateSum[f.key] = (cmp.gateSum[f.key] || 0) + g;
      cmp.gateN[f.key] = (cmp.gateN[f.key] || 0) + 1;
    }
  }
  const gated = k => { const g = gates[k]; return g !== 2 && g < SYNC_MIN; };
  let any = false;
  for (const f of FEATURES){
    if (!featOn(f)) continue;
    const arr = (cmp.aWin[f.key] = cmp.aWin[f.key] || []);
    let ka = va[f.key];
    if (ka == null){
      const lastA = arr.slice(-1)[0];
      if (lastA && tA - lastA[0] <= 0.25) ka = lastA[1]; // то же удержание, что у B — окно 0.25с
    }
    if (ka != null){
      arr.push([tA, ka]);
      while (arr.length > 1 && tA - arr[0][0] > win) arr.shift();
      if (arr.length > 80) arr.shift();
    } else if (arr.length && tA - arr[arr.length-1][0] > 3) arr.length = 0;
    const kb = heldB[f.key];
    let bestSim = null, bestT = null, bestD = null;
    if (kb != null && arr.length){
      if (s.camOn){
        // камерный путь: выбор выравнивания — softSim по окну A, полоса вокруг
        // прогнозируемого лага (acq=захват — по всему окну, пока лаг не сошёлся)
        const dw = liveMatch(arr, kb, tA, cmp.curLagA, cmp.lagAcq, win, thr);
        if (dw){ bestT = dw.tAt; bestD = dw.err; }
        else {
          // полоса пуста (резко выпал из ритма) — резерв: поиск по всему окну
          const best = bestInWindow(arr, kb, thr, tA - (cmp.curLagA ?? 0));
          if (best){ bestT = best.bestT; bestD = best.bestD; }
        }
      } else {
        const best = bestInWindow(arr, kb, thr, tA);
        if (best){ bestT = best.bestT; bestD = best.bestD; }
      }
      // честная шкала (Фаза 3): ошибка в ° → гауссиан с потолком от σ_noise
      if (bestD != null) bestSim = simReported(bestD, thr, cmp.sigmaNoise[f.key] ?? DEFAULT_SIGMA, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR);
    }
    sm.a[f.key] = ka ?? null; sm.b[f.key] = kb ?? null;
    sm.tA_[f.key] = bestT;
    if (bestSim != null){
      // per-feature статика: B застыл (<1.5°), а по A явное движение (>8°) → ошибка (штраф)
      if (bStuck[f.key] && rangeOf(cmp.aWin[f.key]) > 8) bestSim = 0;
      if (gated(f.key)) bestSim = 0;
      const cv = covOf(cmp.smoothA3D, f) * covOf(cmp.smoothB3D, f) || 0;
      sm.s[f.key] = bestSim;
      sm.e[f.key] = bestD; // ошибка в ° на лучшем совпадении (до гейта) — честная «погрешность позы»
      sm.w[f.key] = (cv > 0.05 ? 1 : (cv ? cv : 0.05)) * refW(f);
      sm.wsum += sm.w[f.key];
      sm.sim += bestSim * sm.w[f.key];
      any = true;
      cmp.featW[f.key] = (cmp.featW[f.key] || 0) + sm.w[f.key];
      cmp.featN[f.key] = (cmp.featN[f.key] || 0) + 1;
      cmp.featSum[f.key] = (cmp.featSum[f.key] || 0) + bestSim * sm.w[f.key];
    }
  }
  if (sm.wsum) sm.sim /= sm.wsum;
  sm.moved = moved;
  if (any){
    cmp.samples.push(sm);
    cmp.framesTotal++;
    let lgA = 0, lnA = 0;
    for (const f of FEATURES){
      if (!featOn(f)) continue;
      const ta = sm.tA_[f.key];
      if (ta != null){ lgA += tA - ta; lnA++; }
    }
    if (s.camOn && lnA){
      const lagSec = lgA / lnA;
      // кольцо лагов + усечённое среднее: устойчиво к одиночным «мимо»
      cmp.lagRing.push(lagSec);
      if (cmp.lagRing.length > 12) cmp.lagRing.shift();
      if (cmp.lagRing.length >= 6) cmp.lagAcq = false; // лаги сошлись — уходим в стейди-режим
      const r = [...cmp.lagRing].sort((x, y) => x - y);
      const k = Math.max(0, Math.floor(r.length * 0.25)); // отсекаем по четверти с каждого края (устойчиво к «мимо»)
      const mid = r.slice(k, r.length - k);
      cmp.curLagA = mid.reduce((a, x) => a + x, 0) / mid.length;
      sm.lag = lagSec;
    } else {
      sm.lag = tB - tA;
    }
    cmp.shiftSum += sm.lag; cmp.shiftCnt++;
  }
}

// Честный итог по DTW (файл-файл): усреднение по фичам с покрытием.
function finalDTW(){
  if (cmp.samples.length < 10) return;
  const thr = Number($("thr").value);
  // Полоса выравнивания: медианный шаг сэмплов × 2с (макс. «прощение задержки»).
  // Кап не даёт пути «растянуться» на 12% длительности длинного видео и копить
  // время/память O(n·K); delay1 (сдвиг 1с) укладывается.
  const dts = [];
  for (let i = 1; i < cmp.samples.length; i++){
    const d = cmp.samples[i].tA - cmp.samples[i-1].tA;
    if (d > 0 && d < 1) dts.push(d);
  }
  let sps = 30;
  if (dts.length){
    dts.sort((x, y) => x - y);
    sps = 1 / dts[Math.floor(dts.length / 2)];
  }
  const band = Math.max(4, Math.round(2 * sps));
  // Гейт формы надёжен только при плотном сэмплинге: на разрежённой камере (~1 сэмпл/с)
  // быстрые фичи алиасятся и корреляция идентичного контента тоже низкая (диагноз Шага 0),
  // поэтому в редких сессиях по гейту не нулим — только по большой ошибке DTW.
  const gateReliable = sps >= SYNC_REL_MIN_SPS;
  const feat = {}; let any = false;
  for (const f of FEATURES){
    if (!featOn(f)) continue;
    const a = [], b = [];
    for (const sm of cmp.samples){
      if (sm.a[f.key] != null && sm.b[f.key] != null){ a.push(sm.a[f.key]); b.push(sm.b[f.key]); }
    }
    if (a.length < 5 || b.length < 5) continue;
    const res = dtwAlign(a, b, thr, band);
    if (res){
      // честная шкала (Фаза 3): DTW-ошибка в ° → гауссиан с потолком от σ_noise
      res.meanSim = simReported(res.meanAbs, thr, cmp.sigmaNoise[f.key] ?? DEFAULT_SIGMA, SIGMA_TOL_FACTOR, CEIL_ERR_K, CEIL_FLOOR);
      // форма-гейт на итоге: не повторяющий форму человек не должен получить % даже при близких углах.
      // Почти-статические фичи уже обходит syncGate (gate===2), поэтому честное совпадение шума
      // не зануляется; здесь достаточно безусловного зануления при низкой корреляции формы.
      // meanAbs <= thr*0.5: сам DTW доказал, что форма повторяется (одинаковые видео),
      // — полу-статичные фичи с шумовой корреляцией гейта не зануляем (иначе % гуляет 64↔100).
      // gate берём как среднее по сессии (не последний сэмпл — иначе скачок в конце решает всё).
      const g = cmp.gateN[f.key] ? cmp.gateSum[f.key] / cmp.gateN[f.key] : cmp.gate[f.key];
      if (g !== 2 && g < SYNC_MIN){
        if (res.meanAbs > thr * 0.5) res.meanSim = 0;
        // «совсем не то» при малых углах: случайно близкие углы чужого движения
        // не должны спасаться исключением abs<=thr*0.5 (foreign файл был 44% из-за
        // локтей/развода/twist с gate 0.2–0.5 и abs 1–19°). Но только при плотном
        // сэмплинге, где корреляция формы достоверна.
        else if (gateReliable && g < SYNC_HARD) res.meanSim = 0;
      }
      feat[f.key] = res; any = true;
    }
  }
  if (!any) return;
  let sum = 0, w = 0;
  for (const k in feat){ sum += feat[k].meanSim * feat[k].coverage; w += feat[k].coverage; }
  if (w > 0) cmp.dtw = { overall: sum / w * 100, feat };
}

// Обновление всех цифр на странице режима «Сравнение» (раз в ~6 кадров).
function cmpUpdateUI(){
  const n = cmp.samples.length;
  const last = n ? cmp.samples[n-1] : null;
  const exEl = $("exTimer");
  if (exEl){
    let t = (cmp.running && last) ? last.tA : null;
    if (t == null && cmp.running && cmp.t0) t = (performance.now() - cmp.t0) / 1000;
    const mm = Math.floor((t || 0) / 60), ss = Math.round((t || 0) % 60);
    exEl.textContent = mm + ":" + (ss < 10 ? "0" : "") + ss;
  }
  const durA = vA.duration || 0;
  const pct = durA ? Math.min(100, (last ? last.tA : 0) / durA * 100).toFixed(0) : 0;
  $("progFillC").style.width = pct + "%";
  const fps = cmp.frames ? (cmp.frames / ((performance.now()-cmp.t0)/1000)).toFixed(1) : "0";
  const shift = cmp.shiftCnt ? (cmp.shiftSum / cmp.shiftCnt * 1000) : null;
  const shiftTxt = shift == null
      ? ""
      : s.camOn
        ? `отставание <b>~${Math.round(shift)} мс</b>`
        : (shift >= 0 ? "+" : "−") + Math.abs(shift).toFixed(0) + " мс";
  const camH = (s.camOn && cmp.smoothB.length) ? camHintB() : "";
  const blindWin = [];
  const winView = cmp.samples.slice(-120);
  if (winView.length){
    for (const f of FEATURES){
      if (!featOn(f)) continue;
      let vis = 0;
      for (const sm of winView) if (sm.b[f.key] != null) vis++;
      if (vis === 0) blindWin.push(f.name);
    }
  }
  const statParts = [
    `кадры <b>${n}</b>`,
    `A <b>${last ? last.tA.toFixed(1) : "0.0"} с</b>`,
    `B <b>${s.camOn ? "live" : (last ? last.tB.toFixed(1) : "0.0")} с</b>`,
    `сдвиг ${shiftTxt || "—"}`,
    `обработка <b>${fps}</b> кадр/с`,
    camH ? `<b class="warn">⚠ ${camH}</b>` : "",
    blindWin.length ? `<b class="warn">⚠ не видно: ${blindWin.join(", ")} — даёт 0%</b>` : ""
  ];
  $("statC").innerHTML = statParts.filter(Boolean).map(h => `<span>${h}</span>`).join("");

  const LIVE = 120; // живое окно: ~2с при 60 к/с — «скользящая» оценка счётчика
  const winS = cmp.samples.slice(-LIVE);
  if (cmp.exType == null) detectExerciseType();
  if (cmp.exType !== "hold" && cmp.primary == null) cmp.primary = resolvePrimary();

  const lSum = {}, wSum = {}, raw = {};
  let lMv = 0;
  for (const sm of winS){
    if (sm.moved) lMv++;
    for (const k in sm.s){
      const w = sm.w[k] || 1;
      lSum[k] = (lSum[k]||0) + sm.s[k] * w;
      wSum[k] = (wSum[k]||0) + w;
      raw[k] = (raw[k]||0) + 1;
    }
  }
  // покрытие: невидимая фича режет свой вес (не хитро из знаменателя)
  const scaled = {}, meanPct = {}, cov = {};
  for (const f of FEATURES){
    if (!featOn(f)) continue;
    const key = f.key;
    meanPct[key] = wSum[key] ? (lSum[key] / wSum[key] * 100) : null;
    cov[key] = winS.length ? (wSum[key] / winS.length * 100) : 0;
    scaled[key] = winS.length ? (wSum[key] ? (lSum[key] / winS.length * 100) : 0) : null; // meanPct × cov
  }
  let overall = null, oN = 0, oSum = 0;
  for (const f of FEATURES){
    if (!featOn(f) || scaled[f.key] == null) continue;
    oSum += scaled[f.key]; oN++;
  }
  if (oN) overall = oSum / oN;

  let session = computeSession();
  // очки (0..10000): накопление с нуля + множитель комбо + проседание на МИМО
  // UI обновляется раз в ~6 кадров, но очки копим по каждому новому сэмплу;
  // шаг константен (заморожен по замерам через ~20 сэмплов) → счёт растёт ровно к концу видео
  if (cmp.running || cmp._uiScored !== cmp.samples.length){
    const durS = vA.duration > 0 ? vA.duration : (vB.duration > 0 ? vB.duration : 60);
    for (let i = cmp._uiScored || 0; i < cmp.samples.length; i++){
      const s2 = cmp.samples[i];
      if (!s2.wsum) continue;
      if (cmp._sps == null && i >= 20) cmp._sps = (i + 1) / Math.max(0.01, s2.tA);
      const step = TIER_MAX / Math.max(60, durS * (cmp._sps || 15));
      const tier = tierFor(s2.sim);
      const wasMimo = cmp.tier && cmp.tier.name === "МИМО";
      if (tier.name === "МИМО"){
        if (!wasMimo) cmp.score = Math.max(0, (cmp.score || 0) - step * 0.5);
        cmp.combo = 0;
      } else {
        cmp.combo++;
        if (cmp.combo > cmp.maxCombo) cmp.maxCombo = cmp.combo;
        cmp.score = Math.min(TIER_MAX, (cmp.score || 0) + s2.sim * step * (1 + 0.02 * Math.min(cmp.combo, 10)));
      }
      cmp.tier = tier;
    }
    cmp._uiScored = cmp.samples.length;
  }
  renderScore();

  // лёгкий EMA только на ОТОБРАЖАЕМЫЙ процент — число плавное, расчёт не трогаем
  if (overall == null) cmp._dispOv = null;
  else cmp._dispOv = cmp._dispOv == null ? overall : cmp._dispOv * 0.6 + overall * 0.4;
  $("scoreBig").textContent = overall == null ? "—" : cmp._dispOv.toFixed(1) + "%";
  // «средняя ошибка в °»: среднее |Δ| по живым сэмплам (есть у выровненных фич);
  // финальный итог — по DTW (meanAbs, coverage-взвешенно).
  let eSum = 0, eN = 0;
  for (const sm of winS) for (const k in sm.e){ eSum += sm.e[k]; eN++; }
  const avgErr = eN ? eSum / eN : null;
  let dtwErr = null;
  if (cmp.dtw){
    let es = 0, ew = 0;
    for (const k in cmp.dtw.feat){ es += cmp.dtw.feat[k].meanAbs * cmp.dtw.feat[k].coverage; ew += cmp.dtw.feat[k].coverage; }
    if (ew) dtwErr = es / ew;
  }
  const dtwTxt = cmp.dtw
      ? ` · DTW-итог ${cmp.dtw.overall.toFixed(1)}%${dtwErr != null ? ` · Δ ${dtwErr.toFixed(1)}°` : ""}`
      : "";
  const errTxt = avgErr != null ? ` · Δ ${avgErr.toFixed(1)}°` : "";
  $("scoreSub").textContent = overall == null
      ? "запустите сравнение"
      : `живой ~${LIVE} фр${errTxt}${session == null ? "" : ` · сессия ${session.toFixed(1)}%`}${dtwTxt}${lMv < winS.length ? ` · застыл ${winS.length - lMv} из ${winS.length}` : ""}`;

  let per = "";
  for (const f of FEATURES){
    if (!featOn(f)) continue;
    const key = f.key;
    const mp = meanPct[key];
    const bar = mp == null ? `<div class="fbar"></div>`
              : `<div class="fbar"><div style="width:${Math.min(100, mp)}%"></div></div>`;
    const ov = cov[key];
    let tip = raw[key] ? `${raw[key]} ср.` : "—";
    const rw = refW(f);
    if (rw < 1) tip += ` · вес ${rw.toFixed(2)}`;
    if (ov != null && ov < 98) tip += ` · покр. ${Math.round(ov)}%`;
    // ошибка по фиче в °: финальный DTW (meanAbs) или живое Δ по окну
    let errDeg = null;
    if (cmp.dtw && cmp.dtw.feat[key]) errDeg = cmp.dtw.feat[key].meanAbs;
    else {
      let eF = 0, eFn = 0;
      for (const sm of winS){ if (sm.e[key] != null){ eF += sm.e[key]; eFn++; } }
      if (eFn) errDeg = eF / eFn;
    }
    if (errDeg != null) tip += ` · Δ ${errDeg.toFixed(1)}°`;
    per += `<div class="frow"><span>${f.name}</span>${bar}<b>${mp == null ? "—" : Math.round(mp) + "%"}</b><i>${tip}</i></div>`;
  }
  $("ffePer").innerHTML = per;

  const blindA = [], blindB = [];
  const vaNow = cmp.smoothA3D.length ? cmpFeatures(cmp.smoothA3D) : null;
  const vbNow = cmp.smoothB3D.length ? cmpFeatures(cmp.smoothB3D) : null;
  if (vaNow) for (const f of FEATURES) if (!featOn(f) || vaNow[f.key] == null) blindA.push(f.name);
  if (vbNow) for (const f of FEATURES) if (!featOn(f) || vbNow[f.key] == null) blindB.push(f.name);
  if (blindA.length) $("infoA").textContent = "⚠ не видно: " + blindA.join(", ");
  if (blindB.length) $("infoB").textContent = "⚠ не видно: " + blindB.join(", ");

  renderReps(winS, last);
  renderHold(winS);
}

// ── загрузка видео в поля A/B ──
function loadCmp(video, canvas, ctx_, info, file, key){
  if (!file) return;
  if (cmp["blobUrl" + key]){ try { URL.revokeObjectURL(cmp["blobUrl" + key]); } catch(_){} }
  cmp["lastTime"+key] = -1;
  cmp["smooth"+key] = [];
  const url = URL.createObjectURL(file);
  cmp["blobUrl" + key] = url;
  video.src = url;
  canvas.hidden = true;
  info.textContent = `${file.name} (${(file.size/1048576).toFixed(1)} МБ)`;
  cmp["name"+key] = file.name;
  video.onloadedmetadata = () => {
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
    canvas.hidden = false;
  };
  video.onloadeddata = () => { try { ctx_.drawImage(video, 0, 0, canvas.width, canvas.height); } catch(e){} };
  video.onerror = () => say2(`Видео ${key} не открылось. ${mediaErrText(video.error)}`, true);
}

export function loadA(f){
  if (!f) return;
  s.hasA = true;
  // новый эталон — сбрасываем модели, чтобы детектор не тащил состояние прошлого видео
  try { if (s.lmA) s.lmA.close(); if (s.lmB) s.lmB.close(); } catch(e){}
  s.lmA = null; s.lmB = null; cmp.failsA = 0; cmp.failsB = 0;
  loadCmp(vA, cvA, ctxA, $("infoA"), f, "A");
  cmp.aProf = null; cmp.maskApplied = false;
  $("aProfPanel").hidden = true;
  vA.onloadeddata = () => {
    try { ctxA.drawImage(vA, 0, 0, cvA.width, cvA.height); } catch(e){}
    scheduleAnalyzeA();
  };
  syncCmpBtns();
}
export function loadB(f){ if (!f) return; s.hasB = true; loadCmp(vB, cvB, ctxB, $("infoB"), f, "B"); syncCmpBtns(); }
function syncCmpBtns(){
  const bReady = s.hasB || s.camOn;
  $("cmpGo").disabled = !(s.hasA && bReady);
  $("cmpMark").disabled = !(s.hasA && bReady);
  $("cmpPreview").disabled = !s.hasA;
}

// ── анализ эталона: карточка упражнения + авто-маска фич ──
function ensureLmA(){
  if (s.lmA) return Promise.resolve(s.lmA);
  const del = $("delegate").value;
  say2(`загрузка модели для анализа (${del})…`);
  const prog = p => say2(`загрузка модели (${del})… ${Math.round(p * 100)}%`);
  return makeLandmarker(del, prog).then(lm => { if (s.lmA) s.lmA.close(); s.lmA = lm; return s.lmA; })
    .catch(() => makeLandmarker("CPU", prog).then(lm => { if (s.lmA) s.lmA.close(); s.lmA = lm; return s.lmA; }));
}
function scheduleAnalyzeA(){
  clearTimeout(s.aAnalyzeT);
  if (cmp._noAnalyze) return;
  cmp.aProf = null; cmp.maskApplied = false;
  $("aProfPanel").hidden = true;
  s.aAnalyzeT = setTimeout(() => analyzeA(), 800);
}
async function analyzeA(){
  if (!s.hasA || !(vA.duration > 0)) return;
  if (cmp.running) return;
  const job = (s.aAnalyze = { run:true });
  const dur = vA.duration;
  const N = Math.max(12, Math.min(40, Math.round(dur)));
  try {
    const lm = await ensureLmA();
    if (!job.run || job !== s.aAnalyze) return;
    if (cmp.running) return;
    vA.pause();
    const series = {}; for (const f of FEATURES) series[f.key] = [];
    let prevTs = 0, det = 0;
    for (let i = 0; i < N; i++){
      if (cmp.running || !job.run || job !== s.aAnalyze) return;
      vA.currentTime = dur * i / (N - 1);
      await new Promise(res => {
        const h = () => res();
        vA.addEventListener("seeked", h, { once:true });
        setTimeout(h, 1200);
      });
      if (cmp.running || !job.run || job !== s.aAnalyze) return;
      const ts = Math.max(prevTs + 1, Math.round(vA.currentTime * 1000)); prevTs = ts;
      let fa = null;
      try { fa = await lm.detectForVideo(vA, ts); } catch(e){ continue; }
      if (!fa?.landmarks?.length) continue;
      det++;
      const ang = cmpFeatures(featSource(fa.worldLandmarks?.[0], fa.landmarks[0]));
      for (const f of FEATURES){
        const v = ang[f.key];
        if (v != null && isFinite(v)) series[f.key].push(v);
      }
      say2(`анализ эталона… ${Math.round((i + 1) / N * 100)}%`);
    }
    if (!job.run || job !== s.aAnalyze) return;
    const per = {};
    for (const f of FEATURES){
      const arr = series[f.key];
      if (!arr.length){ per[f.key] = { n:0, cov:0, rng:0, mean:null, series:[] }; continue; }
      let mn = 1e9, mx = -1e9, s2 = 0;
      for (const v of arr){ if (v < mn) mn = v; if (v > mx) mx = v; s2 += v; }
      per[f.key] = { n:arr.length, cov:arr.length / N, rng:mx - mn, mean:s2 / arr.length, series:arr };
    }
    const type = guessExerciseType(per);
    const prof = (cmp.aProf = { N, det, per, type, primary:null, holdish:type === "hold" });
    const maxRng = Math.max(1, ...FEATURES.map(f => per[f.key].rng || 0));
    prof.maxRng = maxRng;
    applyAProfMask(prof);
    renderAProf(prof);
    say2(`Анализ эталона: распознано ${det}/${N} кадров.`);
  } catch(err){
    say2("Анализ эталона: " + ((err && err.message) || err), true);
  } finally {
    if (!cmp.running && !cmp.preview){ try { vA.currentTime = 0; } catch(e){} }
    if (job === s.aAnalyze) s.aAnalyze = null;
  }
}
function guessExerciseType(per){
  let total = 0, ext = 0, key = null, br = -1;
  for (const f of FEATURES){
    const p = per[f.key]; if (!p.series.length) continue;
    total += p.rng;
    if (p.rng > br){ br = p.rng; key = f.key; }
    const e = countExtrema(p.series, 25);
    if (e > ext) ext = e;
  }
  if (!key || total < 18) return "hold";
  return ext >= 3 ? "cycle" : "flow";
}
function countExtrema(arr, amp){
  let ext = 0, dir = 0, prev = null;
  for (const v of arr){
    if (prev == null){ prev = v; continue; }
    const d = v - prev;
    if (Math.abs(d) > amp){
      if (dir === 0 || (d > 0 && dir < 0) || (d < 0 && dir > 0)) ext++;
      dir = d > 0 ? 1 : -1;
    }
    prev = v;
  }
  return ext;
}
function applyAProfMask(prof){
  if (!prof) return;
  const ACTIVE_COV = 0.4, ACTIVE_RNG = 15;
  for (const f of FEATURES){
    const p = prof.per[f.key];
    const active = !!(p && p.cov >= ACTIVE_COV && p.rng >= ACTIVE_RNG);
    $("chk_" + f.key).checked = active;
  }
  if (prof.holdish || FEATURES.every(f => !$("chk_" + f.key).checked)){
    for (const f of FEATURES) $("chk_" + f.key).checked = true;
    prof.holdish = true;
  }
  cmp.maskApplied = true;
}
function renderAProf(prof){
  const wrap = $("aProfPanel"); if (!wrap) return;
  wrap.hidden = false;
  const typeTxt = prof.holdish ? "удержание (статичная поза)"
      : prof.type === "cycle" ? "повторы (циклы)"
      : prof.type === "flow" ? "поток (фазы)" : "—";
  $("aProfType").textContent = typeTxt;
  let best = null, br = -1;
  let html = "";
  for (const f of FEATURES){
    const p = prof.per[f.key] || { n:0, cov:0, rng:0 };
    const on = $("chk_" + f.key).checked;
    if (on && p.rng > br){ br = p.rng; best = f; }
    const w = prof.maxRng ? Math.min(100, p.rng / prof.maxRng * 100) : 0;
    html += `<div class="frow"><span>${f.name}${on ? " ✓" : ""}</span>
      <div class="fbar"><div style="width:${w}%;background:${on ? "var(--hot)" : "var(--dim)"}"></div></div>
      <b>${Math.round(p.rng)}°</b><i>${p.cov ? "видно " + Math.round(p.cov * 100) + "%" : "—"}</i></div>`;
  }
  $("aProfBars").innerHTML = html;
  $("aProfAccent").textContent = best ? `акцент: ${best.name}, размах ${Math.round(br)}°` : "";
  $("aProfTip").textContent = prof.holdish
      ? "движения почти нет — оцениваем точность позы целиком"
      : `по эталону снимаем нерабочие части (${FEATURES.filter(f => !$("chk_" + f.key).checked).map(f => f.name).join(", ") || "все задействованы"})`;
  $("aProfNote").textContent = cmp.maskApplied
      ? "авто-маска применена: считаются только активные части; любой чекбокс можно вернуть вручную."
      : "";
}

// ── подсказка кадра для живой камеры ──
function camHintB(){
  const lm = cmp.smoothB[cmp.smoothB.length - 1];
  if (!lm || !lm.length) return "";
  let x0 = 1, y0 = 1, x1 = 0, y1 = 0, got = 0;
  for (const p of lm){
    if ((p.v ?? 1) < 0.4) continue;
    if (p.x < x0) x0 = p.x; if (p.x > x1) x1 = p.x;
    if (p.y < y0) y0 = p.y; if (p.y > y1) y1 = p.y;
    got++;
  }
  if (got < 8) return "";
  const msgs = [];
  if (y0 < 0.03 && y1 < 0.6) msgs.push("голова у края кадра");
  if (y1 > 0.97 && y1 - y0 < 0.6) msgs.push("ноги за кадром — отступают");
  if ((x0 < 0.03 || x1 > 0.97)) msgs.push("руки у краёв — отойдите от камеры");
  if (y1 - y0 < 0.30) msgs.push("видно мелко — подойдите ближе");
  return msgs.join(", ");
}

// ── источник B и камера ──
function setBSource(cam){
  s.useCamB = cam;
  $("cmpBFile").disabled = cam;
  $("camBtn").disabled = !cam;
  $("cntWrap").hidden = !cam;
  if (cam && !s.camOn){ $("infoB").textContent = "нажмите «Включить камеру»"; }
  if (!cam && s.camOn) stopCamera();
  s.lagTouched = false;   // источник сменился — вернуть дефолтное окно для режима (2с камера / 0.5с файл)
  defaultLag();
  syncCmpBtns();
}
function armBFrame(){
  if (!s.camOn || !vB.srcObject) return;
  if (!vB.requestVideoFrameCallback || typeof vB.requestVideoFrameCallback !== "function"){
    cmp.bNoRVC = true;
    cmp.bNew = false;
    return;
  }
  try {
    vB.requestVideoFrameCallback(() => { cmp.bNew = true; armBFrame(); });
  } catch(er){ cmp.bNoRVC = true; }
}

export async function startCamera(){
  try {
    if (!navigator.mediaDevices?.getUserMedia)
      throw new Error("getUserMedia недоступен — нужен HTTPS или localhost");
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 960 }, height: { ideal: 540 } },
      audio: false
    });
    s.camStream = stream; s.camOn = true;
    vB.playsInline = true; vB.muted = true;
    vB.srcObject = stream;
    cvB.hidden = true;
    vB.onloadedmetadata = () => {
      cvB.width = vB.videoWidth; cvB.height = vB.videoHeight;
      cvB.hidden = false;
    };
    await vB.play();
    cvB.classList.add("mirror");
    armBFrame();
    $("camBtn").textContent = "Выключить камеру";
    $("infoB").textContent = "камера активна · live";
    say2("Камера включена. Держите камеру <b>горизонтально</b>, отойдите так, чтобы был виден ваш торс и руки целиком. Нажмите «Сравнить» и повторяйте за эталоном A.");
    syncCmpBtns();
  } catch(err){
    let msg = err.message || "ошибка доступа";
    if (err.name === "NotAllowedError") msg = "Нет доступа к камере (заблокировано браузером)";
    else if (err.name === "NotFoundError") msg = "Камера не найдена";
    else if (err.name === "SecurityError") msg = "Нет allow camera";
    msg += " — камера доступна только в HTTPS или на localhost (python pose_serve.py + туннель).";
    say2("Камера: " + msg, true);
  }
}
export function stopCamera(){
  if (s.camStream){ s.camStream.getTracks().forEach(t => t.stop()); s.camStream = null; }
  s.camOn = false;
  vB.srcObject = null;
  cvB.classList.remove("mirror");
  $("camBtn").textContent = "Включить камеру";
  $("infoB").textContent = "";
  syncCmpBtns();
}

// ── отсчёт «Подготовка» перед стартом камеры ──
function runCountdown(n){
  return new Promise(resolve => {
    const ov = $("cvOverlay"), num = $("cvNum"), note = $("cvNote");
    ov.hidden = false;
    num.textContent = n + "";
    note.textContent = "встаньте в начальную позу, как на эталоне";
    beep(660, 0.1);
    let cur = n;
    const finishResolve = ok => { clearInterval(iv); ov.hidden = true; resolve(ok); };
    const iv = setInterval(() => {
      if (!cmp.running){ finishResolve(false); return; }
      cur--;
      num.textContent = Math.max(0, cur) + "";
      const label = cur > 2 ? "встаньте в начальную позу, как на эталоне"
                  : cur > 0 ? "приготовьтесь" : "старт";
      note.textContent = label;
      beep(cur > 0 ? 660 : 990, cur > 0 ? 0.1 : 0.35);
      if (cur <= 0){ finishResolve(true); return; }
    }, 1000);
  });
}

// ── старт сравнения ──
async function startCompare(){
  $("cmpGo").disabled = true;
  clearTimeout(s.aAnalyzeT);
  if (s.aAnalyze) s.aAnalyze.run = false;
  s.aAnalyze = null;
  cmp._noAnalyze = true;
  if (cmp.preview) stopPreview();
  if (s.useCamB && !s.camOn){
    say2("Сначала включите камеру («Включить камеру»).", true);
    $("cmpGo").disabled = false; return;
  }
  try {
    await ensureMeta(vA); await ensureMeta(vB);
    if (!cvA.width || !cvB.width) throw new Error("нет метаданных видео");
    const del = s.camOn ? "GPU" : $("delegate").value;
    if (s.lmA && s.lmA.del !== del){ s.lmA.close(); s.lmA = null; }
    if (s.lmB && s.lmB.del !== del){ s.lmB.close(); s.lmB = null; }
    if (s.lmA && s.lmA.del === del && s.lmB && s.lmB.del === del){
      // модели уже готовы (например, из анализа эталона)
    } else {
      say2(`загрузка модели (${del})…`);
      const prog = p => say2(`загрузка модели (${del})… ${Math.round(p * 100)}%`);
      try {
        if (!s.lmA) s.lmA = await makeLandmarker(del, prog);
        if (!s.lmB) s.lmB = await makeLandmarker(del, prog);
      } catch(err){
        if (del === "GPU"){ say2("GPU не поднялся, пробую CPU…"); s.lmA = await makeLandmarker("CPU", prog); s.lmB = await makeLandmarker("CPU", prog); }
        else throw err;
      }
    }
  } catch(err){
    say2(`Не стартовало: ${err.message}. Нужна сеть для модели или локальный .task во втором поле.`, true);
    $("cmpGo").disabled = false; return;
  }

  cmp.samples = []; cmp.featSum = {}; cmp.featW = {}; cmp.featN = {}; cmp.framesTotal = 0; cmp.aWin = {};
  cmp.gate = {}; cmp.gateSum = {}; cmp.gateN = {};
  cmp.sigmaNoise = {}; cmp.sigmaFrozen = {}; cmp.resid = {};
  const exEl0 = $("exTimer"); if (exEl0) exEl0.textContent = "0:00";
  cmp.frames = 0; cmp.everyN = 0;
  cmp.camTS = s.lmB?._lastTs ?? 0;      // таймстампы растут и между запусками: graph не
  cmp.tsA = s.lmA?._lastTs ?? -1;       // пересоздаётся, а MediaPipe требует строго
  cmp.tsB = s.lmB?._lastTs ?? -1;       // возрастающие ts (иначе "norm_rect timestamp mismatch")
  cmp.audioPending = !s.sound.muted;    // звук включаем с первого обработанного кадра
  cmp.failsA = 0; cmp.failsB = 0; cmp.fbA = false; cmp.fbB = false;
  cmp.bNew = false; cmp.bNoRVC = !vB.requestVideoFrameCallback || typeof vB.requestVideoFrameCallback !== "function";
  cmp.armed = false;
  cmp.modeAtStart = s.camOn ? "camera" : "file";
  cmp.delAtStart = s.camOn ? "GPU" : $("delegate").value;
  cmp.t0 = performance.now();
  cmp.warmUntil = performance.now() + 1000; // 1с прогрева: не считаем, пока детекторы не прогрелись
  cmp.shiftSum = 0; cmp.shiftCnt = 0;
  cmp.smoothA = []; cmp.smoothB = []; cmp.smoothA3D = []; cmp.smoothB3D = [];
  cmp.lastTimeA = -1; cmp.lastTimeB = -1;
  cmp.bHist = {}; cmp.bHistS = {};
  cmp.curLagA = null; cmp.lagAcq = true; cmp.lagRing = []; cmp._dispOv = null;
  cmp.score = null; cmp.combo = 0; cmp.maxCombo = 0; cmp.tier = null; cmp._uiScored = 0; cmp._sps = null;
  cmp.detB = {}; cmp.repScores = [];
  cmp.primary = null; cmp.exType = null; cmp.dtw = null; cmp.tag = "";
  $("scoreNum").textContent = "—";
  $("combo").textContent = "";
  $("tier").textContent = "";
  $("repChips").innerHTML = "";
  $("csvBtn").disabled = true;
  buildCharts();
  cmp.running = true; $("cmpStop").disabled = false; $("cmpStop").hidden = false;
  vA.currentTime = cmp.markA;
  if (!s.camOn) vB.currentTime = cmp.markB;
  let prepSec = s.camOn ? (Number($("cnt").value) || 0) : 0;
  vA.pause();
  if (s.camOn){ try { await vB.play(); } catch(err){} }
  if (prepSec > 0){
    say2(`подготовка — встаньте в начальную позу. Старт через ${prepSec} с`);
    cmpTick();
    const ok = await runCountdown(prepSec);
    if (!ok){ say2("Подготовка отменена."); return; }
    cmp.armed = true;
    vA.volume = s.sound.vol;                       // звук — только у эталона A
    const pA = playVideo(vA, false);   // звук — с первого обработанного кадра (audioPending)
    try { await vB.play(); } catch(err){ say2(`Не запустилось: ${err.message}`, true); }
    try { await pA; } catch(err){ say2(`Не запустилось: ${err.message}`, true); }
  } else {
    cmp.armed = true;
    vA.volume = s.sound.vol;
    const pA = playVideo(vA, false);   // звук — с первого обработанного кадра (audioPending)
    try { await vB.play(); } catch(err){ say2(`Не запустилось: ${err.message}`, true); }
    try { await pA; } catch(err){ say2(`Не запустилось: ${err.message}`, true); }
    cmpTick();
  }
  say2(`сравнение… старт A ${cmp.markA.toFixed(2)}с${s.camOn ? " · камера live" : ", B " + cmp.markB.toFixed(2) + "с"}`);
}

export function cmpStop(){
  if (cmp.preview){ stopPreview(); return; }
  const wasRun = cmp.running;
  cmp.running = false;
  cmp.audioPending = false;
  cmp._noAnalyze = false;
  const ov = $("cvOverlay");
  if (ov) ov.hidden = true;
  vA.pause(); vB.pause();
  $("cmpGo").disabled = !(s.hasA && (s.hasB || s.camOn));
  $("cmpStop").disabled = true;
  $("cmpStop").hidden = true;
  let session = computeSession();
  if (cmp.exType == null) detectExerciseType();
  if (cmp.samples.length){
    finalDTW();
    if (cmp.dtw) $("scoreBig").textContent = cmp.dtw.overall.toFixed(1) + "%";
    else if (session != null) $("scoreBig").textContent = session.toFixed(1) + "%";
    renderScore();
    const last = cmp.samples[cmp.samples.length - 1];
    renderReps(cmp.samples.slice(-120), cmp.running ? last : null);
    renderHold(cmp.samples.slice(-120));
    cmpUpdateUI(); drawCharts();
    $("csvBtn").disabled = false;
  }
  const fps = cmp.frames ? (cmp.frames/((performance.now()-cmp.t0)/1000)).toFixed(1) : "0";
  const overall = cmp.dtw ? cmp.dtw.overall.toFixed(1) : (session != null ? session.toFixed(1) : "—");
  let extra = "";
  if (cmp.maxCombo) extra += `, макс комбо ×${cmp.maxCombo}, счёт ${fmtN(cmp.score)}`;
  const done = cmp.repScores.filter(r => r.pct != null);
  if (done.length){
    const avg = done.reduce((a, r) => a + r.pct, 0) / done.length;
    const pre = cmp.exType === "flow" ? "фаз" : "повторов";
    extra += `, ${pre}: ${done.length} (ср. ${avg.toFixed(0)}%)`;
  }
  if (cmp.dtw) extra += ` · итог по DTW`;
  say2(wasRun
    ? `Готово. Сходство <b>${overall}%</b>, кадров <b>${cmp.samples.length}</b>, ${fps} кадр/с.${extra}`
    : "Сравнение остановлено.");
  if (s.camOn) stopCamera();
}

// ── просмотр эталона (просто видео, без скелета) ──
function previewEnd(){
  vA.pause();
  cmp.preview = false;
  $("cmpPreview").hidden = true;
  $("cmpPreview").textContent = "Просмотр";
  $("cmpPreviewReplay").hidden = false;
  $("cmpStop").hidden = true;
  syncCmpBtns();
  say2("Просмотр закончен. Можно «Повторить заново» или начать «Сравнить».");
}
function stopPreview(){
  if (!cmp.preview) return;
  cmp.preview = false;
  vA.pause();
  $("cmpPreview").hidden = false;
  $("cmpPreview").textContent = "Возобновить";
  $("cmpPreviewReplay").hidden = true;
  $("cmpStop").hidden = true;
  syncCmpBtns();
}
function previewTick(){
  if (!cmp.preview) return;
  drawCmpBg(ctxA, cvA.width, cvA.height, vA, "video");
  if (vA.ended){ previewEnd(); return; }
  requestAnimationFrame(previewTick);
}
function startPreview(){
  if (cmp.preview || !s.hasA) return;
  cmp.running = false;
  cmp.preview = true;
  vA.pause();
  $("cmpPreview").hidden = true;
  $("cmpPreview").textContent = "Просмотр";
  $("cmpPreviewReplay").hidden = false;
  $("cmpGo").disabled = true; $("cmpMark").disabled = true; $("cmpStop").disabled = false;
  $("cmpStop").hidden = false;
  if (vA.currentTime <= 0 || vA.currentTime >= (vA.duration || Infinity) - 0.05){
    vA.currentTime = cmp.markA;
  }
  vA.volume = s.sound.vol;
  playVideo(vA, !s.sound.muted)
    .then(() => say2("Просмотр эталона — только видео. Остановить можно кнопкой «Стоп»."))
    .catch(err => say2(`Просмотр не запустился: ${err.message}`, true));
  previewTick();
}

// ── экспорт CSV ──
function downloadCSV(){
  const fkeys = FEATURES.filter(featOn).map(f => f.key);
  const thr = Number($("thr").value);
  const session = computeSession();
  const rng = {}, cov = {};
  for (const f of FEATURES){
    const p = cmp.aProf && cmp.aProf.per ? cmp.aProf.per[f.key] : null;
    rng[f.key] = p && p.rng != null ? Math.round(p.rng) : null;
    cov[f.key] = p ? +(p.cov || 0).toFixed(2) : null;
  }
  const sig = {};
  for (const f of FEATURES) if (cmp.sigmaNoise[f.key] != null) sig[f.key] = +cmp.sigmaNoise[f.key].toFixed(2);
  const dtwErrF = {};
  if (cmp.dtw) for (const k in cmp.dtw.feat) dtwErrF[k] = +cmp.dtw.feat[k].meanAbs.toFixed(2);
  const meta = {
    ver: "2026-08-11.world", t: new Date().toISOString(),
    mode: cmp.modeAtStart || (s.camOn ? "camera" : "file"),
    delegate: cmp.delAtStart || (s.camOn ? "GPU" : $("delegate").value),
    smoothing: $("smC").value, tolerance: thr, lagWin: currentWin(),
    countdown: Number($("cnt").value), preset: $("exSel").value,
    aName: cmp.nameA || "", bName: cmp.nameB || "",
    markA: cmp.markA, markB: cmp.markB,
    aType: cmp.exType || "",
    aProf: cmp.aProf ? { N: cmp.aProf.N, det: cmp.aProf.det, holdish: !!cmp.aProf.holdish, type: cmp.aProf.type } : null,
    aRng: rng, aCov: cov,
    mask: fkeys, weights: featWeights(),
    sigmaNoise: sig, dtwErr: dtwErrF,
    dtw: cmp.dtw ? +cmp.dtw.overall.toFixed(1) : null,
    session: session != null ? +session.toFixed(1) : null,
    score: cmp.score, maxCombo: cmp.maxCombo,
  };
  const rows = [];
  rows.push(["#", "META", JSON.stringify(meta)]);
  rows.push([]);
  const head = ["#","эл(мс)","tA","tB","лаг(мс)","движение",
    ...fkeys.flatMap(k => [k+"A", k+"B", k+"tAt", k+"err", k+"sim", k+"w", k+"cov"]),
    "сходство%","score","combo","tier"];
  rows.push(head);
  const durS = vA.duration > 0 ? vA.duration : (vB.duration > 0 ? vB.duration : 60);
  let sps = null;
  let score = 0, combo = 0, maxCombo = 0, tierName = "", wasMimo = false;
  for (let i = 0; i < cmp.samples.length; i++){
    const s2 = cmp.samples[i];
    if (!s2.wsum) continue;
    if (sps == null && i >= 20) sps = (i + 1) / Math.max(0.01, s2.tA);
  }
  for (let i = 0; i < cmp.samples.length; i++){
    const s2 = cmp.samples[i];
    const lag = s2.lag != null ? s2.lag : (s2.tB - s2.tA);
    const row = [i + 1, (cmp.modeAtStart === "camera" && cmp.t0) ? ((s2.tB*1000 - cmp.t0)).toFixed(0) : "", s2.tA.toFixed(3), cmp.modeAtStart === "camera" ? "" : s2.tB.toFixed(3),
                 (lag * 1000).toFixed(1), s2.moved ? "да" : "нет"];
    const sims = []; let sw = 0, sweight = 0;
    for (const k of fkeys){
      const a = s2.a[k], b = s2.b[k], taA = s2.tA_[k];
      row.push(a != null ? a.toFixed(2) : "");
      row.push(b != null ? b.toFixed(2) : "");
      row.push(taA != null ? taA.toFixed(2) : "");
      row.push(s2.e[k] != null ? s2.e[k].toFixed(2) : "");
      // sim — готовое scored-значение (уже с tie-break на лучшем совпадении и
      // гейтами, как в живом счёте/сессии): консистентно со скобкой и тирами.
      // err (s2.e[k]) рядом — сырая «погрешность в °» на лучшем совпадении.
      const sim = s2.s[k] != null ? s2.s[k] : null;
      row.push(sim != null ? sim.toFixed(3) : "");
      row.push((s2.w[k] || 0).toFixed(3));
      row.push((a != null && b != null) ? 1 : 0);
      if (sim != null){ sims.push(sim * (s2.w[k] || 0)); sw += (s2.w[k] || 0); sweight++; }
    }
    row.push(sw ? (sims.reduce((x, y) => x + y, 0) / sw * 100).toFixed(1) : "");
    if (s2.wsum){
      const step = TIER_MAX / Math.max(60, durS * (sps || 15));
      const tier = tierFor(s2.sim);
      const isMimo = tier.name === "МИМО";
      if (isMimo){ if (!wasMimo) score = Math.max(0, score - step * 0.5); combo = 0; }
      else {
        combo++;
        if (combo > maxCombo) maxCombo = combo;
        score = Math.min(TIER_MAX, score + s2.sim * step * (1 + 0.02 * Math.min(combo, 10)));
      }
      wasMimo = isMimo;
      tierName = tier.name;
    }
    row.push(score ? Math.round(score) : 0, combo, tierName);
    rows.push(row);
  }
  rows.push([]);
  rows.push(["ИТОГ","","","","","", ...Array(fkeys.length * 7).fill(""), session == null ? "" : session.toFixed(1)]);
  if (cmp.dtw) rows.push(["DTW","","","","","", ...Array(fkeys.length * 7).fill(""), cmp.dtw.overall.toFixed(1)]);
  const done = cmp.repScores.filter(r => r.pct != null);
  rows.push(["ОЦЕНКА","счёт","макс. комбо","повторы","тип","", `ср. повторов: ${done.length ? (done.reduce((a, r) => a + r.pct, 0) / done.length).toFixed(1) + "%" : ""}`]);
  rows.push(["", fmtN(cmp.score), cmp.maxCombo ? "×" + cmp.maxCombo : "", done.length, cmp.exType || "auto"]);
  const csv = rows.map(r => r.map(c => `"${String(c == null ? "" : c).replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  const url = URL.createObjectURL(blob);
  a.href = url;
  a.download = `compare_angles_${Date.now() >> 10}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ── пресеты упражнений · задержка · амплитуда ──
function defaultLag(){
  if (s.lagTouched) return;
  $("lagWin").value = s.useCamB ? 2 : 0.5;
  $("lagWinV").textContent = Number($("lagWin").value).toFixed(1) + " с";
}

// ── раскладки окон: меняют только размеры, движок сравнения не трогают ──
let curLayout = "split";
let pipState = 0;      // 0 — скрыто, 1 — показано на 5 с, 2 — закреплено
let pipT = null;
function pipStage(){ return curLayout === "trainer" ? cvB : cvA; }
function pipLabel(){ return curLayout === "trainer" ? "меня" : "тренера"; }
function setPiP(show){
  pipStage().parentElement.classList.toggle("pip-show", show);
  $("pipBtn").textContent = show ? "скрыть " + pipLabel() : "показать " + pipLabel();
}
export function setLayout(lay){
  curLayout = lay;
  const row = $("cstageRow");
  row.classList.remove("lay-split", "lay-trainer", "lay-self");
  row.classList.add("lay-" + lay);
  row.dataset.layout = lay;
  $("layTrainer").classList.toggle("act", lay === "trainer");
  $("laySplit").classList.toggle("act", lay === "split");
  $("laySelf").classList.toggle("act", lay === "self");
  if (pipT){ clearTimeout(pipT); pipT = null; }
  pipState = 0;
  if (lay === "split"){
    $("pipBtn").hidden = true;
    if (cvA.parentElement.classList.contains("pip-show")) cvA.parentElement.classList.remove("pip-show");
    if (cvB.parentElement.classList.contains("pip-show")) cvB.parentElement.classList.remove("pip-show");
  } else {
    $("pipBtn").hidden = false;
    setPiP(false);
  }
}
export function cycleLayout(){ const seq = ["split","trainer","self"]; setLayout(seq[(seq.indexOf(curLayout)+1) % seq.length]); }
function applyPreset(){
  const sel = $("exSel").value;
  const ex = EXERCISES[sel] || EXERCISES.auto;
  const el = $("exTip");
  let tip = ex.tip || "";
  if (ex.win != null) tip += ` · окно ${ex.win} с`;
  if (ex.thr != null) tip += ` · допуск ~${ex.thr}°`;
  el.textContent = tip;
  if (!s.lagTouched && ex.win != null) $("lagWin").value = ex.win;
  $("lagWinV").textContent = Number($("lagWin").value).toFixed(1) + " с";
  if (sel === "yogaHold" || sel === "plank") cmp.exType = "hold";
  else if (sel !== "auto") cmp.exType = sel === "yogaFlow" ? "flow" : "cycle";
  else cmp.exType = null;
  cmp.primary = resolvePrimary();
  cmp.tag = "";
  cmp.detB = {}; cmp.repScores = [];
}

// Привязка событий режима (вызывается из main.js после готовности DOM).
export function init(){
  $("cmpAFile").onchange = e => loadA(e.target.files[0]);
  $("cmpBFile").onchange = e => loadB(e.target.files[0]);
  $("srcBFile").onchange = () => setBSource(false);
  $("srcBCam").onchange = () => setBSource(true);
  $("camBtn").onclick = () => { s.camOn ? stopCamera() : startCamera(); };
  $("cmpMark").onclick = () => {
    cmp.markA = vA.currentTime; cmp.markB = vB.currentTime;
    $("markInfo").textContent = `старт A ${cmp.markA.toFixed(2)}с · B ${s.camOn ? "live" : cmp.markB.toFixed(2) + "с"}`;
  };
  $("cmpGo").onclick = startCompare;
  $("cmpStop").onclick = cmpStop;
  $("cmpPreview").onclick = startPreview;
  vA.addEventListener("ended", () => { if (cmp.preview) previewEnd(); });
  $("cmpPreviewReplay").onclick = () => {
    cmp.running = false;
    cmp.preview = true;
    vA.pause();
    $("cmpPreview").hidden = true;
    $("cmpPreview").textContent = "Просмотр";
    $("cmpPreviewReplay").hidden = false;
    $("cmpGo").disabled = true; $("cmpMark").disabled = true; $("cmpStop").disabled = false;
    $("cmpStop").hidden = false;
    vA.currentTime = cmp.markA;
    vA.volume = s.sound.vol;
    playVideo(vA, !s.sound.muted).catch(err => say2(`Не запустилось: ${err.message}`, true));
    previewTick();
  };
  $("aProfBtn").onclick = () => analyzeA();
  $("csvBtn").onclick = downloadCSV;
  $("exSel").onchange = applyPreset;
  $("lagWin").oninput = e => {
    s.lagTouched = true;
    $("lagWinV").textContent = Number(e.target.value).toFixed(1) + " с";
  };
  $("repAmp").oninput = e => $("repAmpV").textContent = e.target.value + "°";
  $("repAmpV").textContent = "25°";
  applyPreset();
  defaultLag();
  $("layTrainer").onclick = () => setLayout("trainer");
  $("laySplit").onclick = () => setLayout("split");
  $("laySelf").onclick = () => setLayout("self");
  $("pipBtn").onclick = () => {
    if (curLayout === "split") return;
    clearTimeout(pipT); pipT = null;
    if (pipState === 0){
      pipState = 1;
      setPiP(true);
      pipT = setTimeout(() => { pipState = 0; setPiP(false); }, 5000);
      say2("Окно показано на 5 с — нажмите ещё раз, чтобы закрепить.");
    } else if (pipState === 1){ pipState = 2; setPiP(true); }
    else { pipState = 0; setPiP(false); }
  };
  setLayout("split");

  // Отладочные хуки в window (для тестов/консоли).
  try { window.__cmp = cmp; window.__camOn = () => s.camOn; window.__liveMatch = liveMatch; window.__downloadCSV = downloadCSV; window.__pearson = pearson; window.__syncGate = syncGate; window.__softSim = softSim; window.__featOf = (wm, lm) => cmpFeatures(featSource(wm, lm)); } catch(_){}
}