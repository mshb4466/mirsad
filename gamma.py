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
BUCKETS = ("0", "wk", "mo", "later")        # سلال تقويمية منفصلة لا تتداخل: اليوم / بقية الأسبوع (حتى الجمعة) / بقية الشهر / ما بعد الشهر
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


def bucket_bounds(ref_day):
    """حدود السلال التقويمية من يوم اللقطة: {سلة: (من, إلى)}، إلى=None تعني بلا نهاية. لا تتداخل ولا تترك فجوة.
    الأسبوع ينتهي أول جمعة ≥ اليوم (في عطلة الأسبوع = الجمعة القادمة)؛ والشهر ينتهي آخر يوم من شهر اليوم؛
    وإن عبر الأسبوعُ نهايةَ الشهر تكون سلة «بقية الشهر» فارغة وتبدأ «ما بعد» بعد نهاية الأسبوع."""
    from datetime import date as _d
    wk_end = ref_day + timedelta(days=(4 - ref_day.weekday()) % 7)
    nxt = _d(ref_day.year + (ref_day.month == 12), ref_day.month % 12 + 1, 1)
    mo_end = nxt - timedelta(days=1)
    last = max(wk_end, mo_end)
    return {"0": (ref_day, ref_day), "wk": (ref_day + timedelta(days=1), wk_end),
            "mo": (wk_end + timedelta(days=1), mo_end), "later": (last + timedelta(days=1), None)}


def bucket_of(exp_day, ref_day):
    """سلة الاستحقاق لتاريخ انتهاء: كل عقد ينتمي لسلة واحدة فقط (لا تداخل). المنتهي قبل اليوم يُعد «اليوم» هنا؛
    يُستبعد قبل ذلك في compute عند تمرير today."""
    b = bucket_bounds(ref_day)
    if exp_day <= b["0"][1]:
        return "0"
    for k in ("wk", "mo"):
        if b[k][0] <= exp_day <= b[k][1]:
            return k
    return "later"


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
        groups[bucket_of(_exp_date(c["exp"]), ref_day)].append(c)
    rows = _rows(spot, contracts)
    net = sum(r["net"] for r in rows)
    call_wall, put_wall = _walls(rows, spot)
    flip = gamma_flip(spot, contracts, ref_utc)
    prof = gamma_profile(spot, contracts, ref_utc)
    exps = sorted({c["exp"] for c in contracts})
    inband = lambda rs: [r for r in rs if abs(r["k"] - spot) <= spot * STRIKE_BAND]
    keep = inband(rows)
    buckets = {}
    bnd = bucket_bounds(ref_day)
    for b in BUCKETS:
        br = _rows(spot, groups[b]) if groups[b] else []
        cw, pw = _walls(br, spot) if br else (None, None)
        lo, hi = bnd[b]
        buckets[b] = {"from": lo.isoformat(), "to": hi.isoformat() if hi else None, "n": len(groups[b]), "net_gex": sum(r["net"] for r in br), "call_wall": cw, "put_wall": pw, "strikes": inband(br),
                      "prof": gamma_profile(spot, groups[b], ref_utc) if groups[b] else None}
    return {"net_gex": net, "regime": "positive" if net >= 0 else "negative", "gamma_flip": flip,
            "call_wall": call_wall, "put_wall": put_wall, "strikes": keep, "buckets": buckets, "prof": prof,
            "expiries": ["20" + e[:2] + "-" + e[2:4] + "-" + e[4:] for e in exps], "n_contracts": len(contracts)}


def _expiry_t(exp, ref_utc):
    """الزمن حتى إغلاق 16:15 نيويورك يوم الاستحقاق، بالسنوات (حد أدنى 30 دقيقة)."""
    d = datetime.strptime("20" + exp, "%Y%m%d").replace(hour=16, minute=15)
    d = d.replace(tzinfo=NY) if NY else d.replace(tzinfo=timezone(timedelta(hours=-4)))
    mins = (d.astimezone(timezone.utc) - ref_utc).total_seconds() / 60.0
    return max(mins, 30.0) / (365.0 * 24 * 60)


def _gex_curve(spot, contracts, ref_utc=None, lo=0.92, hi=1.08, steps=49, minc=50):
    """منحنى صافي GEX (دولار لكل 1%) عند أسعار افتراضية: gamma تُعاد بنموذج بلاك-شولز بالـIV لكل عقد. قائمة (سعر، قيمة) أو None."""
    import math
    ref_utc = ref_utc or now_utc()
    cs = [c for c in contracts if c["oi"] > 0 and c["iv"] > 0.01 and abs(c["k"] - spot) <= spot * 0.25]
    if len(cs) < minc:
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
    return pts


def gamma_flip(spot, contracts, ref_utc=None, lo=0.92, hi=1.08, steps=49):
    """Gamma Flip: السعر الذي يتقاطع عنده صافي GEX مع الصفر (أقرب تقاطع للسعر الحالي) أو None."""
    pts = _gex_curve(spot, contracts, ref_utc, lo, hi, steps)
    if pts is None:
        return None
    cands = []
    for (a, ga), (b, gb) in zip(pts, pts[1:]):
        if ga == 0:
            cands.append(a)
        elif (ga < 0) != (gb < 0):
            cands.append(a + (b - a) * abs(ga) / (abs(ga) + abs(gb)))
    return round(min(cands, key=lambda x: abs(x - spot)), 2) if cands else None


PROF_LO, PROF_HI, PROF_N = 0.94, 1.06, 73


def gamma_profile(spot, contracts, ref_utc=None):
    """منحنى الجاما المحفوظ لمجموعة عقود: {lo, hi, n, v} بمليار دولار لكل 1% (شبكة موحّدة لكل السلال فيُجمع بعضها إلى بعض)
    فيُحسب Flip وحالة السوق عند كل سعر لأي مجموعة استحقاقات يختارها المستخدم. None إن قلّت العقود الصالحة."""
    pts = _gex_curve(spot, contracts, ref_utc, PROF_LO, PROF_HI, PROF_N, minc=5)
    if pts is None:
        return None
    return {"lo": round(pts[0][0], 2), "hi": round(pts[-1][0], 2), "n": PROF_N, "v": [round(v / 1e9, 4) for _, v in pts]}


def _px(prof, r):
    """منحنى SPY بمحور SPX-مكافئ: الشبكة × النسبة (القيم بالدولار كما هي)."""
    if not prof:
        return None
    return dict(prof, lo=round(prof["lo"] * r, 2), hi=round(prof["hi"] * r, 2))


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
        live = in_session(to_ny(spx_ts)) or in_session(to_ny(ts))
        if live and gap > SPY_MAX_GAP_MIN:
            return {"ok": False, "reason": "ختم ملف SPY بعيد عن ختم SPX (%d دقيقة)" % gap}
        if not live and _session_day(to_ny(ts)) != _session_day(to_ny(spx_ts)):
            return {"ok": False, "reason": "ملف SPY من جلسة تداول مختلفة عن ملف SPX (%s مقابل %s)" % (_session_day(to_ny(ts)), _session_day(to_ny(spx_ts)))}
        res = compute(spot, cs, fetched, today)
        why = validate(res, spot, cs)
        if ts > fetched + timedelta(minutes=5):
            why = why or "ختم ملف SPY في المستقبل"
        if why:
            return {"ok": False, "reason": "SPY: " + why}
        r = ref["ratio"]
        fx = lambda v: round(v * r, 1) if v is not None else None
        bks = {b: {"n": v["n"], "net_gex": v["net_gex"], "call_wall": v["call_wall"], "put_wall": v["put_wall"],
                   "call_wall_x": fx(v["call_wall"]), "put_wall_x": fx(v["put_wall"]), "strikes": _x(_rnd(v["strikes"]), r), "prof": _px(v.get("prof"), r)}
               for b, v in res["buckets"].items()}
        return {"ok": True, "asset": "SPY", "snapshot_utc": ts.isoformat(), "snapshot_et": to_ny(ts).strftime("%Y-%m-%d %H:%M"),
                "spot": spot, "ratio": round(r, 5), "ref_time_utc": ref["ref_time_utc"], "ref_mode": ref["mode"],
                "ref_gap_min": ref["ref_gap_min"], "spx_ref": ref["spx_ref"], "net_gex": res["net_gex"], "regime": res["regime"],
                "gamma_flip": res["gamma_flip"], "gamma_flip_x": fx(res["gamma_flip"]),
                "call_wall": res["call_wall"], "put_wall": res["put_wall"],
                "call_wall_x": fx(res["call_wall"]), "put_wall_x": fx(res["put_wall"]),
                "strikes": _x(_rnd(res["strikes"]), r), "prof": _px(res.get("prof"), r), "buckets": bks, "n_contracts": res["n_contracts"], "reason": None}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "SPY: %s" % e}


def _rnd(rows):
    """تقريب الدولار لأقرب عدد صحيح لتصغير الملف (الصافي = Call + Put بعد التقريب)."""
    out = []
    for r in rows:
        c, p = int(round(r["call"])), int(round(r["put"]))
        out.append({"k": r["k"], "call": c, "put": p, "net": c + p})
    return out


def _session_day(et):
    """يوم الجلسة التي تعكسها البيانات: قبل 09:30 نيويورك أو في عطلة الأسبوع = آخر جلسة سابقة (إغلاقها)."""
    d = et.date()
    if et.hour * 60 + et.minute < 9 * 60 + 30:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


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
            "call_wall": res["call_wall"], "put_wall": res["put_wall"], "strikes": _rnd(res["strikes"]), "prof": res["prof"],
            "buckets": {b: dict(v, strikes=_rnd(v["strikes"])) for b, v in res["buckets"].items()},
            "expiries": res["expiries"], "n_contracts": res["n_contracts"],
            "status": status_of(ts, fetched), "reason": why, "spy": {"ok": False}}
    if why is None and not in_session(et):
        if snap["status"] == "fresh":
            snap["status"] = "late"
        snap["reason"] = "خارج ساعات الجلسة (09:30–16:15 نيويورك): الأسعار والمستويات مبنية على آخر إغلاق وليست حية."
    # الطبقات الاختيارية (ES وSPY) لا تُسقط SPX أبداً: أي استثناء فيها يعني تعطيل الطبقة فقط مع سبب صريح
    try:
        snap["es"] = es_basis() if (with_es and why is None) else None
    except Exception as e:  # noqa: BLE001
        snap["es"] = None
        print("تعطّل ES (SPX سليم):", e)
    with_spy = with_es if with_spy is None else with_spy
    if with_spy and why is None:
        try:
            snap["spy"] = build_spy(ts, fetched, et.date(), raw=spy_raw)
        except Exception as e:  # noqa: BLE001
            snap["spy"] = {"ok": False, "reason": "تعطّل طبقة SPY: %s" % e}
            print("تعطّل SPY (SPX سليم):", e)
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


LEVELS_HEADER = "asof_utc,%s,basis,%s,mode,%s"


def levels_es_rows(snap):
    """مستويات جاهزة للمنصة (Sierra Chart) بسعر ES: price,label,kind,strength,color,style,width.
    الجدران وFlip ثم القمم/القيعان (قوية متصلة، متوسطة منقّطة). SPX وSPY بوسم المصدر. تُهمل بلا فرق ES."""
    es = snap.get("es") or {}
    if es.get("basis") is None:
        return None
    bs = float(es["basis"])
    sc = snap_scale(snap)
    rows = []

    def add(src, k, label, kind, strength, color, style, width):
        if k is None:
            return
        rows.append([round(round((float(k) + bs) * 4) / 4, 2), "%s %s" % (src, label), kind, strength, color, style, width])
    GREEN, RED, YEL = "00E0A0", "FF5C7A", "FFD24A"
    lv = level_map(snap)
    for key, v in lv.items():
        a, kind = key.split("|")
        r = 1.0 if a == "SPX" else sc.get("SPY")
        if not r:
            continue
        if kind == "CALL WALL":
            add(a, v * r, "CALL WALL", "wall", "wall", GREEN, "solid", 3)
        elif kind == "PUT WALL":
            add(a, v * r, "PUT WALL", "wall", "wall", RED, "solid", 3)
        elif kind == "GAMMA FLIP":
            add(a, v * r, "GAMMA FLIP", "flip", "flip", YEL, "solid", 3)
    for a, pks in (_safe_peaks(snap) or {}).items():
        for x in pks:
            sign = "+" if x["s"] > 0 else "-"
            strong = bool(x["strong"])
            add(a, x["k"], "PEAK%s %s" % (sign, "S" if strong else "M"), "peak", "strong" if strong else "medium",
                GREEN if x["s"] > 0 else RED, "solid" if strong else "dash", 2 if strong else 1)
    rows.sort(key=lambda r: -r[0])
    return rows


def write_levels_es(snap, root=OUT_DIR):
    """يكتب gamma/levels_es.csv لدراسة Sierra Chart. فشل ناعم؛ لا يمس الخريطة."""
    try:
        rows = levels_es_rows(snap)
        if not rows:
            return False
        es = snap.get("es") or {}
        lines = [LEVELS_HEADER % (snap["snapshot_utc"], es.get("basis"), es.get("mode")), "price,label,kind,strength,color,style,width"]
        lines += [",".join(str(c) for c in r) for r in rows]
        path = os.path.join(root, "levels_es.csv")
        os.makedirs(root, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
        return True
    except Exception as e:  # noqa: BLE001
        print("تعذّر كتابة levels_es.csv (الخريطة سليمة):", e)
        return False


DAY_MAX_PTS = 120


def day_point(snap):
    """نقطة الخط الزمني: المستويات بمكافئ SPX (SPX وSPY) والقمم والأساس وسعر ES. صغيرة لتبقى الملفات خفيفة."""
    sc = snap_scale(snap)
    lv = {}
    for k, v in level_map(snap).items():
        a = k.split("|")[0]
        r = 1.0 if a == "SPX" else sc.get("SPY")
        if r:
            lv[k] = round(float(v) * r, 2)
    pk = _safe_peaks(snap) or {}
    es = snap.get("es") or {}
    return {"t": snap["snapshot_utc"], "sp": snap.get("spot"), "b": es.get("basis"), "lv": lv,
            "pk": {a: [[x["k"], x["s"], 1 if x["strong"] else 0] for x in v] for a, v in pk.items()}}


def append_day(snap, root=OUT_DIR):
    """يضيف نقطة لجلسة اليوم (gamma/day.json) ويبدأ ملفاً جديداً عند تغيّر اليوم. فشل ناعم."""
    try:
        et = to_ny(datetime.fromisoformat(snap["snapshot_utc"]))
        day = et.strftime("%Y-%m-%d")
        path = os.path.join(root, "day.json")
        cur = _rjson(path)
        if not cur or cur.get("day") != day:
            cur = {"day": day, "pts": []}
        if any(p_["t"] == snap["snapshot_utc"] for p_ in cur["pts"]):
            return False
        cur["pts"].append(day_point(snap))
        cur["pts"] = sorted(cur["pts"], key=lambda p_: p_["t"])[-DAY_MAX_PTS:]
        _wjson(path, cur)
        return True
    except Exception as e:  # noqa: BLE001
        print("تعذّر حفظ الخط الزمني لليوم (الخريطة سليمة):", e)
        return False


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


CHANGE_MIN_PTS = 5.0      # أصغر تغيّر في مستوى جاما (بنقاط SPX/ES) يستحق التنبيه


def snap_scale(snap):
    """معامل تحويل كل أصل إلى مكافئ SPX في هذه اللقطة: SPX=1، SPY=نسبة SPX/SPY المتزامنة."""
    sp = snap.get("spy") if isinstance(snap.get("spy"), dict) and snap["spy"].get("ok") else None
    return {"SPX": 1.0, "SPY": float(sp["ratio"]) if sp and sp.get("ratio") else None}


def level_map(snap):
    """المستويات الرئيسية بوحدة الأصل نفسه (SPX بنقاط SPX، وSPY بـ Strike الـ SPY): {"SPX|CALL WALL": k, ...}.
    المقارنة بوحدة الأصل تمنع أن تُحسب حركة نسبة SPX/SPY تغيّراً في المستوى."""
    sp = snap.get("spy") if isinstance(snap.get("spy"), dict) and snap["spy"].get("ok") else {}
    src = {"SPX": (snap.get("call_wall"), snap.get("put_wall"), snap.get("gamma_flip")),
           "SPY": (sp.get("call_wall"), sp.get("put_wall"), sp.get("gamma_flip"))}
    out = {}
    for a, (c, p_, f) in src.items():
        for kind, v in (("CALL WALL", c), ("PUT WALL", p_), ("GAMMA FLIP", f)):
            if v is not None:
                out["%s|%s" % (a, kind)] = round(float(v), 3)
    return out


def level_changes(old, new, thr=CHANGE_MIN_PTS, sc_old=None, sc_new=None):
    """مستويات تغيّرت بمقدار thr نقطة SPX أو أكثر. المقارنة بوحدة الأصل (حدّ SPY = thr ÷ النسبة الحالية).
    الناتج: old/new بمكافئ SPX في لقطة كل منهما، وdelta = التغيّر الحقيقي بمكافئ SPX (بنسبة اللقطة الحالية)."""
    sc_old = sc_old or {"SPX": 1.0, "SPY": None}; sc_new = sc_new or {"SPX": 1.0, "SPY": None}
    out = []
    for k, v in new.items():
        o = old.get(k)
        if o is None:
            continue
        a, kind = k.split("|")
        rn = sc_new.get(a) or 1.0; ro = sc_old.get(a) or rn
        if abs(v - o) * rn >= thr - 1e-9:
            out.append({"key": k, "src": a, "kind": kind, "change": "moved", "old": round(o * ro, 2), "new": round(v * rn, 2),
                        "delta": round((v - o) * rn, 2)})
    return sorted(out, key=lambda x: (x["src"], x["kind"]))


BASIS_NOTE_MIN = 1.0      # تغيّر فرق ES−SPX (نقاط ES) الذي يُنبَّه إليه لأنه يزحزح كل أسعار ES بلا تغيّر في الجاما
PEAK_MIN_REL = 0.25       # قمة/قاع محلي مهم: ≥ 25% من أكبر |net| (كما في خريطة المستويات)
PEAK_STRONG_REL = 0.6     # «قوي» ≥ 60%
PEAK_BAND = 150.0         # نطاق المستويات حول السعر (نقاط SPX)
PEAK_PAIR_MAX = 25.0      # أبعد مسافة لاعتبار قمة قديمة وجديدة نفس القمة وقد تحرّكت


def _peaks_of(rows, spot, walls):
    """قمم/قيعان net المحلية المهمة لأصل واحد. rows: [(k_بمكافئ_SPX, net, k_بوحدة_الأصل)]. تُستثنى القمم المطابقة (≤3) لجدار الأصل نفسه فهي تُتابَع كجدار.
    k = مكافئ SPX في تلك اللقطة، n = Strike بوحدة الأصل نفسه (للمقارنة بلا أثر لتغيّر نسبة SPX/SPY)."""
    rs = sorted((float(k), float(v), float(n)) for k, v, n in rows if abs(float(k) - spot) <= PEAK_BAND)
    if not rs:
        return []
    mx = max(1.0, max(abs(v) for _, v, _ in rs))
    out = []
    for i, (k, v, n) in enumerate(rs):
        a = rs[i - 1][1] if i > 0 else 0.0
        b = rs[i + 1][1] if i < len(rs) - 1 else 0.0
        if ((v > 0 and v >= a and v >= b) or (v < 0 and v <= a and v <= b)) and abs(v) >= PEAK_MIN_REL * mx:
            if any(w is not None and abs(k - float(w)) <= 3 for w in walls):
                continue
            out.append({"k": round(k, 1), "n": round(n, 3), "s": 1 if v > 0 else -1, "strong": abs(v) / mx >= PEAK_STRONG_REL})
    return out


def peak_map(snap):
    """{"SPX": [قمم], "SPY": [قمم]} من اللقطة الكاملة (كل السلال)؛ k بمكافئ SPX وn بوحدة الأصل."""
    spot = float(snap["spot"])
    out = {"SPX": _peaks_of([(r["k"], r["net"], r["k"]) for r in snap.get("strikes") or []], spot, (snap.get("call_wall"), snap.get("put_wall")))}
    sp = snap.get("spy") if isinstance(snap.get("spy"), dict) and snap["spy"].get("ok") else None
    if sp:
        out["SPY"] = _peaks_of([(r["kx"], r["net"], r["k"]) for r in sp.get("strikes") or [] if r.get("kx") is not None], spot, (sp.get("call_wall_x"), sp.get("put_wall_x")))
    return out


def peak_changes(old, new, thr=CHANGE_MIN_PTS, sc_new=None):
    """تغيّر القمم بوحدة الأصل: قمة بالإشارة نفسها خلال أقل من thr نقطة SPX = لم تتغير؛ وإلا تُقرن الأقرب (≤25 نقطة) كـ«تحرّكت»، والباقي «جديدة»/«اختفت»."""
    sc_new = sc_new or {}
    out = []
    for a in sorted(set(old) & set(new)):
        rn = sc_new.get(a) or 1.0
        o_l, n_l = list(old[a]), list(new[a])
        d = lambda x, y: abs(float(x.get("n", x["k"])) - float(y.get("n", y["k"]))) * rn
        for s in (1, -1):
            os_ = [x for x in o_l if x["s"] == s]; ns = [x for x in n_l if x["s"] == s]
            for x in list(os_):
                m = [y for y in ns if d(x, y) < thr - 1e-9]
                if m:
                    os_.remove(x); ns.remove(min(m, key=lambda y: d(x, y)))
            pairs = sorted(((d(x, y), x, y) for x in os_ for y in ns if d(x, y) <= PEAK_PAIR_MAX), key=lambda z: z[0])
            for _, x, y in pairs:
                if x in os_ and y in ns:
                    os_.remove(x); ns.remove(y)
                    out.append({"key": "%s|PEAK" % a, "src": a, "kind": "PEAK", "sign": s, "change": "moved", "old": x["k"], "new": y["k"],
                                "delta": round((float(y.get("n", y["k"])) - float(x.get("n", x["k"]))) * rn, 2), "strong": y["strong"], "ostrong": x["strong"]})
            for y in ns:
                out.append({"key": "%s|PEAK" % a, "src": a, "kind": "PEAK", "sign": s, "change": "new", "old": None, "new": y["k"], "delta": None, "strong": y["strong"]})
            for x in os_:
                out.append({"key": "%s|PEAK" % a, "src": a, "kind": "PEAK", "sign": s, "change": "gone", "old": x["k"], "new": None, "delta": None, "strong": x["strong"], "ostrong": x["strong"]})
    return sorted(out, key=lambda x: (x["src"], x["new"] if x["new"] is not None else x["old"]))


def _safe_peaks(snap):
    try:
        return peak_map(snap)
    except Exception:  # noqa: BLE001
        return None


def curve_of(snap, rng=150):
    """منحنى صافي GEX القديم للتراكب: {"SPX": [[k, net]], "SPY": [[kx, net]]} ضمن ±rng من السعر (بمكافئ SPX). فشل ناعم."""
    try:
        sp = float(snap["spot"])
        out = {"SPX": [[r["k"], r["net"]] for r in snap.get("strikes") or [] if abs(float(r["k"]) - sp) <= rng and r.get("net") is not None]}
        y = snap.get("spy") if isinstance(snap.get("spy"), dict) and snap["spy"].get("ok") else None
        if y:
            out["SPY"] = [[r["kx"], r["net"]] for r in y.get("strikes") or [] if r.get("kx") is not None and abs(float(r["kx"]) - sp) <= rng and r.get("net") is not None]
        return out
    except Exception:  # noqa: BLE001
        return None


def preopen_baseline(snap, root=OUT_DIR):
    """نقطة المقارنة: أول لقطة صالحة قبل الافتتاح في يوم الجلسة نفسه، ما دامت أقدم من اللقطة الحالية."""
    try:
        et = to_ny(datetime.fromisoformat(snap["snapshot_utc"]))
        b = _rjson(os.path.join(root, "preopen", et.strftime("%Y-%m-%d") + ".json"))
        if not b or not b.get("ok") or b.get("snapshot_utc", "") >= snap["snapshot_utc"]:
            return None
        return {"snapshot_utc": b["snapshot_utc"], "snapshot_et": b["snapshot_et"], "levels": level_map(b), "scale": snap_scale(b), "peaks": _safe_peaks(b),
                "basis": (b.get("es") or {}).get("basis"), "basis_mode": (b.get("es") or {}).get("mode"), "curve": curve_of(b)}
    except Exception:  # noqa: BLE001
        return None


def attach_changes(snap, root=OUT_DIR):
    """يضيف إلى اللقطة baseline (مستويات ما قبل الافتتاح) وchanges (ما تغيّر 5 نقاط فأكثر). فشل ناعم: لا يمس بيانات SPX."""
    try:
        b = preopen_baseline(snap, root)
        snap["baseline"] = b
        sc_n = snap_scale(snap)
        items = level_changes(b["levels"], level_map(snap), sc_old=b.get("scale"), sc_new=sc_n) if b else []
        if b and b.get("peaks"):
            try:
                items += peak_changes(b["peaks"], peak_map(snap), sc_new=sc_n)
            except Exception as e:  # noqa: BLE001
                print("تعذّر حساب تغيّر القمم (الجدران سليمة):", e)
        bn = (snap.get("es") or {}).get("basis")
        drift = round(float(bn) - float(b["basis"]), 2) if b and bn is not None and b.get("basis") is not None else None
        snap["changes"] = {"n": len(items), "thr": CHANGE_MIN_PTS, "items": items, "basis_old": b.get("basis") if b else None, "basis_new": bn,
                           "basis_drift": drift, "basis_note": bool(drift is not None and abs(drift) >= BASIS_NOTE_MIN)}
    except Exception as e:  # noqa: BLE001
        snap["baseline"], snap["changes"] = None, None
        print("تعذّر حساب تغيّر المستويات (SPX سليم):", e)
    return snap


def telegram_text(text):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False
    try:
        data = json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode("utf-8")
        req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % tok, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
        return True
    except Exception:  # noqa: BLE001
        return False


def notify_changes(snap, root=OUT_DIR, send=None):
    """رسالة تيليجرام واحدة لكل تغيّر جديد (توقيع المستويات) في اليوم نفسه؛ لا تكرار. فشل ناعم."""
    try:
        ch = snap.get("changes") or {}
        if not ch.get("n") or snap.get("status") == "stale":
            return False
        et = to_ny(datetime.fromisoformat(snap["snapshot_utc"]))
        sig = "|".join("%s%s=%s" % (i["key"], i.get("change", ""), "-" if i["new"] is None else "%.0f" % i["new"]) + ("@%.0f" % i["old"] if i.get("old") is not None and i.get("change") != "moved" else "") for i in ch["items"])
        sp = os.path.join(root, "alert_state.json")
        st = _rjson(sp) or {}
        day = et.strftime("%Y-%m-%d")
        if st.get("day") == day and st.get("sig") == sig:
            return False
        bs_new = float((snap.get("es") or {}).get("basis") or 0)
        bs_old = float(((snap.get("baseline") or {}).get("basis")) or bs_new)
        lines = ["⚠ تغيّرت %d مستويات في الجاما (%d نقطة فأكثر)" % (ch["n"], int(ch["thr"])),
                 "مقارنة بلقطة ما قبل الافتتاح %s نيويورك، والحالية %s." % ((snap.get("baseline") or {}).get("snapshot_et", "—"), snap.get("snapshot_et", "—"))]
        for i in ch["items"]:
            o_es = None if i["old"] is None else round((i["old"] + bs_old) * 4) / 4
            n_es = None if i["new"] is None else round((i["new"] + bs_new) * 4) / 4
            nm = "%s %s" % (i["src"], i["kind"]) if i["kind"] != "PEAK" else "%s %s %s" % (i["src"], "قمة" if i.get("sign", 1) > 0 else "قاع", "قوية" if i.get("strong") else "متوسطة")
            if o_es is None:
                lines.append("%s: جديد عند %.2f" % (nm, n_es))
            elif n_es is None:
                lines.append("%s: اختفى (كان %.2f)" % (nm, o_es))
            else:
                tot = n_es - o_es
                real = i.get("delta")
                extra = " — منه حقيقي %+.2f" % real if real is not None and abs(tot - real) >= 0.5 else ""
                lines.append("%s: %.2f ← %.2f (%+.2f)%s" % (nm, o_es, n_es, tot, extra))
        if ch.get("basis_note"):
            lines.append("ملاحظة: فرق ES−SPX تغيّر من %.2f إلى %.2f (%+.2f)؛ كل أسعار ES تحرّكت بهذا المقدار بلا تغيّر في الجاما." % (ch["basis_old"], ch["basis_new"], ch["basis_drift"]))
        lines.append("أسعار ES بالفرق الحالي. للاطلاع فقط وليست توصية.")
        ok = (send or telegram_text)("\n".join(lines))
        if ok:
            _wjson(sp, {"day": day, "sig": sig, "at": now_utc().isoformat()})
        return bool(ok)
    except Exception as e:  # noqa: BLE001
        print("تعذّر إشعار تغيّر المستويات (SPX سليم):", e)
        return False


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
    if snap.get("ok"):
        attach_changes(snap, root)
    wrote = archive(snap, root)
    if snap.get("ok") and append_day(snap, root):
        wrote.append("day.json")
    if snap.get("ok") and write_levels_es(snap, root):
        wrote.append("levels_es.csv")
    if snap.get("ok"):
        notify_changes(snap, root)
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
