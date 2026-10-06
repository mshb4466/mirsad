#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — تحويل التقرير الحقيقي إلى بيانات الواجهة (docs/data.json) لتعرضها صفحة GitHub Pages.
لا حسابات جديدة هنا: فقط إعادة تشكيل ما حسبه collector وmacro وauction وgeo.
"""
import json
import events_ctx
import os
from datetime import timedelta

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
        "gapTitle": ("فجوة تسعير " + gap["size"]) if gap else "تسعير السوق",
        "gap": gap["direction"] if gap else "تعذّر تقدير ما يسعّره السوق",
        "meet": (f"الاجتماع القادم: {meet['date']} (بعد {meet['days']} يوماً)" if meet else ""),
    }


def build_view(report, events, now, news_labels=None):
    """يحوّل تقرير collector إلى بنية الواجهة."""
    if "error" in report:
        return {"live": True, "updated": _baghdad(now), "error": report["error"]}
    r = report["risk"]
    comps = [{"key": c["key"], "name": c["name"], "score": c["score"], "weight": c["weight"], "note": c.get("note", "")}
             for c in r["components"]]
    bearish = [f"{c['name']}: {c['note']}" for c in sorted(comps, key=lambda x: -x["score"]) if c["score"] >= 6][:4]
    bullish = [f"{c['name']}: {c['note']}" for c in sorted(comps, key=lambda x: x["score"]) if c["score"] <= 2][:4]
    au = _auction(report)
    stance, rec = _stance((report.get("tilt") or {}).get("score"))
    vol = next((c for c in comps if c["key"] == "volatility"), None)
    info = report.get("info", {})
    upcoming = []
    for e in events or []:
        if e.get("impact") in ("High", "Medium") and now <= e["time"] <= now + timedelta(hours=24):
            upcoming.append(events_ctx.describe(e, (e["time"] + timedelta(hours=3)).strftime("%H:%M"),
                                                (report.get("macro") or {}).get("label", "")))
    later = []
    for e in events or []:
        if e.get("impact") == "High" and now + timedelta(hours=24) < e["time"] <= now + timedelta(days=7):
            bt = e["time"] + timedelta(hours=3)
            day = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"][bt.weekday()]
            dd = events_ctx.describe(e, f"{day} {bt.strftime('%H:%M')}",
                                     (report.get("macro") or {}).get("label", ""))
            later.append(dd)
    geo = report.get("geo") or {}
    view = {
        "live": True, "updated": _baghdad(now),
        "risk": {"real": True, "score": r["score"], "label": r["level"], "main_reason": r["main_reason"], "reason_label": r.get("reason_label", "السبب"),
                 "advice": r["advice"], "weights_note": r.get("weights_note", []), "components": comps},
        "quick_call": {"stance": stance, "recommendation": rec, "confidence": ""},
        "intensity": ({"score": vol["score"], "label": vol["note"]} if vol else None),
        "pressures": {"bullish": bullish, "bearish": bearish},
        "auction": au, "macro": _macro(report),
        "events": upcoming, "events_next": later[:3],
        "info": [info[k] for k in ("rates", "tech", "mag7", "banks", "cot", "earnings") if k in info],
        "geo": [{"title": t["title"], "severity": t["severity"], "sources": t["sources"],
                 "regions": t["regions"], "deesc": t["deesc"]} for t in (geo.get("top") or [])[:3]],
        "geo_confirmed": bool(geo.get("confirmed")),
        "news": {(news_labels or {}).get(k, k): v for k, v in (report.get("news") or {}).items() if v},
        "data_age": info.get("data_age", ""),
        "problems": report.get("problems", []),
        "detailed_summary": report.get("notification", ""),
    }
    return view


def publish(report, events, now, news_labels=None, docs_dir=None):
    """يكتب docs/data.json. فشل ناعم: لا يوقف التقرير."""
    d = docs_dir or DOCS_DIR
    os.makedirs(d, exist_ok=True)
    view = build_view(report, events, now, news_labels)
    with open(os.path.join(d, "data.json"), "w", encoding="utf-8") as f:
        json.dump(view, f, ensure_ascii=False, indent=1, default=str)
    return view


def page_url():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return ""
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"
