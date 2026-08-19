"""Port of js/signature.js — motion-signature segmentation, server side.

Same algorithm, 1:1 with the JS original (see cv_fitness/js/signature.js for
the annotated version). Operates on MediaPipe world landmarks (33 points,
metres, body-local frame) rather than normalized image landmarks — the
angles/geometry it computes are camera-angle invariant.
"""

import math
import statistics as st

WINDOW = 5.0   # seconds - signature window / context
STEP = 2.0     # seconds - window step
RATE_HZ = 5    # frame sampling rate signature was tuned against

WEIGHTS = {"angles": 0.4, "geometry": 0.4, "tempo": 0.1, "pose": 0.1}

# Angle features: {key, a, b, c} or {key, tilt/spread/twist: True}.
FEATURES = [
    {"key": "lElbow", "a": 11, "b": 13, "c": 15},
    {"key": "rElbow", "a": 12, "b": 14, "c": 16},
    {"key": "lKnee", "a": 23, "b": 25, "c": 27},
    {"key": "rKnee", "a": 24, "b": 26, "c": 28},
    {"key": "lHip", "a": 11, "b": 23, "c": 25},
    {"key": "rHip", "a": 12, "b": 24, "c": 26},
    {"key": "tilt", "tilt": True},
    {"key": "spread", "spread": True},
    {"key": "twist", "twist": True},
]

GEOM_FEATURES = [
    "torsoTilt", "shoulderHipTwist",
    "lArmElev", "lArmAz", "lForElev", "lForAz", "lWristHt",
    "rArmElev", "rArmAz", "rForElev", "rForAz", "rWristHt",
    "lKneeHt", "rKneeHt", "lAnkleHt", "rAnkleHt", "legSpread",
]
POSE_FEATURES = ["torsoTilt", "shoulderHipTwist"]

GROUPS = {
    "angles": [f["key"] for f in FEATURES],
    "geometry": [k for k in GEOM_FEATURES if k not in POSE_FEATURES],
    "tempo": ["globalRate"],
    "pose": POSE_FEATURES,
}


# ── vector helpers ──
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    m = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)
    return (a[0] / m, a[1] / m, a[2] / m) if m else None


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _vang(a, b):
    n1, n2 = _norm(a), _norm(b)
    if n1 is None or n2 is None:
        return None
    c = max(-1.0, min(1.0, _dot(n1, n2)))
    return math.degrees(math.acos(c))


def _pt(lm, i):
    p = lm[i] if i < len(lm) else None
    return (p["x"], p["y"], p.get("z", 0.0)) if p else (0.0, 0.0, 0.0)


def _vis(lm, i):
    p = lm[i] if i < len(lm) else None
    return p.get("v", 1.0) if p else 0.0


def median(arr):
    return st.median(arr) if arr else None


def robust_spread(arr):
    if not arr:
        return 0.0
    a = sorted(arr)
    n = len(a)

    def p(q):
        pos = q * (n - 1)
        lo, hi = math.floor(pos), math.ceil(pos)
        return a[max(0, min(n - 1, lo))]

    return p(0.9) - p(0.1)


def ang3w(p1, p2, p3):
    u = _sub(p1, p2)
    w = _sub(p3, p2)
    mu = math.sqrt(u[0] ** 2 + u[1] ** 2 + u[2] ** 2)
    mw = math.sqrt(w[0] ** 2 + w[1] ** 2 + w[2] ** 2)
    if not mu or not mw:
        return None
    cos = max(-1.0, min(1.0, _dot(u, w) / (mu * mw)))
    return math.degrees(math.acos(cos))


def feat_angle(lm, f):
    if f.get("tilt"):
        lsh, rsh, lhip, rhip = _pt(lm, 11), _pt(lm, 12), _pt(lm, 23), _pt(lm, 24)
        neck = tuple((a + b) / 2 for a, b in zip(lsh, rsh))
        pelv = tuple((a + b) / 2 for a, b in zip(lhip, rhip))
        dx, dy, dz = neck[0] - pelv[0], neck[1] - pelv[1], neck[2] - pelv[2]
        m = math.sqrt(dx * dx + dy * dy + dz * dz)
        if not m:
            return None
        return math.degrees(math.acos(max(-1.0, min(1.0, (-dy) / m))))
    if f.get("spread"):
        lsh, rsh = _pt(lm, 11), _pt(lm, 12)
        sh = tuple((a + b) / 2 for a, b in zip(lsh, rsh))
        return ang3w(_pt(lm, 15), sh, _pt(lm, 16))
    if f.get("twist"):
        ls, rs, lh, rh = _pt(lm, 11), _pt(lm, 12), _pt(lm, 23), _pt(lm, 24)
        sx, sz = rs[0] - ls[0], rs[2] - ls[2]
        hx, hz = rh[0] - lh[0], rh[2] - lh[2]
        ms, mh = math.hypot(sx, sz), math.hypot(hx, hz)
        if not ms or not mh:
            return None
        cos = max(-1.0, min(1.0, (sx * hx + sz * hz) / (ms * mh)))
        return math.degrees(math.acos(cos))
    if any(_vis(lm, i) <= 0 for i in (f["a"], f["b"], f["c"])):
        return None
    return ang3w(_pt(lm, f["a"]), _pt(lm, f["b"]), _pt(lm, f["c"]))


# ── per-frame descriptors from world landmarks ──
def frame_descriptors(wlm):
    if not wlm or len(wlm) < 33:
        return None
    if min(_vis(wlm, i) for i in (11, 12, 23, 24)) < 0.5:
        return None

    lsh, rsh, lhip, rhip = _pt(wlm, 11), _pt(wlm, 12), _pt(wlm, 23), _pt(wlm, 24)
    S = tuple((a + b) / 2 for a, b in zip(lsh, rsh))
    H = tuple((a + b) / 2 for a, b in zip(lhip, rhip))

    up = _norm(_sub(S, H))
    lat = _norm(_sub(rsh, lsh))
    fwd = _norm(_cross(up, lat)) if (up and lat) else None
    if not up or not lat or not fwd:
        return None

    geom = {}
    geom["torsoTilt"] = _vang(up, (0.0, 1.0, 0.0))
    sl, hl = _sub(rsh, lsh), _sub(rhip, lhip)
    tw = _vang(sl, hl)
    geom["shoulderHipTwist"] = None if tw is None else min(tw, 180 - tw)

    def proj(v):
        upc = _dot(v, up)
        return _sub(v, tuple(c * upc for c in up))

    for side, sh, el_i, wr_i in (("l", lsh, 13, 15), ("r", rsh, 14, 16)):
        el, wr = _pt(wlm, el_i), _pt(wlm, wr_i)
        A, F = _sub(el, sh), _sub(wr, el)
        geom[side + "ArmElev"] = _vang(A, up)
        geom[side + "ForElev"] = _vang(F, up)

        Ap = proj(A)
        m = math.sqrt(Ap[0] ** 2 + Ap[1] ** 2 + Ap[2] ** 2)
        geom[side + "ArmAz"] = math.degrees(math.atan2(_dot(Ap, fwd), _dot(Ap, lat))) if m >= 1e-4 else None

        Fp = proj(F)
        m2 = math.sqrt(Fp[0] ** 2 + Fp[1] ** 2 + Fp[2] ** 2)
        geom[side + "ForAz"] = math.degrees(math.atan2(_dot(Fp, fwd), _dot(Fp, lat))) if m2 >= 1e-4 else None

        geom[side + "WristHt"] = _dot(_sub(wr, sh), up)

    lkn, rkn, lan, ran = _pt(wlm, 25), _pt(wlm, 26), _pt(wlm, 27), _pt(wlm, 28)
    geom["lKneeHt"] = _dot(_sub(lkn, H), up)
    geom["rKneeHt"] = _dot(_sub(rkn, H), up)
    geom["lAnkleHt"] = _dot(_sub(lan, H), up)
    geom["rAnkleHt"] = _dot(_sub(ran, H), up)
    geom["legSpread"] = math.dist(lan, ran)

    angles = {f["key"]: feat_angle(wlm, f) for f in FEATURES}
    return {"valid": True, "angles": angles, "geom": geom}


# ── window signature ──
def window_signature(frames, win_sec=WINDOW):
    if not frames or len(frames) < 3:
        return None
    sig = {}
    rates = []
    for f in FEATURES:
        key = f["key"]
        vals, ts = [], []
        for fr in frames:
            v = fr["desc"]["angles"].get(key) if fr.get("desc") else None
            if v is not None and math.isfinite(v):
                vals.append(v)
                ts.append(fr["time"])
        if len(vals) < 3:
            sig[key] = None
            continue
        amp = robust_spread(vals)
        vel_s, vel_n = 0.0, 0
        for i in range(1, len(vals)):
            dt = ts[i] - ts[i - 1]
            if dt > 0 and math.isfinite(dt):
                vel_s += abs((vals[i] - vals[i - 1]) / dt)
                vel_n += 1
        mn, mx = min(vals), max(vals)
        mid = (mn + mx) / 2
        zc = sum(1 for i in range(1, len(vals)) if (vals[i - 1] - mid) * (vals[i] - mid) < 0)
        rate = zc / win_sec if win_sec > 0 else 0
        sig[key] = {
            "vel": vel_s / vel_n if vel_n else 0.0,
            "amp": amp,
            "dir": min(1.0, abs(vals[-1] - vals[0]) / amp) if amp > 1e-3 else 0.0,
            "rate": rate,
        }
        rates.append(rate)

    for key in GEOM_FEATURES:
        vals = [fr["desc"]["geom"].get(key) for fr in frames if fr.get("desc")]
        vals = [v for v in vals if v is not None and math.isfinite(v)]
        if len(vals) < 2:
            sig[key] = None
            continue
        sig[key] = {"med": median(vals), "rng": robust_spread(vals)}

    rs = [r for r in rates if math.isfinite(r)]
    sig["globalRate"] = {"med": median(rs) if rs else 0}
    return sig


def build_windows(frames, win_sec=WINDOW, step=STEP):
    out = []
    if not frames:
        return out
    t0, t1 = frames[0]["time"], frames[-1]["time"]
    s = t0
    while s + win_sec <= t1 + 1e-6:
        sel = [f for f in frames if s - 1e-9 <= f["time"] <= s + win_sec]
        sig = window_signature(sel, win_sec)
        if sig:
            out.append({"t0": s, "t1": s + win_sec, "tMid": s + win_sec / 2, "sig": sig})
        s += step
    return out


def mad_normalize(windows):
    by_comp = {}
    for w in windows:
        for key, val in w["sig"].items():
            if not val:
                continue
            for c, v in val.items():
                if v is None or not math.isfinite(v):
                    continue
                by_comp.setdefault(f"{key}.{c}", []).append(v)
    norms = {}
    for ck, arr in by_comp.items():
        med = median(arr)
        mad = median([abs(v - med) for v in arr]) * 1.4826
        norms[ck] = {"med": med, "mad": mad}
    return norms


def comp_diff(key, a, b, norms):
    if not a or not b:
        return None
    s, n = 0.0, 0
    for c, av in a.items():
        bv = b.get(c)
        if av is None or bv is None or not math.isfinite(av) or not math.isfinite(bv):
            continue
        nm = norms.get(f"{key}.{c}")
        if not nm or not (nm["mad"] > 0):
            continue
        za = (av - nm["med"]) / nm["mad"]
        zb = (bv - nm["med"]) / nm["mad"]
        s += (za - zb) ** 2
        n += 1
    return math.sqrt(s / n) if n else None


def _group_dist(key_list, a, b, norms):
    s, n = 0.0, 0
    for k in key_list:
        d = comp_diff(k, a.get(k), b.get(k), norms)
        if d is not None:
            s += d
            n += 1
    return s / n if n else None


def change_distance(sig_l, sig_r, norms):
    d_a = _group_dist(GROUPS["angles"], sig_l, sig_r, norms)
    d_g = _group_dist(GROUPS["geometry"], sig_l, sig_r, norms)
    d_t = _group_dist(GROUPS["tempo"], sig_l, sig_r, norms)
    d_p = _group_dist(GROUPS["pose"], sig_l, sig_r, norms)
    w = WEIGHTS
    motion = ((d_a or 0) * w["angles"] + (d_t or 0) * w["tempo"]) / (w["angles"] + w["tempo"]) \
        if (d_a is not None or d_t is not None) else None
    posep = ((d_g or 0) * w["geometry"] + (d_p or 0) * w["pose"]) / (w["geometry"] + w["pose"]) \
        if (d_g is not None or d_p is not None) else None
    if motion is not None and posep is not None:
        combined = motion * 0.5 + posep * 0.5
    else:
        combined = motion if motion is not None else posep
    return {"D_motion": motion, "D_pose": posep, "combined": combined}


def median_win(win_list):
    sigs = [w["sig"] for w in win_list if w.get("sig")]
    if not sigs:
        return None
    keys = set()
    for sg in sigs:
        keys.update(sg.keys())
    out = {}
    for k in keys:
        comps = set()
        for sg in sigs:
            if sg.get(k):
                comps.update(sg[k].keys())
        vals_by_c = {}
        for c in comps:
            vals = [sg[k][c] for sg in sigs if sg.get(k) and sg[k].get(c) is not None and math.isfinite(sg[k][c])]
            if vals:
                vals_by_c[c] = median(vals)
        out[k] = vals_by_c or None
    return out


def context_distance(windows, t, norms, ctx_sec=WINDOW):
    left = [w for w in windows if t - ctx_sec <= w["tMid"] < t]
    right = [w for w in windows if t <= w["tMid"] <= t + ctx_sec]
    ml, mr = median_win(left), median_win(right)
    if not ml or not mr:
        return None
    return change_distance(ml, mr, norms)


# ── candidates / segments ──
def autothreshold(sig, pct_high=0.95, pct_low=0.7, channel="comb"):
    vals = [s[channel] for s in sig if s.get(channel) is not None and math.isfinite(s[channel])]
    if len(vals) < 10:
        return None
    a = sorted(vals)

    def p(q):
        pos = q * (len(a) - 1)
        lo, hi = math.floor(pos), math.ceil(pos)
        return a[lo] + (a[hi] - a[lo]) * (pos - lo)

    high, low = p(pct_high), p(pct_low)
    return {"high": high, "low": low} if high > low else None


def _finish(sig, a, b, frac, channel):
    base = min((sig[i][channel] for i in range(max(0, a - 3), a + 1) if sig[i][channel] is not None), default=0)
    peak, peak_i = -math.inf, a
    for i in range(a, b + 1):
        c = sig[i][channel]
        if c is not None and c > peak:
            peak, peak_i = c, i
    if not math.isfinite(peak) or peak <= base:
        return {"startT": sig[a]["t"], "endT": sig[b]["t"], "peak": peak, "peakT": sig[peak_i]["t"],
                "boundary": sig[a]["t"], "conf": 0, "Dm": None, "Dp": None}
    bi = -1
    for i in range(a, peak_i + 1):
        c = sig[i][channel]
        if c is not None and c >= base + frac * (peak - base):
            bi = i
            break
    boundary = sig[a]["t"] if bi < 0 else sig[bi]["t"]
    p = sig[peak_i]
    return {"startT": sig[a]["t"], "endT": sig[b]["t"], "peak": peak, "peakT": sig[peak_i]["t"],
            "boundary": boundary, "conf": peak - base, "Dm": p["Dm"], "Dp": p["Dp"]}


def detect_candidates(sig, high, low, frac=0.7, channel="comb"):
    out = []
    state, start = 0, -1
    for i, s in enumerate(sig):
        c = s.get(channel)
        if state == 0:
            if c is not None and c > high:
                state, start = 1, i
        else:
            if c is None or c < low:
                out.append(_finish(sig, start, i - 1, frac, channel))
                state, start = 0, -1
    if state == 1:
        out.append(_finish(sig, start, len(sig) - 1, frac, channel))
    return out


def detect_candidates_union(signal, frac=0.7, dup_sec=3, comb_pct=(0.95, 0.7), chg_pct=(0.9, 0.7)):
    out = []

    def add(lst):
        for c in lst:
            j = next((i for i, o in enumerate(out) if abs(o["boundary"] - c["boundary"]) <= dup_sec), None)
            if j is not None:
                if c["conf"] > out[j]["conf"]:
                    out[j] = c
            else:
                out.append(c)

    at_c = autothreshold(signal, *comb_pct, "comb")
    at_g = autothreshold(signal, *chg_pct, "chg")
    if at_c:
        add(detect_candidates(signal, at_c["high"], at_c["low"], frac, "comb"))
    if at_g:
        add(detect_candidates(signal, at_g["high"], at_g["low"], frac, "chg"))
    out.sort(key=lambda c: c["boundary"])
    return out


def _dominant(c):
    dm, dp = c["Dm"], c["Dp"]
    if dm is None and dp is None:
        return "—"
    if dm is None:
        return "D_pose"
    if dp is None:
        return "D_motion"
    if abs(dm - dp) < 0.05:
        return "оба"
    return "D_motion" if dm > dp else "D_pose"


def segments_from_candidates(cands, duration, t0=0.0):
    segs = []
    prev, n = t0, 1
    for c in cands:
        if c["boundary"] <= prev + 0.05:
            continue
        segs.append({"n": n, "start": prev, "end": c["boundary"], "boundary": c["boundary"],
                     "conf": c["conf"], "dom": _dominant(c)})
        n += 1
        prev = c["boundary"]
    if duration - prev > 0.05 or not segs:
        segs.append({"n": n, "start": prev, "end": duration, "boundary": None, "conf": None, "dom": None})
    return segs


def segment_video(frames, duration, cfg=None):
    """frames: [{time, desc}] (desc from frame_descriptors, or None). Returns segments list."""
    cfg = cfg or {}
    win, step, ctx = cfg.get("win", 5), cfg.get("step", 2), cfg.get("ctx", 5)
    frac, dup_sec = cfg.get("frac", 0.7), cfg.get("dupSec", 3)
    comb_pct, chg_pct = cfg.get("combPct", (0.95, 0.7)), cfg.get("chgPct", (0.9, 0.7))

    windows = build_windows(frames, win, step)
    norms = mad_normalize(windows)
    sig = []
    for w in windows:
        d = context_distance(windows, w["tMid"], norms, ctx) or {}
        dm, dp = d.get("D_motion"), d.get("D_pose")
        chg = max(dm or 0, dp or 0) if (dm is not None or dp is not None) else None
        sig.append({"t": w["tMid"], "Dm": dm, "Dp": dp, "comb": d.get("combined"), "chg": chg})

    valid = sum(1 for f in frames if f.get("desc"))
    cands = detect_candidates_union(sig, frac, dup_sec, comb_pct, chg_pct) if valid >= 10 else []
    return segments_from_candidates(cands, duration)
