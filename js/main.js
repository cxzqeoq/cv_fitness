// main.js — точка входа: переключение режимов, глобальные хоткеи,
// перетаскивание/вставка видео, слайдеры допуска и общие инициализации.
import { CYCLES, PART_KEYS } from "./config.js";
import { $, say, say2, diag } from "./utils.js";
import { s, cmp } from "./state.js";
import * as single from "./singles.js";
import { init as initCompare, cmpStop, loadA, loadB, stopCamera, cycleLayout } from "./compare.js";

let mode = "single";

function setMode(m){
  mode = m;
  $("tabSingle").classList.toggle("act", m === "single");
  $("tabCmp").classList.toggle("act", m === "cmp");
  $("modeSingle").hidden = m !== "single";
  $("modeCmp").hidden = m !== "cmp";
  if (m === "cmp" && single.isRunning()) single.stop();
  if (m === "single" && (cmp.running || cmp.preview)) cmpStop();
  if (m !== "cmp" && s.camOn) stopCamera();
  diag("режим: " + (m === "cmp" ? "Сравнение" : "Один"));
}

function cycle(key){
  const el = $(key), list = CYCLES[key];
  el.value = list[(list.indexOf(el.value) + 1) % list.length];
}

// ── глобальные события ──
addEventListener("keydown", e => {
  const t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
  const k = e.key.toLowerCase();
  if (k === " "){
    e.preventDefault();
    if (mode === "cmp"){
      if (cmp.preview) cmpStop();
      else cmp.running ? cmpStop() : $("cmpGo").click();
    }
    else { single.isRunning() ? single.stop() : $("go").click(); }
    return;
  }
  if (k === "escape"){ if (mode === "cmp"){ if (cmp.running || cmp.preview) cmpStop(); } else single.stop(); return; }
  if (mode === "cmp"){
    if (k === "l"){ cycleLayout(); return; }
    return;
  }
  if (k === "p"){ cycle("poses"); return; }
  if (k === "r"){ $("rec").checked = !$("rec").checked; return; }
  if (PART_KEYS[k]){ const el = $(PART_KEYS[k]); el.checked = !el.checked; return; }
  if (k === "b") cycle("bg");
  if (k === "s") cycle("style");
});

addEventListener("dragover", e => {
  e.preventDefault();
  const dz = e.target.closest?.("#dropzone, .dz");
  if (dz) dz.classList.add("hot");
});
addEventListener("dragleave", e => {
  if (e.target === document) document.querySelectorAll(".hot").forEach(el => el.classList.remove("hot"));
});
addEventListener("drop", e => {
  e.preventDefault();
  document.querySelectorAll(".hot").forEach(el => el.classList.remove("hot"));
  const f = [...e.dataTransfer.files].find(x => x.type.startsWith("video/"));
  if (!f) return;
  const id = e.target.closest?.("#dropzone, .dz")?.id || "";
  if (mode === "cmp" && (id === "dzA" || (id !== "dzB" && !s.hasA))) loadA(f);
  else if (mode === "cmp"){ if (!s.useCamB) loadB(f); else say2("Источник B — камера: верните «файл» или выключите камеру.", true); }
  else single.loadFile(f);
});
addEventListener("paste", e => {
  const f = [...(e.clipboardData?.files || [])].find(x => x.type.startsWith("video/"));
  if (!f) return;
  if (mode === "cmp"){ s.hasA && !s.useCamB ? loadB(f) : loadA(f); }
  else single.loadFile(f);
});

// Допуск (градусы) — подпись у ползунка.
$("thr").oninput = e => $("thrv").textContent = e.target.value + "°";

// ── звук видео: громкость + mute, применяются на лету (A — эталон, v — «Один») ──
function applyAudio(){
  for (const id of ["vA", "v"]){
    const el = document.getElementById(id);
    if (!el) continue;
    el.volume = s.sound.vol;
    el.muted = s.sound.muted;
  }
}
$("vol").oninput = e => {
  s.sound.vol = +e.target.value / 100;
  $("volV").textContent = e.target.value + "%";
  applyAudio();
};
$("sndOn").onchange = e => { s.sound.muted = !e.target.checked; applyAudio(); };
applyAudio();

// ── запуск ──
single.init();
initCompare();
$("tabSingle").onclick = () => setMode("single");
$("tabCmp").onclick = () => setMode("cmp");

diag("JS: загружен " + new Date().toLocaleTimeString());
const diagEl = $("diagRow");
if (diagEl) diagEl.textContent =
  `изоляция: ${crossOriginIsolated ? "да" : "нет"} · wakeLock: ${"wakeLock" in navigator ? "да" : "нет"}`;