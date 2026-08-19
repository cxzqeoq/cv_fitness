// Лёгкий плеер: видео + canvas-скелет поверх, читает трек и сегменты с сервера.
// Не тянет MediaPipe/WASM на клиент — только рисует уже готовые landmarks.
//
// Трек хранит только точки, нужные для 2D-отрисовки (без z, без лица/пальцев) —
// компактный формат: frame = [t, x0,y0,v0, x1,y1,v1, ...], позиции ниже
// соответствуют порядку TRACK_LM на сервере (pipeline.py).
const P = { NOSE:0, LSH:1, RSH:2, LEL:3, REL:4, LWR:5, RWR:6,
            LHIP:7, RHIP:8, LKN:9, RKN:10, LAN:11, RAN:12 };

const BONES = [
  [P.LSH,P.RSH],[P.LSH,P.LHIP],[P.RSH,P.RHIP],[P.LHIP,P.RHIP],
  [P.LSH,P.LEL],[P.LEL,P.LWR],[P.RSH,P.REL],[P.REL,P.RWR],
  [P.LHIP,P.LKN],[P.LKN,P.LAN],[P.RHIP,P.RKN],[P.RKN,P.RAN],
  [P.NOSE,P.LSH],[P.NOSE,P.RSH],
];

const VIS_LO = 0.15;

export async function initPlayer(videoId) {
  const video = document.getElementById("player");
  const canvas = document.getElementById("overlay");
  const cr = canvas.getContext("2d");
  const segBar = document.getElementById("seg-bar");
  const segLabel = document.getElementById("seg-label");
  const subtitleEl = document.getElementById("subtitle");

  const [trackRes, segments] = await Promise.all([
    fetch(`/api/videos/${videoId}/track`).then(r => (r.ok ? r.json() : null)),
    fetch(`/api/videos/${videoId}/segments`).then(r => r.json()),
  ]);

  const frames = trackRes ? trackRes.frames : [];
  renderSegBar(segBar, segments, video.duration || 0);

  function resize() {
    canvas.width = video.clientWidth;
    canvas.height = video.clientHeight;
  }
  window.addEventListener("resize", resize);
  video.addEventListener("loadedmetadata", () => {
    resize();
    renderSegBar(segBar, segments, video.duration || 0);
  });

  function frameAt(t) {
    if (!frames.length) return null;
    // frames идут по возрастанию t (frame[0]) — бинарный поиск ближайшего.
    let lo = 0, hi = frames.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (frames[mid][0] < t) lo = mid + 1; else hi = mid;
    }
    return frames[lo];
  }

  function segmentAt(t) {
    return segments.find(s => t >= s.start && t < s.end) || null;
  }

  function draw() {
    const t = video.currentTime;
    cr.clearRect(0, 0, canvas.width, canvas.height);

    const f = frameAt(t);
    if (f && f.length > 1) drawSkeleton(cr, canvas.width, canvas.height, f);

    const seg = segmentAt(t);
    segLabel.textContent = seg?.label || "";
    subtitleEl.textContent = seg?.subtitle || "";

    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);
}

// f: [t, x0,y0,v0, x1,y1,v1, ...] — точка i живёт по смещению 1 + i*3.
function pointAt(f, i) {
  const o = 1 + i * 3;
  return o + 2 < f.length ? { x: f[o], y: f[o + 1], v: f[o + 2] } : null;
}

function drawSkeleton(cr, w, h, f) {
  cr.save();
  cr.strokeStyle = "#34d399";
  cr.lineWidth = Math.max(2, w / 200);
  cr.lineCap = "round";
  for (const [a, b] of BONES) {
    const pa = pointAt(f, a), pb = pointAt(f, b);
    if (!pa || !pb || pa.v < VIS_LO || pb.v < VIS_LO) continue;
    cr.beginPath();
    cr.moveTo(pa.x * w, pa.y * h);
    cr.lineTo(pb.x * w, pb.y * h);
    cr.stroke();
  }
  cr.fillStyle = "#10b981";
  for (let i = 0; i < 13; i++) {
    const p = pointAt(f, i);
    if (!p || p.v < VIS_LO) continue;
    cr.beginPath();
    cr.arc(p.x * w, p.y * h, Math.max(2, w / 220), 0, Math.PI * 2);
    cr.fill();
  }
  cr.restore();
}

function renderSegBar(el, segments, duration) {
  el.innerHTML = "";
  if (!duration) return;
  for (const s of segments) {
    const chip = document.createElement("div");
    const left = (s.start / duration) * 100;
    const width = ((s.end - s.start) / duration) * 100;
    chip.style.left = `${left}%`;
    chip.style.width = `${width}%`;
    chip.title = s.label || "";
    chip.className = "absolute h-full bg-emerald-600/60 border-r border-slate-950";
    el.appendChild(chip);
  }
}
