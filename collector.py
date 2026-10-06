#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — جامع البيانات (النسخة 0.3)

يسحب الأسعار والمؤشرات العالمية والتقويم الاقتصادي ويحسب بالكود، دون أي إدخال يدوي،
مقياس مخاطرة (0-10) من 12 مكوّناً بأوزان متكيّفة، إضافةً إلى كتل معلوماتية لا تدخل الدرجة.

التشغيل:
    python collector.py            # بيانات حقيقية
    python collector.py --demo     # بيانات تجريبية لاختبار المنطق دون إنترنت

حدود معلنة: لا يحلّل الأخبار نصّياً (يحتاج نموذجاً لغوياً مدفوعاً)، ولا يحسب اتجاه السوق،
ولا يملك مصدراً مجانياً لتمركز الخيارات (Gamma) أو لتقارير البنوك المدفوعة.
"""
import argparse
import csv
import gzip
import io
import json
import math
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

import geo
import macro

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

MAG7 = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
BANKS = ["JPM", "GS", "MS", "C", "BAC", "WFC"]

SYMBOLS = {
    "es": "ES=F", "nq": "NQ=F",
    "vix": "^VIX", "vix3m": "^VIX3M", "move": "^MOVE",
    "oil": "CL=F", "gold": "GC=F", "dxy": "DX-Y.NYB",
    "y10": "^TNX", "y5": "^FVX", "irx": "^IRX",
    "jpy": "JPY=X", "nikkei": "^N225", "dax": "^GDAXI", "hsi": "^HSI",
    "spy": "SPY", "rsp": "RSP", "hyg": "HYG", "ief": "IEF", "xlf": "XLF", "kre": "KRE",
}
SYMBOLS.update({"m_" + t: t for t in MAG7})
SYMBOLS.update({"b_" + t: t for t in BANKS})

CAL_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FRED_SERIES = {"t10y2y": "T10Y2Y", "dgs2": "DGS2", "hy_oas": "BAMLH0A0HYM2"}
COT_URL = "https://www.cftc.gov/dea/newcot/deafut.txt"
UA = {"User-Agent": "Mozilla/5.0 (mirsad-collector)"}

# تقويم بورصة نيويورك 2026 (يُراجع سنوياً)
HOLIDAYS = {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
            "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"}
EARLY_CLOSE = {"2026-11-27", "2026-12-24"}

# الأوزان الأساسية (تقديرية؛ تُعايَر بسجل الأداء لاحقاً)
BASE_WEIGHTS = {
    "events": 0.10, "volatility": 0.09, "vix_term": 0.06, "priced_in": 0.07,
    "geopolitics": 0.07, "geo_news": 0.05, "conflict": 0.06, "liquidity": 0.04, "rates": 0.06,
    "front_end": 0.05, "dollar": 0.05, "credit": 0.05, "breadth": 0.04, "global_mkts": 0.04, "calendar": 0.05,
    "fed_system": 0.08, "net_liq": 0.04,
}
NAMES = {
    "events": "قرب الأحداث الكبرى", "volatility": "التقلب (VIX)", "vix_term": "هيكل VIX",
    "priced_in": "التسعير المسبق", "geopolitics": "التوتر الجيوسياسي (من السوق)",
    "geo_news": "الأخبار الجيوسياسية (تصنيف بالقواعد)", "front_end": "الطرف القصير من العوائد (سنتان/5س/13أسبوع)", "dollar": "الدولار DXY", "fed_system": "المنظومة الكلية وتوقع الفدرالي", "net_liq": "السيولة الصافية (الفدرالي/الخزانة/RRP)", "conflict": "تعارض الإشارات والارتباطات", "liquidity": "السيولة", "rates": "العوائد والفائدة",
    "credit": "الائتمان والبنوك", "breadth": "اتساع السوق وقيادته", "global_mkts": "الأسواق العالمية والين",
    "calendar": "التقويم (خيارات/نهاية فصل/عطل)",
}
# مكوّنات مدفوعة مخطَّطة: أوزان محجوزة تدخل الحساب تلقائياً متى قدّم مزوّدٌ درجتها (انظر ROADMAP.md)
PLANNED_WEIGHTS = {"gamma": 0.08, "fed_expect": 0.08, "sentiment": 0.04, "news_ai": 0.10, "order_flow": 0.06}
PLANNED_NAMES = {
    "gamma": "تمركز الخيارات (Gamma)", "fed_expect": "توقعات الفائدة (احتمالات الاجتماعات)",
    "sentiment": "المعنويات والتدفقات", "news_ai": "تفسير الأخبار بنموذج لغوي",
    "order_flow": "تدفق الأوامر (Order Flow)",
}
ALL_WEIGHTS = {**BASE_WEIGHTS, **PLANNED_WEIGHTS}


def name_of(key):
    return NAMES.get(key) or PLANNED_NAMES.get(key) or key
# مضاعفات تقريبية مستندة إلى دراسات تاريخية صغيرة العينة
TYPE_MULT = {"FOMC": 1.5, "NFP": 1.5, "CPI": 1.1, "OTHER": 1.2}
TYPE_AR = {"FOMC": "قرار الفائدة", "NFP": "تقرير الوظائف", "CPI": "تقرير التضخم", "OTHER": "حدث اقتصادي"}


# ───────────────────────── أدوات عامة ─────────────────────────

def clamp(x, lo=0.0, hi=10.0):
    return max(lo, min(hi, x))


def et_date(now):
    tz = ZoneInfo("America/New_York") if ZoneInfo else timezone.utc
    return now.astimezone(tz).date()


def pearson(x, y):
    n = len(x)
    if n < 5 or n != len(y):
        return None
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def corr_pair(a_closes, b_closes, n):
    """ارتباط عوائد يومية آخر n يوم مشترك. closes: [(date_iso, close)]."""
    da, db = dict(a_closes), dict(b_closes)
    common = sorted(set(da) & set(db))
    if len(common) < n + 1:
        return None
    cs = common[-(n + 1):]
    ra = [da[cs[i]] / da[cs[i - 1]] - 1 for i in range(1, len(cs)) if da[cs[i - 1]]]
    rb = [db[cs[i]] / db[cs[i - 1]] - 1 for i in range(1, len(cs)) if db[cs[i - 1]]]
    return pearson(ra, rb) if len(ra) == len(rb) else None


def compute_correlations(p):
    out = {}
    es = p.get("es")
    if not es or not es.get("closes"):
        return out
    for key in ("dxy", "gold", "oil", "y10"):
        o = p.get(key)
        if not o or not o.get("closes"):
            continue
        c20 = corr_pair(es["closes"], o["closes"], 20)
        c60 = corr_pair(es["closes"], o["closes"], 60)
        if c20 is not None:
            out[key] = {"c20": c20, "c60": c60}
    return out


# ───────────────────────── جلب البيانات ─────────────────────────

def fetch_prices(now):
    """أسعار يومية من Yahoo (غير رسمي). يعيد (البيانات، المشاكل)."""
    import yfinance as yf
    out, problems = {}, []
    et = ZoneInfo("America/New_York") if ZoneInfo else timezone.utc
    for key, sym in SYMBOLS.items():
        try:
            h = yf.Ticker(sym).history(period="3mo", interval="1d", auto_adjust=False).dropna(subset=["Close"])
            if len(h) < 6:
                raise ValueError("بيانات غير كافية")
            dates = [i.to_pydatetime().date().isoformat() for i in h.index]
            close = [float(x) for x in h["Close"]]
            scale = 0.1 if key in ("y10", "y5", "irx") and close[-1] > 20 else 1.0   # بعض الإصدارات تعرض العائد ×10
            close = [x * scale for x in close]
            last, prev = close[-1], close[-2]
            item = {
                "symbol": sym, "last": last,
                "chg1": (last / prev - 1) * 100, "chg3": (last / close[-4] - 1) * 100,
                "chg5": (last / close[-6] - 1) * 100, "diff1": last - prev,
                "bar_time": h.index[-1].to_pydatetime().astimezone(timezone.utc).isoformat(),
                "closes": list(zip(dates, close))[-70:],
            }
            if key == "es":
                if "High" in h and "Low" in h:
                    item["bars"] = [(dates[i], float(h["High"].iloc[i]), float(h["Low"].iloc[i]), close[i])
                                    for i in range(max(0, len(dates) - 10), len(dates))]
                if "Volume" in h:
                    vols = [float(v) for v in h["Volume"]]
                    last_bar_et = h.index[-1].to_pydatetime().astimezone(et)
                    now_et = now.astimezone(et)
                    if last_bar_et.date() == now_et.date() and now_et.hour < 17 and len(vols) > 22:
                        vols = vols[:-1]   # شمعة اليوم الجارية ناقصة الحجم
                    base = vols[-21:-1]
                    if len(base) >= 10 and sum(base) > 0:
                        item["vol_ratio"] = vols[-1] / (sum(base) / len(base))
            out[key] = item
        except Exception as e:  # noqa: BLE001
            problems.append(f"تعذّر جلب {key} ({sym}): {e}")
    return out, problems


def fetch_calendar():
    req = urllib.request.Request(CAL_URL, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_get(url, timeout, tries=2):
    """طلب GET مع إعادة محاولة قصيرة. يرفع آخر خطأ إن فشلت كل المحاولات."""
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                raw = r.read()
            return gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def _fred_api(sid, cosd, key):
    """الواجهة الرسمية (تحتاج مفتاحاً مجانياً FRED_API_KEY): أكثر ثباتاً من ملف CSV على خوادم GitHub."""
    url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={sid}"
           f"&api_key={key}&file_type=json&observation_start={cosd}")
    data = json.loads(_http_get(url, 25).decode("utf-8"))
    return [(o["date"], float(o["value"])) for o in data.get("observations", [])
            if o.get("value") not in (".", "", None)]


def _fred_csv_batch(sids, cosd):
    """طلب واحد لعدة سلاسل معاً (fredgraph يقبل id=A,B,C) بدل طلب لكل سلسلة."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={','.join(sids)}&cosd={cosd}"
    rows = list(csv.reader(io.StringIO(_http_get(url, 45).decode("utf-8"))))
    head, body = rows[0], rows[1:]
    out = {}
    for j, sid in enumerate(head[1:], start=1):
        vals = []
        for row in body:
            try:
                vals.append((row[0], float(row[j])))
            except (ValueError, IndexError):
                continue
        out[sid] = vals
    return out


def fetch_fred(now, days=45, series=None):
    """سلاسل FRED اليومية (متأخرة يوماً تقريباً). يعيد ({مفتاح: [(تاريخ، قيمة)]}، المشاكل).
    الأولوية: واجهة FRED الرسمية إن وُجد FRED_API_KEY، وإلا ملف CSV بطلب مجمَّع.
    قاطع دائرة: بعد 3 إخفاقات متتالية يتوقف الجلب بدل إضاعة دقائق في مهلات."""
    out, problems = {}, []
    cosd = (now - timedelta(days=days)).date().isoformat()
    items = dict(series or FRED_SERIES)
    key = os.environ.get("FRED_API_KEY", "").strip()
    if key:
        fails = 0
        for k, sid in items.items():
            if fails >= 3:
                problems.append(f"تعذّر جلب {sid} من FRED: أُوقف الجلب بعد إخفاقات متتالية")
                continue
            try:
                rows = _fred_api(sid, cosd, key)
                if not rows:
                    raise ValueError("بيانات غير كافية")
                out[k] = rows
                fails = 0
            except Exception as e:  # noqa: BLE001
                fails += 1
                problems.append(f"تعذّر جلب {sid} من FRED (API): {type(e).__name__}")
        return out, problems
    try:
        got = _fred_csv_batch(list(items.values()), cosd)
        for k, sid in items.items():
            if got.get(sid):
                out[k] = got[sid]
            else:
                problems.append(f"تعذّر جلب {sid} من FRED: لا بيانات")
    except Exception as e:  # noqa: BLE001
        problems.append(f"تعذّر جلب FRED (طلب مجمّع لـ {len(items)} سلسلة، بلا مفتاح API — FRED_API_KEY غير واصل للبرنامج): {type(e).__name__}: {e}")
    return out, problems


def fetch_cot():
    """مراكز المضاربين الكبار في عقد E-mini S&P 500 (تقرير CFTC الأسبوعي). صيغة الملف لم تُتحقق منها."""
    req = urllib.request.Request(COT_URL, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        text = r.read().decode("utf-8", errors="replace")
    for row in csv.reader(io.StringIO(text)):
        if row and "E-MINI S&P 500" in row[0].upper() and "CHICAGO MERCANTILE" in row[0].upper():
            oi, nl, ns = int(row[7]), int(row[8]), int(row[9])
            if oi <= 0 or nl < 0 or ns < 0 or nl > oi or ns > oi:
                raise ValueError("أرقام COT غير منطقية: الصيغة تغيّرت على الأرجح")
            return {"date": row[2].strip(), "net_pct": (nl - ns) / oi * 100, "oi": oi}
    raise ValueError("لم يُعثر على عقد E-mini S&P 500 في ملف COT")


def fetch_earnings(now):
    """مواعيد أرباح الشركات السبع والبنوك (Yahoo، غير رسمي). يعيد [(رمز، تاريخ)]."""
    import yfinance as yf
    out = []
    for t in MAG7 + BANKS:
        try:
            cal = yf.Ticker(t).calendar
            dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
            for d in dates or []:
                out.append((t, d.isoformat() if hasattr(d, "isoformat") else str(d)))
        except Exception:  # noqa: BLE001
            continue
    return out


# ───────────────────────── التقويم الاقتصادي ─────────────────────────

def classify(title):
    t = title.lower()
    if "federal funds rate" in t or "fomc statement" in t or "fomc press conference" in t:
        return "FOMC"
    if "non-farm" in t or "nonfarm" in t:
        return "NFP"
    if "cpi" in t:
        return "CPI"
    return "OTHER"


def parse_events(raw):
    events = []
    for e in raw or []:
        if e.get("country") != "USD":
            continue
        try:
            when = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
        except Exception:  # noqa: BLE001
            continue
        events.append({
            "title": e.get("title", ""), "impact": e.get("impact", ""), "time": when,
            "forecast": e.get("forecast", ""), "previous": e.get("previous", ""),
            "actual": e.get("actual", ""), "type": classify(e.get("title", "")),
        })
    return sorted(events, key=lambda x: x["time"])


def pick_event(events, now):
    """أقرب حدث عالي التأثير: قادم، أو صدر خلال آخر ساعتين."""
    cands = [e for e in events if e["impact"] == "High" and e["time"] >= now - timedelta(hours=2)]
    return cands[0] if cands else None


def holiday_soon(events, now):
    return any(e["impact"] == "Holiday" and abs((e["time"] - now).total_seconds()) <= 24 * 3600 for e in events)


def fed_speakers_soon(events, now):
    return [e for e in events if "fomc member" in e["title"].lower() or "fed chair" in e["title"].lower()
            if 0 <= (e["time"] - now).total_seconds() <= 24 * 3600]


# ───────────────────────── الدرجات (0-10) ─────────────────────────

def score_events(ev, now, events, earnings_names=()):
    if ev is None:
        medium = [e for e in events if e["impact"] == "Medium" and 0 <= (e["time"] - now).total_seconds() <= 24 * 3600]
        s, note, h = (3.5, "أحداث متوسطة التأثير خلال 24 ساعة", None) if medium else (1.5, "لا حدث كبير قريب", None)
    else:
        h = (ev["time"] - now).total_seconds() / 3600
        if h < 0:
            s, note = 8.0, "صدر قبل قليل: تقلب ما بعد الحدث"
        else:
            s = 9.0 if h <= 3 else 8.0 if h <= 8 else 6.5 if h <= 24 else 4.0 if h <= 72 else 1.5
            note = ev["title"]
    if earnings_names:
        s = min(10.0, s + 1.5)
        note += " + أرباح قريبة: " + "، ".join(earnings_names[:4])
    return s, note, h


def score_volatility(vix):
    if not vix:
        return None, "بيانات VIX غير متوفرة"
    v, c = vix["last"], vix["chg1"]
    s = 1.0 if v < 13 else 2.5 if v < 16 else 4.0 if v < 20 else 6.0 if v < 25 else 8.0 if v < 30 else 9.5
    if c >= 10:
        s += 1.5
    elif c >= 5:
        s += 0.8
    return clamp(s), f"VIX عند {v:.1f} ({c:+.1f}% يومياً)"


def score_vix_term(p):
    vix, v3 = p.get("vix"), p.get("vix3m")
    if not vix or not v3 or not v3["last"]:
        return None, "بيانات هيكل VIX غير متوفرة"
    r = vix["last"] / v3["last"]
    s = 1.5 if r < 0.85 else 3.0 if r < 0.95 else 5.0 if r < 1.0 else 7.5 if r < 1.05 else 9.5
    return s, f"VIX/VIX3M = {r:.2f}" + (" (مقلوب: ضغط قصير الأجل)" if r >= 1.0 else "")


def score_priced_in(es, ev, now):
    if not es:
        return None, "بيانات ES غير متوفرة"
    m = abs(es["chg3"])
    base = 8.0 if m >= 2 else 6.0 if m >= 1.2 else 4.0 if m >= 0.6 else 2.0
    near = ev is not None and (ev["time"] - now).total_seconds() <= 48 * 3600
    return (base if near else min(base, 3.0)), f"تحرك ES {es['chg3']:+.1f}% خلال 3 أيام" + ("" if near else " (لا حدث قريب)")


def score_geopolitics(p):
    """إشارات توتر من السوق: ذهب↑ نفط↑ VIX↑ ES↓ معاً."""
    sig, parts, avail = 0, [], 0
    checks = [("gold", lambda x: x["chg1"] >= 1.0, "الذهب"), ("oil", lambda x: x["chg1"] >= 2.0, "النفط"),
              ("vix", lambda x: x["chg1"] >= 8.0, "VIX"), ("es", lambda x: x["chg1"] <= -0.8, "ES")]
    for k, fn, nm in checks:
        if k in p:
            avail += 1
            if fn(p[k]):
                sig += 1
                parts.append(nm)
    if avail < 3:
        return None, "بيانات غير كافية لقياس التوتر"
    return clamp(1 + 2.25 * sig), ("إشارات: " + "، ".join(parts)) if parts else "لا إشارات توتر واضحة في السوق"


def score_conflict(p, corrs):
    es = p.get("es")
    if not es:
        return None, "بيانات ES غير متوفرة"
    s, notes = 2.0, []
    vix = p.get("vix")
    if vix and ((es["chg1"] > 0.3 and vix["chg1"] > 2) or (es["chg1"] < -0.3 and vix["chg1"] < -2)):
        s += 4.0
        notes.append("ES وVIX في الاتجاه نفسه")
    if (es["chg1"] > 0.3 and es["chg5"] < -1) or (es["chg1"] < -0.3 and es["chg5"] > 1):
        s += 2.0
        notes.append("الحركة اليومية عكس اتجاه 5 أيام")
    labels = {"dxy": "الدولار", "gold": "الذهب", "oil": "النفط", "y10": "العائد"}
    broken = [labels[k] for k, v in corrs.items() if v.get("c60") is not None and abs(v["c20"] - v["c60"]) >= 0.5]
    if broken:
        s += min(4.0, 1.5 * len(broken))
        notes.append("انكسر الارتباط المعتاد مع ES: " + "، ".join(broken))
    return clamp(s), ("، ".join(notes) if notes else "الإشارات والارتباطات متسقة نسبياً")


def score_liquidity(es, holiday):
    s, notes = None, []
    if es and "vol_ratio" in es:
        r = es["vol_ratio"]
        s = 7.0 if r < 0.6 else 5.0 if r < 0.8 else 2.0
        notes.append(f"حجم ES = {r:.0%} من متوسط 20 يوماً")
    if holiday:
        s = (s if s is not None else 2.0) + 3.0
        notes.append("عطلة رسمية قريبة")
    if s is None:
        return None, "بيانات الحجم غير متوفرة"
    return clamp(s), "، ".join(notes)


def score_rates(p, fred):
    y10 = p.get("y10")
    if not y10:
        return None, "بيانات العوائد غير متوفرة"
    bp = y10["diff1"] * 100
    s = 8.5 if abs(bp) >= 12 else 6.5 if abs(bp) >= 8 else 4.5 if abs(bp) >= 5 else 2.0
    notes = [f"عائد 10 سنوات {y10['last']:.2f}% ({bp:+.0f} نقطة أساس)"]
    mv = p.get("move")
    if mv:
        if mv["last"] >= 130:
            s += 2.0
            notes.append(f"MOVE مرتفع جداً ({mv['last']:.0f})")
        elif mv["last"] >= 110:
            s += 1.0
            notes.append(f"MOVE مرتفع ({mv['last']:.0f})")
    d2 = (fred or {}).get("dgs2")
    if d2 and len(d2) >= 2:
        d2bp = (d2[-1][1] - d2[-2][1]) * 100
        if abs(d2bp) >= 8:
            s += 1.0
            notes.append(f"عائد سنتين {d2bp:+.0f} نقطة أساس (توقعات الفائدة تتبدّل)")
    return clamp(s), "، ".join(notes)


def score_dollar(p):
    d = p.get("dxy")
    if not d:
        return None, "بيانات الدولار غير متوفرة"
    a1, a5 = abs(d["chg1"]), abs(d["chg5"])
    s = 8.0 if a1 >= 1.0 else 6.5 if a1 >= 0.7 else 4.0 if a1 >= 0.4 else 1.5
    if a5 >= 2.0:
        s += 1.5
    elif a5 >= 1.2:
        s += 0.7
    way = "صعود" if d["chg1"] > 0 else "هبوط"
    note = f"DXY {d['last']:.2f} ({d['chg1']:+.2f}% يومياً، {d['chg5']:+.2f}% خلال 5 أيام)"
    if a1 >= 0.7:
        note += f" — {way} حاد في الدولار"
    return clamp(s), note


def score_front_end(p, fred):
    """الطرف القصير: عائد سنتين (FRED، متأخر يوماً) وخمس سنوات وأذون 13 أسبوعاً (Yahoo) كمؤشر لتوقعات الفائدة."""
    moves, notes = [], []
    d2 = (fred or {}).get("dgs2")
    if d2 and len(d2) >= 2:
        bp = (d2[-1][1] - d2[-2][1]) * 100
        moves.append(abs(bp))
        notes.append(f"2Y {d2[-1][1]:.2f}% ({bp:+.0f}bp، متأخر يوماً)")
    y5 = p.get("y5")
    s5 = 0.0
    if y5:
        bp = y5["diff1"] * 100
        moves.append(abs(bp))
        notes.append(f"5Y {y5['last']:.2f}% ({bp:+.0f}bp)")
        cl = y5.get("closes") or []
        if len(cl) >= 6:
            b5 = (cl[-1][1] - cl[-6][1]) * 100
            if abs(b5) >= 15:
                s5 = 1.5
                notes.append(f"5Y {b5:+.0f}bp خلال 5 أيام (إعادة تسعير للفائدة)")
    irx = p.get("irx")
    s_irx = 0.0
    if irx:
        bp = irx["diff1"] * 100
        notes.append(f"13 أسبوع {irx['last']:.2f}% ({bp:+.0f}bp)")
        if abs(bp) >= 5:
            s_irx = 1.0
    if not moves and not irx:
        return None, "بيانات الطرف القصير غير متوفرة"
    m = max(moves) if moves else 0.0
    s = (8.0 if m >= 10 else 6.0 if m >= 6 else 3.5 if m >= 3 else 1.5) + s5 + s_irx
    lead = (y5 or {}).get("diff1")
    if lead is None and d2 and len(d2) >= 2:
        lead = d2[-1][1] - d2[-2][1]
    if lead is not None and m >= 6:
        notes.append("ارتفاع: تسعير تشدد أكثر" if lead > 0 else "انخفاض: تسعير تيسير أو هروب للأمان")
    return clamp(s), "، ".join(notes)


def score_credit(p, fred):
    s, notes = None, []
    oas = (fred or {}).get("hy_oas")
    if oas:
        lvl = oas[-1][1]
        s = 1.5 if lvl < 3 else 3.0 if lvl < 3.75 else 5.0 if lvl < 4.5 else 7.0 if lvl < 5.5 else 9.0
        notes.append(f"فروق عوائد السندات عالية المخاطر {lvl:.2f}%")
        if len(oas) >= 6 and lvl - oas[-6][1] >= 0.3:
            s += 1.5
            notes.append("اتسعت بأكثر من 0.3 نقطة خلال 5 أيام")
    elif p.get("hyg") and p.get("ief"):
        rel5 = p["hyg"]["chg5"] - p["ief"]["chg5"]
        s = 7.0 if rel5 <= -1.5 else 5.0 if rel5 <= -0.8 else 2.5
        notes.append(f"سندات عالية المخاطر مقابل الخزانة (5 أيام): {rel5:+.1f}%")
    xlf, spy, kre = p.get("xlf"), p.get("spy"), p.get("kre")
    if xlf and spy and xlf["chg5"] - spy["chg5"] <= -2:
        s = (s if s is not None else 2.5) + 1.5
        notes.append("القطاع المالي متأخر عن السوق")
    if kre and kre["chg5"] <= -5:
        s = (s if s is not None else 2.5) + 1.5
        notes.append("البنوك الإقليمية هبطت أكثر من 5% خلال 5 أيام")
    if s is None:
        return None, "بيانات الائتمان غير متوفرة"
    return clamp(s), "، ".join(notes)


def mag7_changes(p):
    return {t: p["m_" + t]["chg1"] for t in MAG7 if "m_" + t in p}


def score_breadth(p):
    s, notes, evaluated = 2.0, [], 0
    es, nq, spy, rsp = p.get("es"), p.get("nq"), p.get("spy"), p.get("rsp")
    if es and nq:
        evaluated += 1
        if abs(nq["chg1"] - es["chg1"]) >= 0.8:
            s += 2.5
            notes.append(f"تباعد ناسداك عن ES ({nq['chg1']:+.1f}% مقابل {es['chg1']:+.1f}%)")
    if spy and rsp:
        evaluated += 1
        if spy["chg5"] - rsp["chg5"] >= 1.5:
            s += 2.5
            notes.append("الصعود ضيق: المؤشر يتفوق كثيراً على المتساوي الوزن")
    mags = mag7_changes(p)
    if len(mags) >= 5 and spy:
        evaluated += 1
        avg = sum(mags.values()) / len(mags)
        if abs(avg - spy["chg1"]) >= 1.0:
            s += 2.5
            notes.append(f"السبعة الكبار {avg:+.1f}% مقابل المؤشر {spy['chg1']:+.1f}%")
    if evaluated == 0:
        return None, "بيانات الاتساع غير متوفرة"
    return clamp(s), "، ".join(notes) if notes else "قيادة السوق متوازنة نسبياً"


def score_global(p):
    names = {"nikkei": "نيكاي", "dax": "DAX", "hsi": "هانغ سنغ"}
    if not any(k in p for k in list(names) + ["jpy"]):
        return None, "بيانات الأسواق العالمية غير متوفرة"
    s, notes = 1.5, []
    jpy = p.get("jpy")
    if jpy and jpy["chg1"] <= -1.2:
        s += 4.0
        notes.append(f"الين يقوى بحدة (دولار/ين {jpy['chg1']:+.1f}%): خطر تفكك تجارة الفائدة")
    for k, nm in names.items():
        if p.get(k) and p[k]["chg1"] <= -1.5:
            s += 2.0
            notes.append(f"{nm} {p[k]['chg1']:+.1f}%")
    return clamp(s), "، ".join(notes) if notes else "الأسواق العالمية هادئة نسبياً"


def third_friday(y, m):
    first = date(y, m, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 14)


def score_calendar(now):
    d = et_date(now)
    s, notes = 1.5, []
    tf = third_friday(d.year, d.month)
    quad = tf.month in (3, 6, 9, 12)
    days = (tf - d).days
    if days == 0:
        s = max(s, 7.0 if quad else 5.5)
        notes.append("اليوم انتهاء " + ("خيارات فصلية (Quad Witching)" if quad else "الخيارات الشهرية"))
    elif days == 1:
        s = max(s, 6.0 if quad else 4.0)
        notes.append("غداً انتهاء " + ("خيارات فصلية (Quad Witching)" if quad else "الخيارات الشهرية"))
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    if (nxt - timedelta(days=1) - d).days <= 1:
        s = max(s, 3.5 + (1.5 if d.month in (3, 6, 9, 12) else 0.0))
        notes.append("نهاية " + ("الفصل" if d.month in (3, 6, 9, 12) else "الشهر") + ": إعادة توازن الصناديق")
    for k, label in ((0, "اليوم"), (1, "غداً")):
        iso = (d + timedelta(days=k)).isoformat()
        if iso in HOLIDAYS:
            s = max(s, 4.0)
            notes.append(f"{label} عطلة بورصة")
        if iso in EARLY_CLOSE:
            s = max(s, 4.0)
            notes.append(f"{label} إغلاق مبكر")
    return s, "، ".join(notes) if notes else "لا تأثيرات تقويمية خاصة"


# ───────────────────────── الأوزان والمقياس ─────────────────────────

def adapt_weights(available, ev, now, vix, comps, earn_soon):
    w = {k: ALL_WEIGHTS[k] for k in available}
    notes = []
    tm = TYPE_MULT[ev["type"]] if ev else 1.3
    if "events" in w:
        h = (ev["time"] - now).total_seconds() / 3600 if ev else None
        if h is not None and h <= 24:
            w["events"] *= tm
            notes.append(f"حدث كبير قريب ({TYPE_AR[ev['type']]}): رُفع وزن الأحداث")
        elif h is not None and h <= 72:
            w["events"] *= 1.1
            notes.append("حدث كبير خلال أيام: رفع طفيف لوزن الأحداث")
        else:
            w["events"] *= 0.5
            notes.append("لا حدث قريب: خُفّض وزن الأحداث")
        if earn_soon:
            w["events"] *= 1.2
            notes.append("أرباح شركات كبرى قريبة: رُفع وزن الأحداث")
    if vix and "volatility" in w:
        v = vix["last"]
        if v >= 30:
            w["volatility"] *= 1.4
            notes.append("VIX مرتفع جداً: رُفع وزن التقلب")
        elif v >= 22:
            w["volatility"] *= 1.2
            notes.append("VIX مرتفع: رُفع وزن التقلب")
        elif v <= 14:
            w["volatility"] *= 0.8
            notes.append("VIX منخفض: خُفّض وزن التقلب")
    geo = max([x for x in (comps.get("geopolitics", (None,))[0], comps.get("geo_news", (None,))[0]) if x is not None] or [None],
              key=lambda x: -1 if x is None else x)
    if geo is not None and geo >= 7 and "geopolitics" in w:
        w["geopolitics"] *= 1.5
        if "volatility" in w:
            w["volatility"] *= 1.1
        notes.append("إشارات توتر: رُفع وزن الجيوسياسة والتقلب")
    for key, thr, mult, msg in (("calendar", 6, 1.5, "يوم انتهاء خيارات فصلية: رُفع وزن التقويم"),
                                ("credit", 7, 1.3, "ضغط ائتماني: رُفع وزن الائتمان"),
                                ("global_mkts", 7, 1.3, "اضطراب عالمي: رُفع وزن الأسواق العالمية")):
        sc = comps.get(key, (None,))[0]
        if sc is not None and sc >= thr and key in w:
            w[key] *= mult
            notes.append(msg)
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}, notes


def level(score):
    if score <= 3:
        return "منخفضة", "🟢", "ظروف طبيعية."
    if score <= 6:
        return "متوسطة", "🟡", "قلّل الحجم قليلاً."
    if score <= 8:
        return "عالية", "🔴", "حجم أصغر ووقف أوسع، أو انتظر ما بعد الحدث."
    return "قصوى", "⛔", "الأفضل غالباً عدم الدخول."


def fmt_hours(h):
    if h is None:
        return ""
    if h < 0:
        return "صدر قبل قليل"
    if h < 1:
        return f"بعد {int(h * 60)} دقيقة"
    if h < 24:
        return f"بعد {h:.0f} ساعة"
    return f"بعد {h / 24:.0f} يوم"


def earnings_within(earnings, now, days=2):
    d0 = et_date(now)
    out = []
    for t, ds in earnings or []:
        try:
            d = date.fromisoformat(str(ds)[:10])
        except ValueError:
            continue
        if 0 <= (d - d0).days <= days and t not in out:
            out.append(t)
    return out


# ───────────────────────── الكتل المعلوماتية (لا تدخل الدرجة) ─────────────────────────

def build_info(p, fred, cot, earn_names, corrs, events, now):
    info = {}
    y10 = p.get("y10")
    if y10:
        line = f"10Y {y10['last']:.2f}% ({y10['diff1'] * 100:+.0f}bp)"
        t = (fred or {}).get("t10y2y")
        if t:
            line += f" | منحنى 2-10: {t[-1][1]:+.2f}"
        if p.get("move"):
            line += f" | MOVE {p['move']['last']:.0f}"
        info["rates"] = line
    dx = p.get("dxy")
    if dx:
        info["dollar"] = f"الدولار DXY {dx['last']:.2f} ({dx['chg1']:+.2f}% | 5 أيام {dx['chg5']:+.2f}%)"
    fe = []
    d2 = (fred or {}).get("dgs2")
    if d2:
        fe.append(f"2Y {d2[-1][1]:.2f}%")
    if p.get("y5"):
        fe.append(f"5Y {p['y5']['last']:.2f}% ({p['y5']['diff1'] * 100:+.0f}bp)")
    if p.get("irx"):
        fe.append(f"13 أسبوع {p['irx']['last']:.2f}%")
    if fe:
        info["front"] = "الطرف القصير: " + " | ".join(fe)
    es, nq = p.get("es"), p.get("nq")
    if es and nq:
        info["tech"] = f"ES {es['chg1']:+.2f}% | NQ {nq['chg1']:+.2f}%"
    mags = mag7_changes(p)
    if len(mags) >= 3:
        hi, lo = max(mags, key=mags.get), min(mags, key=mags.get)
        info["mag7"] = (f"السبعة الكبار: متوسط {sum(mags.values()) / len(mags):+.2f}% | "
                        f"الأقوى {hi} {mags[hi]:+.1f}% | الأضعف {lo} {mags[lo]:+.1f}%")
    bks = {t: p["b_" + t]["chg1"] for t in BANKS if "b_" + t in p}
    if bks:
        extra = "".join(f" | {n} {p[k]['chg1']:+.1f}%" for k, n in (("xlf", "XLF"), ("kre", "KRE")) if k in p)
        info["banks"] = f"البنوك الكبرى: متوسط {sum(bks.values()) / len(bks):+.2f}%{extra}"
    if corrs:
        lab = {"dxy": "الدولار", "gold": "الذهب", "oil": "النفط", "y10": "العائد"}
        parts = [f"{lab[k]} {v['c20']:+.2f}" + (f" (60ي {v['c60']:+.2f})" if v.get("c60") is not None else "")
                 for k, v in corrs.items()]
        info["corr"] = "ارتباط 20 يوماً مع ES: " + " | ".join(parts)
    if cot:
        info["cot"] = f"تمركز المضاربين الكبار في ES: صافي {cot['net_pct']:+.1f}% من الفائدة المفتوحة (تقرير {cot['date']})"
    if earn_names:
        info["earnings"] = "أرباح خلال 48 ساعة: " + "، ".join(earn_names)
    fs = fed_speakers_soon(events, now)
    if fs:
        info["fed"] = f"خطابات مسؤولي الفيدرالي خلال 24 ساعة: {len(fs)}"
    if es:
        info["data_age"] = f"آخر شمعة يومية لـ ES: {es['bar_time'][:10]} (بيانات Yahoo المجانية قد تتأخر)"
    return info


# ───────────────────────── التقرير ─────────────────────────

def build_report(prices, events, now, problems=None, extras=None):
    problems = list(problems or [])
    extras = extras or {}
    fred, cot, news = extras.get("fred") or {}, extras.get("cot"), extras.get("news") or {}
    earn_names = earnings_within(extras.get("earnings"), now)
    ev = pick_event(events, now) if events else None
    corrs = compute_correlations(prices)

    comps = {}
    if events:
        s, note, h = score_events(ev, now, events, earn_names)
        comps["events"] = (s, note + (f" — {fmt_hours(h)}" if h is not None and ev else ""))
    else:
        h = None
        comps["events"] = (None, "التقويم الاقتصادي غير متوفر")
    comps["volatility"] = score_volatility(prices.get("vix"))
    comps["vix_term"] = score_vix_term(prices)
    comps["priced_in"] = score_priced_in(prices.get("es"), ev, now)
    comps["geopolitics"] = score_geopolitics(prices)
    geo_items = extras.get("geo")
    gs, gnote, geo_detail = geo.score_geo_news(geo_items, comps["geopolitics"][0], now)
    comps["geo_news"] = (gs, gnote)
    macro_view = macro.analyze(extras.get("macro"), prices, now)
    comps["fed_system"] = macro.score_fed_system(macro_view)
    comps["net_liq"] = macro.score_net_liquidity(extras.get("macro"))
    comps["conflict"] = score_conflict(prices, corrs)
    comps["liquidity"] = score_liquidity(prices.get("es"), holiday_soon(events, now) if events else False)
    comps["rates"] = score_rates(prices, fred)
    comps["front_end"] = score_front_end(prices, fred)
    comps["dollar"] = score_dollar(prices)
    comps["credit"] = score_credit(prices, fred)
    comps["breadth"] = score_breadth(prices)
    comps["global_mkts"] = score_global(prices)
    comps["calendar"] = score_calendar(now)

    # مكوّنات مدفوعة (إن وُجد مزوّد فعّال): {مفتاح: (درجة 0-10، ملاحظة)}
    for k, val in (extras.get("premium") or {}).items():
        try:
            s, note = val
            if k in PLANNED_WEIGHTS and s is not None:
                comps[k] = (clamp(float(s)), str(note))
        except (TypeError, ValueError):
            problems.append(f"مخرجات مزوّد مدفوع غير صالحة: {k}")

    available = [k for k in comps if comps[k][0] is not None]
    missing = [NAMES[k] for k in BASE_WEIGHTS if k not in available]
    if len(available) < 3 or "volatility" not in available and "events" not in available:
        return {"generated_at": now.isoformat(), "error": "بيانات غير كافية لحساب مقياس موثوق",
                "problems": problems, "missing": missing}

    weights, wnotes = adapt_weights(available, ev, now, prices.get("vix"), comps, bool(earn_names))
    score = round(sum(comps[k][0] * weights[k] for k in available))
    lv, emoji, advice = level(score)

    contrib = sorted(((comps[k][0] * weights[k], k) for k in available if comps[k][0] >= 5), reverse=True)
    reasons = []
    for _, k in contrib[:2]:
        if k == "events" and ev:
            reasons.append(f"{TYPE_AR[ev['type']]} {fmt_hours(h)}")
        elif k == "events":
            reasons.append("أرباح شركات كبرى قريبة")
        elif k == "volatility":
            reasons.append(comps[k][1].split(" (")[0])
        elif k == "vix_term":
            reasons.append("هيكل VIX مقلوب")
        elif k == "priced_in":
            reasons.append("تحرك سعري كبير قبل الحدث")
        elif k == "geopolitics":
            reasons.append("إشارات توتر في الأسواق")
        elif k == "geo_news":
            reasons.append("أخبار جيوسياسية بارزة")
        elif k == "conflict":
            reasons.append("تعارض إشارات الأسواق")
        elif k == "liquidity":
            reasons.append("سيولة ضعيفة")
        elif k == "rates":
            reasons.append("تحرك حاد في العوائد")
        elif k == "fed_system":
            reasons.append("فجوة بين البيانات وتسعير الفائدة" if macro_view and macro_view.get("gap") and macro_view["gap"]["size"] != "صغيرة" else "اجتماع الفيدرالي والمنظومة الكلية")
        elif k == "net_liq":
            reasons.append("تجفيف في السيولة الصافية")
        elif k == "front_end":
            reasons.append("تحرك في العوائد القصيرة (توقعات الفائدة)")
        elif k == "dollar":
            reasons.append("حركة حادة في الدولار")
        elif k == "credit":
            reasons.append("ضغط في الائتمان/البنوك")
        elif k == "breadth":
            reasons.append("قيادة السوق ضيقة أو متباعدة")
        elif k == "global_mkts":
            reasons.append("اضطراب في الأسواق العالمية/الين")
        elif k == "calendar":
            reasons.append(comps[k][1].split("،")[0])
        else:
            reasons.append(name_of(k))
    main_reason = " + ".join(reasons) if reasons else "ظروف هادئة نسبياً"
    # حين يكون الخطر العام منخفضاً، المكوّنات المرتفعة منفردة هي «ما يُتابَع» وليست سبب الخطر
    reason_label = "أبرز ما يُتابَع (الخطر العام منخفض)" if (score <= 3 and reasons) else "السبب"
    if missing:
        problems.append("مكوّنات استُبعدت لنقص البيانات: " + "، ".join(missing))

    return {
        "generated_at": now.isoformat(),
        "risk": {
            "score": score, "level": lv, "emoji": emoji, "advice": advice, "main_reason": main_reason, "reason_label": reason_label,
            "weights_note": wnotes or ["الأوزان الافتراضية"],
            "components": [{"key": k, "name": name_of(k), "score": round(comps[k][0], 1),
                            "weight": round(weights[k], 3), "note": comps[k][1]} for k in available],
        },
        "planned_inactive": [name_of(k) for k in PLANNED_WEIGHTS if k not in available],
        "notification": f"المخاطرة: {score}/10 {emoji} | {reason_label}: {main_reason}",
        "next_event": ({"title": ev["title"], "type": ev["type"], "time_utc": ev["time"].isoformat(),
                        "forecast": ev["forecast"], "previous": ev["previous"], "actual": ev["actual"]}
                       if ev else None),
        "info": build_info(prices, fred, cot, earn_names, corrs, events, now),
        "news": news,
        "geo": geo_detail,
        "macro": macro_view,
        "correlations": {k: {"c20": round(v["c20"], 2), "c60": None if v["c60"] is None else round(v["c60"], 2)}
                         for k, v in corrs.items()},
        "data": {k: {"last": round(v["last"], 2), "chg1_pct": round(v["chg1"], 2), "bar_time": v["bar_time"]}
                 for k, v in prices.items()},
        "problems": problems,
        "disclaimer": "إشارات إحصائية لأغراض إثبات الفكرة، لا توصية استثمارية. بيانات مجانية غير رسمية وقد تتأخر.",
    }


# ───────────────────────── بيانات تجريبية ─────────────────────────

def demo_inputs(now):
    iso = lambda dt_: dt_.isoformat()
    bar = iso(now - timedelta(hours=3))
    mk = lambda last, c1, c3=0.0, c5=0.0, **kw: {"last": last, "chg1": c1, "chg3": c3, "chg5": c5,
                                                  "diff1": kw.pop("diff1", 0.0), "bar_time": bar, **kw}
    prices = {
        "es": mk(5900.0, -0.9, -2.3, -1.5, diff1=-53, vol_ratio=0.7), "nq": mk(20500.0, -1.9, -3.0, -2.0),
        "vix": mk(26.4, 12.0, 25.0, 30.0, diff1=2.8), "vix3m": mk(24.0, 3.0),
        "oil": mk(74.0, 2.6, 4.0, 6.0, diff1=1.9), "gold": mk(2700.0, 1.4, 2.0, 3.0, diff1=37),
        "dxy": mk(104.2, 0.9, 1.5, 2.2, diff1=0.9), "y5": mk(4.1, 1.5, 3.0, 5.0, diff1=0.09), "irx": mk(4.3, 0.1, 0.1, 0.1, diff1=0.01), "y10": mk(4.3, 1.0, 2.0, 3.0, diff1=0.11),
        "jpy": mk(146.0, -1.4), "nikkei": mk(38000.0, -2.1), "dax": mk(18500.0, -1.0), "hsi": mk(17000.0, -0.8),
        "spy": mk(590.0, -0.9, -2.3, -1.5), "rsp": mk(170.0, -0.5, -1.0, -0.2),
        "hyg": mk(77.0, -0.4, -1.0, -1.6), "ief": mk(95.0, 0.2, 0.5, 0.8),
        "xlf": mk(45.0, -1.0, -2.0, -3.5), "kre": mk(55.0, -2.0, -4.0, -6.0),
    }
    for t, c in zip(MAG7, (-1.5, -1.0, -3.2, -1.8, -1.1, -2.0, -2.5)):
        prices["m_" + t] = mk(100.0, c)
    for t, c in zip(BANKS, (-0.8, -1.2, -1.1, -0.9, -1.0, -1.3)):
        prices["b_" + t] = mk(50.0, c)
    raw = [
        {"title": "Federal Funds Rate", "country": "USD", "impact": "High",
         "date": iso(now + timedelta(hours=2)), "forecast": "4.50%", "previous": "4.75%"},
        {"title": "Unemployment Claims", "country": "USD", "impact": "Medium",
         "date": iso(now + timedelta(hours=20)), "forecast": "220K", "previous": "219K"},
    ]
    extras = {"fred": {"t10y2y": [("2026-10-01", 0.2), ("2026-10-02", 0.25)],
                       "hy_oas": [("2026-09-24", 3.4), ("2026-09-25", 3.5), ("2026-09-26", 3.5),
                                  ("2026-09-29", 3.7), ("2026-09-30", 3.8), ("2026-10-01", 3.9)]},
              "cot": {"date": "2026-09-29", "net_pct": 6.2, "oi": 2000000}, "earnings": [("NVDA", now.date().isoformat())]}
    return prices, parse_events(raw), extras


# ───────────────────────── التشغيل ─────────────────────────

def main():
    ap = argparse.ArgumentParser(description="مِرصاد — جامع البيانات")
    ap.add_argument("--demo", action="store_true", help="بيانات تجريبية (دون إنترنت)")
    ap.add_argument("--out", default="report_latest.json", help="ملف الإخراج")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)

    if args.demo:
        prices, events, extras = demo_inputs(now)
        problems = ["⚠ وضع تجريبي: الأرقام وهمية لاختبار المنطق فقط"]
    else:
        prices, problems = fetch_prices(now)
        extras = {}
        try:
            events = parse_events(fetch_calendar())
        except Exception as e:  # noqa: BLE001
            events = []
            problems.append(f"تعذّر جلب التقويم الاقتصادي: {e}")
        try:
            extras["fred"], fp = fetch_fred(now)
            problems += fp
        except Exception as e:  # noqa: BLE001
            problems.append(f"تعذّر FRED: {e}")
        for name, fn in (("cot", fetch_cot), ("earnings", lambda: fetch_earnings(now))):
            try:
                extras[name] = fn()
            except Exception as e:  # noqa: BLE001
                problems.append(f"تعذّر جلب {name}: {e}")

    report = build_report(prices, events, now, problems, extras)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    if "error" in report:
        print("✖", report["error"])
        for p in report["problems"]:
            print(" -", p)
        sys.exit(1)
    print(report["notification"])
    print(f"مخاطرة {report['risk']['level']} — {report['risk']['advice']}")
    for c in report["risk"]["components"]:
        print(f"  {c['name']}: {c['score']}/10 (وزن {c['weight']:.0%}) — {c['note']}")
    for line in report["info"].values():
        print("  ·", line)
    for p in report["problems"]:
        print("⚠", p)
    print(f"تم حفظ التقرير في {args.out}")


if __name__ == "__main__":
    main()
