// Юнит-тесты signature.js (Node ESM) — синтетические серии worldLandmarks.
// Запуск: node tests/unit/signature.mjs
// Проверяем физику признаков: разные движения дают разные подписи,
// смена позы даёт D_pose, смена кинематики — D_motion.
import assert from "node:assert/strict";
import { I } from "../../js/config.js";
import {
  frameDescriptors, windowSignature, buildWindows, madNormalize,
  contextDistance, medianWin, detectCandidates, segmentsFromCandidates, autothreshold,
  segmentSignature, mergeSimilarSegments, refineCandidates, smoothSignal
} from "../../js/signature.js";

// ── синтетический скелет: стоит, руки вдоль тела ──
function skel(){
  const p = {};
  const P = (i, x, y, z) => { p[i] = { x, y, z, v: 1 }; };
  P(I.LHIP, -0.16, 0, 0.03); P(I.RHIP, 0.16, 0, 0.03);
  P(I.LSH, -0.22, 0.55, 0);  P(I.RSH, 0.22, 0.55, 0);
  P(I.LEL, -0.22, 0.3, 0);   P(I.REL, 0.22, 0.3, 0);
  P(I.LWR, -0.22, 0.05, 0);  P(I.RWR, 0.22, 0.05, 0);
  P(I.LKN, -0.13, -0.4, 0);  P(I.RKN, 0.13, -0.4, 0);
  P(I.LAN, -0.13, -0.85, 0); P(I.RAN, 0.13, -0.85, 0);
  return p;
}

// Анимация левой руки.
//   circle — вращение руки в горизонтальной плоскости (x-z);
//   raise — подъём руки в сагиттальной плоскости (y-z);
//   raiseLying — подъём руки, но весь скелет повёрнут на 90° (лёжа);
//   static — покой.
function anim(mode, t){
  const p = skel();
  const sh = p[I.LSH];
  const d = (x, y, z) => ({ x, y, z, v: 1 });
  if (mode === "circle"){
    const a = t * 1.6;
    const dir = { x: Math.cos(a), y: 0, z: Math.sin(a) };
    p[I.LEL] = d(sh.x + 0.32 * dir.x, sh.y, sh.z + 0.32 * dir.z);
    p[I.LWR] = d(sh.x + 0.62 * dir.x, sh.y, sh.z + 0.62 * dir.z);
  } else if (mode === "raise" || mode === "raiseLying"){
    const up = (Math.sin(t * 1.6) + 1) / 2;   // 0..1
    p[I.LEL] = d(sh.x, sh.y + 0.32 * up, sh.z + 0.1 * (1 - up));
    p[I.LWR] = d(sh.x, sh.y + 0.62 * up, sh.z + 0.2 * (1 - up));
  }
  if (mode === "raiseLying" || mode === "staticLying"){
    // поворот на 90° вокруг оси X: «вверх» уходит в «вперёд»
    for (const k of Object.keys(p)) p[k] = { x: p[k].x, y: p[k].z, z: -p[k].y, v: p[k].v };
  }
  return p;
}

function toArr(p){
  const a = [];
  for (let i = 0; i < 33; i++) a.push(p[i] || { x: 0, y: 0, z: 0, v: 0 });
  return a;
}

// spec: {время: режим} — режим действует от своего времени и дальше.
function buildFrames(spec, dur, rateHz = 5){
  const frames = [];
  const dt = 1 / rateHz;
  const keys = Object.keys(spec).map(Number).sort((x, y) => x - y);
  for (let t = 0; t < dur - 1e-6; t += dt){
    let mode = spec[keys[0]];
    for (const b of keys) if (t >= b) mode = spec[b];
    const desc = frameDescriptors(toArr(anim(mode, t)));
    if (desc) frames.push({ time: t, desc });
  }
  return frames;
}

function run(frames, boundary, inside){
  const wins = buildWindows(frames);
  const norms = madNormalize(wins);
  return {
    boundary: contextDistance(wins, boundary, norms),
    inside: contextDistance(wins, inside, norms)
  };
}

// 1. Два разных движения рук (горизонтальное вращение vs подъём) — combined высок на стыке.
// Рука прямая в обоих → суставы не меняются; различие в траектории → D_pose (геометрия) доминирует.
{
  const r = run(buildFrames({ 0: "circle", 10: "raise" }, 20), 10, 4);
  assert(r.boundary && r.inside, "contextDistance не вернул результат");
  assert(r.boundary.combined > r.inside.combined * 2,
    `combined на стыке (${r.boundary.combined.toFixed(2)}) должен быть >> внутри (${r.inside.combined.toFixed(2)})`);
  assert(r.boundary.combined > 0.5, `combined на стыке = ${r.boundary.combined.toFixed(2)}`);
  assert(r.boundary.D_pose > r.boundary.D_motion,
    `смена траектории руки: D_pose (${r.boundary.D_pose.toFixed(2)}) должен доминировать над D_motion (${r.boundary.D_motion.toFixed(2)})`);
  console.log(`1. circle vs raise: combined стык ${r.boundary.combined.toFixed(2)} / внутри ${r.inside.combined.toFixed(2)} (D_pose ${r.boundary.D_pose.toFixed(2)} / D_motion ${r.boundary.D_motion.toFixed(2)}) — OK`);
}

// 2. Смена позы без движения (стоит → лежит) — D_pose доминирует.
// D_motion может быть null: углы константны (MAD=0), кинематики нет.
{
  const r = run(buildFrames({ 0: "static", 10: "staticLying" }, 20), 10, 4);
  assert(r.boundary, "нет результата");
  const dm = r.boundary.D_motion ?? 0;
  assert(r.boundary.D_pose > dm * 1.5,
    `смена позы: D_pose (${r.boundary.D_pose.toFixed(2)}) должен >> D_motion (${dm.toFixed(2)})`);
  assert(r.boundary.D_pose > 0.25, `D_pose = ${r.boundary.D_pose.toFixed(2)}`);
  console.log(`2. стоим→лежим (без движения): D_pose ${r.boundary.D_pose.toFixed(2)} / D_motion ${r.boundary.D_motion === null ? "null" : r.boundary.D_motion.toFixed(2)} — OK`);
}

// 2b. Смена позы + движение — оба сигнала растут (tilt — угол, законно входит в D_motion).
{
  const r = run(buildFrames({ 0: "raise", 10: "raiseLying" }, 20), 10, 4);
  assert(r.boundary, "нет результата");
  assert(r.boundary.combined > 0.5, `combined = ${r.boundary.combined.toFixed(2)}`);
  assert(r.boundary.D_pose > 0.2, `D_pose = ${r.boundary.D_pose.toFixed(2)}`);
  console.log(`2b. стоим→лежим (с движением): combined ${r.boundary.combined.toFixed(2)} (D_motion ${r.boundary.D_motion.toFixed(2)} / D_pose ${r.boundary.D_pose.toFixed(2)}) — OK`);
}

// 3. Покой → движение — и D_motion, и D_pose растут (подъём руки: и углы, и геометрия).
{
  const r = run(buildFrames({ 0: "static", 10: "raise" }, 20), 10, 3);
  assert(r.boundary, "нет результата");
  assert(r.boundary.combined > r.inside.combined * 2,
    `combined стык (${r.boundary.combined.toFixed(2)}) >> внутри (${r.inside.combined.toFixed(2)})`);
  assert(r.boundary.D_motion > 0.3, `D_motion = ${r.boundary.D_motion.toFixed(2)}`);
  assert(r.boundary.combined > 0.5, `combined = ${r.boundary.combined.toFixed(2)}`);
  console.log(`3. покой→движение: combined ${r.boundary.combined.toFixed(2)} (D_motion ${r.boundary.D_motion.toFixed(2)} / D_pose ${r.boundary.D_pose.toFixed(2)}) — OK`);
}

// 4. Устойчивость к выбросам: MAD-нормализация и робастный размах не ломаются
// от одиночного «телепорта» вдали от границы; граничный combined остаётся в разумных пределах.
{
  const frames = buildFrames({ 0: "circle", 10: "raise" }, 20);
  const fi = Math.floor(frames.length / 3);            // t ≈ 6.7 — не у границы
  frames[fi].desc.geom.lWristHt = 1e6;
  frames[fi + 1].desc.angles.rElbow = 1e6;
  const wins = buildWindows(frames);
  const norms = madNormalize(wins);
  const d = contextDistance(wins, 10, norms);
  assert(d && isFinite(d.combined) && isFinite(d.D_motion) && isFinite(d.D_pose), "выброс ломает расстояния");
  assert(d.combined > 0.3, `combined при выбросе = ${d.combined}`);
  assert(d.combined < 10, `выброс раздул combined = ${d.combined}`);
  console.log(`4. выбросы: combined ${d.combined.toFixed(2)} — OK`);
}

// 5. Дескрипторы одного кадра: поза и руки корректны.
{
  const desc = frameDescriptors(toArr(anim("circle", 0)));
  assert(desc.valid);
  assert(Math.abs(desc.geom.torsoTilt) < 10, `torsoTilt стоя = ${desc.geom.torsoTilt}`);
  assert(desc.angles.lElbow != null);
  const lying = frameDescriptors(toArr(anim("raiseLying", 0)));
  assert(Math.abs(lying.geom.torsoTilt - 90) < 10, `torsoTilt лёжа = ${lying.geom.torsoTilt}`);
  console.log(`5. torsoTilt стоя ${desc.geom.torsoTilt.toFixed(1)}° / лёжа ${lying.geom.torsoTilt.toFixed(1)}° — OK`);
}

// 6. Пустые/мелкие окна и medianWin.
{
  assert(windowSignature([]) === null);
  assert(windowSignature([{ time: 0, desc: {} }, { time: 0.2, desc: {} }]) === null);
  assert(medianWin([]) === null);
  console.log("6. граничные случаи (пустые окна) — OK");
}

// ── кандидаты и сегменты ──
// Простой сигнал: плато-пик t=8..12 на фоне 0.2.
function plateau(peakT0, peakT1, peakVal, dur = 20){
  const sig = [];
  for (let t = 0; t <= dur; t += 1){
    const comb = (t >= peakT0 && t <= peakT1) ? peakVal : 0.2;
    sig.push({ t, comb, Dm: 0.3, Dp: 0.9 });
  }
  return sig;
}

// 7. Один пик → один кандидат; граница = первый образец ≥ base + 0.7·(peak−base).
{
  const sig = plateau(8, 12, 1.0);
  const cands = detectCandidates(sig, 0.6, 0.3, 0.7);
  assert(cands.length === 1, `ожидал 1 кандидат, got ${cands.length}`);
  assert(cands[0].boundary === 8, `boundary=${cands[0].boundary}`);
  assert(cands[0].conf > 0.7, `conf=${cands[0].conf}`);
  console.log(`7. один пик → кандидат, граница ${cands[0].boundary} с, conf ${cands[0].conf.toFixed(2)} — OK`);
}

// 8. Два раздельных пика → два кандидата; гистерезис не сливает.
{
  const sig = plateau(6, 9, 1.0, 30);
  for (let t = 20; t <= 23; t++) sig[t].comb = 0.9;
  const cands = detectCandidates(sig, 0.6, 0.3, 0.7);
  assert(cands.length === 2, `ожидал 2 кандидата, got ${cands.length}`);
  assert(cands[0].boundary === 6 && cands[1].boundary === 20);
  console.log("8. два пика → 2 кандидата — OK");
}

// 9. Нет пиков → нет кандидатов; автопорог корректен.
{
  const flat = plateau(0, 0, 0.2);
  assert(detectCandidates(flat, 0.6, 0.3, 0.7).length === 0);
  // Плавный пик с единственным максимумом (95-й перцентиль < максимума).
  const bump = [];
  for (let t = 0; t <= 40; t++){
    const d = Math.abs(t - 10);
    const comb = d <= 3 ? 2.0 * (1 - d / 4) : 0.2;
    bump.push({ t, comb });
  }
  const at = autothreshold(bump);
  assert(at && at.high > at.low && isFinite(at.high) && isFinite(at.low),
    `autothreshold = ${JSON.stringify(at)}`);
  assert(at.high < 2.0, `high ${at.high} не должен равняться максимуму`);
  assert(at.low >= 0.2, `low ${at.low}`);
  console.log(`9. без пиков → 0 кандидатов; autothreshold high ${at.high.toFixed(2)} / low ${at.low.toFixed(2)} — OK`);
}

// 10. Сегменты из кандидатов: границы делят видео.
{
  const sig = plateau(8, 12, 1.0, 20);
  const cands = detectCandidates(sig, 0.6, 0.3, 0.7);
  const segs = segmentsFromCandidates(cands, 20);
  assert(segs.length === 2, `сегментов ${segs.length}`);
  assert(segs[0].start === 0 && segs[0].end === 8);
  assert(segs[1].start === 8 && segs[1].end === 20);
  // Признаки перехода — на сегменте, ЗАКАНЧИВАЮЩЕМСЯ границей.
  assert(segs[0].dom === "D_pose" && segs[0].conf > 0.7, `dom=${segs[0].dom} conf=${segs[0].conf}`);
  const none = segmentsFromCandidates([], 20);
  assert(none.length === 1 && none[0].end === 20 && none[0].boundary === null);
  console.log("10. сегменты: [0→8] с признаками, [8→20] хвост; без кандидатов — один до конца — OK");
}

// 11. segmentSignature возвращает медианную подпись окон сегмента (не null).
{
  const frames = buildFrames({ 0: "static", 12: "circle", 40: "static" }, 50, 5);
  const wins = buildWindows(frames, 5, 2);
  const sig = segmentSignature(wins, 0, 10, 0);
  assert(sig, "segmentSignature вернул null — окна внутри сегмента должны быть");
  assert(typeof sig.torsoTilt === "object" && sig.torsoTilt.med != null, "подпись не содержит med-компоненты");
  // окно, не содержащее окон → null
  assert(segmentSignature(wins, 999, 1000) == null, "сегмент вне диапазона должен давать null");
  console.log("11. segmentSignature — медиана окон сегмента (не null) — OK");
}

// 12. mergeSimilarSegments объединяет похожие соседние сегменты (одно движение, разная интенсивность).
{
  // Три сегмента: circle-повторение с двумя всплесками внутри (same pattern) — должны слиться,
  // затем переход в static (другой паттерн) — должен остаться.
  const frames = buildFrames({ 0: "circle", 8: "circle", 24: "static" }, 40, 5);
  const wins = buildWindows(frames, 5, 2);
  const norms = madNormalize(wins);
  const cands = [
    { boundary: 8,  conf: 2.0, Dm: 1.0, Dp: 1.0 },
    { boundary: 16, conf: 2.0, Dm: 1.0, Dp: 1.0 },
    { boundary: 24, conf: 2.0, Dm: 1.0, Dp: 1.0 }
  ];
  const segs0 = segmentsFromCandidates(cands, 40);
  assert(segs0.length === 4, `ожидал 4 сегмента, got ${segs0.length}`);
  const merged = mergeSimilarSegments(segs0, wins, norms, { mergeThr: 0.3, maxIter: 10, pad: 0 });
  assert(merged.length < segs0.length, `merge не объединил похожие сегменты (${merged.length} >= ${segs0.length})`);
  assert(merged.some(s => s.boundary === 24), "граница перехода в static потеряна при merge");
  console.log("12. mergeSimilarSegments — сливает похожие, сохраняет смену паттерна — OK");
}

// 13. refineCandidates: вырожденный (conf=0), низкая prominence и NMS по расстоянию.
{
  const sig = [];
  for (let t = 0; t <= 60; t++) sig.push({ t, comb: 0.2, Dm: 0, Dp: 0 });
  // пик с высокой conf (base 0.2, peak 2.2) и хорошей prominence
  for (let t = 18; t <= 26; t++) sig[t].comb = 0.2 + (t - 18) * 0.5;
  for (let t = 26; t <= 30; t++) sig[t].comb = 2.2 - (t - 26) * 0.4;
  sig[26].comb = 2.2;
  // вырожденный кандидат (conf=0) и слабый сосед на 22 (близко к пику)
  const cands = [
    { boundary: 5,  peakT: 5,  peak: 0.5, conf: 0.0,  Dm: 1, Dp: 1 },
    { boundary: 22, peakT: 22, peak: 1.0, conf: 0.8,  Dm: 1, Dp: 1 },
    { boundary: 26, peakT: 26, peak: 2.2, conf: 2.0,  Dm: 1, Dp: 1 }
  ];
  const ref = refineCandidates(cands, sig, { minProm: 0.3, minDist: 12, minConf: 0.05 });
  assert(!ref.some(c => c.boundary === 5), "вырожденный (conf=0) не отфильтрован");
  assert(!ref.some(c => c.boundary === 22), "близкий сосед (NMS) не отфильтрован");
  assert(ref.some(c => c.boundary === 26), "сильный кандидат потерян");
  assert(ref.length === 1, `ожидал 1 кандидат после refine, got ${ref.length}`);
  console.log("13. refineCandidates — вырожденные, prominence, NMS — OK");
}

console.log("\nВсе тесты signature.mjs прошли.");