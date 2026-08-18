// debug_seg.js — эксперимент: авто-сегментация длинного видео по «подписи движения».
// Отдельная отладочная страница (debug_seg.html), основной app не трогает.
// Сбор кадров: seek-and-detect — пауза, ровная сетка 0.2 с (5 Гц), на каждую точку
// seek + detectForVideo (как офлайн-скрипт). Первый кадр на t=0 = прогрев модели.
// Режим A: автозапуск после выбора файла, гарантированный старт с 0 (seekTo),
// плейхед-линия на таймлайне + подсветка текущего сегмента.
// Затем: окна подписи → MAD-нормализация → contextDistance → сигналы D_motion/D_pose/combined,
// кандидаты-интервалы с гистерезисом, граница = 70% нарастания, метрики против референса.
import { $, say, ensureMeta } from "./utils.js";
import { makeLandmarker, close, clearModelCache } from "./model.js";
import { frameDescriptors, buildWindows, madNormalize, contextDistance,
         detectCandidates, segmentsFromCandidates, autothreshold, detectCandidatesUnion } from "./signature.js";

const v = document.getElementById("segVideo");
const cv = document.getElementById("timeline");
const cg = cv.getContext("2d");

let lm = null, blobUrl = null;
let frames = [], signal = [], cands = [], segments = [], refs = [];
let running = false, cancel = false;
let lastT = -1, lastTs = -1;
let dur = 0;

// сериализация запусков: один проход за раз, новый отменяет текущий
let runId = 0, runPromise = Promise.resolve();
let raf = 0, lastHl = -1;

const toT = t => t.toFixed(1);

function status(msg, isErr){ say(msg, isErr); }

// ── надёжный seek: ставим и ждём 'seeked' (иначе проход мог стартовать не с 0) ──
function seekTo(t){
  return new Promise(res => {
    if (Math.abs(v.currentTime - t) < 0.01){ res(); return; }
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      v.removeEventListener("seeked", finish);
      v.removeEventListener("error", finish);
      res();
    };
    const timer = setTimeout(finish, 3000);
    v.addEventListener("seeked", finish, { once: true });
    v.addEventListener("error", finish, { once: true });
    v.currentTime = t;
  });
}

// ── файл видео: автостарт ──
export function loadFile(f){
  if (!f) return;
  if (blobUrl) try { URL.revokeObjectURL(blobUrl); } catch(_){}
  blobUrl = URL.createObjectURL(f);
  v.src = blobUrl;
  // Видео сразу блокируем на 0: пока качается модель, его нельзя сдвинуть —
  // иначе проход начинается «с середины» (currentTime ≈ 46 с вместо 0).
  v.muted = true;
  v.controls = false;
  try { v.pause(); v.currentTime = 0; } catch(_){}
  frames = []; signal = []; cands = []; segments = []; refs = [];
  $("progFill").style.width = "0%";
  $("prog").textContent = "";
  renderSegments();
  $("vinfo").textContent = `${f.name} (${(f.size / 1048576).toFixed(1)} МБ)`;
  status(`выбран ${f.name} — запускаю сбор…`);
  scheduleRun();
}

// ── планировщик: отменить текущий проход → дождаться его → запустить новый ──
function scheduleRun(){
  const myId = ++runId;
  cancel = true;
  runPromise = runPromise.catch(() => {}).then(() => runCollect(myId));
  return runPromise;
}

// ── сбор кадров ──
async function runCollect(myId){
  if (running) return;
  running = true; cancel = false;
  $("btnRun").disabled = true; $("btnStop").disabled = false;
  try {
    await collect(myId);
  } catch(err){
    status(`Ошибка: ${err.message}`, true);
  } finally {
    try { v.pause(); v.controls = true; } catch(_){}
    running = false;
    $("btnRun").disabled = false; $("btnStop").disabled = true;
    if (myId === runId) drawAll();
  }
}

async function collect(myId){
  if (!v.src || !v.src.startsWith("blob:")) throw new Error("сначала выбери видеофайл");
  if (v.readyState < 1){ status("жду метаданные видео…"); await ensureMeta(v); }
  if (myId !== runId) return;
  dur = v.duration || 0;
  const del = $("delegate").value;
  status(`загрузка модели (${del})…`);
  const prog = p => status(`загрузка модели (${del})… ${Math.round(p * 100)}%`);
  try {
    close(lm); lm = await makeLandmarker(del, prog);
  } catch(err){
    if (del === "GPU"){
      status("GPU не поднялся, пробую CPU…");
      lm = await makeLandmarker("CPU", prog);
    } else throw err;
  }
  if (myId !== runId) return;
  frames = []; lastT = -1; lastTs = -1;
  v.muted = true;
  v.controls = false;
  try { v.pause(); } catch(_){}
  status(`сбор ${dur.toFixed(0)} с, сетка 5 Гц…`);
  await seekTo(0);
  if (myId !== runId) return;
  // seek-and-detect: пауза → ровная сетка 0.2 с → seek + детекция.
  // Первый кадр на t=0 — это и есть прогрев модели (~5–6 с, компиляция шейдеров GPU);
  // видео на паузе, поэтому «прыжка в середину» нет. Механика = офлайн-скрипт (Python).
  const stepSec = 0.2;
  const n = Math.floor(dur / stepSec) + 1;
  const t0 = performance.now();
  for (let i = 0; i < n; i++){
    if (cancel || myId !== runId) return;
    const t = Math.min(i * stepSec, dur);
    await seekTo(t);
    if (cancel || myId !== runId) return;
    processFrame(t);
    if (i % 25 === 0){
      const per = (performance.now() - t0) / (i + 1);
      const left = Math.max(0, (n - i - 1) * per / 1000);
      $("progFill").style.width = Math.min(100, t / dur * 100).toFixed(1) + "%";
      $("prog").textContent = `сбор ${(t / dur * 100).toFixed(0)}% · кадров ${i + 1}/${n} · t=${t.toFixed(1)} · осталось ~${left.toFixed(0)} с`;
    }
  }
  if (myId !== runId) return;
  try { v.pause(); v.playbackRate = 1; } catch(_){}
  computeSignal();
  const valid = frames.filter(f => f.desc).length;
  const cov = frames.length
    ? `кадры ${frames[0].time.toFixed(1)}–${frames[frames.length - 1].time.toFixed(1)} с`
    : "кадров нет";
  status(`Готово: ${frames.length} кадров, валидных дескрипторов ${valid} (${cov} из ${dur.toFixed(1)} с) → ${segments.length} сегмента. Перематывай и смотри.`);
}

function stopCollect(){
  cancel = true;
}

function processFrame(t){
  const now = v.currentTime;
  const ts = Math.max(lastTs + 1, Math.round((now || t) * 1000));
  lastTs = ts;
  let res = null;
  try { res = lm.detectForVideo(v, ts); } catch(_){}
  const w = res && res.worldLandmarks && res.worldLandmarks[0];
  const desc = w ? frameDescriptors(w) : null;
  frames.push({ time: t, desc });
}

// ── сигналы из кадров ──
function computeSignal(){
  const win = +$("win").value, step = +$("step").value, ctxSec = +$("ctx").value;
  const wins = buildWindows(frames, win, step);
  const norms = madNormalize(wins);
  signal = wins.map(w => {
    const d = contextDistance(wins, w.tMid, norms, ctxSec) || {};
    const Dm = d.D_motion ?? null, Dp = d.D_pose ?? null;
    const chg = Dm != null || Dp != null ? Math.max(Dm ?? 0, Dp ?? 0) : null;
    return { t: w.tMid, Dm, Dp, comb: d.combined ?? null, chg };
  });
  updateCandidates();
}

// ── кандидаты: автопорог + гистерезис (логика в signature.js) ──
function updateCandidates(){
  if ($("auto").checked){
    const at = autothreshold(signal);
    if (at){
      $("high").value = +at.high.toFixed(3);
      $("low").value = +at.low.toFixed(3);
    }
    cands = detectCandidatesUnion(signal, { frac: +$("frac").value, dupSec: 3, combPct: [0.95, 0.7], chgPct: [0.9, 0.7] });
  } else {
    const high = +$("high").value, low = +$("low").value, frac = +$("frac").value;
    cands = detectCandidates(signal, high, low, frac, "comb");
  }
  segments = segmentsFromCandidates(cands, dur);
  drawAll();
  renderSegments();
  renderMetrics();
}

function fmt(sec){
  if (!isFinite(sec) || sec == null) return "—";
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function renderSegments(){
  const el = $("segs");
  if (!segments.length){ el.innerHTML = running ? "Сбор…" : "Выбери видео — обработка начнётся автоматически."; return; }
  el.innerHTML = `<table><tr><th>№</th><th>начало</th><th>конец</th><th>граница</th><th>conf</th><th>сигнал</th></tr>` +
    segments.map(s =>
      `<tr data-s="${s.start}"><td>${s.n}</td><td>${fmt(s.start)}</td><td>${fmt(s.end)}</td>` +
      `<td>${fmt(s.boundary)}</td><td>${s.conf == null ? "—" : s.conf.toFixed(2)}</td><td>${s.dom}</td></tr>`
    ).join("") + `</table>`;
}

// ── референс ──
function parseRefs(text){
  const refs = [];
  try {
    const j = JSON.parse(text);
    if (Array.isArray(j)){
      for (const e of j){
        if (Array.isArray(e) && e.length >= 2){
          refs.push({ start: +e[0], end: +e[1], label: String(e[2] || "") });
        }
      }
      return refs;
    }
  } catch(_){}
  for (const line of text.split(/\n/)){
    const s = line.trim();
    if (!s) continue;
    const m = s.match(/^([\d.]+)[\s\t\-]+([\d.]+)(?:\s+(.*))?$/);
    if (m) refs.push({ start: +m[1], end: +m[2], label: (m[3] || "").trim() });
  }
  return refs;
}

// ── метрики ──
function overlap(r, c){
  const a = Math.max(r.start, c.startT), b = Math.min(r.end, c.endT);
  const inter = Math.max(0, b - a);
  const uni = Math.max(r.end - r.start, c.endT - c.startT);
  return uni ? inter / uni : 0;
}

function evaluate(iouThr){
  if (!refs.length) return null;
  const errs = [];
  for (const r of refs){
    let best = Infinity;
    for (const c of cands) best = Math.min(best, Math.abs(c.boundary - r.start));
    errs.push(best);
  }
  const mae = errs.reduce((a, b) => a + b, 0) / errs.length;
  const used = new Set();
  let tp = 0, missed = 0;
  for (const r of refs){
    let ok = false;
    for (let j = 0; j < cands.length; j++){
      if (used.has(j)) continue;
      if (overlap(r, cands[j]) >= iouThr){ ok = true; tp++; used.add(j); break; }
    }
    if (!ok) missed++;
  }
  const fp = cands.length - used.size;
  const prec = tp / (tp + fp || 1), rec = tp / (tp + missed || 1);
  const f1 = prec + rec ? 2 * prec * rec / (prec + rec) : 0;
  return { mae, tp, fp, missed, prec, rec, f1 };
}

function renderMetrics(){
  const m = evaluate(+$("iou").value);
  const el = $("metrics");
  if (!m){ el.innerHTML = "Нет референса — метрики не считаются."; return; }
  el.innerHTML = `MAE границ <b>${m.mae.toFixed(1)} с</b> · TP <b>${m.tp}</b> · FP <b>${m.fp}</b> · пропущено <b>${m.missed}</b>` +
    ` · precision <b>${(m.prec * 100).toFixed(0)}%</b> · recall <b>${(m.rec * 100).toFixed(0)}%</b> · F1 <b>${m.f1.toFixed(2)}</b>`;
}

// ── плейхед + подсветка текущего сегмента ──
function playheadLoop(){
  raf = requestAnimationFrame(playheadLoop);
  if (running || !signal.length) return;
  drawAll();
  const t = v.currentTime;
  if (t - lastHl >= 0.2 || t < lastHl){ lastHl = t; highlightSegment(t); }
}

function highlightSegment(t){
  const seg = segments.find(s => t >= s.start && t < s.end) ||
              (t >= dur - 0.01 ? segments[segments.length - 1] : null);
  $("segs").querySelectorAll("tr[data-s]").forEach(tr =>
    tr.classList.toggle("cur", !!seg && +tr.dataset.s === seg.start));
}

// ── отрисовка таймлайна ──
function drawAll(){
  const W = cv.width, H = cv.height;
  cg.clearRect(0, 0, W, H);
  if (!dur && v.duration) dur = v.duration || 0;
  // фон рисуем всегда — пустой канвас не должен выглядеть как «0 кадров»
  cg.fillStyle = "#10131a"; cg.fillRect(0, 0, W, H);
  if (!dur) return;
  const x = t => t / dur * W;
  const VB = H - 6;
  drawCoverage();
  if (!signal.length){
    const valid = frames.length ? frames.filter(f => f.desc).length : 0;
    cg.fillStyle = "#99a"; cg.font = "12px sans-serif";
    cg.fillText(frames.length
      ? `сигнал пуст: кадров ${frames.length}, валидных дескрипторов ${valid}`
      : "пока пусто — выбери видео и дождись сбора", 8, VB / 2 - 8);
    return;
  }
  const sigMax = Math.max(1, ...signal.map(s => s.comb ?? 0)) * 1.15;

  // невалидные зоны (нет скелета в окне)
  cg.fillStyle = "rgba(255,255,255,.06)";
  for (let i = 0; i < signal.length; i++){
    const s = signal[i];
    if (s.comb == null){
      const x1 = i ? x((signal[i - 1].t + s.t) / 2) : 0;
      const x2 = i < signal.length - 1 ? x((s.t + signal[i + 1].t) / 2) : W;
      cg.fillRect(x1, 0, Math.max(1, x2 - x1), VB);
    }
  }

  // пороги
  const yOf = c => VB - (c / sigMax * VB);
  cg.strokeStyle = "rgba(255,180,60,.8)"; cg.setLineDash([4, 4]);
  line(yOf(+$("high").value)); cg.setLineDash([]);
  cg.strokeStyle = "rgba(120,140,220,.6)"; cg.setLineDash([2, 4]);
  line(yOf(+$("low").value)); cg.setLineDash([]);

  // кривые
  cg.lineWidth = 1.5;
  drawCurve(s => s.Dm, "#7fd0ff");
  drawCurve(s => s.Dp, "#ffb56b");
  drawCurve(s => s.comb, "#9aff8f");

  // кандидаты
  for (const c of cands){
    cg.fillStyle = "rgba(255,80,80,.22)";
    cg.fillRect(x(c.startT), 0, Math.max(1, x(c.endT) - x(c.startT)), VB);
    cg.strokeStyle = "#ff5050"; cg.lineWidth = 1.5;
    cg.beginPath();
    cg.moveTo(x(c.boundary), 0); cg.lineTo(x(c.boundary), VB);
    cg.stroke();
    cg.fillStyle = "#ff9090";
    cg.font = "10px sans-serif";
    cg.fillText(toT(c.boundary), x(c.boundary) + 2, 12);
  }

  // референс
  const pal = ["#7ee0ff", "#ffb56b", "#9aff8f", "#e07ee0", "#ffe07e"];
  refs.forEach((r, i) => {
    cg.fillStyle = pal[i % pal.length] + "55";
    cg.fillRect(x(r.start), VB - 18, Math.max(1, x(r.end) - x(r.start)), 12);
    cg.fillStyle = pal[i % pal.length];
    cg.font = "10px sans-serif";
    cg.fillText(r.label || i, x(r.start), VB - 20);
  });

  // плейхед видео
  if (!running && isFinite(v.currentTime) && v.currentTime > 0){
    cg.strokeStyle = "rgba(255,255,255,.9)"; cg.lineWidth = 1.5;
    cg.beginPath(); cg.moveTo(x(v.currentTime), 0); cg.lineTo(x(v.currentTime), H); cg.stroke();
  }

  // подписи осей
  cg.fillStyle = "#99a"; cg.font = "10px sans-serif";
  for (let t = 0; t <= dur; t += Math.ceil(dur / 12 / 60) * 60 || 60){
    cg.fillText(toT(t), x(t) + 2, H - 2);
  }
  cg.fillStyle = "#aaf";
  cg.fillText("combined", 4, 12);
  cg.fillStyle = "#7fd0ff"; cg.fillText("D_motion", 4, 24);
  cg.fillStyle = "#ffb56b"; cg.fillText("D_pose", 4, 36);

  function line(y){ cg.beginPath(); cg.moveTo(0, y); cg.lineTo(W, y); cg.stroke(); }
  function drawCurve(get, color){
    cg.strokeStyle = color;
    cg.beginPath();
    let started = false;
    for (const s of signal){
      const val = get(s);
      if (val == null){ started = false; continue; }
      const px = x(s.t), py = yOf(Math.max(0, val));
      if (!started){ cg.moveTo(px, py); started = true; } else cg.lineTo(px, py);
    }
    cg.stroke();
  }
}

// покрытие кадров (серая полоса внизу — участки без кадров); рисуется всегда,
// даже когда сигнал пуст
function drawCoverage(){
  if (!frames.length) return;
  const W = cv.width, H = cv.height;
  const x = t => t / dur * W;
  cg.fillStyle = "rgba(130,130,170,.18)";
  const f0 = frames[0].time, fl = frames[frames.length - 1].time;
  if (f0 > 0) cg.fillRect(0, H - 4, x(f0), 3);
  for (let i = 1; i < frames.length; i++){
    if (frames[i].time - frames[i - 1].time > 0.5)
      cg.fillRect(x(frames[i - 1].time), H - 4, Math.max(1, x(frames[i].time) - x(frames[i - 1].time)), 3);
  }
  if (fl < dur) cg.fillRect(x(fl), H - 4, Math.max(1, W - x(fl)), 3);
}

// ── клик → seek + контекст ──
function onTimelineClick(e){
  if (running) return;
  const r = cv.getBoundingClientRect();
  const t = (e.clientX - r.left) / r.width * dur;
  try { v.currentTime = t; } catch(_){}
  const s = signal.reduce((a, b) => Math.abs(b.t - t) < Math.abs(a.t - t) ? b : a, signal[0]);
  const el = $("ctx");
  if (!s){ el.textContent = ""; return; }
  el.innerHTML = `клик t=${toT(t)} с → ближайший образец t=${toT(s.t)} с<br>` +
    `combined <b>${s.comb == null ? "—" : s.comb.toFixed(2)}</b> · D_motion <b>${s.Dm == null ? "—" : s.Dm.toFixed(2)}</b> · D_pose <b>${s.Dp == null ? "—" : s.Dp.toFixed(2)}</b>`;
  const f = frames.reduce((a, b) => Math.abs(b.time - t) < Math.abs(a.time - t) ? b : a, frames[0]);
  if (f && f.desc){
    const g = f.desc.geom;
    el.innerHTML += `<br>кадр ${toT(f.time)} с: torsoTilt <b>${g.torsoTilt.toFixed(0)}°</b> · lArmElev <b>${g.lArmElev == null ? "—" : g.lArmElev.toFixed(0)}°</b>` +
      ` · lArmAz <b>${g.lArmAz == null ? "—" : g.lArmAz.toFixed(0)}°</b> · lWristHt <b>${g.lWristHt == null ? "—" : g.lWristHt.toFixed(2)}</b>`;
  }
}

// ── экспорт ──
function exportConfig(){
  const out = {
    settings: {
      win: +$("win").value, step: +$("step").value, ctx: +$("ctx").value,
      rate: +$("rate").value, high: +$("high").value, low: +$("low").value,
      frac: +$("frac").value, iou: +$("iou").value,
      norm: "global", combPct: [0.95, 0.7], chgPct: [0.9, 0.7], dup: 3
    },
    duration: dur, frames: frames.length,
    refs, cands: cands.map(c => ({ ...c, peak: +c.peak.toFixed(3), conf: +c.conf.toFixed(3) })),
    segments,
    metrics: evaluate(+$("iou").value),
    signal: signal.map(s => ({ t: +s.t.toFixed(2), comb: s.comb == null ? null : +s.comb.toFixed(3),
                              Dm: s.Dm == null ? null : +s.Dm.toFixed(3), Dp: s.Dp == null ? null : +s.Dp.toFixed(3),
                              chg: s.chg == null ? null : +s.chg.toFixed(3) }))
  };
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "seg_config.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

// ── привязка ──
export function init(){
  const isolated = typeof self !== "undefined" && self.crossOriginIsolated === true;
  status(`Потоки CPU: ${navigator.hardwareConcurrency ?? "?"} · изоляция: ${isolated ? "да" : "нет (детекция в 1 поток — будет медленно)"}. Выбери видео.`);
  $("vfile").onchange = e => loadFile(e.target.files[0]);
  $("mfile").onchange = () => clearModelCache();
  $("btnRun").onclick = scheduleRun;
  $("btnStop").onclick = stopCollect;
  $("segVideo").onloadedmetadata = () => {
    dur = v.duration || 0;
    $("vinfo").textContent += ` · ${v.videoWidth}×${v.videoHeight} · ${toT(dur)} с`;
  };
  cv.addEventListener("click", onTimelineClick);
  $("segs").addEventListener("click", e => {
    const tr = e.target.closest("tr[data-s]");
    if (!tr || running) return;
    try { v.currentTime = +tr.dataset.s; } catch(_){}
    v.play().catch(() => {});
  });
  for (const id of ["win", "step", "ctx"]){
    $(id).addEventListener("change", () => { if (signal.length) computeSignal(); });
  }
  $("rate").addEventListener("change", () => { try { v.playbackRate = +$("rate").value; } catch(_){} });
  for (const id of ["high", "low", "frac", "iou"]){
    $(id).addEventListener("input", () => { if (signal.length) updateCandidates(); });
  }
  $("auto").addEventListener("input", () => {
    $("high").disabled = $("auto").checked;
    $("low").disabled = $("auto").checked;
    if (signal.length) updateCandidates();
  });
  $("high").disabled = $("auto").checked;
  $("low").disabled = $("auto").checked;
  $("refs").addEventListener("input", () => {
    refs = parseRefs($("refs").value);
    drawAll();
    renderMetrics();
  });
  $("btnExport").onclick = exportConfig;
  playheadLoop();
}

// авто-инициализация (для прямого <script type="module"> без main.js)
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
else init();