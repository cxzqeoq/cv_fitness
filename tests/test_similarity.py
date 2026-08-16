# E2E-регресс сходства (Playwright, headless-Chromium).
#
# Сценарии (файл-файл, CPU, сглаживание по умолчанию):
#   identical — 0808.mp4 в A и B          ожидается >=85% (предел шума lite-модели)
#   delay1    — 0808.mp4, B смещён на +1с ожидается >=75% (DTW прощает задержку)
#   foreign   — A=0808.mp4, B=clip1.mp4   ожидается <=55% (чужое движение честно низко;
#               гейт наклона шумит в headless, реальный разброс 44–53)
#   yoga      — clip1.mp4 в A и B         ожидается >=80%
#   profile   — анализ эталона 0808: карточка строится, маска снимает неактивные фичи
#   cam-*     — headless-камера (canvas.captureStream): путь getUserMedia→rVFC→детект.
#               cam-identical: A=0808, камера(B)=0808 → >=70% и лаг статус ≠ 0 (компенсация liveMatch)
#               cam-foreign:   A=0808, камера(B)=clip1 → <=50%
#
# Считается честный ИТОГ = cmp.dtw.overall (DTW), иначе session.
# В сравнении не должен проскочить NaN (фикс «0% вместо NaN%»).
#
# Пороги можно перебить:  python tests/test_similarity.py identical>80 yoga<99
# Ключи:
#   --reps=N      число прогонов (по умолчанию 1 — быстро; полный регресс: 3-5)
#   --skip-camera  не гонять камерные сценарии (напр. если rVFC не работает в headless)
#   --nofull       пропустить камеру и детальную диагностику identical
# Выход: exit code 0 — все прошли, 1 — кто-то не прошёл.
#
# Страница открывается ОДИН раз и переиспользуется между сценариями:
# смена файлов через set_input_files (onchange → loadA/loadB), а модель
# держится в modelBufCache модуля — не качается с CDN на каждый сценарий.
import subprocess
import sys
import time
import os
import json
import re
from pathlib import Path
import urllib.request

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Нет playwright — установите: pip install -r requirements.txt && playwright install chromium")
    sys.exit(2)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
V0808 = ROOT / "some" / "test-video" / "0808.mp4"
VYOG = ROOT / "some" / "test-video" / "clip1.mp4"

SCENARIOS = [
    {"name": "identical", "a": V0808, "b": V0808, "shift": 0.0, "min": 85, "max": 101},
    {"name": "delay1",    "a": V0808, "b": V0808, "shift": 1.0, "min": 75, "max": 101},
    {"name": "foreign",   "a": V0808, "b": VYOG,  "shift": 0.0, "min": 0,  "max": 55},
    {"name": "yoga",      "a": VYOG,  "b": VYOG,  "shift": 0.0, "min": 80, "max": 101},
]
# Камерные сценарии: «камера» = тот же файл, но через getUserMedia→canvas.captureStream.
# cam — имя файла в some/test-video/, который играет фейковая камера.
CAM_SCENARIOS = [
    {"name": "cam-identical", "a": V0808, "cam": "0808.mp4", "min": 70, "max": 101},
    {"name": "cam-foreign",   "a": V0808, "cam": "clip1.mp4", "min": 0,  "max": 50},
]
SM_C = 55.0
TIMEOUT = 300

# Headless-камера: переопределяем getUserMedia ещё ДО загрузки страницы.
# Возвращает canvas.captureStream, который рисует кадры видео-файла (эмуляция
# камеры). Источник задаётся тестом: window.__fakeCamSrc = URL в some/test-video/.
# Лаг: видео камеры стартует через __fakeCamLagMs мс после старта эталона A
# (детектируем vA.currentTime > 0.05) — так камера честно «отстаёт», как в реальности.
FAKE_CAM_INIT = r"""
() => {
  if (window.__fakeCamInstalled) return;
  window.__fakeCamInstalled = true;
  try {
    Object.defineProperty(navigator, 'mediaDevices', {
      value: navigator.mediaDevices || {},
      configurable: true, writable: true,
    });
  } catch(e){}
  navigator.mediaDevices.getUserMedia = (constraints) => new Promise((resolve, reject) => {
    const src = window.__fakeCamSrc;
    if (!src){ reject(new Error('нет __fakeCamSrc')); return; }
    const v = document.createElement('video');
    v.muted = true; v.loop = true; v.playsInline = true; v.preload = 'auto';
    v.src = src;
    const canvas = document.createElement('canvas');
    canvas.width = 960; canvas.height = 540;
    const ctx = canvas.getContext('2d');
    const draw = () => {
      if (v.videoWidth) ctx.drawImage(v, 0, 0, 960, 540);
      requestAnimationFrame(draw);
    };
    const lagMs = (typeof window.__fakeCamLagMs === 'number') ? window.__fakeCamLagMs : 400;
    let playing = false, played = false;
    const vA = document.getElementById('vA');
    const tick = () => {
      if (!playing && vA && vA.currentTime > 0.05){ playing = true; window.__fakeCamStartedAt = performance.now(); }
      if (playing && !played && performance.now() - window.__fakeCamStartedAt >= lagMs){
        played = true;
        v.play().then(() => {}, () => {});
      }
      requestAnimationFrame(tick);
    };
    v.onloadeddata = () => {
      draw();
      requestAnimationFrame(tick);
      resolve(canvas.captureStream(15));
    };
    v.onerror = () => reject(new Error('fake cam: не загрузился ' + src));
  });
}
"""


def start_server():
    p = subprocess.Popen(
        [sys.executable, str(ROOT / "pose_serve.py")],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        try:
            urllib.request.urlopen("http://localhost:8000/index.html", timeout=1)
            return p
        except Exception:
            time.sleep(0.2)
    p.kill()
    raise RuntimeError("сервер не поднялся")


def wait_finish(pg):
    deadline = time.time() + TIMEOUT
    saw_run = False
    while time.time() < deadline:
        try:
            st = pg.evaluate("() => window.__cmp ? window.__cmp.running : null")
        except Exception:
            st = None
        if st is True:
            saw_run = True
        elif st is False and saw_run:
            return True
        time.sleep(0.5)
    return False


def set_input_forced(pg, selector, path):
    """Принудительная установка файла: сброс через [] гарантирует срабатывание
    change-события, даже когда файл тот же (иначе loadA/loadB не вызываются
    и между сценариями остаётся грязное состояние видео/модели)."""
    pg.set_input_files(selector, [])
    pg.set_input_files(selector, str(path))


def load_a(pg, path):
    """Загрузить эталон A и дождаться его анализа (aProf построен, модели готовы)."""
    set_input_forced(pg, "#cmpAFile", path)
    pg.wait_for_function("() => (window.__cmp && window.__cmp.aProf && window.__cmp.aProf.det > 0)", timeout=120000)


def collect_result(pg, extra_keys=()):
    """Общая выгрузка результатов прогона (используется файл-файл и камерой)."""
    _dbg = pg.evaluate("""(thr) => {
        const c = window.__cmp;
        const cap = thr * 2.2;
        const keys = ['lElbow','rElbow','lKnee','rKnee','lHip','rHip','tilt','spread','twist'];
        const out = {};
        const N = c.samples.length;
        for (const k of keys){
            let n=0, s=0, w=0, spikes=0, aMiss=0, bMiss=0, both=0;
            let mnA=1e9, mxA=-1e9, mnB=1e9, mxB=-1e9;
            for (const sm of c.samples){
                const a = sm.a[k], b = sm.b[k];
                if (a == null) aMiss++; else { if (a<mnA) mnA=a; if (a>mxA) mxA=a; }
                if (b == null) bMiss++; else { if (b<mnB) mnB=b; if (b>mxB) mxB=b; }
                const v = sm.s[k];
                if (v == null) continue;
                n++; s += v * (sm.w[k]||1); w += (sm.w[k]||1);
                if (a != null && b != null){ both++; if (Math.abs(a-b) > cap) spikes++; }
            }
            out[k] = {
                meanSim: w ? +(s/w*100).toFixed(1) : null,
                cov: N ? +(w/N*100).toFixed(1) : 0,
                paired: N ? +(both/N*100).toFixed(1) : 0,
                gate: (c.gate[k] != null) ? +c.gate[k].toFixed(3) : null,
                spikesPct: both ? +(spikes/both*100).toFixed(1) : 0,
                aMissPct: N ? +(aMiss/N*100).toFixed(1) : 0,
                bMissPct: N ? +(bMiss/N*100).toFixed(1) : 0,
                rangeA: mxA > mnA ? +(mxA-mnA).toFixed(1) : 0,
                rangeB: mxB > mnB ? +(mxB-mnB).toFixed(1) : 0,
            };
        }
        return out;
    }""", float(pg.evaluate("() => document.querySelector('#thr').value")))
    res = pg.evaluate("""() => {
        const c = window.__cmp;
        let sess = null, sn = 0;
        if (c.framesTotal){
            for (const k in c.featSum){
                if (c.featSum[k] == null) continue;
                sess = (sess||0) + c.featSum[k]/c.framesTotal*100; sn++;
            }
            if (sn) sess = sess/sn;
        }
        const keys = Object.keys(c.featSum);
        const feat = {};
        for (const k of keys){
            let s=0, w=0;
            for (const sm of c.samples){
                const v = sm.s[k];
                if (v == null) continue;
                s += v * (sm.w[k]||1); w += (sm.w[k]||1);
            }
            feat[k] = { meanSim: w ? s/w*100 : null, n: w ? Object.values(c.samples).filter(x=>x.s[k]!=null).length : 0 };
        }
        let lastSimWin = null;
        const win = c.samples.slice(-120);
        if (win.length){ let s=0,w=0; for (const sm of win){ if (sm.sim!=null){ s+=sm.sim*(sm.wsum||1); w+=(sm.wsum||1);} } if (w) lastSimWin = s/w*100; }
        const out = {
            samples: c.samples.length,
            session: sess,
            dtw: c.dtw ? c.dtw.overall : null,
            exType: c.exType,
            score: c.score,
            maxCombo: c.maxCombo,
            liveWin: lastSimWin,
            scoreSub: (document.querySelector('#scoreSub')||{}).textContent || "",
            scoreBig: (document.querySelector('#scoreBig')||{}).textContent || "",
            curLagA: c.curLagA,
            lagAcq: c.lagAcq,
            camOn: (typeof window.__camOn === 'function') ? window.__camOn() : false,
            failsB: c.failsB,
            smoothB: c.smoothB.length,
        };
        for (const k of %s){ if (out[k] === undefined) out[k] = null; }
        return out;
    }""" % json.dumps(list(extra_keys)))
    res["dbg"] = _dbg
    diag = pg.evaluate("() => document.querySelector('#diag').textContent")
    res["diag"] = diag
    return res


def run_scenario(pg, sc):
    if not sc["a"].exists() or not sc["b"].exists():
        raise RuntimeError(f"нет видео {sc['a']} / {sc['b']}")
    load_a(pg, sc["a"])
    set_input_forced(pg, "#cmpBFile", sc["b"])
    pg.wait_for_function("!document.querySelector('#cmpGo').disabled", timeout=60000)
    pg.evaluate("sh => { window.__cmp.markB = sh; }", sc["shift"])
    pg.click("#cmpGo")
    if not wait_finish(pg):
        return {"error": "timeout: сравнение не завершилось за " + str(TIMEOUT) + "с"}
    return collect_result(pg)


def run_profile(pg):
    """Фоновый анализ эталона: строится профиль, активные фичи 0808 включены маской."""
    load_a(pg, V0808)
    d = pg.evaluate("""() => {
        const c = window.__cmp, p = c.aProf;
        const on = [];
        for (const k of ['lElbow','rElbow','lKnee','rKnee','lHip','rHip','tilt','spread','twist'])
            if (document.querySelector('#chk_' + k).checked) on.push(k);
        return {
            N: p.N, det: p.det, holdish: p.holdish, maskApplied: c.maskApplied,
            panelHidden: document.querySelector('#aProfPanel').hidden,
            accent: document.querySelector('#aProfAccent').textContent || '',
            on: on,
            detN: p.det / Math.max(1, p.N),
        };
    }""")
    return d


def run_dtwmap(pg):
    """Живое совпадение (liveMatch): задержка не должна ронять сходство.
    fileShift — файл со сдвигом 1.6с: захват лага (acq=true) ищет по всему окну.
    camSteady — камера: лаг 0.4с в полосе (acq=false) — сходство высокое.
    camJam — камера: лаг 0.4с + джиттер 4° при захвате — окно вытаскивает."""
    d = pg.evaluate("""() => {
        const lm = window.__liveMatch;
        if (typeof lm !== 'function') return { fail: 'liveMatch не доступен' };
        const ang = t => 120 + 28 * Math.cos(2 * Math.PI * t / 5);
        let seed = 42;
        const rnd = () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
        const gauss = () => (rnd() + rnd() + rnd() + rnd() - 2) * 2;
        const tAnow = 18.0, win = 2.0, tol = 20;
        const a = [];
        for (let t = tAnow - win; t <= tAnow; t += 0.1) a.push([+t.toFixed(2), +ang(t).toFixed(1)]);
        const r = (bVal, lag, acq) => { const o = lm(a, bVal, tAnow, lag, acq, win, tol); return o ? +o.sim.toFixed(3) : 0; };
        return {
            fileShift: r(ang(tAnow - 1.6), null, true),
            camSteady: r(ang(tAnow - 0.4), 0.4, false),
            camJam: r(ang(tAnow - 0.4) + gauss(), null, true),
        };
    }""")
    return d


def run_camera(pg, sc):
    """Камерный сценарий: источник B — headless-камера (canvas.captureStream)."""
    if not sc["a"].exists():
        raise RuntimeError(f"нет видео {sc['a']}")
    load_a(pg, sc["a"])
    pg.evaluate("""(cfg) => { window.__fakeCamSrc = cfg.url; window.__fakeCamLagMs = cfg.lag; }""",
                {"url": f"http://localhost:8000/some/test-video/{sc['cam']}", "lag": 400})
    pg.click("#srcBCam")
    pg.click("#camBtn")
    pg.wait_for_function("() => window.__camOn() === true", timeout=30000)
    pg.evaluate("() => { const el = document.querySelector('#cnt'); if (el) el.value = '0'; }")
    pg.evaluate("sh => { window.__cmp.markB = sh; }", 0.0)
    pg.click("#cmpGo")
    if not wait_finish(pg):
        return {"error": "timeout: сравнение не завершилось за " + str(TIMEOUT) + "с"}
    return collect_result(pg, extra_keys=("curLagA", "lagAcq", "camOn", "failsB", "smoothB"))


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def report_scenario(sc, runs, extra_prints=None):
    print()
    print(f"=== {sc['name']} — {len(runs)} прогонов ===")
    finals = [r.get("dtw") if r.get("dtw") is not None else r.get("session") for r in runs]
    finals = [f or 0 for f in finals]
    med = median(finals)
    ok = sc["min"] <= med <= sc["max"]
    print(f"  итоги: {' '.join(f'{f:.1f}' for f in finals)}  "
          f"· медиана {med:.1f}% · min {min(finals):.1f} · max {max(finals):.1f}  "
          f"ожидание [{sc['min']}..{sc['max']}]  {'PASS' if ok else 'FAIL'}")
    last = runs[-1]
    print(f"  live-окно {last.get('liveWin') is not None and ('%.1f'%last.get('liveWin')) or '—'}% · "
          f"сессия {last.get('session') is not None and ('%.1f'%last.get('session')) or '—'}% · "
          f"тип {last.get('exType')} · счёт {last.get('score') is not None and round(last.get('score')) or '—'} · "
          f"комбо ×{last.get('maxCombo') or 0} · сэмплов {last.get('samples')}")
    if extra_prints:
        for line in extra_prints:
            print("  " + line)
    return ok


def main():
    argv = list(sys.argv[1:])
    reps = 1
    skip_camera = "--skip-camera" in argv
    nofull = "--nofull" in argv
    argv = [a for a in argv if a not in ("--skip-camera", "--nofull")]
    for i, a in enumerate(argv):
        if a is None:
            continue
        if a == "--reps":
            reps = int(argv[i + 1])
            argv[i] = argv[i + 1] = None
        elif a.startswith("--reps="):
            reps = int(a.split("=", 1)[1])
            argv[i] = None
    for a in (x for x in argv if x is not None):
        m = re.match(r"^(\w+)([<>])(\d+(?:\.\d+)?)$", a)
        if m:
            name, op, val = m.group(1), m.group(2), float(m.group(3))
            sc = next((s for s in SCENARIOS + CAM_SCENARIOS if s["name"] == name), None)
            if sc:
                if op == ">": sc["min"] = val
                else: sc["max"] = val

    server = start_server()
    failed = 0
    skipped = 0
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            pg = b.new_page()
            pg.add_init_script("(" + FAKE_CAM_INIT + ")()")
            pg.goto("http://localhost:8000/index.html")
            pg.click("#tabCmp")
            pg.evaluate("() => { document.querySelector('#delegate').value = 'CPU'; }")
            pg.evaluate("smc => { document.querySelector('#smC').value = String(smc); }", SM_C)

            for sc in SCENARIOS:
                runs = []
                for it in range(reps):
                    res = run_scenario(pg, sc)
                    if "error" in res:
                        print(f"  [run {it+1}] ERROR: {res['error']}")
                        continue
                    diag = res.pop("diag", "")
                    if re.search(r"cmp:T|rejection|ошибка", diag):
                        print(f"  [run {it+1}] JS-ERROR в diag:", diag)
                    big = res.pop("scoreBig", "")
                    if "NaN" in res.get("scoreSub", "") or "NaN" in big:
                        print(f"  [run {it+1}] FAIL NaN в счёте:", res.get("scoreSub"), big)
                    runs.append(res)
                if not runs:
                    failed += 1
                    print(f"=== {sc['name']} — НЕТ ПРОГОНОВ (все ошибки) ===")
                    continue
                extra = []
                last = runs[-1]
                top = sorted(last.get("feat", {}).items(), key=lambda kv: -(kv[1]["meanSim"] or 0))[:3]
                worst = sorted(last.get("feat", {}).items(), key=lambda kv: (kv[1]["meanSim"] or 0))[:3]
                if top and worst:
                    extra.append("лучшие: " + ", ".join(f"{k} {v['meanSim']:.0f}%({v['n']})" for k, v in top))
                    extra.append("худшие: " + ", ".join(f"{k} {v['meanSim']:.0f}%({v['n']})" for k, v in worst))
                if not nofull and sc["name"] == "identical" and last.get("dbg"):
                    dbg = last["dbg"]
                    thr = float(pg.evaluate("() => document.querySelector('#thr').value"))
                    extra.append(f"── диагноз identical (thr={thr:.0f}°, кап={thr * 2.2:.0f}°) ──")
                    extra.append("фича     " + "sim   cov  paired gate   вспл%  A∅%  B∅%  размахA  размахB")
                    for k, d in dbg.items():
                        extra.append(f"{k.ljust(9)} {str(d['meanSim']).ljust(5)} {str(d['cov']).ljust(5)} {str(d['paired']).ljust(7)} "
                                     f"{str(d['gate']).ljust(6)} {str(d['spikesPct']).ljust(6)} {str(d['aMissPct']).ljust(4)} {str(d['bMissPct']).ljust(4)} "
                                     f"{str(d['rangeA']).ljust(8)} {str(d['rangeB'])}")
                    low = [k for k, d in dbg.items() if d["gate"] is not None and d["gate"] < 0.78]
                    extra.append("низкая корреляция формы (<0.78): " + (", ".join(low) if low else " нет"))
                if not report_scenario(sc, runs, extra):
                    failed += 1

            prof = run_profile(pg)
            ok = (prof["panelHidden"] is False and prof["detN"] >= 0.5
                  and len(prof["on"]) >= 8 and prof["maskApplied"] and prof["accent"])
            print()
            print(f"=== profile (A=0808.mp4, фон. анализ эталона) ===")
            print(f"  N={prof['N']} · распознано {prof['det']} · holdish={prof['holdish']} · "
                  f"маска={prof['maskApplied']} · активны {len(prof['on'])} · «{prof['accent']}»")
            print(f"  {('PASS' if ok else 'FAIL')}")
            if not ok:
                failed += 1

            dtm = run_dtwmap(pg)
            ok = not dtm.get("fail") and dtm.get("fileShift", 0) > 0.9 \
                 and dtm.get("camSteady", 0) > 0.8 and dtm.get("camJam", 0) > 0.5
            print()
            print(f"=== dtwmap (живое совпадение: задержка/сдвиг мешать не должны) ===")
            print(f"  файл-сдвиг 1.6с={dtm.get('fileShift')} · камера-полоса(лаг0.4)={dtm.get('camSteady')} · "
                  f"камера-захват(лаг0.4+шум4°)={dtm.get('camJam')}"
                  f"{(' · ' + dtm['fail']) if dtm.get('fail') else ''}")
            print(f"  {('PASS' if ok else 'FAIL')}")
            if not ok:
                failed += 1

            if not nofull and not skip_camera:
                for cs in CAM_SCENARIOS:
                    res = run_camera(pg, cs)
                    if "error" in res:
                        print(f"=== {cs['name']} — ERROR: {res['error']} (камера не дала кадров в headless?) ===")
                        skipped += 1
                        continue
                    diag = res.pop("diag", "")
                    if re.search(r"cmp:T|rejection|ошибка", diag):
                        print(f"  JS-ERROR в diag:", diag)
                    ok = report_scenario(cs, [res], [
                        f"лаг {res.get('curLagA') is not None and ('%.3fс' % res['curLagA']) or '—'} · "
                        f"acq={res.get('lagAcq')} · B-кадров {res.get('smoothB')} · failsB={res.get('failsB')}"
                    ])
                    if cs["name"] == "cam-identical":
                        lag_ok = res.get("curLagA") is not None and abs(res["curLagA"]) > 0.05
                        ok = ok and lag_ok
                        print(f"  лаг-статус: {'OK' if lag_ok else 'FAIL (лаг ≈ 0 — камера не отстаёт)'}")
                    if not ok:
                        failed += 1
            else:
                skipped += 1
                print()
                print("=== cam-* пропущены (--skip-camera / --nofull) ===")

            b.close()
    finally:
        server.kill()

    print()
    print("РЕЗУЛЬТАТ:", "ВСЕ ПРОШЛИ" if not failed else f"{failed} сценариев FAILED",
          f"(пропущено {skipped})" if skipped else "")
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
