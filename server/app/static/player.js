// Лёгкий плеер: видео + canvas-скелет поверх, читает готовый трек с сервера.
const P = { NOSE:0, LSH:1, RSH:2, LEL:3, REL:4, LWR:5, RWR:6,
            LHIP:7, RHIP:8, LKN:9, RKN:10, LAN:11, RAN:12 };

const BONES = [
  [P.LSH,P.RSH],[P.LSH,P.LHIP],[P.RSH,P.RHIP],[P.LHIP,P.RHIP],
  [P.LSH,P.LEL],[P.LEL,P.LWR],[P.RSH,P.REL],[P.REL,P.RWR],
  [P.LHIP,P.LKN],[P.LKN,P.LAN],[P.RHIP,P.RKN],[P.RKN,P.RAN],
  [P.NOSE,P.LSH],[P.NOSE,P.RSH],
];

const VIS_LO = 0.15;

export async function initPlayer({ apiBase, showSkeleton = true }) {
  const video = document.getElementById("player");
  const canvas = document.getElementById("overlay");
  const context = canvas.getContext("2d");
  const segmentBar = document.getElementById("seg-bar");
  const segmentLabel = document.getElementById("seg-label");
  const segmentCounter = document.getElementById("segment-counter");
  const description = document.getElementById("description");
  const subtitle = document.getElementById("subtitle");
  const subtitleWrap = document.getElementById("subtitle-wrap");
  const coachFeedback = document.getElementById("coach-feedback");
  const coachScores = document.getElementById("coach-scores");
  const coachComment = document.getElementById("coach-comment");
  const previousButton = document.getElementById("previous-segment");
  const nextButton = document.getElementById("next-segment");
  const segmentButtons = [...document.querySelectorAll(".segment-button")];

  const segmentResponse = await fetch(`${apiBase}/segments`);
  const segments = segmentResponse.ok ? await segmentResponse.json() : [];
  let frames = [];
  let activeIndex = -1;
  let animationFrame = null;

  if (showSkeleton) {
    fetch(`${apiBase}/track`)
      .then(response => response.ok ? response.json() : null)
      .then(track => {
        frames = track?.frames || [];
        drawCurrentFrame();
      })
      .catch(() => {
        frames = [];
      });
  }

  function resize() {
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(video.clientWidth * ratio);
    canvas.height = Math.round(video.clientHeight * ratio);
    drawCurrentFrame();
  }

  function frameAt(time) {
    if (!frames.length) return null;
    let low = 0;
    let high = frames.length - 1;
    while (low < high) {
      const middle = (low + high) >> 1;
      if (frames[middle][0] < time) low = middle + 1;
      else high = middle;
    }
    return frames[low];
  }

  function segmentIndexAt(time) {
    const index = segments.findIndex(segment => time >= segment.start && time < segment.end);
    if (index >= 0) return index;
    if (segments.length && time >= segments[segments.length - 1].end) return segments.length - 1;
    return -1;
  }

  function updateSegment(index) {
    if (index === activeIndex) return;
    activeIndex = index;
    const segment = segments[index] || null;
    segmentCounter.textContent = segment ? `Упражнение ${index + 1} из ${segments.length}` : "Выберите упражнение";
    segmentLabel.textContent = segment?.label || "";
    description.textContent = segment?.description || "";
    subtitle.textContent = segment?.subtitle || "";
    subtitleWrap.classList.toggle("hidden", !segment?.subtitle);
    const feedback = segment?.coach_feedback || null;
    const scoreLabels = [
      ["technique", "Техника"],
      ["range_of_motion", "Амплитуда"],
      ["stability", "Стабильность"],
      ["tempo", "Темп"],
      ["symmetry", "Симметрия"],
    ];
    coachScores.replaceChildren();
    if (feedback) {
      for (const [field, label] of scoreLabels) {
        if (feedback[field] == null) continue;
        const badge = document.createElement("span");
        badge.className = "rounded bg-black/20 px-2 py-1 text-[11px] text-slate-300";
        badge.textContent = `${label}: ${feedback[field]}`;
        coachScores.appendChild(badge);
      }
      coachComment.textContent = feedback.comment || "";
    } else {
      coachComment.textContent = "";
    }
    coachFeedback.classList.toggle(
      "hidden",
      !feedback || (!feedback.comment && coachScores.childElementCount === 0),
    );
    previousButton.disabled = index <= 0;
    nextButton.disabled = index < 0 || index >= segments.length - 1;

    for (const [buttonIndex, button] of segmentButtons.entries()) {
      const isActive = buttonIndex === index;
      button.setAttribute("aria-current", isActive ? "true" : "false");
      button.classList.toggle("border-violet-500/70", isActive);
      button.classList.toggle("bg-violet-500/10", isActive);
    }
  }

  function drawCurrentFrame() {
    context.clearRect(0, 0, canvas.width, canvas.height);
    const frame = frameAt(video.currentTime);
    if (frame && frame.length > 1) {
      drawSkeleton(context, canvas.width, canvas.height, frame);
    }
    updateSegment(segmentIndexAt(video.currentTime));
  }

  function animate() {
    drawCurrentFrame();
    if (!video.paused && !video.ended) {
      animationFrame = requestAnimationFrame(animate);
    }
  }

  function seekToSegment(index) {
    const segment = segments[index];
    if (!segment) return;
    video.currentTime = segment.start;
    updateSegment(index);
    video.play().catch(() => {});
  }

  for (const [index, button] of segmentButtons.entries()) {
    button.addEventListener("click", () => seekToSegment(index));
  }
  previousButton.addEventListener("click", () => seekToSegment(activeIndex - 1));
  nextButton.addEventListener("click", () => seekToSegment(activeIndex + 1));

  window.addEventListener("resize", resize);
  video.addEventListener("loadedmetadata", () => {
    resize();
    renderSegmentBar(segmentBar, segments, video.duration || segments.at(-1)?.end || 0, seekToSegment);
    updateSegment(segmentIndexAt(video.currentTime));
  });
  video.addEventListener("play", () => {
    if (animationFrame !== null) cancelAnimationFrame(animationFrame);
    animationFrame = requestAnimationFrame(animate);
  });
  for (const eventName of ["pause", "seeked", "timeupdate", "ended"]) {
    video.addEventListener(eventName, drawCurrentFrame);
  }

  resize();
  renderSegmentBar(segmentBar, segments, segments.at(-1)?.end || 0, seekToSegment);
  updateSegment(segments.length ? 0 : -1);
}

function pointAt(frame, index) {
  const offset = 1 + index * 3;
  return offset + 2 < frame.length
    ? { x: frame[offset], y: frame[offset + 1], v: frame[offset + 2] }
    : null;
}

function drawSkeleton(context, width, height, frame) {
  context.save();
  context.strokeStyle = "#a78bfa";
  context.lineWidth = Math.max(2, width / 200);
  context.lineCap = "round";
  for (const [start, end] of BONES) {
    const first = pointAt(frame, start);
    const second = pointAt(frame, end);
    if (!first || !second || first.v < VIS_LO || second.v < VIS_LO) continue;
    context.beginPath();
    context.moveTo(first.x * width, first.y * height);
    context.lineTo(second.x * width, second.y * height);
    context.stroke();
  }
  context.fillStyle = "#8b5cf6";
  for (let index = 0; index < 13; index += 1) {
    const point = pointAt(frame, index);
    if (!point || point.v < VIS_LO) continue;
    context.beginPath();
    context.arc(point.x * width, point.y * height, Math.max(2, width / 220), 0, Math.PI * 2);
    context.fill();
  }
  context.restore();
}

function renderSegmentBar(element, segments, duration, onSelect) {
  element.innerHTML = "";
  if (!duration) return;
  for (const [index, segment] of segments.entries()) {
    const marker = document.createElement("button");
    marker.type = "button";
    marker.style.left = `${segment.start / duration * 100}%`;
    marker.style.width = `${(segment.end - segment.start) / duration * 100}%`;
    marker.title = segment.label || `Упражнение ${index + 1}`;
    marker.setAttribute("aria-label", marker.title);
    marker.className = "absolute top-0 h-full bg-violet-500/60 hover:bg-violet-400 border-r border-slate-950";
    marker.addEventListener("click", () => onSelect(index));
    element.appendChild(marker);
  }
}
