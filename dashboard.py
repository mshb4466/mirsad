#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — تحويل التقرير الحقيقي إلى بيانات الواجهة (docs/data.json) لتعرضها صفحة GitHub Pages.
لا حسابات جديدة هنا: فقط إعادة تشكيل ما حسبه collector وmacro وauction وgeo.
"""
import json
import actuals
import events_ctx
import verdict
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
                "tone": (vd or {}).get("es", "") , "effect": (vd or {}).get("effect", ""), "kind": d.get("kind", ""),
                "status": d.get("status", ""), "status_ar": d.get("status_ar", ""), "last_attempt": d.get("last_attempt", ""),
                "id": actuals.event_id(e), "source": e.get("actual_source", "") if e.get("actual") else "",
                "revision": (f"السابق عُدّل إلى {e['prev_revised']}" if e.get("prev_revised") else "") + (("؛ " if e.get("prev_revised") else "") + f"الفعلي عُدّل من {e['revised_from']}" if e.get("revised_from") else ""),
                "impact": e.get("impact", ""), "in_min": int((e["time"] - now).total_seconds() // 60)}
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


TONE_AR_ = {"bear": "ضغط على الأسهم", "bull": "دعم للأسهم", "flat": "أثر محدود", "warn": "تنبيه"}
KIND_CAP = 2   # أقصى عدد من النوع الواحد حتى لا تتكرر الصورة نفسها


def _top3(report, pulse, past):
    """أهم ثلاثة تطورات جوهرية الآن: ترتيب عرض فقط من مخرجات المحرك الموجودة (لا حساب جديد للمخاطر أو الانحياز).
    الأولوية: خلل بيانات مؤثر > حركة سوق مؤكَّدة بالزخم والحجم > حدث صدر وله أثر > خبر جيوسياسي > فجوة تسعير الفدرالي > عوامل اتجاهية > السيولة."""
    c = []
    for i in ((report.get("safety") or {}).get("issues") or []):
        if i.get("sev") in ("major", "critical"):
            c.append({"p": 100 if i["sev"] == "critical" else 90, "kind": "safety", "tone": "warn", "arrow": "⚠", "title": "خلل في البيانات: " + i["msg"][:90],
                      "why": "رصده مراقب السلامة؛ الاستنتاج المتأثر معلَّق أو مخفَّضة ثقته حتى يُصحَّح.", "src": "مراقب سلامة التحليل"})
    for r in pulse or []:
        if r.get("confirmed"):
            c.append({"p": 80 + min(10.0, float(r.get("ratio") or 1) * 2), "kind": "move", "tone": r.get("tone") or "flat", "arrow": "▲" if (r.get("v") or 0) > 0 else "▼",
                      "title": f"{r.get('name')} {r.get('val')} خلال {r.get('w')} دقيقة", "why": "حركة مؤكَّدة بالزخم وارتفاع حجم التداول معاً؛ " + str(r.get("why") or ""),
                      "src": "Yahoo (متأخر 15–30 دقيقة)"})
    for x in past or []:
        vd = x.get("verdict")
        if vd and not x.get("items"):
            c.append({"p": 70 + (10 if x.get("high") else 0), "kind": "event", "tone": vd.get("es") or "flat", "arrow": "▲" if vd.get("k") == "above" else "▼" if vd.get("k") == "below" else "◆",
                      "title": f"{x.get('name') or x.get('title')}: {vd.get('label')}",
                      "why": f"الفعلي {x.get('actual') or '—'} مقابل المتوقع {x.get('forecast') or '—'}. {vd.get('effect') or ''}", "src": x.get("actual_note") or "تقويم الأحداث"})
    for t in ((report.get("geo") or {}).get("top") or [])[:3]:
        if (t.get("severity") or 0) >= 2:
            c.append({"p": 50 + 5 * t["severity"], "kind": "geo", "tone": "bear", "arrow": "▲", "title": "جيوسياسة: " + t["title"][:90],
                      "why": f"حدّة {t['severity']}/4، {t.get('sources')} مصدر. تصنيف بالقواعد وليس تفسيراً بالذكاء الاصطناعي.", "src": "أخبار Google (قواعد)"})
    g = (report.get("macro") or {}).get("gap")
    if g and g.get("size") in ("كبيرة", "متوسطة"):
        c.append({"p": 55 if g["size"] == "كبيرة" else 45, "kind": "fed", "tone": "warn", "arrow": "◆", "title": f"فجوة تسعير الفدرالي {g['size']}",
                  "why": g.get("direction", ""), "src": "FRED + منحنى الأذون"})
    for d in report.get("drivers") or []:
        if d.get("tone") in ("bear", "bull"):
            c.append({"p": 40 + 5 * min(5.0, float(d.get("strength") or 0)), "kind": "driver", "tone": d["tone"], "arrow": d.get("arrow") or "◆",
                      "title": f"{d['name']} {d.get('val', '')}".strip(), "why": f"{d.get('text', '')}. القاعدة: ارتفاع الدولار والعوائد والنفط وVIX يضغط على الأسهم، وهبوطها يدعمها.", "src": "Yahoo/FRED"})
    lq = report.get("liquidity")
    if lq and lq.get("tone") in ("bear", "bull"):
        c.append({"p": 35, "kind": "liq", "tone": lq["tone"], "arrow": lq.get("arrow") or "◆", "title": f"السيولة الصافية: {lq.get('word')}", "why": lq.get("meaning", ""), "src": "FRED"})
    c.sort(key=lambda x: -x["p"])
    out, per = [], {}
    for x in c:
        if per.get(x["kind"], 0) >= KIND_CAP:
            continue
        per[x["kind"]] = per.get(x["kind"], 0) + 1
        out.append({k: x[k] for k in ("kind", "tone", "arrow", "title", "why", "src")})
        if len(out) == 3:
            break
    return out


PULSE_SYMS = [("es", "ES", "pct", "es"), ("nq", "NQ", "pct", "nq"), ("y2", "2Y", "bp", "y2"), ("y10", "10Y", "bp", "y10"),
              ("dxy", "DXY", "pct", "dxy"), ("vix", "VIX", "pct", "vix"), ("oil", "WTI", "pct", "oil"), ("gold", "Gold", "pct", None)]


def _intensity_word(x):
    return None if x is None else ("خفيفة" if x < 3.5 else "متوسطة" if x < 6.5 else "قوية")


def _hhmm_baghdad(iso):
    """وقت آخر شمعة بتوقيت بغداد HH:MM، أو «غير معروف» إن تعذّر التحليل (لا نخمّن)."""
    try:
        return (datetime.fromisoformat(str(iso)) + timedelta(hours=3)).strftime("%H:%M") if datetime.fromisoformat(str(iso)).utcoffset() is not None else "غير معروف"
    except Exception:  # noqa: BLE001
        return "غير معروف"


PULSE_AR = {"ES": "عقود S&P (ES)", "NQ": "ناسداك (NQ)", "2Y": "عائد سنتين", "10Y": "عائد 10 سنوات", "DXY": "الدولار (DXY)",
            "VIX": "مؤشر التقلب VIX", "WTI": "النفط (WTI)", "Gold": "الذهب"}
PULSE_STATE_KEY = {"es": "es", "nq": "nq", "y10": "y10", "dxy": "dxy", "vix": "vix", "oil": "oil", "gold": "gold"}
COLOR_OF = {"bull": "support", "bear": "pressure"}
EFFECT_AR = {"support": "يدعم ES", "pressure": "يضغط على ES", "mixed": "أثر مختلط/مشروط", "calm": "هادئ — أثر محدود", "na": "غير متاح"}


def _pulse8(report, pulse_state=None):
    """نبض الأسواق الموحّد: بطاقة واحدة لكل مؤشر (ES، NQ، 2Y، 10Y، DXY، VIX، WTI، الذهب).
    لون البطاقة (color) = الأثر على ES: support أخضر | pressure أحمر | mixed كهرماني (مشروط/متعارض) | na رمادي (غير متاح)؛
    وcalm = حركة ضمن النطاق المعتاد (لا لون تحذير ولا دعم: الهدوء ليس دعماً). السهم (arrow) يعكس حركة المؤشر نفسه لا أثره.
    tier (0-2) يحدّد الترتيب بثبات: لا يتبدّل الترتيب بتغيرات صغيرة. لا قيم افتراضية: الناقص «غير متاح»."""
    import impact
    prices = report.get("data") or {}
    bias = report.get("bias") or {}
    bk = bias.get("key") if bias.get("available") else None
    by_state = {r.get("key"): r for r in (pulse_state or [])}
    drv = {d.get("key"): d for d in (report.get("drivers") or [])}
    out = []
    for key, sym, unit, pk in PULSE_SYMS:
        base = {"sym": sym, "name": PULSE_AR.get(sym, sym), "key": key}
        chg = last = when = src = None
        if key == "y2":
            f = (report.get("fred_last") or {}).get("dgs2")
            if f and f.get("diff1") is not None:
                chg, last, when, src = f["diff1"] * 100, f["last"], f["date"], "FRED"
        else:
            p = prices.get(key)
            if p:
                last, when, src = p["last"], p.get("bar_time") or "", "Yahoo"
                chg = p.get("chg1_pct")
                if unit == "bp":
                    chg = p["diff1"] * 100 if p.get("diff1") is not None else None
        if chg is None or last is None:
            out.append(dict(base, available=False, color="na", effect=EFFECT_AR["na"], tier=-1))
            continue
        why_oil = ""
        if pk == "oil":                      # النفط بالسياق لا بالاتجاه وحده، والسبب مرجَّح لا مثبت
            gs, gr = impact.geo_flags(report.get("geo"))
            tone, cause, why_oil = impact.oil_cause(chg, (prices.get("es") or {}).get("chg1"), (prices.get("dxy") or {}).get("chg1"),
                                                    (prices.get("vix") or {}).get("chg1"), gs, gr)
        else:
            tone = impact.tone(pk, chg) if pk else "flat"
        band = impact.POLARITY.get(pk or "", (0, 0.5))[1] if pk else 0.3
        small = abs(chg) <= band
        color = COLOR_OF.get(tone) or ("calm" if small else "mixed")
        if pk == "oil" and color in ("support", "pressure"):
            why_oil = "(تفسير مرجَّح من سياق الحركة لا سبب مثبت) " + why_oil
        if bk is None:
            cf = "na"
        elif src == "FRED":                  # سلسلة يومية (إغلاق أمس): ليست تأكيداً لحظياً بعد خبر
            cf = "daily"
        elif tone == "flat":
            cf = "flat"
        else:
            cf = "yes" if ((bk == "pressure" and tone == "bear") or (bk == "support" and tone == "bull")) else \
                 "flat" if bk == "neutral" else "no"
        st = by_state.get(PULSE_STATE_KEY.get(pk or "", ""))
        strength = impact.strength(pk, chg) if pk else 0.0
        if st and (st.get("ratio") or 0) >= 1.0:
            strength = max(strength, 3.0)
        tier = 2 if strength >= 3 else 1 if strength >= 1 else 0
        d = drv.get(pk) or {}
        eff = EFFECT_AR[color] if not why_oil else (EFFECT_AR[color] + ": " + why_oil)
        if pk != "oil" and d.get("text") and color in ("support", "pressure"):
            eff = EFFECT_AR[color]
        if sym == "ES":
            eff = "حركة ES نفسه: " + ("صاعد" if chg > 0 else "هابط" if chg < 0 else "ثابت")
        out.append(dict(base, available=True, last=last, chg=round(chg, 2), unit=unit, arrow="▲" if chg > 0 else "▼" if chg < 0 else "◆",
                        tone=tone, color=color, effect=eff, confirm=cf, tier=tier,
                        window="منذ إغلاق أمس" if src == "Yahoo" else "آخر قراءة يومية",
                        time=_hhmm_baghdad(when) if src == "Yahoo" else str(when)[:10], src=src,
                        windows=({"c15": st.get("c15"), "c60": st.get("c60"), "c180": st.get("c180"), "confirmed": bool(st.get("confirmed")), "why": st.get("why") or ""} if st else None)))
    return out


def _order_pulse(cards, prev_cards):
    """ترتيب مستقر: الفئة (tier) تنازلياً، وداخل الفئة الترتيب السابق المنشور ثم الترتيب الثابت. تغيّر طفيف لا يبدّل المواقع.
    وتُوسَم البطاقة «تغيّر جديد» إن ارتفعت فئتها أو انقلب لونها إلى دعم/ضغط مقارنة باللقطة السابقة (يزول في اللقطة التالية)."""
    prev = {c.get("sym"): (i, c) for i, c in enumerate(prev_cards or [])}
    fixed = {s: i for i, (_, s, _, _) in enumerate(PULSE_SYMS)}
    for c in cards:
        c["new"] = False
        pv = prev.get(c["sym"])
        if pv and c.get("available") and pv[1].get("available"):
            c["new"] = (c["tier"] > pv[1].get("tier", 0) and c["tier"] >= 1) or (c["color"] != pv[1].get("color") and c["color"] in ("support", "pressure"))
    return sorted(cards, key=lambda c: (-c.get("tier", -1), prev[c["sym"]][0] if c["sym"] in prev else 99, fixed.get(c["sym"], 99)))


def _changes(top3, prev_titles):
    """التغيرات منذ الفحص السابق: ما لم يكن في اللقطة السابقة فقط."""
    if prev_titles is None:
        return {"has_prev": False, "items": top3, "new_count": 0}
    items = [dict(t, new=True) for t in top3 if t["title"] not in prev_titles]
    return {"has_prev": True, "items": items, "new_count": len(items)}


def _actuals_summary(events, now):
    """ملخص حالة الأرقام الفعلية للأحداث عالية التأثير الصادرة خلال 48 ساعة: التعريف نفسه المستعمل في quality وصحة مرصاد
    (actuals.summary). الخطب والعطل لا تدخل لا في المعلّق ولا في التغطية."""
    sm = actuals.summary(events, now, 48, True)
    rev = sum(1 for e in events or [] if e.get("impact") == "High" and e.get("status") == "revised" and actuals.is_verified(e)
              and timedelta(0) <= now - e["time"] <= timedelta(hours=48))
    return {"total": sm["total"], "verified": sm["verified"], "official": sum(1 for e in events or [] if e.get("status") == "verified_official" and e.get("impact") == "High"
                                                                              and timedelta(0) <= now - e["time"] <= timedelta(hours=48)),
            "needs_check": sm["needs_check"], "awaiting": sm["awaiting"], "unsupported": sm["unsupported"], "failed": sm["failed"], "revised": rev,
            "coverage_pct": sm["coverage_pct"], "supported_coverage_pct": sm["supported_coverage_pct"],
            "last_attempt": events_ctx._hhmm_attempt(sm["last_attempt"]) if sm["last_attempt"] else ""}


def build_view(report, events, now, news_labels=None, alerts=None, pulse=None, es_series=None, series=None, fed_heads=None, health=None, week_news=None, prev_titles=None, quality=None, verdict_prev=None, prev_view=None):
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
            dd["in_min"] = int((e["time"] - now).total_seconds() // 60)
            dd["at"], dd["importance"] = e["time"].isoformat(), e.get("impact", "")
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
            dd["in_min"] = int((e["time"] - now).total_seconds() // 60)
            dd["at"], dd["importance"] = e["time"].isoformat(), e.get("impact", "")
            later.append(dd)
    geo = report.get("geo") or {}
    past_ = _past_events(events, now, report, series or ({"es": es_series} if es_series else {}), fed_heads)
    view = {
        "live": True, "updated": _baghdad(now), "published_at": now.isoformat(), "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "risk": {"real": True, "score": r["score"], "label": r["level"], "main_reason": r["main_reason"], "reason_label": r.get("reason_label", "السبب"),
                 "advice": r["advice"], "weights_note": r.get("weights_note", []), "components": comps},
        "quick_call": {"stance": stance, "available": report.get("tilt") is not None, "recommendation": rec, "confidence": (report.get("confidence") or {}).get("label", "")},
        "confidence": ({"score": round((report["confidence"]["points"]) / 10), "label": report["confidence"]["label"],
                        "why": report["confidence"].get("why", [])} if report.get("confidence") else None),
        "intensity": ({"score": report["intensity"], "word": _intensity_word(report["intensity"]), "label": (vol["note"] if vol else "")} if report.get("intensity") is not None else
                      ({"score": vol["score"], "label": vol["note"]} if vol else None)),
        "drivers": [dict({k: d[k] for k in ("key", "name", "val", "tone", "arrow", "last", "text")}, **({"cause": d["cause"]} if d.get("cause") else {})) for d in drv],
        "regime": report.get("regime"), "liquidity": report.get("liquidity"), "bias": report.get("bias"),
        "safety": _safety(report.get("safety")),
        "pressures": {"bullish": bullish, "bearish": bearish, "calm": calm},
        "auction": au, "macro": _macro(report),
        "events": upcoming, "events_next": later[:3], "events_past": past_,
        "top3": _top3(report, pulse, past_),
        "changes": _changes(_top3(report, pulse, past_), prev_titles),
        "pulse8": _order_pulse(_pulse8(report, pulse), (prev_view or {}).get("pulse8")),
        "verdict": verdict.build(report, now, verdict_prev, events),
        "releases": _releases_view(report.get("releases")),
        "actuals_status": _actuals_summary(events, now),
        "quality": quality,
        "next_event": next((u for u in upcoming if u.get("high")), None) or (upcoming[0] if upcoming else None) or (later[0] if later else None),
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
        "week_news": _week_news(week_news, now),
        "asset": "ES",
    }
    return view


def _releases_view(rel):
    """ما يلزم الواجهة من أثر الإصدارات: الإصدارات المدموجة ومساهمة كل مجموعة، والمعلّق، وتأكيد السوق (لا أرقام مكررة)."""
    if not rel:
        return None
    return {"signal": rel.get("signal"), "weight": rel.get("weight"), "fed_discount": rel.get("fed_discount"), "note": rel.get("note", ""),
            "market": rel.get("market"), "pending": rel.get("pending") or [],
            "groups": [{"kind": g["kind"], "lead": g["lead"], "value": g["value"], "importance": g["importance"], "mode": g["mode"], "ids": g["ids"],
                        "initial": g["initial"], "revision": g["revision"], "effect": g["effect"], "conflict": g.get("conflict", ""),
                        "trend": g.get("trend", ""), "explain": g.get("explain") or {}} for g in rel.get("groups") or []]}


REQUIRED_KEYS = ("live", "published_at", "risk", "verdict", "pulse8", "alerts", "next_event")


def validate_view(view):
    """لقطة صالحة للنشر: إما حالة خطأ صريحة (تقييم غير مكتمل) أو لقطة تحمل كل المفاتيح الجوهرية بأنواعها. (ok, سبب)."""
    if not isinstance(view, dict):
        return False, "اللقطة ليست كائناً"
    if view.get("error"):
        return True, ""
    miss = [k for k in REQUIRED_KEYS if k not in view]
    if miss:
        return False, "مفاتيح ناقصة: " + "، ".join(miss)
    if not isinstance(view["pulse8"], list) or not isinstance(view["alerts"], list) or not isinstance(view["verdict"], dict):
        return False, "أنواع حقول غير صحيحة"
    if not isinstance(view["risk"], dict) or view["risk"].get("score") is None:
        return False, "مقياس المخاطر مفقود"
    return True, ""


def publish(report, events, now, news_labels=None, docs_dir=None, alerts=None, pulse=None, es_series=None, series=None, fed_heads=None, health=None, week_news=None, prev_titles=None, quality=None, verdict_prev=None):
    """يكتب docs/data.json. لا يكتب لقطة معيبة: تبقى آخر لقطة صالحة منشورة ويُرفع ValueError (فلا يُعدّ النشر ناجحاً)."""
    d = docs_dir or DOCS_DIR
    os.makedirs(d, exist_ok=True)
    prev_titles, prev_view = None, None
    try:
        with open(os.path.join(d, "data.json"), encoding="utf-8") as f:
            prev_view = json.load(f)
        if prev_view.get("top3") is not None:
            prev_titles = {t.get("title") for t in prev_view["top3"]}
    except Exception:  # noqa: BLE001
        prev_titles, prev_view = None, None
    view = build_view(report, events, now, news_labels, alerts, pulse, es_series, series, fed_heads, health, week_news, prev_titles, quality,
                      verdict_prev=verdict_prev, prev_view=prev_view)
    ok, why = validate_view(view)
    if not ok:
        raise ValueError("لقطة الواجهة معيبة ولم تُنشر: " + why)
    json.dumps(view, ensure_ascii=False, default=str)           # يتأكد أنها قابلة للتسلسل قبل استبدال الملف
    _write_json(os.path.join(d, "data.json"), view)
    return view


def _write_json(path, obj):
    """كتابة ذرّية (ملف مؤقت ثم استبدال): لا يبقى data.json نصف مكتوب إن توقفت العملية."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, path)


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
