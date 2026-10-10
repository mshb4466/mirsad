#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — تحويل التقرير الحقيقي إلى بيانات الواجهة (docs/data.json) لتعرضها صفحة GitHub Pages.
لا حسابات جديدة هنا: فقط إعادة تشكيل ما حسبه collector وmacro وauction وgeo.
"""
import json
import events_ctx
import impact
import os
from datetime import datetime, timedelta

DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
LOC_AR = {"above_value": "أعلى قيمة الأمس", "below_value": "أسفل قيمة الأمس", "inside_value": "داخل قيمة الأمس"}


def _baghdad(now):
    t = now + timedelta(hours=3)
    return t.strftime("%Y-%m-%d %H:%M")


def _stance(score):
    if score is None:
        return "neutral", "لا ميل واضح"
    if score >= 0.25:
        return "buy", "ميل سياقي صاعد (تجريبي)"
    if score <= -0.25:
        return "sell", "ميل سياقي هابط (تجريبي)"
    return "neutral", "ميل سياقي متوازن (تجريبي)"


def _auction(report):
    a = report.get("auction")
    if not a:
        return None
    p, g = a["prior"], a["gap"]
    o = a.get("overnight")
    on = ({"high": o["high"], "low": o["low"], "last": o["last"], "inv": o["inventory"]} if o
          else {"high": a["prior"]["high"], "low": a["prior"]["low"], "last": g["points"] + p["close"], "inv": 0.5})
    loc = a["location"]
    chips = [["t-ok" if loc == "above_value" else "t-crit" if loc == "below_value" else "t-neutral",
              ("▲ " if loc == "above_value" else "▼ " if loc == "below_value" else "◆ ") + LOC_AR[loc]],
             ["t-hi" if abs(g["pct"]) >= 0.3 else "t-neutral",
              f"فجوة {'صاعدة' if g['points'] >= 0 else 'هابطة'} {abs(g['points']):.1f} نقطة ({g['pct']:+.2f}%)"]]
    if o:
        chips.append(["t-hi" if o["inventory"] >= 0.7 or o["inventory"] <= 0.3 else "t-neutral", o["inventory_label"]])
    vix = (report.get("data") or {}).get("vix", {}).get("last")
    if vix:
        chips.append(["t-neutral", f"VIX {vix:.1f}"])
    exp = ""
    if a.get("expected"):
        e = a["expected"]
        exp = (f"المدى المتوقع (من VIX): نحو {e['sigma_pts']:.0f} نقطة بانحراف معياري واحد، "
               f"ومدى الجلسة نحو {e['range_pts']:.0f} نقطة (غالباً أقل فعلياً)")
    t = report.get("tilt")
    tilt = {"score": 0.0, "word": "لا ميل", "arrow": "◆", "why": "بيانات غير كافية"}
    if t:
        import auction as au
        lab, arrow = au.tilt_label(t["score"])
        top = sorted(t["parts"].items(), key=lambda kv: abs(kv[1]) * au.TILT_W[kv[0]], reverse=True)[:3]
        why = "، ".join(f"{au.TILT_NAMES[k]} {'▲' if v > 0.15 else '▼' if v < -0.15 else '◆'}" for k, v in top)
        tilt = {"score": t["score"], "word": lab, "arrow": arrow, "why": why}
    rd = lambda d: {k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items()}
    return {"prior": rd({k: p[k] for k in ("high", "low", "close", "val", "poc", "vah")}),
            "on": rd(on), "loc": loc, "chips": chips, "exp": exp, "play": a.get("playbook", []), "tilt": tilt}


def _macro(report):
    m = report.get("macro")
    if not m:
        return None
    gap = m.get("gap")
    nl = m.get("net_liquidity")
    meet = m.get("meeting")
    return {
        "label": m["label"], "arrow": m["arrow"], "lean": m["lean"], "conf": f"ثقة {m['confidence']}",
        "pillars": [{"name": x["name"], "arrow": x["arrow"], "note": x["note"]} for x in m["pillars"]],
        "liq": (f"السيولة الصافية ≈{nl['net_bn']:,.0f} مليار$ ({nl['chg_pct']:+.1f}% خلال 4 أسابيع)" if nl else ""),
        "liqView": impact.liquidity_view(nl),
        "gapTitle": ("فجوة تسعير " + gap["size"]) if gap else "تسعير السوق",
        "gap": gap["direction"] if gap else "تعذّر تقدير ما يسعّره السوق",
        "meet": (f"الاجتماع القادم: {meet['date']} (بعد {meet['days']} يوماً)" if meet else ""),
    }


def _move(series, t0, unit="pct"):
    """تغير الأصل من لحظة الحدث حتى آخر سعر متاح (% أو نقاط أساس). None إن لم تتوفر بيانات."""
    if not series:
        return None
    before = [p for t, p in series if t <= t0]
    after = [p for t, p in series if t > t0]
    if not before or not after or not before[-1]:
        return None
    if unit == "bp":
        return round((series[-1][1] - before[-1]) * 100, 1)
    return round((series[-1][1] / before[-1] - 1) * 100, 2)


def _react(series, t0):
    series = series or {}
    return {"es": _move(series.get("es"), t0), "y10": _move(series.get("y10"), t0, "bp"),
            "dxy": _move(series.get("dxy"), t0), "oil": _move(series.get("oil"), t0)}


EFF = {"bear": "ضغط على ES", "bull": "دعم لـ ES", "neu": "أثر محدود"}


def _verdict(hit, scs, basis=""):
    sc = next((s for s in scs if s["k"] == hit), None)
    return None if not sc else {"k": hit, "label": sc["label"], "es": sc.get("es", "neu"), "effect": EFF.get(sc.get("es", "neu"), ""),
                                "text": sc["text"], "basis": basis}


def _agree(es_chg, vd):
    """هل تحرك ES فعلاً في اتجاه الأثر المتوقع؟"""
    if vd is None or es_chg is None:
        return ""
    if abs(es_chg) < 0.05:
        return "flat"
    if vd["es"] == "neu":
        return ""
    return "match" if (vd["es"] == "bull") == (es_chg > 0) else "mismatch"


def _day_label(t, now, past=True):
    """تسمية اليوم حسب تاريخ بغداد (وليس نافذة 24 ساعة المتدحرجة)."""
    d, n = (t + timedelta(hours=3)).date(), (now + timedelta(hours=3)).date()
    if d == n:
        return "اليوم"
    return "أمس" if d < n else "غداً"


def _past_events(events, now, report, series, fed_heads=None):
    """أحداث صدرت خلال آخر 24 ساعة، مفصولة حسب يوم بغداد (اليوم ثم أمس)، مع نتيجتها وأثرها على ES والعوائد والدولار."""
    ml = (report.get("macro") or {}).get("label", "")
    ctx = events_ctx.build_ctx(report)
    out = []
    for e in sorted(events or [], key=lambda x: x["time"], reverse=True):
        if events_ctx.relevant(e) and now - timedelta(hours=24) <= e["time"] < now:
            d = events_ctx.describe(e, (e["time"] + timedelta(hours=3)).strftime("%H:%M"), ml, ctx)
            d["released"] = True
            d["day"] = _day_label(e["time"], now)
            d["has_number"] = bool(e.get("actual"))
            d["react"] = _react(series, e["time"])
            d["reaction"] = d["react"]["es"]
            d["_t"] = e["time"]
            out.append(d)
    result = []
    for day in ("اليوم", "أمس"):
        part = [o for o in out if o["day"] == day]
        for x in events_ctx.group(part):
            kind = x.get("kind")
            times = [o["_t"] for o in part if o.get("kind") == kind] if kind else [o["_t"] for o in part if o["title"] == x["title"]]
            t_last = min(times) if times else None
            x["day"] = day
            x["react"] = _react(series, t_last) if (x.get("items") and t_last) else x.get("react")
            x["reaction"] = (x.get("react") or {}).get("es")
            if kind == "speech":
                k, basis = events_ctx.speech_outcome(fed_heads, x.get("react"))
                x["verdict"] = _verdict(k, x.get("scenarios") or [], basis)
                x["heads"] = list(fed_heads or [])[:3]
                for it in x.get("items") or []:
                    it["verdict"] = None
            else:
                x["verdict"] = _verdict(x.get("hit"), x.get("scenarios") or [])
                for it in x.get("items") or []:
                    it["verdict"] = _verdict(it.get("hit"), x.get("scenarios") or [])
            x["agree"] = _agree(x["reaction"], x["verdict"])
            for it in x.get("items") or []:
                it["kind"] = kind
            x.pop("_t", None)
            result.append(x)
    return result


def _safety(sf):
    if not sf:
        return None
    return {"state": sf["state"], "label": sf["label"], "coverage": sf.get("coverage"), "checked_at": sf.get("checked_at"),
            "issues": [{"sev": i["sev"], "sev_ar": i["sev_ar"], "msg": i["msg"], "code": i["code"]} for i in sf.get("issues", [])]}


DAYS_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def _week(events, now, report):
    """أهم أحداث الأسبوع (عالية التأثير + محاضر الفدرالي) مرتبة حسب يوم بغداد، ما صدر منها وما سيصدر.
    مصدرها تقويم الأسبوع الحالي فقط؛ لا تُعرض أحداث بلا بيانات."""
    ml, ctx = (report.get("macro") or {}).get("label", ""), events_ctx.build_ctx(report)
    today = (now + timedelta(hours=3)).date()
    days = {}
    for e in sorted(events or [], key=lambda x: x["time"]):
        title = (e.get("title") or "").lower()
        if not (e.get("impact") == "High" or "minutes" in title):
            continue
        bt = e["time"] + timedelta(hours=3)
        d = events_ctx.describe(e, bt.strftime("%H:%M"), ml, ctx)
        vd = _verdict(d.get("hit"), d.get("scenarios") or []) if e.get("actual") else None
        item = {"time": bt.strftime("%H:%M"), "name": d.get("name") or e.get("title", ""), "title": e.get("title", ""),
                "released": e["time"] < now, "forecast": e.get("forecast", ""), "previous": e.get("previous", ""),
                "actual": e.get("actual", ""), "surprise": d.get("surprise", ""), "note": e.get("actual_note", ""),
                "tone": (vd or {}).get("es", "") , "effect": (vd or {}).get("effect", ""), "kind": d.get("kind", "")}
        days.setdefault(bt.date(), []).append(item)
    out = []
    for dt in sorted(days):
        rel = "اليوم" if dt == today else "أمس" if dt == today - timedelta(days=1) else "غداً" if dt == today + timedelta(days=1) else ""
        out.append({"label": f"{DAYS_AR[dt.weekday()]} {dt.day}/{dt.month}", "rel": rel, "today": dt == today, "items": days[dt]})
    return out


def _week_news(wn, now):
    """أخبار الأصل خلال الأسبوع بتوقيت بغداد. None إن لم يُجلب شيء (تُعرض الواجهة السبب)."""
    if not wn:
        return None
    topics = []
    today = (now + timedelta(hours=3)).date()
    for key, g in (wn.get("data") or {}).items():
        items = []
        for it in g.get("items", []):
            try:
                bt = datetime.fromisoformat(it["t"]) + timedelta(hours=3)
            except Exception:  # noqa: BLE001
                continue
            d = bt.date()
            rel = "اليوم" if d == today else "أمس" if d == today - timedelta(days=1) else f"{DAYS_AR[d.weekday()]} {d.day}/{d.month}"
            items.append({"when": f"{rel} {bt.strftime('%H:%M')}", "title": it["title"], "src": it.get("src", "")})
        if items:
            topics.append({"key": key, "label": g.get("label", key), "items": items})
    return {"topics": topics, "failed": wn.get("failed") or [], "at": wn.get("at"), "error": wn.get("error")}


MAG7_AR = {"AAPL": "أبل", "MSFT": "مايكروسوفت", "NVDA": "إنفيديا", "AMZN": "أمازون", "GOOGL": "ألفابت", "META": "ميتا", "TSLA": "تسلا",
           "JPM": "جيه بي مورغان", "GS": "غولدمان", "MS": "مورغان ستانلي", "C": "سيتي", "BAC": "بنك أمريكا", "WFC": "ويلز فارغو"}
MAG7 = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA")


def _week_earnings(report):
    """أرباح الأسبوع التي تحرّك ES: السبعة الكبار (نحو ثلث وزن المؤشر تقريباً) والبنوك الكبرى. تواريخ Yahoo غير رسمية."""
    out = []
    for ds, tickers in report.get("earnings_week") or []:
        import datetime as _dt
        dt = _dt.date.fromisoformat(ds)
        out.append({"label": f"{DAYS_AR[dt.weekday()]} {dt.day}/{dt.month}",
                    "items": [{"t": t, "name": MAG7_AR.get(t, t), "mag7": t in MAG7} for t in tickers]})
    return out


def build_view(report, events, now, news_labels=None, alerts=None, pulse=None, es_series=None, series=None, fed_heads=None, health=None, week_news=None):
    """يحوّل تقرير collector إلى بنية الواجهة."""
    if "error" in report:
        return {"live": True, "updated": _baghdad(now), "error": report["error"]}
    r = report["risk"]
    comps = [{"key": c["key"], "name": c["name"], "score": c["score"], "weight": c["weight"], "note": c.get("note", "")}
             for c in r["components"]]
    # الدعم والضغط يُحسبان باتجاه التأثير (impact.py) لا بهدوء المكوّن: الهدوء ليس دعماً.
    # المكوّنات الاتجاهية (دولار/عوائد/سيولة) تُمثَّل بعواملها الاتجاهية، والبقية تدخل الضغوط إن كانت مرتفعة.
    drv = report.get("drivers") or []
    DIRECTIONAL = {"dollar", "rates", "front_end", "net_liq"}
    bearish = [f"{d['name']}: {d['text']}" for d in drv if d["tone"] == "bear"]
    bearish += [f"{c['name']}: {c['note']}" for c in sorted(comps, key=lambda x: -x["score"]) if c["score"] >= 6 and c["key"] not in DIRECTIONAL]
    bullish = [f"{d['name']}: {d['text']}" for d in drv if d["tone"] == "bull"]
    bearish, bullish = bearish[:5], bullish[:5]
    calm = [c["name"] for c in sorted(comps, key=lambda x: x["score"]) if c["score"] <= 2][:6]
    au = _auction(report)
    stance, rec = _stance((report.get("tilt") or {}).get("score"))
    vol = next((c for c in comps if c["key"] == "volatility"), None)
    info = report.get("info", {})
    upcoming = []
    ml_, ctx_ = (report.get("macro") or {}).get("label", ""), events_ctx.build_ctx(report)
    for e in sorted(events or [], key=lambda x: x["time"]):
        if events_ctx.relevant(e) and now <= e["time"] <= now + timedelta(hours=24):
            dd = events_ctx.describe(e, (e["time"] + timedelta(hours=3)).strftime("%H:%M"), ml_, ctx_)
            dd["day"] = _day_label(e["time"], now)
            upcoming.append(dd)
    _up = []
    for day in ("اليوم", "غداً"):
        for g in events_ctx.group([u for u in upcoming if u["day"] == day]):
            g["day"] = day
            _up.append(g)
    upcoming = _up
    later = []
    for e in events or []:
        if e.get("impact") == "High" and now + timedelta(hours=24) < e["time"] <= now + timedelta(days=7):
            bt = e["time"] + timedelta(hours=3)
            day = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"][bt.weekday()]
            dd = events_ctx.describe(e, f"{day} {bt.strftime('%H:%M')}",
                                     (report.get("macro") or {}).get("label", ""), events_ctx.build_ctx(report))
            later.append(dd)
    geo = report.get("geo") or {}
    view = {
        "live": True, "updated": _baghdad(now),
        "risk": {"real": True, "score": r["score"], "label": r["level"], "main_reason": r["main_reason"], "reason_label": r.get("reason_label", "السبب"),
                 "advice": r["advice"], "weights_note": r.get("weights_note", []), "components": comps},
        "quick_call": {"stance": stance, "recommendation": rec, "confidence": (report.get("confidence") or {}).get("label", "")},
        "confidence": ({"score": round((report["confidence"]["points"]) / 10), "label": report["confidence"]["label"],
                        "why": report["confidence"].get("why", [])} if report.get("confidence") else None),
        "intensity": ({"score": report["intensity"], "label": (vol["note"] if vol else "")} if report.get("intensity") is not None else
                      ({"score": vol["score"], "label": vol["note"]} if vol else None)),
        "drivers": [{k: d[k] for k in ("key", "name", "val", "tone", "arrow", "last", "text")} for d in drv],
        "regime": report.get("regime"), "liquidity": report.get("liquidity"),
        "safety": _safety(report.get("safety")),
        "pressures": {"bullish": bullish, "bearish": bearish, "calm": calm},
        "auction": au, "macro": _macro(report),
        "events": upcoming, "events_next": later[:3], "events_past": _past_events(events, now, report, series or ({"es": es_series} if es_series else {}), fed_heads),
        "info": [info[k] for k in ("rates", "long_end", "tech", "mag7", "banks", "cot", "earnings") if k in info],
        "geo": [{"title": t["title"], "severity": t["severity"], "sources": t["sources"],
                 "regions": t["regions"], "deesc": t["deesc"]} for t in (geo.get("top") or [])[:3]],
        "geo_confirmed": bool(geo.get("confirmed")),
        "news": {(news_labels or {}).get(k, k): v for k, v in (report.get("news") or {}).items() if v},
        "data_age": info.get("data_age", ""),
        "problems": report.get("problems", []),
        "detailed_summary": report.get("notification", ""),
        "alerts": alerts or [], "pulse": pulse or [],
        "health": health,
        "week": _week(events, now, report),
        "week_earnings": _week_earnings(report),
        "asset": "ES",
        "week_news": _week_news(week_news, now),
        "asset": "ES",
    }
    return view


def publish(report, events, now, news_labels=None, docs_dir=None, alerts=None, pulse=None, es_series=None, series=None, fed_heads=None, health=None, week_news=None):
    """يكتب docs/data.json. فشل ناعم: لا يوقف التقرير."""
    d = docs_dir or DOCS_DIR
    os.makedirs(d, exist_ok=True)
    view = build_view(report, events, now, news_labels, alerts, pulse, es_series, series, fed_heads, health, week_news)
    with open(os.path.join(d, "data.json"), "w", encoding="utf-8") as f:
        json.dump(view, f, ensure_ascii=False, indent=1, default=str)
    return view


def patch_health(hv, docs_dir=None):
    """يحدّث حقل الصحة فقط في data.json القائم (عند تعذّر بناء لقطة جديدة)، فلا تبقى حالة «سليمة» قديمة."""
    p = os.path.join(docs_dir or DOCS_DIR, "data.json")
    try:
        with open(p, encoding="utf-8") as f:
            v = json.load(f)
    except Exception:  # noqa: BLE001
        v = {"live": True}
    v["health"] = hv
    with open(p, "w", encoding="utf-8") as f:
        json.dump(v, f, ensure_ascii=False, indent=1, default=str)


def page_url():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return ""
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"
