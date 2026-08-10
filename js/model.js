// model.js — загрузка MediaPipe (WASM-бандл с CDN) и pose-модели.
// Модель тянется с CDN один раз и кэшируется (модуль держит буфер modelBufCache);
// локальный .task (второе поле) перекрывает CDN-модель.
import { CDN, MODEL } from "./config.js";
import { $ } from "./utils.js";

let vision = null, PoseLandmarker = null, modelBufCache = null;

// Однократно грузим vision_bundle + WASM-резолвер с CDN.
export async function ensureBundle(){
  if (PoseLandmarker) return;
  const mod = await import(`${CDN}/vision_bundle.mjs`);
  PoseLandmarker = mod.PoseLandmarker;
  vision = await mod.FilesetResolver.forVisionTasks(`${CDN}/wasm`);
}

// Читает модель: локальный файл сразу, иначе — стрим с CDN с прогрессом (кэш в RAM).
export async function fetchModelBuffer(local, onProg){
  if (local){
    const b = await local.arrayBuffer();
    if (onProg) onProg(1);
    return new Uint8Array(b);
  }
  if (modelBufCache) return modelBufCache;
  const res = await fetch(MODEL);
  if (!res.ok) throw new Error("HTTP " + res.status);
  const total = +res.headers.get("content-length") || 0;
  const reader = res.body.getReader();
  const chunks = []; let got = 0;
  for(;;){
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value); got += value.length;
    if (total && onProg) onProg(got / total);
  }
  const buf = new Uint8Array(got); let off = 0;
  for (const c of chunks){ buf.set(c, off); off += c.length; }
  modelBufCache = buf;
  if (onProg) onProg(1);
  return buf;
}

// Сброс кэша — когда выбрали новый локальный .task.
export function clearModelCache(){ modelBufCache = null; }

// Создаёт новый детектор PoseLandmarker.
//   delegate — "GPU" | "CPU", onProg — колбэк прогресса загрузки модели.
export async function makeLandmarker(delegate, onProg, numPoses = 1){
  await ensureBundle();
  const buf = await fetchModelBuffer($("mfile").files[0], onProg);
  const lm = await PoseLandmarker.createFromOptions(vision, {
    baseOptions: { modelAssetBuffer: buf, delegate },
    runningMode: "VIDEO", numPoses,
    minPoseDetectionConfidence: 0.5, minPosePresenceConfidence: 0.5, minTrackingConfidence: 0.5
  });
  lm.del = delegate;
  return lm;
}

// Безопасное закрытие детектора.
export function close(lm){ try { lm?.close(); } catch(_){} }