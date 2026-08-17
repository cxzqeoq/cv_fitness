// analyze.mjs — офлайн-анализ видео: data/<name>_wm.json → сигнал → кандидаты → сегменты.
// Использует те же функции signature.js, что и debug-страница (паритет гарантирован).
// Запуск: node tools/analyze.mjs <имя>   (по умолчанию "clip1")
//   читает data/<имя>_wm.json, пишет data/<имя>_signal.json (схема браузерного экспорта).
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { frameDescriptors, buildWindows, madNormalize, madNormalizeLocal, contextDistance,
         autothreshold, detectCandidatesUnion, segmentsFromCandidates } from "../js/signature.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const name = process.argv[2] || "clip1";
const NORM = process.argv[3] || "global"; // global | cap | local
const WIN = 5, STEP = 2, CTX = 5, RADIUS = 120, FRAC = 0.7;

const json = JSON.parse(readFileSync(join(HERE, "..", "data", name + "_wm.json"), "utf-8"));
const frames = json.frames.map(f => ({ time: f.t, desc: f.wm ? frameDescriptors(f.wm) : null }));
const dur = json.duration || (frames.length ? frames[frames.length - 1].time : 0);

const wins = buildWindows(frames, WIN, STEP);
const norms = NORM === "global" ? madNormalize(wins) : madNormalizeLocal(wins, RADIUS, NORM === "cap");
const signal = wins.map((w, i) => {
  const d = contextDistance(wins, w.tMid, NORM === "global" ? norms : norms[i], CTX) || {};
  const Dm = d.D_motion ?? null, Dp = d.D_pose ?? null;
  const chg = Dm != null || Dp != null ? Math.max(Dm ?? 0, Dp ?? 0) : null;
  return { t: w.tMid, Dm, Dp, comb: d.combined ?? null, chg };
});
const cands = detectCandidatesUnion(signal, { frac: FRAC, dupSec: 3, combPct: [0.95, 0.7], chgPct: [0.9, 0.7] });
const segments = segmentsFromCandidates(cands, dur);

const valid = frames.filter(f => f.desc).length;
console.log(`${name}: dur=${dur.toFixed(1)} с · кадров ${frames.length} (валид ${valid}) · окон ${wins.length} · норм=${NORM}${NORM === "global" ? "" : "(" + RADIUS + "с)"}`);
const atC = autothreshold(signal, 0.95, 0.7, "comb");
const atG = autothreshold(signal, 0.95, 0.7, "chg");
console.log(`автопорог: comb high=${atC ? atC.high.toFixed(3) : "—"} low=${atC ? atC.low.toFixed(3) : "—"} · chg high=${atG ? atG.high.toFixed(3) : "—"} low=${atG ? atG.low.toFixed(3) : "—"}`);
const vals = signal.filter(s => s.comb != null);
if (vals.length){
  const mx = vals.reduce((a, b) => a.comb > b.comb ? a : b);
  console.log(`сигнал: ${vals.length} точек, max comb=${mx.comb.toFixed(2)} на t=${mx.t.toFixed(1)} с`);
} else {
  console.log("сигнал пуст — нечего сегментировать");
}
console.log(`кандидаты (union): ${cands.length}`);
for (const c of cands){
  const dom = c.Dm == null && c.Dp == null ? "—"
    : c.Dm == null ? "D_pose" : c.Dp == null ? "D_motion"
    : Math.abs(c.Dm - c.Dp) < 0.05 ? "оба" : c.Dm > c.Dp ? "D_motion" : "D_pose";
  console.log(`  [${c.startT.toFixed(1)}–${c.endT.toFixed(1)}] boundary=${c.boundary.toFixed(1)} с · conf=${c.conf.toFixed(2)} · peak=${c.peak.toFixed(2)} · ${dom}`);
}
console.log("сегменты:");
for (const s of segments)
  console.log(`  №${s.n} ${s.start.toFixed(1)}–${s.end.toFixed(1)} · граница=${s.boundary == null ? "—" : s.boundary.toFixed(1)} · conf=${s.conf == null ? "—" : s.conf.toFixed(2)} · ${s.dom}`);

const out = {
  settings: { win: WIN, step: STEP, ctx: CTX, rate: json.rate_hz || 5,
              norm: NORM, radius: RADIUS, frac: FRAC, dup: 3, iou: 0.3,
              combPct: [0.95, 0.7], chgPct: [0.9, 0.7] },
  duration: +dur.toFixed(3), frames: frames.length, refs: [],
  cands: cands.map(c => ({ ...c, peak: +c.peak.toFixed(3), conf: +c.conf.toFixed(3) })),
  segments,
  metrics: null,
  signal: signal.map(s => ({ t: +s.t.toFixed(2), comb: s.comb == null ? null : +s.comb.toFixed(3),
                             Dm: s.Dm == null ? null : +s.Dm.toFixed(3),
                             Dp: s.Dp == null ? null : +s.Dp.toFixed(3),
                             chg: s.chg == null ? null : +s.chg.toFixed(3) }))
};
const outPath = join(HERE, "..", "data", name + "_signal.json");
writeFileSync(outPath, JSON.stringify(out, null, 2));
console.log(`фикстура: ${outPath}`);