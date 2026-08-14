// singles.js — режим «Один»: скелет поверх одного видео/камеры ноутбука,
// стили, фон, сглаживание, запись результата в файл.
// Состояние — внутри модуля; наружу отдаём start/stop/loadFile через init().
import { I, GROUPS } from "./config.js";
import { $, say, setStat, fadeA, mid, pair, ensureMeta, mediaErrText, playVideo } from "./utils.js";
import { s } from "./state.js";
import { makeLandmarker, close, clearModelCache } from "./model.js";

const v = $("v"), cv = $("cv"), ctx = cv.getContext("2d", { alpha:true });

let landmarker = null, running = false, lastTs = -1, lastTime = -1, lastRes = null;
let recorder = null, chunks = [], frames = 0, t0 = 0;
let smoothPoses = [];

const pc = { w:1, col:"#c6ff2e", style:"stick", bg:"video",
             parts:{ head:true, torso:true, arms:true, legs:true } };

const px = p => [p.x * cv.width, p.y * cv.height];
function baseW(){ return pc.w * Math.max(1.5, cv.width / 480); }

// Толстая линия с прозрачностью по видимости (неон — двойным проходом).
function strokePath(pts, mult, glow){
  if (pts.some(p => fadeA(p.v ?? 1) === 0)) return;
  const alpha = Math.min(...pts.map(p => fadeA(p.v ?? 1)));
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = pc.col;
  ctx.lineWidth = baseW() * mult;
  ctx.lineCap = "round"; ctx.lineJoin = "round";
  if (glow){ ctx.shadowColor = pc.col; ctx.shadowBlur = baseW() * 5; }
  ctx.beginPath();
  pts.forEach((p,i) => { const [x,y] = px(p); i ? ctx.lineTo(x,y) : ctx.moveTo(x,y); });
  ctx.stroke();
  if (glow){
    ctx.shadowBlur = 0;
    ctx.lineWidth = baseW() * mult * 0.55;
    ctx.stroke();
  }
  ctx.restore();
}

// Сустав: тёмная заливка + обводка.
function joint(p, r){
  const a = fadeA(p.v ?? 1);
  if (!a) return;
  const [x,y] = px(p);
  ctx.save();
  ctx.globalAlpha = Math.max(a, 0.4);
  ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI*2);
  ctx.fillStyle = "#0e1113"; ctx.fill();
  ctx.lineWidth = baseW() * 0.5; ctx.strokeStyle = pc.col; ctx.stroke();
  ctx.restore();
}

// Стиль «палочки»: прямые связки + голова-круг.
function drawStick(g){
  const neck = mid(pair(g,I.LSH), pair(g,I.RSH));
  const pelvis = mid(pair(g,I.LHIP), pair(g,I.RHIP));
  const P = pc.parts;

  if (P.torso){
    strokePath([neck, pelvis], 1.1, 0);
    strokePath([pair(g,I.LSH), pair(g,I.RSH)], 1.1, 0);
  }
  if (P.arms){
    strokePath([pair(g,I.LSH), pair(g,I.LEL), pair(g,I.LWR)], 1, 0);
    strokePath([pair(g,I.RSH), pair(g,I.REL), pair(g,I.RWR)], 1, 0);
  }
  if (P.legs){
    strokePath([pelvis, pair(g,I.LKN), pair(g,I.LAN)], 1, 0);
    strokePath([pelvis, pair(g,I.RKN), pair(g,I.RAN)], 1, 0);
  }
  if (P.head){
    const le = pair(g,I.LEA), re = pair(g,I.REA);
    const ears = fadeA(le.v ?? 1) > 0 && fadeA(re.v ?? 1) > 0;
    const head = ears ? mid(le, re) : pair(g,I.NOSE);
    const hA = fadeA(head.v ?? 1), nA = fadeA(neck.v ?? 1);
    if (hA && nA){
      const [hx,hy] = px(head), [nx,ny] = px(neck);
      let r;
      if (ears){
        const [lx,ly] = px(le), [rx,ry] = px(re);
        r = Math.hypot(lx-rx, ly-ry) * 0.85;
      } else {
        r = Math.hypot(hx-nx, hy-ny) * 0.5;
      }
      r = Math.max(r, baseW() * 2.2);
      const d = Math.hypot(hx-nx, hy-ny) || 1;
      const tx = nx + (hx-nx) * (1 - r/d), ty = ny + (hy-ny) * (1 - r/d);
      ctx.save();
      ctx.globalAlpha = Math.min(hA, nA);
      ctx.strokeStyle = pc.col; ctx.lineWidth = baseW(); ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(nx,ny); ctx.lineTo(tx,ty); ctx.stroke();
      ctx.beginPath(); ctx.arc(hx, hy, r, 0, Math.PI*2); ctx.stroke();
      ctx.restore();
    }
  }
}

// Стиль «полный/неон/прозрачный»: все связи по GROUPS + суставы.
function drawFull(g){
  const P = pc.parts, glow = pc.style === "neon";
  for (const part of ["head","torso","arms","legs"]){
    if (!P[part]) continue;
    for (const [a,b] of GROUPS[part])
      strokePath([pair(g,a), pair(g,b)], 1, glow);
  }
  if (pc.style !== "stick"){
    const nodes = new Set();
    for (const part of ["head","torso","arms","legs"]){
      if (!P[part]) continue;
      for (const [a,b] of GROUPS[part]){ nodes.add(a); nodes.add(b); }
    }
    for (const n of nodes) joint(pair(g,n), baseW() * 1.7);
  }
}

// Сглаживание точек во времени (убирает дрожь): при резком скачке (>0.22) — не доверяем.
function smoothUpdate(idx, lm){
  const a = Number($("sm").value) / 100;
  let arr = smoothPoses[idx];
  if (!arr){
    arr = lm.map(p => ({ x:p.x, y:p.y, v:p.visibility ?? 1 }));
    smoothPoses[idx] = arr;
    return arr;
  }
  const out = lm.map((p,j) => {
    const vn = p.visibility ?? 1;
    const o = arr[j];
    if (vn < VIS_LO) return o;
    if (o.v < VIS_LO) return { x:p.x, y:p.y, v: vn };
    if (Math.hypot(p.x - o.x, p.y - o.y) > 0.22) return { x:p.x, y:p.y, v: vn };
    return { x: a*o.x + (1-a)*p.x, y: a*o.y + (1-a)*p.y, v: Math.max(o.v, vn) };
  });
  smoothPoses[idx] = out;
  return out;
}
import { VIS_LO } from "./config.js";

// Отрисовка текущего кадра видео + скелет.
function render(){
  const style = $("style").value;
  const bgSel = $("bg").value;
  const bg = style === "ghost" ? "ghost" : bgSel;
  pc.style = style;
  pc.w = Number($("w").value);
  pc.col = $("col").value;
  pc.parts = { head:$("pHead").checked, torso:$("pTorso").checked,
               arms:$("pArms").checked, legs:$("pLegs").checked };

  if (bg === "ghost"){ }
  else if (bg === "black"){ ctx.fillStyle = "#000"; ctx.fillRect(0,0,cv.width,cv.height); }
  else {
    ctx.drawImage(v, 0, 0, cv.width, cv.height);
    if (bg === "dim"){ ctx.fillStyle = "rgba(0,0,0,.55)"; ctx.fillRect(0,0,cv.width,cv.height); }
  }

  if (v.currentTime !== lastTime && v.readyState >= 2){
    lastTime = v.currentTime;
    const ts = Math.max(lastTs + 1, Math.round(v.currentTime * 1000));
    if (lastTs !== -1 && ts - lastTs > 200) smoothPoses = [];
    lastTs = ts;
    try { lastRes = landmarker.detectForVideo(v, ts); } catch(e){}
    frames++;
  }

  if (lastRes?.landmarks?.length){
    for (let i = 0; i < lastRes.landmarks.length; i++)
      pc.style === "stick" ? drawStick(smoothUpdate(i, lastRes.landmarks[i]))
                           : drawFull(smoothUpdate(i, lastRes.landmarks[i]));
  }

  if (frames % 10 === 0 && frames){
    const now = performance.now();
    const fps = (frames / ((now - t0)/1000)).toFixed(1);
    const dur = v.duration || 0;
    const pct = dur ? (v.currentTime / dur * 100).toFixed(0) : 0;
    const left = dur - v.currentTime;
    setStat(`кадр <b>${v.videoWidth}×${v.videoHeight}</b>`, `длит. <b>${dur.toFixed(1)} с</b>`,
            `обработка <b>${fps}</b> кадр/с`, `прогресс <b>${pct}%</b>`,
            left > 0 ? `осталось <b>${left.toFixed(0)} с</b>` : '');
    $("progFill").style.width = pct + "%";
    say(`обработка — <b>${pct}%</b>, <b>${fps}</b> кадр/с`);
  }
}

function loop(){
  if (!running) return;
  render();
  requestAnimationFrame(loop);
}

export function isRunning(){ return running; }

// Выбор видеофайла: подставляем blob-URL, активируем «Запустить».
export function loadFile(f){
  if (!f) return;
  lastRes = null; lastTime = -1; smoothPoses = [];
  v.src = URL.createObjectURL(f);
  $("go").disabled = false;
  $("vinfo").textContent = `${f.name} (${(f.size/1048576).toFixed(1)} МБ)`;
  say(`${f.name} — читаю…`);
}

// Запуск: ждём метаданные, грузим/перзагружаем модель, при желании — запись, затем loop().
async function run(){
  $("go").disabled = true;
  try {
    if (v.readyState < 1){
      say("жду метаданные видео…");
      await ensureMeta(v);
      cv.width = v.videoWidth; cv.height = v.videoHeight;
      cv.hidden = false; $("hint").style.display = "none";
    }
    if (!cv.width) throw new Error("нулевой размер кадра");

    const del = $("delegate").value;
    say(`загрузка модели (${del})…`);
    const prog = p => say(`загрузка модели (${del})… ${Math.round(p * 100)}%`);
    try { await loadModelV2(+$("poses").value, del, prog); }
    catch(err){
      if (del === "GPU"){ say("GPU не поднялся, пробую CPU…"); await loadModelV2(+$("poses").value, "CPU", prog); }
      else throw err;
    }
  } catch(err){
    say(`Не стартовало: ${err.message}. Если это про модель — нужна сеть или локальный .task во втором поле.`, true);
    $("go").disabled = false; return;
  }

  if ($("rec").checked){
    const mime = ["video/mp4;codecs=avc1","video/webm;codecs=vp9","video/webm"]
      .find(t => window.MediaRecorder && MediaRecorder.isTypeSupported(t));
    if (!mime) say("Запись не поддерживается этим браузером, показываю без сохранения.");
    else {
      chunks = [];
      recorder = new MediaRecorder(cv.captureStream(30), { mimeType: mime, videoBitsPerSecond: 8e6 });
      recorder.ondataavailable = e => e.data.size && chunks.push(e.data);
      recorder.onstop = () => {
        const blob = new Blob(chunks, { type: mime });
        const a = $("dl") || document.createElement("a");
        a.id = "dl";
        a.href = URL.createObjectURL(blob);
        a.download = "record_pose." + (mime.startsWith("video/mp4") ? "mp4" : "webm");
        a.textContent = "скачать " + a.download;
        $("status").after(a);
        a.click();
      };
      recorder.start();
      $("recOn").classList.add("on");
    }
  }

  frames = 0; t0 = performance.now(); lastTs = -1; lastTime = -1;
  smoothPoses = []; running = true;
  $("stop").disabled = false;
  if (v.currentTime <= 0 || v.currentTime >= (v.duration || Infinity) - 0.05){
    v.currentTime = 0;
  }
  v.volume = s.sound.vol;
  try { await playVideo(v, !s.sound.muted); } catch(err){ say(`Видео не запустилось: ${err.message}`, true); }
  loop();
}

async function loadModelV2(numPoses, del, prog){
  close(landmarker); landmarker = null;
  landmarker = await makeLandmarker(del, prog, numPoses);
}

export function stop(){
  if (!running) return;
  running = false;
  $("go").disabled = false; $("stop").disabled = true;
  v.pause();
  if (recorder && recorder.state !== "inactive"){
    recorder.stop();
    $("recOn").classList.remove("on");
  }
  const fps = (frames / ((performance.now() - t0)/1000)).toFixed(1);
  say(`Готово. Кадров: <b>${frames}</b>, средняя скорость <b>${fps}</b> кадр/с.`);
}

// Привязка событий режима (вызывается из main.js после готовности DOM).
export function init(){
  $("vfile").onchange = e => loadFile(e.target.files[0]);
  $("mfile").onchange = () => { clearModelCache(); };
  v.onloadedmetadata = () => {
    cv.width = v.videoWidth; cv.height = v.videoHeight;
    cv.hidden = false; $("hint").style.display = "none";
    say(`${v.videoWidth}×${v.videoHeight}, ${v.duration.toFixed(1)} с. Готово к запуску.`);
  };
  v.onloadeddata = () => { try { ctx.drawImage(v, 0, 0, cv.width, cv.height); } catch(e){} };
  v.onerror = () => say(`Видео не открылось. ${mediaErrText(v.error)}`, true);
  $("go").onclick = run;
  $("stop").onclick = stop;
  v.onended = stop;
  $("sm").oninput = e => $("smv").textContent = (e.target.value/100).toFixed(2);
  $("smv").textContent = (55/100).toFixed(2);
}