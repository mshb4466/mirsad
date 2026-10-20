"""Gamma Map: سحب سلسلة خيارات SPX من ملف CBOE العام المتأخر وحساب Gamma Exposure لكل Strike.

- المكتبة القياسية فقط (والرسم اختياري إن توفر matplotlib).
- لا يُعرض Open Interest في أي مكان؛ هو مدخل حسابي داخلي فقط (GEX = gamma × OI × 100 × spot² × 0.01).
- الأرشفة: gamma/archive/YYYY-MM-DD/HHMM.json (لكل لقطة صالحة)، وgamma/latest.json (للواجهة)،
  وgamma/preopen/YYYY-MM-DD.json (أول لقطة صالحة قبل 09:30 نيويورك: الأولى تفوز).
- last_before_open(date): آخر خريطة متاحة قبل الافتتاح دون تحيّز النظر للمستقبل
  (وقت بيانات اللقطة ووقت جمعها كلاهما <= 09:30 نيويورك).

الاستخدام:
  python gamma.py --collect          # لقطة واحدة + أرشفة + تحديث latest.json
  python gamma.py --probe            # فحص مفصّل يكتب gamma/probe.json (+ صورة إن أمكن)
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    NY = None

URLS = ["https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json",
        "https://cdn-api.cboe.com/api/global/delayed_quotes/options/_SPX.json"]
SPY_URLS = ["https://cdn.cboe.com/api/global/delayed_quotes/options/SPY.json",
            "https://cdn-api.cboe.com/api/global/delayed_quotes/options/SPY.json"]
UA = "Mozilla/5.0 (compatible; mirsad-gamma/1.0)"
SOURCE = "CBOE (متأخر ~15 د)"
MODEL = "GEX = gamma × OI × 100 × spot² × 0.01؛ Call موجب وPut سالب (تقدير مراكز صناع السوق)؛ كل الاستحقاقات (مجموع 4 سلال منفصلة)"
OPT_RE = re.compile(r"^(SPXW?|SPX)(\d{6})([CP])(\d{8})$")
SPY_RE = re.compile(r"^(SPY)(\d{6})([CP])(\d{8})$")
BUCKETS = ("0", "1-7", "8-30", "30+")       # سلال استحقاق منفصلة لا تتداخل: يوم الاستحقاق = اليوم / 1–7 / 8–30 / أكثر من 30 يوماً
SPY_MAX_GAP_MIN = 30                          # أقصى فرق بين ختم ملفي SPX وSPY لاعتماد SPY
OUT_DIR = "gamma"
WALL_BAND = 0.04           # الجدران: Call Wall فوق السعر وPut Wall تحته ضمن ±4%
STRIKE_BAND = 0.06          # يُحفظ ±6% حول السعر في latest (الأرشيف يحفظ نفس النطاق)
FRESH_MIN, LATE_MIN = 30, 180


def now_utc():
    return datetime.now(timezone.utc)


def to_ny(dt):
    return dt.astimezone(NY) if NY else dt - timedelta(hours=4)


def fetch(url=None, timeout=90, tries=3):
    last = None
    for u in (list(url) if isinstance(url, (list, tuple)) else [url] if url else URLS):
        for i in range(tries):
            try:
                t0 = time.time()
                req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    raw = r.read()
                return json.loads(raw.decode("utf-8")), {"url": u, "bytes": len(raw), "secs": round(time.time() - t0, 2)}
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2 * (i + 1))
    raise RuntimeError("تعذّر جلب ملف CBOE: %s" % last)


def parse_ts(s):
    """ختم CBOE = وقت توليد الملف بتوقيت UTC (ثبت بفحص 19 أكتوبر: 06:15:16 مقابل 06:18 UTC وقت الجلب)."""
    s = str(s).strip().replace("T", " ")[:19]
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def parse_chain(raw, opt_re=None):
    """يعيد (spot, ts_utc, contracts[{exp,kind,k,gamma,oi}]) أو يرفع ValueError."""
    opt_re = opt_re or OPT_RE
    if not isinstance(raw, dict) or "data" not in raw:
        raise ValueError("بنية الملف غير متوقعة")
    d = raw["data"]
    spot = None
    for key in ("current_price", "close", "last_trade_price", "prev_day_close"):
        v = d.get(key) if isinstance(d, dict) else None
        if isinstance(v, (int, float)) and v > 0:
            spot = float(v)
            break
    ts = parse_ts(raw.get("timestamp"))
    opts = d.get("options") if isinstance(d, dict) else None
    if not opts:
        raise ValueError("لا عقود في الملف")
    out = []
    for o in opts:
        m = opt_re.match(str(o.get("option", "")))
        if not m:
            continue
        g, oi = o.get("gamma"), o.get("open_interest")
        if not isinstance(g, (int, float)) or not isinstance(oi, (int, float)):
            continue
        iv = o.get("iv")
        out.append({"exp": m.group(2), "kind": m.group(3), "k": int(m.group(4)) / 1000.0,
                    "gamma": float(g), "oi": float(oi), "iv": float(iv) if isinstance(iv, (int, float)) else 0.0})
    if not out:
        raise ValueError("لا عقود SPX صالحة بعد التحليل")
    return spot, ts, out


def _exp_date(exp):
    return datetime.strptime("20" + exp, "%Y%m%d").date()


def bucket_of(days):
    """سلة الاستحقاق: كل عقد ينتمي لسلة واحدة فقط (لا تداخل)."""
    if days <= 0:
        return "0"
    return "1-7" if days <= 7 else "8-30" if days <= 30 else "30+"


def _rows(spot, contracts):
    by = {}
    for c in contracts:
        gex = c["gamma"] * c["oi"] * 100.0 * spot * spot * 0.01
        row = by.setdefault(c["k"], {"call": 0.0, "put": 0.0})
        if c["kind"] == "C":
            row["call"] += gex
        else:
            row["put"] -= gex
    return [{"k": k, "call": by[k]["call"], "put": by[k]["put"], "net": by[k]["call"] + by[k]["put"]} for k in sorted(by)]


def _walls(rows, spot):
    up = [r for r in rows if spot <= r["k"] <= spot * (1 + WALL_BAND)]
    dn = [r for r in rows if spot * (1 - WALL_BAND) <= r["k"] <= spot]
    return (max(up, key=lambda r: r["call"])["k"] if up else None,
            min(dn, key=lambda r: r["put"])["k"] if dn else None)


def compute(spot, contracts, ref_utc=None, today=None):
    """GEX لكل Strike (مجموع كل الاستحقاقات = مجموع السلال الأربع بالضبط) + سلال منفصلة.
    today: تاريخ نيويورك للقطة؛ إن مُرّر تُستبعد العقود المنتهية (قبله). وإلا لا تُستبعد (تُحسب سلة «اليوم»)."""
    ref_day = today or to_ny(ref_utc or now_utc()).date()
    if today is not None:
        contracts = [c for c in contracts if _exp_date(c["exp"]) >= today]
    groups = {b: [] for b in BUCKETS}
    for c in contracts:
        groups[bucket_of((_exp_date(c["exp"]) - ref_day).days)].append(c)
    rows = _rows(spot, contracts)
    net = sum(r["net"] for r in rows)
    call_wall, put_wall = _walls(rows, spot)
    flip = gamma_flip(spot, contracts, ref_utc)
    exps = sorted({c["exp"] for c in contracts})
    inband = lambda rs: [r for r in rs if abs(r["k"] - spot) <= spot * STRIKE_BAND]
    keep = inband(rows)
    buckets = {}
    for b in BUCKETS:
        br = _rows(spot, groups[b]) if groups[b] else []
        cw, pw = _walls(br, spot) if br else (None, None)
        buckets[b] = {"n": len(groups[b]), "net_gex": sum(r["net"] for r in br), "call_wall": cw, "put_wall": pw, "strikes": inband(br)}
    return {"net_gex": net, "regime": "positive" if net >= 0 else "negative", "gamma_flip": flip,
            "call_wall": call_wall, "put_wall": put_wall, "strikes": keep, "buckets": buckets,
            "expiries": ["20" + e[:2] + "-" + e[2:4] + "-" + e[4:] for e in exps], "n_contracts": len(contracts)}


def _expiry_t(exp, ref_utc):
    """الزمن حتى إغلاق 16:15 نيويورك يوم الاستحقاق، بالسنوات (حد أدنى 30 دقيقة)."""
    d = datetime.strptime("20" + exp, "%Y%m%d").replace(hour=16, minute=15)
    d = d.replace(tzinfo=NY) if NY else d.replace(tzinfo=timezone(timedelta(hours=-4)))
    mins = (d.astimezone(timezone.utc) - ref_utc).total_seconds() / 60.0
    return max(mins, 30.0) / (365.0 * 24 * 60)


def gamma_flip(spot, contracts, ref_utc=None, lo=0.92, hi=1.08, steps=49):
    """Gamma Flip: السعر الذي يتقاطع عنده صافي GEX مع الصفر عند إعادة حساب gamma (بلاك-شولز بالـIV لكل عقد)
    على أسعار افتراضية حول السعر الحالي. يعيد أقرب تقاطع للسعر أو None."""
    import math
    ref_utc = ref_utc or now_utc()
    cs = [c for c in contracts if c["oi"] > 0 and c["iv"] > 0.01 and abs(c["k"] - spot) <= spot * 0.25]
    if len(cs) < 50:
        return None
    tcache = {}
    pre = []
    for c in cs:
        T = tcache.setdefault(c["exp"], _expiry_t(c["exp"], ref_utc))
        pre.append((c["k"], c["iv"] * math.sqrt(T), c["oi"] * (1.0 if c["kind"] == "C" else -1.0)))
    pts = []
    for i in range(steps):
        S = spot * (lo + (hi - lo) * i / (steps - 1))
        tot = 0.0
        for k, sv, sg in pre:
            d1 = (math.log(S / k) + 0.5 * sv * sv) / sv
            g = math.exp(-0.5 * d1 * d1) / (2.5066282746310002 * S * sv)
            tot += g * sg
        pts.append((S, tot * 100.0 * S * S * 0.01))
    cands = []
    for (a, ga), (b, gb) in zip(pts, pts[1:]):
        if ga == 0:
            cands.append(a)
        elif (ga < 0) != (gb < 0):
            cands.append(a + (b - a) * abs(ga) / (abs(ga) + abs(gb)))
    return round(min(cands, key=lambda x: abs(x - spot)), 2) if cands else None


def validate(res, spot, contracts, prev=None):
    """يعيد نص السبب إن كانت اللقطة معيبة، وإلا None."""
    if not spot or spot < 100:
        return "السعر المرجعي غير موجود في الملف"
    if all(c["gamma"] == 0 for c in contracts):
        return "كل قيم gamma صفرية (الـ greeks غير محدّثة بعد)"
    if abs(res["net_gex"]) < 1:
        return "الصافي = 0"
    if res["call_wall"] is None or res["put_wall"] is None:
        return "الجدران غير محددة"
    if abs(res["put_wall"] - spot) > spot * 0.10 or abs(res["call_wall"] - spot) > spot * 0.10:
        return "جدار بعيد جداً عن السعر"
    if len(res["strikes"]) < 20:
        return "عدد الـ Strikes قليل (%d)" % len(res["strikes"])
    if prev and prev.get("snapshot_utc"):
        pass
    return None


def _pair(a, b):
    """آخر دقيقة مشتركة بين رمزين (yfinance 1m). يعيد (t, قيمة_a, قيمة_b) أو None."""
    import yfinance as yf
    # 5 أيام لا يوماً واحداً: ES=F يتداول ليلاً فيكون «اليوم» عنده جلسة جديدة بينما ^GSPC ما زال على جلسة الأمس ولا تقاطع بينهما
    sa = yf.Ticker(a).history(period="5d", interval="1m", auto_adjust=False)["Close"].dropna()
    sb = yf.Ticker(b).history(period="5d", interval="1m", auto_adjust=False)["Close"].dropna()
    idx = sa.index.intersection(sb.index)
    if len(idx) == 0:
        return None
    t = idx[-1]
    return t, float(sa[t]), float(sb[t])


def ref_mode(ref_utc, now=None):
    """live: السعران من الجلسة الجارية وحديثان؛ close: مرجع آخر إغلاق (SPX مغلق) فيُحسب الفرق من سعري الإغلاق المتزامنين."""
    now = now or now_utc()
    gap = (now - ref_utc).total_seconds() / 60.0
    return "live" if (in_session(to_ny(now)) and gap <= 30) else "close"


def es_basis(now=None):
    """فرق ES-SPX من أسعار دقيقة متزامنة (yfinance). يعيد dict أو None.
    SPX مغلق: آخر دقيقة مشتركة = إغلاق أمس (نفس اللحظة لـ ES وSPX، فلا تدخل حركة ES الليلية في الفرق).
    بعد افتتاح SPX: آخر دقيقة مشتركة حالية (mode = live)."""
    try:
        p = _pair("ES=F", "^GSPC")
        if not p:
            return None
        t, e, s = p
        tu = t.to_pydatetime().astimezone(timezone.utc)
        gap = (now_utc() - tu).total_seconds() / 60.0
        return {"basis": round(e - s, 2), "es_ref": round(e, 2), "spx_ref": round(s, 2), "ref_gap_min": round(gap, 1),
                "ref_time_utc": tu.isoformat(), "mode": ref_mode(tu, now)}
    except Exception:  # noqa: BLE001
        return None


def spy_ref():
    """نسبة SPX/SPY من سعرين متزامنين (نفس الدقيقة). يعيد dict أو None."""
    try:
        p = _pair("^GSPC", "SPY")
        if not p:
            return None
        t, x, y = p
        if y <= 0:
            return None
        tu = t.to_pydatetime().astimezone(timezone.utc)
        return {"ratio": x / y, "spx_ref": round(x, 2), "spy_ref": round(y, 2), "ref_time_utc": tu.isoformat(),
                "ref_gap_min": round((now_utc() - tu).total_seconds() / 60.0, 1), "mode": ref_mode(tu)}
    except Exception:  # noqa: BLE001
        return None


def _x(rows, ratio):
    """يضيف kx = مكافئ SPX لـ Strike السباي (Strike × SPX/SPY)."""
    return [dict(r, kx=round(r["k"] * ratio, 1)) for r in rows]


def build_spy(spx_ts, fetched, today, ref=None, raw=None):
    """لقطة SPY من SPY.json: السعر المرجعي والنسبة من yfinance المتزامن، والمستويات بمكافئ SPX.
    تُعطَّل (ok=False مع سبب) إن غاب السعر المتزامن أو كان ختم ملف SPY بعيداً عن ختم SPX أو فشل التحقق."""
    try:
        ref = ref or spy_ref()
        if not ref:
            return {"ok": False, "reason": "لا سعر SPY/SPX متزامن (yfinance)"}
        if raw is None:
            raw, _ = fetch(SPY_URLS)
        _, ts, cs = parse_chain(raw, SPY_RE)
        spot = ref["spy_ref"]
        gap = abs((ts - spx_ts).total_seconds()) / 60.0
        if gap > SPY_MAX_GAP_MIN:
            return {"ok": False, "reason": "ختم ملف SPY بعيد عن ختم SPX (%d دقيقة)" % gap}
        res = compute(spot, cs, fetched, today)
        why = validate(res, spot, cs)
        if ts > fetched + timedelta(minutes=5):
            why = why or "ختم ملف SPY في المستقبل"
        if why:
            return {"ok": False, "reason": "SPY: " + why}
        r = ref["ratio"]
        fx = lambda v: round(v * r, 1) if v is not None else None
        bks = {b: {"n": v["n"], "net_gex": v["net_gex"], "call_wall": v["call_wall"], "put_wall": v["put_wall"],
                   "call_wall_x": fx(v["call_wall"]), "put_wall_x": fx(v["put_wall"]), "strikes": _x(_rnd(v["strikes"]), r)}
               for b, v in res["buckets"].items()}
        return {"ok": True, "asset": "SPY", "snapshot_utc": ts.isoformat(), "snapshot_et": to_ny(ts).strftime("%Y-%m-%d %H:%M"),
                "spot": spot, "ratio": round(r, 5), "ref_time_utc": ref["ref_time_utc"], "ref_mode": ref["mode"],
                "ref_gap_min": ref["ref_gap_min"], "spx_ref": ref["spx_ref"], "net_gex": res["net_gex"], "regime": res["regime"],
                "gamma_flip": res["gamma_flip"], "gamma_flip_x": fx(res["gamma_flip"]),
                "call_wall": res["call_wall"], "put_wall": res["put_wall"],
                "call_wall_x": fx(res["call_wall"]), "put_wall_x": fx(res["put_wall"]),
                "strikes": _x(_rnd(res["strikes"]), r), "buckets": bks, "n_contracts": res["n_contracts"], "reason": None}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "SPY: %s" % e}


def _rnd(rows):
    """تقريب الدولار لأقرب عدد صحيح لتصغير الملف (الصافي = Call + Put بعد التقريب)."""
    out = []
    for r in rows:
        c, p = int(round(r["call"])), int(round(r["put"]))
        out.append({"k": r["k"], "call": c, "put": p, "net": c + p})
    return out


def in_session(et):
    if et.weekday() >= 5:
        return False
    m = et.hour * 60 + et.minute
    return 9 * 60 + 30 <= m <= 16 * 60 + 15


def status_of(ts_utc, fetched=None):
    m = ((fetched or now_utc()) - ts_utc).total_seconds() / 60.0
    return "fresh" if m < FRESH_MIN else "late" if m < LATE_MIN else "stale"


def build(raw, fetched=None, with_es=True, with_spy=None, spy_raw=None):
    spot, ts, contracts = parse_chain(raw)
    if spot is None:
        raise ValueError("لا يوجد سعر SPX في الملف")
    fetched = fetched or now_utc()
    et = to_ny(ts)
    res = compute(spot, contracts, fetched, et.date())
    why = validate(res, spot, contracts)
    if ts > fetched + timedelta(minutes=5):
        why = why or "ختم الملف في المستقبل؛ لا يُعتمد"
    snap = {"ok": why is None, "asset": "SPX", "snapshot_utc": ts.isoformat(), "snapshot_et": et.strftime("%Y-%m-%d %H:%M"),
            "fetched_utc": fetched.isoformat(), "source": SOURCE, "model": MODEL, "spot": round(spot, 2),
            "regime": res["regime"], "net_gex": res["net_gex"], "gamma_flip": res["gamma_flip"],
            "call_wall": res["call_wall"], "put_wall": res["put_wall"], "strikes": _rnd(res["strikes"]),
            "buckets": {b: dict(v, strikes=_rnd(v["strikes"])) for b, v in res["buckets"].items()},
            "expiries": res["expiries"], "n_contracts": res["n_contracts"],
            "status": status_of(ts, fetched), "reason": why, "spy": {"ok": False}}
    if why is None and not in_session(et):
        if snap["status"] == "fresh":
            snap["status"] = "late"
        snap["reason"] = "خارج ساعات الجلسة (09:30–16:15 نيويورك): الأسعار والمستويات مبنية على آخر إغلاق وليست حية."
    snap["es"] = es_basis() if (with_es and why is None) else None
    with_spy = with_es if with_spy is None else with_spy
    if with_spy and why is None:
        snap["spy"] = build_spy(ts, fetched, et.date(), raw=spy_raw)
    return snap


def _wjson(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _rjson(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def slim(snap):
    """نسخة الأرشيف: Strikes الكلية فقط + ملخص السلال وSPY بلا Strikes (لتقليل حجم المستودع)."""
    o = dict(snap)
    o["buckets"] = {b: {k: v for k, v in d.items() if k != "strikes"} for b, d in (snap.get("buckets") or {}).items()}
    sp = snap.get("spy")
    if isinstance(sp, dict) and sp.get("ok"):
        o["spy"] = {k: v for k, v in sp.items() if k not in ("strikes", "buckets")}
    return o


def archive(snap, root=OUT_DIR):
    """يحفظ اللقطة الصالحة ويحدّث latest وpreopen. يعيد قائمة بما كُتب."""
    done = []
    if not snap.get("ok"):
        return done
    ts = datetime.fromisoformat(snap["snapshot_utc"])
    et = to_ny(ts)
    day = et.strftime("%Y-%m-%d")
    p = os.path.join(root, "archive", day, et.strftime("%H%M") + ".json")
    if not os.path.exists(p):
        _wjson(p, slim(snap))
        done.append(p)
    cur = _rjson(os.path.join(root, "latest.json"))
    if not cur or not cur.get("ok") or cur.get("snapshot_utc", "") <= snap["snapshot_utc"]:
        _wjson(os.path.join(root, "latest.json"), snap)
        done.append("latest.json")
    open_et = et.replace(hour=9, minute=30, second=0, microsecond=0)
    fetched = datetime.fromisoformat(snap["fetched_utc"])
    if et <= open_et and to_ny(fetched) <= open_et:
        pp = os.path.join(root, "preopen", day + ".json")
        if not os.path.exists(pp):        # أول لقطة صالحة قبل 09:30 تفوز
            _wjson(pp, snap)
            done.append(pp)
    return done


def last_before_open(day, root=OUT_DIR):
    """آخر خريطة صالحة ليوم day (YYYY-MM-DD) وقت بياناتها ووقت جمعها <= 09:30 نيويورك. None إن لم توجد."""
    d = os.path.join(root, "archive", day)
    if not os.path.isdir(d):
        return None
    best = None
    for fn in sorted(os.listdir(d)):
        s = _rjson(os.path.join(d, fn))
        if not s or not s.get("ok"):
            continue
        ts, fe = datetime.fromisoformat(s["snapshot_utc"]), datetime.fromisoformat(s["fetched_utc"])
        o = to_ny(ts).replace(hour=9, minute=30, second=0, microsecond=0)
        if to_ny(ts) <= o and to_ny(fe) <= o:
            best = s
    return best


def collect(root=OUT_DIR):
    try:
        raw, meta = fetch()
        snap = build(raw)
    except Exception as e:  # noqa: BLE001
        fail = {"ok": False, "asset": "SPX", "reason": "فشل الجمع: %s" % e, "fetched_utc": now_utc().isoformat(),
                "spy": {"ok": False}}
        cur = _rjson(os.path.join(root, "latest.json"))
        if not cur:
            _wjson(os.path.join(root, "latest.json"), fail)
        print("فشل:", e)
        return None
    wrote = archive(snap, root)
    print("لقطة %s نيويورك | سعر %s | صالحة=%s | %s | كتب: %s" % (snap["snapshot_et"], snap["spot"], snap["ok"], snap["reason"] or "-", wrote))
    if not snap["ok"]:
        cur = _rjson(os.path.join(root, "latest.json"))
        if not cur:
            _wjson(os.path.join(root, "latest.json"), {k: snap[k] for k in ("ok", "asset", "reason", "fetched_utc", "spy")})
    return snap


def probe(root=OUT_DIR):
    """فحص تفصيلي: يكتب gamma/probe.json (ويُلحق gamma/probe_log.jsonl) وصورة إن أمكن."""
    info = {"at_utc": now_utc().isoformat(), "at_et": to_ny(now_utc()).strftime("%Y-%m-%d %H:%M")}
    try:
        raw, meta = fetch()
        info.update(meta)
        d = raw.get("data", {})
        info["top_keys"] = list(raw.keys())
        info["data_keys"] = list(d.keys())[:20] if isinstance(d, dict) else None
        info["timestamp_raw"] = raw.get("timestamp")
        info["data_scalars"] = {k: v for k, v in d.items() if k != "options" and not isinstance(v, (list, dict))}
        near = sorted(d["options"], key=lambda o: abs(int(str(o.get("option", "x00000000"))[-8:] or 0) / 1000.0 - float(d.get("current_price") or 0)) if str(o.get("option", ""))[-8:].isdigit() else 1e9)
        info["sample_option_near_atm"] = near[0] if near else None
        info["n_iv_positive"] = sum(1 for o in d["options"] if isinstance(o.get("iv"), (int, float)) and o["iv"] > 0)
        spot, ts, contracts = parse_chain(raw)
        info["spot"] = spot
        info["snapshot_utc"] = ts.isoformat()
        info["snapshot_et"] = to_ny(ts).strftime("%Y-%m-%d %H:%M")
        info["age_min"] = round((now_utc() - ts).total_seconds() / 60.0, 1)
        info["n_options_total"] = len(raw["data"]["options"])
        info["n_contracts_parsed"] = len(contracts)
        info["n_gamma_nonzero"] = sum(1 for c in contracts if c["gamma"] != 0)
        snap = build(raw, with_es=True)
        info["valid"] = snap["ok"]
        info["reason"] = snap["reason"]
        for k in ("net_gex", "regime", "gamma_flip", "call_wall", "put_wall", "expiries", "es"):
            info[k] = snap.get(k)
        info["n_strikes_kept"] = len(snap["strikes"])
        archive(snap, root)
        try:
            info["chart"] = chart(snap, os.path.join(root, "probe.png"))
        except Exception as e:  # noqa: BLE001
            info["chart"] = "لا رسم: %s" % e
    except Exception as e:  # noqa: BLE001
        info["error"] = str(e)
    _wjson(os.path.join(root, "probe.json"), info)
    with open(os.path.join(root, "probe_log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(info, ensure_ascii=False) + "\n")
    print(json.dumps(info, ensure_ascii=False, indent=1))
    return info


def chart(snap, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows = [r for r in snap["strikes"] if abs(r["k"] - snap["spot"]) <= 150]
    ks = [r["k"] for r in rows]
    fig, ax = plt.subplots(figsize=(7, 10))
    ax.barh(ks, [r["call"] / 1e9 for r in rows], height=4, color="#2fbf71", label="Call")
    ax.barh(ks, [r["put"] / 1e9 for r in rows], height=4, color="#e5484d", label="Put")
    ax.axhline(snap["spot"], color="#2b5fd9", lw=1.5)
    for name, v in (("Flip", snap["gamma_flip"]), ("Call Wall", snap["call_wall"]), ("Put Wall", snap["put_wall"])):
        if v is not None and ks and ks[0] <= v <= ks[-1]:
            ax.axhline(v, ls="--", lw=1, color="gray")
            ax.text(ax.get_xlim()[1], v, " " + name, va="center", fontsize=8)
    ax.set_title("SPX GEX per Strike | %s ET | spot %s | %s" % (snap["snapshot_et"], snap["spot"], snap["regime"]))
    ax.set_xlabel("GEX (B$ per 1%)")
    ax.legend()
    fig.tight_layout()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def telegram_photo(path, caption):
    """إرسال الصورة عبر تيليجرام بالأسرار من البيئة فقط (لا تُطبع)."""
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat or not os.path.exists(path):
        return False
    import uuid
    b = uuid.uuid4().hex
    body = b""
    for k, v in (("chat_id", chat), ("caption", caption)):
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (b, k, v)).encode("utf-8")
    body += ("--%s\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"g.png\"\r\nContent-Type: image/png\r\n\r\n" % b).encode()
    body += open(path, "rb").read() + ("\r\n--%s--\r\n" % b).encode()
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendPhoto" % tok, data=body,
                                 headers={"Content-Type": "multipart/form-data; boundary=" + b})
    try:
        urllib.request.urlopen(req, timeout=60).read()
        return True
    except Exception:  # noqa: BLE001
        return False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--telegram", action="store_true", help="مع --probe: أرسل الصورة إلى تيليجرام (بالأسرار)")
    ap.add_argument("--root", default=OUT_DIR)
    a = ap.parse_args(argv)
    if a.probe:
        info = probe(a.root)
        if a.telegram and info.get("chart", "").endswith(".png"):
            cap = "جاما SPX | لقطة %s نيويورك | عمرها %s د | %s" % (info.get("snapshot_et"), info.get("age_min"), "صالحة" if info.get("valid") else "غير صالحة: %s" % info.get("reason"))
            print("تيليجرام:", telegram_photo(info["chart"], cap))
        return 0
    snap = collect(a.root)
    return 0 if snap is not None else 1


if __name__ == "__main__":
    sys.exit(main())
