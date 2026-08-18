// utils.js — помощники без состояния и мелкие DOM-обёртки.
import { VIS_LO, VIS_SPAN } from "./config.js";

export const $ = id => document.getElementById(id);

// ── сообщения в статусные строки ──
export function say(msg, isErr){ $("status").innerHTML = msg; $("status").className = isErr ? "err" : ""; }

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

// ── работа с точками скелета ──
// Прозрачность по уверенности детектора (visibility): чем увереннее — тем плотнее.
export function fadeA(pv){
  if (pv === undefined) return 1;
  if (pv < VIS_LO) return 0;
  return Math.min(1, Math.max(0.12, (pv - VIS_LO) / VIS_SPAN));
}
export const mid = (a,b) => ({ x:(a.x+b.x)/2, y:(a.y+b.y)/2,
  z:((a.z ?? 0)+(b.z ?? 0))/2, v: Math.min(a.v ?? 1, b.v ?? 1) });
export const pair = (g, i) => (g[i] || { x:0, y:0, v:0 });

// Угол в трёх точках с весом оси z (глубины): zW=1 — полное 3D, меньше — приглушить z.
export function ang3w(p1, p2, p3, zW){
  const uz=(p1.z??0)-(p2.z??0), wz=(p3.z??0)-(p2.z??0);
  const ux=p1.x-p2.x, uy=p1.y-p2.y;
  const wx=p3.x-p2.x, wy=p3.y-p2.y;
  const mu=Math.hypot(ux,uy,uz*zW), mw=Math.hypot(wx,wy,wz*zW);
  if (!mu || !mw) return null;
  const cos=(ux*wx+uy*wy+(uz*zW)*(wz*zW))/(mu*mw);
  return Math.acos(Math.max(-1, Math.min(1, cos))) * 180/Math.PI;
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