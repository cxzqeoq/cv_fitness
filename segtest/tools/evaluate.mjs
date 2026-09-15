// evaluate.mjs — оценка precision/recall/MAE сегментации по референсным границам.
// Читает data/<name>_signal.json (результат analyze.mjs) и data/<name>_refs.json.
// Запуск: node tools/evaluate.mjs <name> [tolSec]
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const name = process.argv[2];
const TOL = parseFloat(process.argv[3]) || 2.0;
const SEG = process.argv[4] === "seg"; // оценивать границы сегментов (после merge), а не кандидаты

if (!name) {
  console.error("Usage: node tools/evaluate.mjs <name> [tolSec] [seg]");
  process.exit(1);
}

const sigPath = join(HERE, "..", "data", `${name}_signal.json`);
const refPath = join(HERE, "..", "data", `${name}_refs.json`);

if (!existsSync(sigPath)) {
  console.error(`Signal not found: ${sigPath}`);
  console.error(`Run: node tools/analyze.mjs ${name}`);
  process.exit(1);
}
if (!existsSync(refPath)) {
  console.error(`Refs not found: ${refPath}`);
  process.exit(1);
}

const signal = JSON.parse(readFileSync(sigPath, "utf-8"));
const refsData = JSON.parse(readFileSync(refPath, "utf-8"));
const refs = Array.isArray(refsData.refs) ? refsData.refs : refsData;
let cands = (signal.cands || []).filter(c => c.boundary != null && isFinite(c.boundary));
if (SEG && Array.isArray(signal.segments)){
  cands = signal.segments.filter(s => s.boundary != null && isFinite(s.boundary))
    .map(s => ({ boundary: s.boundary, conf: s.conf ?? 0, Dm: null, Dp: null }));
}

const matchedCandIdx = new Set();
const matches = [];
const missed = [];

for (const ref of refs) {
  let bestIdx = -1;
  let bestErr = Infinity;
  for (let i = 0; i < cands.length; i++) {
    if (matchedCandIdx.has(i)) continue;
    const err = Math.abs(cands[i].boundary - ref);
    if (err < bestErr) {
      bestErr = err;
      bestIdx = i;
    }
  }
  if (bestErr <= TOL) {
    matchedCandIdx.add(bestIdx);
    matches.push({ ref, boundary: cands[bestIdx].boundary, err: bestErr });
  } else {
    missed.push({ ref, bestErr: bestErr === Infinity ? null : bestErr });
  }
}

const fp = cands.filter((_, i) => !matchedCandIdx.has(i));
const tp = matches.length;
const fn = missed.length;
const precision = tp / (tp + fp.length || 1);
const recall = tp / (tp + fn || 1);
const f1 = precision + recall ? 2 * precision * recall / (precision + recall) : 0;
const mae = matches.length ? matches.reduce((a, b) => a + b.err, 0) / matches.length : 0;

console.log(`\n${name}: tolerance ±${TOL} с`);
console.log(`  refs:      ${refs.length}`);
console.log(`  TP:        ${tp}`);
console.log(`  FP:        ${fp.length}`);
console.log(`  FN:        ${fn}`);
console.log(`  precision: ${precision.toFixed(3)}`);
console.log(`  recall:    ${recall.toFixed(3)}`);
console.log(`  F1:        ${f1.toFixed(3)}`);
console.log(`  MAE:       ${mae.toFixed(2)} с`);

if (matches.length) {
  console.log(`\n  matches:`);
  for (const m of matches) {
    console.log(`    ref ${m.ref.toFixed(1)} → cand ${m.boundary.toFixed(1)} (err ${m.err.toFixed(2)} с)`);
  }
}
if (missed.length) {
  console.log(`\n  missed:`);
  for (const m of missed) {
    console.log(`    ref ${m.ref.toFixed(1)} (nearest ${m.bestErr != null ? m.bestErr.toFixed(2) + " с" : "—"})`);
  }
}
if (fp.length) {
  console.log(`\n  false positives:`);
  for (const c of fp.slice(0, 20)) {
    console.log(`    boundary ${c.boundary.toFixed(1)} с · conf=${(c.conf ?? 0).toFixed(2)} · dom=${c.Dm == null && c.Dp == null ? "—" : c.Dm == null ? "D_pose" : c.Dp == null ? "D_motion" : Math.abs(c.Dm - c.Dp) < 0.05 ? "оба" : c.Dm > c.Dp ? "D_motion" : "D_pose"}`);
  }
  if (fp.length > 20) console.log(`    ... и ещё ${fp.length - 20}`);
}
