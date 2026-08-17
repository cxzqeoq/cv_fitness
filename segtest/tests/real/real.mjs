// real.mjs — офлайн-интеграция на реальных видео (нужны data/*_wm.json, генерируются extract_desc.py).
// Проверяет пайплайн signature.js на реальных данных: полное покрытие с 0, валидные
// дескрипторы, число границ и совпадение с прошлыми прогонами.
// Запуск: node tests/real/real.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { frameDescriptors, buildWindows, madNormalize, contextDistance,
         autothreshold, detectCandidates, segmentsFromCandidates } from "../../js/signature.js";

const HERE = dirname(fileURLToPath(import.meta.url));

const CASES = [
  { name: "clip1", minFrames: 400, maxFirstT: 0.6, minCands: 2, boundary: 76.5, tol: 2.0 },
  { name: "0808", minFrames: 150, maxFirstT: 0.6, minCands: 0, boundary: null },
];

let failed = 0;
for (const c of CASES){
  const json = JSON.parse(readFileSync(join(HERE, "..", "..", "data", c.name + "_wm.json"), "utf-8"));
  const frames = json.frames.map(f => ({ time: f.t, desc: f.wm ? frameDescriptors(f.wm) : null }));
  const dur = json.duration;
  const wins = buildWindows(frames, 5, 2);
  const norms = madNormalize(wins);
  const signal = wins.map(w => {
    const d = contextDistance(wins, w.tMid, norms, 5) || {};
    return { t: w.tMid, comb: d.combined ?? null };
  });
  const at = autothreshold(signal);
  const cands = at ? detectCandidates(signal, at.high, at.low, 0.7) : [];
  const valid = frames.filter(f => f.desc).length;

  const checks = [
    ["кадров >= " + c.minFrames, frames.length >= c.minFrames],
    ["старт с 0 (t0 < " + c.maxFirstT + " с)", frames[0].time < c.maxFirstT],
    ["валид >= 90%", valid / frames.length >= 0.9],
    ["кандидатов >= " + c.minCands, cands.length >= c.minCands],
  ];
  if (c.boundary != null)
    checks.push(["граница ~" + c.boundary + " с (±" + c.tol + ")", cands.some(x => Math.abs(x.boundary - c.boundary) < c.tol)]);

  const ok = checks.every(([, v]) => v);
  if (!ok) failed++;
  console.log(`${c.name}: ${ok ? "OK" : "FAIL"} · кадров ${frames.length} (валид ${valid}) · кандидатов ${cands.length}`);
  for (const [label, v] of checks) if (!v) console.log(`  ✗ ${label}`);
}
process.exit(failed ? 1 : 0);