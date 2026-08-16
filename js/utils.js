// utils.js — помощники без состояния и мелкие DOM-обёртки.
// Ничего не экспортируют сюда из других модулей, кроме config/state (для beep).
import { TIERS } from "./config.js";
import { s } from "./state.js";

export const $ = id => document.getElementById(id);

// ── сообщения в статусные строки ──
export function say(msg, isErr){ $("status").innerHTML = msg; $("status").className = isErr ? "err" : ""; }
export function say2(msg, isErr){ $("statusC").innerHTML = msg; $("statusC").className = isErr ? "err" : ""; }
export function setStat(){ $("stat").innerHTML = [...arguments].map(h => `<span>${h}</span>`).join(""); }

// Техническая отладочная строка (внизу страницы).
export function diag(msg, isErr){
  try {
    const el = document.getElementById("diag");
    el.textContent = msg;
    el.className = isErr ? "err" : (msg.startsWith("JS:") ? "ok" : "");
  } catch(_){}
}

// Глобальные перехватчики ошибок — чтобы падения были видны на странице.
if (typeof window !== "undefined"){
  window.addEventListener("error", e => { try { diag("ошибка: " + (e.message || (e.error && e.error.message) || e.type), true); } catch(_){} });
  window.addEventListener("unhandledrejection", e => { try { diag("rejection: " + ((e.reason && e.reason.message) || e.reason), true); } catch(_){} });
}

export function fmtN(n){ return n == null ? "—" : Math.round(n).toLocaleString("ru-RU"); }

// ── работа с точками скелета ──
// Прозрачность по уверенности детектора (visibility): чем увереннее — тем плотнее.
export function fadeA(pv){
  if (pv === undefined) return 1;
  if (pv < VIS_LO) return 0;
  return Math.min(1, Math.max(0.12, (pv - VIS_LO) / VIS_SPAN));
}
import { VIS_LO, VIS_SPAN } from "./config.js";
export const mid = (a,b) => ({ x:(a.x+b.x)/2, y:(a.y+b.y)/2,
  z:((a.z ?? 0)+(b.z ?? 0))/2, v: Math.min(a.v ?? 1, b.v ?? 1) });
export const pair = (g, i) => (g[i] || { x:0, y:0, v:0 });

// Угол в трёх точках (градусы). Возвращает null, если позиции вырождены.
export function ang3(p1, p2, p3){
  return ang3w(p1, p2, p3, 1);
}
// То же, но с весом оси z (глубины): zW=1 — полное 3D, меньше — приглушить z.
export function ang3w(p1, p2, p3, zW){
  const uz=(p1.z??0)-(p2.z??0), wz=(p3.z??0)-(p2.z??0);
  const ux=p1.x-p2.x, uy=p1.y-p2.y;
  const wx=p3.x-p2.x, wy=p3.y-p2.y;
  const mu=Math.hypot(ux,uy,uz*zW), mw=Math.hypot(wx,wy,wz*zW);
  if (!mu || !mw) return null;
  const cos=(ux*wx+uy*wy+(uz*zW)*(wz*zW))/(mu*mw);
  return Math.acos(Math.max(-1, Math.min(1, cos))) * 180/Math.PI;
}

// ── сходство и тиры ──
// Мягкое сходство: до tol — 100%, дальше плавный спуск до 0 к 2.2×tol,
// ниже — 0 (мимо). «Старался, но неточно» получает частичный процент,
// а не ступеньку «всё или ничего».
export function softSim(delta, tol){
  if (delta <= tol) return 1;
  const cap = tol * 2.2;
  if (delta >= cap) return 0;
  return (cap - delta) / (cap - tol);
}
export function tierFor(sim){
  for (const t of TIERS) if (sim >= t.min) return t;
  return TIERS[TIERS.length - 1];
}

// ── видео: дождаться метаданных (лимит 10 с) ──
export function ensureMeta(video){
  if (video.readyState >= 1) return Promise.resolve();
  return new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error("видео не открылось за 10 с")), 10000);
    video.addEventListener("loadedmetadata", () => { clearTimeout(t); res(); }, { once:true });
    video.addEventListener("error", () => { clearTimeout(t); rej(new Error("файл не читается")); }, { once:true });
  });
}

export function mediaErrText(e){
  return `MediaError <b>${e?.code}</b> — ${MEDIA_ERR[e?.code] || "неизвестно"}` +
      (e?.message ? `<br>${e.message}` : "") +
      `<br>Проверьте профиль: <code>ffprobe -v error -show_entries stream=codec_name,profile,pix_fmt -of default=nw=1 ФАЙЛ</code>`;
}
import { MEDIA_ERR } from "./config.js";

// ── короткий звуковой сигнал (отсчёт, падения детекции) ──
export function beep(freq, dur){
  try {
    s.actx = s.actx || new (window.AudioContext || window.webkitAudioContext)();
    if (s.actx.state === "suspended") s.actx.resume();
    const o = s.actx.createOscillator(), g = s.actx.createGain();
    o.type = "sine"; o.frequency.value = freq || 660;
    g.gain.setValueAtTime(0.1, s.actx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, s.actx.currentTime + (dur || 0.14));
    o.connect(g); g.connect(s.actx.destination);
    o.start(); o.stop(s.actx.currentTime + (dur || 0.16));
  } catch(_){}
}

// ── запуск видео со звуком (обход автоплей-политики) ──
// Реальный звук включается в контексте жеста пользователя; если async-старт со
// звуком запрещён (iOS Safari, старт после await), начинаем как muted и включаем
// звук после успешного старта. Резолвится, как только видео пошло (тихо или со
// звуком); отклоняется только если и прямой, и фолбэк-старт не удались.
export function playVideo(v, sound){
  v.muted = !sound;
  const p = v.play();
  if (!sound || !p) return p || Promise.resolve();
  return p.catch(() => {
    v.muted = true;
    return v.play().then(() => { v.muted = false; }).then(() => true, () => false);
  });
}