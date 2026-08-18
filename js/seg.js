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
  let lastTs = (lm._lastTs ?? 0);
  const t0 = performance.now();

  if (n > 0){
    await seekTo(video, 0);
    abort();
    let playing = true;
    try {
      video.playbackRate = 2;
      await video.play();
    } catch(_){ playing = false; }
    if (playing){
      // Сбор кадров воспроизведением: один проход без перемоток (на телефоне каждая
      // перемотка — декод с keyframe, до 3 с; здесь кадры берутся по ходу проигрывания).
      // playbackRate адаптивен: если детект медленный — видео идёт медленнее, кадров меньше.
      let i = 0, lastDetMs = null;
      let stallT = performance.now(), stallCt = video.currentTime;
      while (i < n && video.readyState >= 2 && video.currentTime < dur + 0.05){
        abort();
        if (video.currentTime !== stallCt){
          stallCt = video.currentTime; stallT = performance.now();
        } else if (performance.now() - stallT > 1500){
          break; // воспроизведение не сдвинулось — не виснем
        }
        const t = i * stepSec;
        if (video.currentTime >= t - 0.01){
          const ts = Math.max(lastTs + 1, Math.round((video.currentTime || t) * 1000));
          lastTs = ts; lm._lastTs = ts;
          const st = performance.now();
          let res = null;
          try { res = lm.detectForVideo(video, ts); } catch(_){}
          lastDetMs = performance.now() - st;
          const w = res?.worldLandmarks?.[0];
          frames.push({ time: video.currentTime, desc: w ? frameDescriptors(w) : null });
          i++;
          if (onProg && i % 10 === 0){
            const per = (performance.now() - t0) / i;
            const detSec = (n - i) * per / 1000;
            const playSec = (dur - video.currentTime) / Math.max(0.1, video.playbackRate || 1);
            onProg({ pct: Math.min(100, video.currentTime / dur * 100),
                     etaSec: Math.max(0, Math.max(detSec, playSec)), done: i, total: n });
          }
          if (lastDetMs){
            const want = 0.9 * (stepSec * 1000) / Math.max(1, lastDetMs);
            try { video.playbackRate = Math.min(2, Math.max(1, want)); } catch(_){}
          }
        } else {
          await new Promise(res => setTimeout(res, 16));
        }
      }
    } else {
      // фолбэк: seek-and-detect, если автоплей заблокирован
      for (let i = 0; i < n; i++){
        abort();
        const t = Math.min(i * stepSec, dur);
        await seekTo(video, t);
        abort();
        const ts = Math.max(lastTs + 1, Math.round((video.currentTime || t) * 1000));
        lastTs = ts; lm._lastTs = ts;
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