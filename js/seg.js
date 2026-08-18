// seg.js — авто-сегментация эталона: seek-and-detect сбор кадров → сигнатура → кандидаты → сегменты.
// Чистый модуль без DOM: получает video-элемент и детектор (s.lmA) извне.
// Пайплайн = тот же, что в segtest (parity), функции из signature.js.
import { frameDescriptors, buildWindows, madNormalize, contextDistance,
         detectCandidatesUnion, segmentsFromCandidates } from "./signature.js";
import { ensureMeta } from "./utils.js";

export const SEG_CONF = {
  win: 5, step: 2, ctx: 5, frac: 0.7, dupSec: 3,
  combPct: [0.95, 0.7], chgPct: [0.9, 0.7]
};

// Надёжный seek: ставим и ждём 'seeked' (лимит 3 с), иначе проход мог стартовать не с той позиции.
function seekTo(video, t){
  return new Promise(res => {
    if (Math.abs(video.currentTime - t) < 0.01){ res(); return; }
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      video.removeEventListener("seeked", finish);
      video.removeEventListener("error", finish);
      res();
    };
    const timer = setTimeout(finish, 3000);
    video.addEventListener("seeked", finish, { once: true });
    video.addEventListener("error", finish, { once: true });
    video.currentTime = t;
  });
}

// segmentVideo — полный проход сегментации.
//   video  — <video> эталона (A); lm — детектор PoseLandmarker (VIDEO-режим).
//   opts   — { rateHz=5, onProg({pct,etaSec,done,total}), signal: AbortSignal }
//   → { segments, signal, cands, n, valid, duration, degraded }
export async function segmentVideo(video, lm, opts = {}){
  const { rateHz = 5, onProg, signal } = opts;
  const abort = () => { try { signal?.throwIfAborted(); } catch(e){ throw e; } };

  if (video.readyState < 1) await ensureMeta(video);
  const dur = video.duration || 0;
  try { video.muted = true; video.pause(); } catch(_){}

  const stepSec = 1 / rateHz;
  const n = dur > 0 ? Math.floor(dur / stepSec) + 1 : 0;
  const frames = [];
  let lastTs = 0;
  const t0 = performance.now();

  if (n > 0){
    await seekTo(video, 0);
    abort();
    for (let i = 0; i < n; i++){
      abort();
      const t = Math.min(i * stepSec, dur);
      await seekTo(video, t);
      abort();
      const ts = Math.max(lastTs + 1, Math.round((video.currentTime || t) * 1000));
      lastTs = ts;
      let res = null;
      try { res = lm.detectForVideo(video, ts); } catch(_){}
      const w = res?.worldLandmarks?.[0];
      frames.push({ time: t, desc: w ? frameDescriptors(w) : null });
      if (onProg && i % 10 === 0){
        const per = (performance.now() - t0) / (i + 1);
        onProg({ pct: Math.min(100, t / dur * 100), etaSec: Math.max(0, (n - i - 1) * per / 1000),
                 done: i + 1, total: n });
      }
    }
    try { video.pause(); } catch(_){}
  }

  const wins = buildWindows(frames, SEG_CONF.win, SEG_CONF.step);
  const norms = madNormalize(wins);
  const sig = wins.map(w => {
    const d = contextDistance(wins, w.tMid, norms, SEG_CONF.ctx) || {};
    const Dm = d.D_motion ?? null, Dp = d.D_pose ?? null;
    return { t: w.tMid, Dm, Dp, comb: d.combined ?? null,
             chg: Dm != null || Dp != null ? Math.max(Dm ?? 0, Dp ?? 0) : null };
  });
  const valid = frames.filter(f => f.desc).length;
  const cands = valid >= 10
    ? detectCandidatesUnion(sig, { frac: SEG_CONF.frac, dupSec: SEG_CONF.dupSec,
                                    combPct: SEG_CONF.combPct, chgPct: SEG_CONF.chgPct })
    : [];
  const degraded = n === 0 || valid < 10;
  const segments = segmentsFromCandidates(cands, dur);
  return { segments, signal: sig, cands, n: frames.length, valid, duration: dur, degraded };
}