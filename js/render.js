// render.js — отрисовка скелета и канвасов режима «Сравнение».
// Функции параметризованы (ctx, размер, поза) и не зависят от состояния сессии.
import { FEATURES, GROUPS, I, VIS_LO } from "./config.js";
import { $, fadeA, mid, pair } from "./utils.js";

// Линия через несколько точек с мягкой прозрачностью по видимости.
export function cPath(cr, cw, ch, col, w, glow, pts){
  if (pts.some(p => (p.v ?? 1) < VIS_LO)) return;
  const alpha = Math.min(...pts.map(p => Math.max(fadeA(p.v ?? 1), 0.12)));
  cr.save(); cr.globalAlpha = alpha;
  cr.strokeStyle = col; cr.lineWidth = Math.max(1, w); cr.lineCap = "round"; cr.lineJoin = "round";
  if (glow){ cr.shadowColor = col; cr.shadowBlur = w * 4; }
  cr.beginPath();
  pts.forEach((p,i) => { const x = p.x*cw, y = p.y*ch; i ? cr.lineTo(x,y) : cr.moveTo(x,y); });
  cr.stroke();
  if (glow){ cr.shadowBlur = 0; cr.lineWidth = Math.max(1, w*0.55); cr.stroke(); }
  cr.restore();
}

// Скелет позы на канвасе сравнения (стиль/толщина/части читаются из DOM-селекторов),
// при showDeg && vals — подписи углов рядом с суставами.
export function drawSkelC(cr, cw, ch, col, g, showDeg, vals){
  const style = $("styleC").value;
  const P = { head:$("cHead").checked, torso:$("cTorso").checked, arms:$("cArms").checked, legs:$("cLegs").checked };
  const base = Number($("wC").value) * Math.max(1.5, cw/480);
  const glow = style === "neon";
  const neck = mid(pair(g,I.LSH), pair(g,I.RSH));
  const pelvis = mid(pair(g,I.LHIP), pair(g,I.RHIP));
  const link = (pts, m) => cPath(cr, cw, ch, col, base*m, glow, pts);
  if (style === "stick"){
    if (P.torso){
      link([neck, pelvis], 1.1);
      link([pair(g,I.LSH), pair(g,I.RSH)], 1.1);
    }
    if (P.arms){
      link([pair(g,I.LSH), pair(g,I.LEL), pair(g,I.LWR)], 1);
      link([pair(g,I.RSH), pair(g,I.REL), pair(g,I.RWR)], 1);
    }
    if (P.legs){
      link([pelvis, pair(g,I.LKN), pair(g,I.LAN)], 1);
      link([pelvis, pair(g,I.RKN), pair(g,I.RAN)], 1);
    }
    if (P.head){
      const le = pair(g,I.LEA), re = pair(g,I.REA);
      const ears = fadeA(le.v ?? 1) > 0 && fadeA(re.v ?? 1) > 0;
      const head = ears ? mid(le, re) : pair(g,I.NOSE);
      const hA = fadeA(head.v ?? 1), nA = fadeA(neck.v ?? 1);
      if (hA && nA){
        const hx = head.x*cw, hy = head.y*ch, nx = neck.x*cw, ny = neck.y*ch;
        let r = ears ? Math.hypot(le.x*cw - re.x*cw, le.y*ch - re.y*ch)*0.85
                     : Math.hypot(hx-nx, hy-ny)*0.5;
        r = Math.max(r, base*2.2);
        const d = Math.hypot(hx-nx, hy-ny) || 1;
        cr.save(); cr.globalAlpha = Math.max(Math.min(hA,nA), 0.12);
        cr.strokeStyle = col; cr.lineWidth = base; cr.lineCap = "round";
        cr.beginPath(); cr.moveTo(nx, ny);
        cr.lineTo(nx+(hx-nx)*(1-r/d), ny+(hy-ny)*(1-r/d)); cr.stroke();
        cr.beginPath(); cr.arc(hx, hy, r, 0, Math.PI*2); cr.stroke();
        cr.restore();
      }
    }
  } else {
    for (const part of ["head","torso","arms","legs"]){
      if (!P[part]) continue;
      for (const [a,b] of GROUPS[part])
        cPath(cr, cw, ch, col, base, glow, [pair(g,a), pair(g,b)]);
    }
    if (style !== "ghost"){
      const nodes = new Set();
      for (const part of ["head","torso","arms","legs"]){
        if (!P[part]) continue;
        for (const [a,b] of GROUPS[part]){ nodes.add(a); nodes.add(b); }
      }
      for (const n of nodes){
        const p = pair(g,n), a = fadeA(p.v ?? 1);
        if (!a) continue;
        const r = base*1.7;
        cr.save(); cr.globalAlpha = Math.max(a, 0.4);
        cr.beginPath(); cr.arc(p.x*cw, p.y*ch, r, 0, Math.PI*2);
        cr.fillStyle = "#0e1113"; cr.fill();
        cr.lineWidth = base*0.45; cr.strokeStyle = col; cr.stroke();
        cr.restore();
      }
    }
  }
  if (showDeg && vals){
    cr.save();
    const font = getComputedStyle(document.body).fontFamily;
    cr.font = `bold ${Math.max(10, base*1.4)}px ${font}`;
    for (const f of FEATURES){
      const val = vals[f.key]; if (val == null) continue;
      const p = (f.spread || f.tilt || f.twist) ? mid(pair(g,I.LSH), pair(g,I.RSH)) : pair(g, f.b);
      if (!p || fadeA(p.v ?? 1) <= 0) continue;
      const x = p.x*cw, y = p.y*ch, t = val.toFixed(0)+"°";
      cr.strokeStyle = "#000"; cr.lineWidth = 3; cr.strokeText(t, x+6, y+6);
      cr.fillStyle = col; cr.fillText(t, x+6, y+6);
    }
    cr.restore();
  }
}

// Фон канваса: видео-кадр, приглушённый или чёрный/прозрачный.
export function drawCmpBg(cr, cw, ch, videoEl, bg){
  if (bg === "ghost") return;
  if (bg === "black"){ cr.fillStyle = "#000"; cr.fillRect(0,0,cw,ch); return; }
  try {
    cr.drawImage(videoEl, 0, 0, cw, ch);
    if (bg === "dim"){ cr.fillStyle = "rgba(0,0,0,.55)"; cr.fillRect(0,0,cw,ch); }
  } catch(e){}
}