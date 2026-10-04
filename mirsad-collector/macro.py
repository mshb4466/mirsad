#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — المنظومة الكلية وتقدير ميل الفدرالي (بالقواعد، بلا ذكاء اصطناعي).

الفكرة: لا تُقرأ الأرقام منفردة. ست ركائز (التضخم، العمل، النمو، الظروف المالية، الطاقة، قاعدة تايلور)
تُدمج في «ميل» واحد بين -1 (تساهل) و+1 (تشدد) مع قياس اتفاقها وتعارضها، ثم يُقارن بما تسعّره السوق للفائدة
(مستخرجاً من منحنى الأذون والعوائد القصيرة في FRED) فتظهر «فجوة التسعير» التي تعني خطر مفاجأة عند الاجتماع.

حدود صريحة: هذا تقدير تقريبي لا بديل عن CME FedWatch. الافتراضات (الحياد الحقيقي r*=1.0 والبطالة الطبيعية u*=4.2)
تقديرية وقابلة للتعديل أدناه. الأوزان تُعايَر لاحقاً بسجل الأداء. أرقام FRED الشهرية تصل متأخرة أسابيع.
"""
from datetime import date, datetime, timezone

# سلاسل FRED (بلا مفتاح): المفتاح الداخلي ← المعرّف
SERIES = {
    "effr": "DFF", "m3": "DGS3MO", "m6": "DGS6MO", "y1": "DGS1", "y2": "DGS2",
    "unrate": "UNRATE", "core_pce": "PCEPILFE", "core_cpi": "CPILFESL", "payems": "PAYEMS",
    "claims": "ICSA", "indpro": "INDPRO", "retail": "RSAFS", "nfci": "NFCI",
    "bei10": "T10YIE", "hy": "BAMLH0A0HYM2",
}

R_STAR = 1.0      # الفائدة الحقيقية المحايدة (تقديرية)
U_STAR = 4.2      # البطالة الطبيعية طويلة الأجل (تقدير تقريبي)
TARGET = 2.0

# اجتماعات الفيدرالي 2026 (يوم القرار) — من تقويم federalreserve.gov
FOMC_2026 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29",
             "2026-09-16", "2026-10-28", "2026-12-09"]

# أوزان الركائز في الميل العام
PILLAR_W = {"inflation": 0.30, "labor": 0.28, "growth": 0.10, "fincond": 0.14, "energy": 0.04, "taylor": 0.14}
PILLAR_NAMES = {"inflation": "التضخم", "labor": "سوق العمل", "growth": "النمو", "fincond": "الظروف المالية",
                "energy": "الطاقة", "taylor": "قاعدة تايلور"}


def clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _vals(series):
    return [v for _, v in (series or [])]


def _ym(d):
    return int(d[:4]), int(d[5:7])


def yoy(series):
    """نسبة التغير السنوي لسلسلة شهرية (مطابقة الشهر نفسه قبل سنة)."""
    if not series or len(series) < 13:
        return None
    y, m = _ym(series[-1][0])
    for d, v in reversed(series[:-1]):
        if _ym(d) == (y - 1, m) and v:
            return (series[-1][1] / v - 1) * 100
    return None


def ann3(series):
    """التغير خلال 3 أشهر محوَّلاً لسنوي (%)."""
    if not series or len(series) < 4 or not series[-4][1]:
        return None
    return ((series[-1][1] / series[-4][1]) ** 4 - 1) * 100


def sahm(unrate):
    v = _vals(unrate)
    if len(v) < 15:
        return None
    ma = [sum(v[i - 2:i + 1]) / 3 for i in range(2, len(v))]
    return ma[-1] - min(ma[-13:-1])


def days_to_meeting(now):
    today = now.date()
    for d in FOMC_2026:
        dd = date.fromisoformat(d)
        if dd >= today:
            return d, (dd - today).days
    return None, None


# ───────────────────────── الركائز ─────────────────────────

def pillar_inflation(s):
    src, shift, tag = ("core_pce", 0.0, "PCE الأساسي"), None, None
    y = yoy(s.get("core_pce"))
    a = ann3(s.get("core_pce"))
    bias = 0.0
    if y is None:
        y, a, bias, tag = yoy(s.get("core_cpi")), ann3(s.get("core_cpi")), 0.4, "CPI الأساسي"
    else:
        tag = "PCE الأساسي"
    if y is None:
        return None
    gap = y - bias - TARGET
    mom = (a - bias - TARGET) if a is not None else gap
    sc = clamp(gap / 1.0) * 0.6 + clamp(mom / 1.5) * 0.4
    note = f"{tag} {y:.1f}% سنوياً (3 أشهر محوَّلة {a:.1f}%)" if a is not None else f"{tag} {y:.1f}% سنوياً"
    b = _vals(s.get("bei10"))
    if b:
        sc += 0.1 if b[-1] > 2.6 else -0.1 if b[-1] < 2.0 else 0.0
        note += f" | توقعات التضخم 10س {b[-1]:.2f}%"
    return clamp(sc), note, {"yoy": y, "ann3": a}


def pillar_labor(s):
    u = _vals(s.get("unrate"))
    if not u:
        return None
    sc = clamp((U_STAR - u[-1]) / 0.6) * 0.35
    notes = [f"البطالة {u[-1]:.1f}%"]
    sh = sahm(s.get("unrate"))
    if sh is not None:
        sc -= clamp(sh / 0.5, 0, 1) * 0.35
        if sh >= 0.3:
            notes.append(f"مؤشر Sahm {sh:.2f} (اقتراب من إنذار ركود)")
    pay = s.get("payems")
    if pay and len(pay) >= 4:
        avg = (pay[-1][1] - pay[-4][1]) / 3
        sc += 0.15 if avg > 150 else -0.3 if avg < 50 else 0.0
        notes.append(f"متوسط الوظائف {avg:.0f} ألف/شهر")
    cl = _vals(s.get("claims"))
    if len(cl) >= 30:
        ma = [sum(cl[i - 3:i + 1]) / 4 for i in range(3, len(cl))]
        low = min(ma[-52:])
        if low and ma[-1] / low - 1 > 0.15:
            sc -= 0.2
            notes.append("طلبات إعانة البطالة ارتفعت أكثر من 15% عن أدنى مستوى سنوي")
    return clamp(sc), " | ".join(notes), {"u": u[-1], "sahm": sh}


def pillar_growth(s, core_infl=None):
    parts, notes = [], []
    ip = ann3(s.get("indpro"))
    if ip is not None:
        parts.append(clamp(ip / 3.0) * 0.5)
        notes.append(f"الإنتاج الصناعي {ip:+.1f}% (3 أشهر محوَّلة)")
    ry = yoy(s.get("retail"))
    if ry is not None:
        real = ry - (core_infl if core_infl is not None else 2.5)
        parts.append(clamp(real / 3.0) * 0.5)
        notes.append(f"مبيعات التجزئة {ry:+.1f}% سنوياً (حقيقي تقريباً {real:+.1f}%)")
    if not parts:
        return None
    return clamp(sum(parts) * (2 if len(parts) == 1 else 1)), " | ".join(notes), {}


def pillar_fincond(s):
    nf, hy = _vals(s.get("nfci")), _vals(s.get("hy"))
    parts, notes = [], []
    if nf:
        parts.append(-clamp(nf[-1] / 0.5) * 0.5)
        notes.append(f"NFCI {nf[-1]:+.2f} ({'أشد' if nf[-1] > 0 else 'أخف'} من المتوسط)")
    if hy:
        parts.append(-clamp((hy[-1] - 4.0) / 2.0) * 0.5)
        notes.append(f"فروق الائتمان عالي المخاطر {hy[-1]:.2f}%")
    if not parts:
        return None
    return clamp(sum(parts) * (2 if len(parts) == 1 else 1)), " | ".join(notes), {}


def pillar_energy(prices):
    oil = (prices or {}).get("oil")
    if not oil:
        return None
    return clamp(oil["chg5"] / 12.0) * 0.5, f"النفط {oil['chg5']:+.1f}% خلال 5 أيام", {}


def taylor(s, infl):
    u, e = _vals(s.get("unrate")), _vals(s.get("effr"))
    if not u or not e or infl is None:
        return None
    rule = R_STAR + infl + 0.5 * (infl - TARGET) - 1.0 * (u[-1] - U_STAR)
    return rule, e[-1]


# ───────────────────────── التسعير الضمني ─────────────────────────

def implied_path(s):
    e = _vals(s.get("effr"))
    if not e:
        return None
    eff = e[-1]
    out = {"effr": eff}
    for k in ("m3", "m6", "y1"):
        v = _vals(s.get(k))
        if v:
            out[k] = (v[-1] - eff) * 100   # نقاط أساس مقارنة بالفائدة الفعلية
    if "m3" not in out and "m6" not in out:
        return None
    ref = out.get("m6", out.get("m3"))
    out["lean"] = clamp(ref / 50.0)
    m3 = out.get("m3")
    if m3 is None:
        out["next"] = "غير متاح"
    elif m3 <= -10:
        out["next"] = "السوق يسعّر ميلاً للتخفيض"
    elif m3 >= 10:
        out["next"] = "السوق يسعّر ميلاً للرفع"
    else:
        out["next"] = "السوق يسعّر التثبيت غالباً"
    return out


# ───────────────────────── الدمج ─────────────────────────

def lean_label(x):
    return ("متشدد", "▲", "🦅") if x > 0.25 else ("متساهل", "▼", "🕊") if x < -0.25 else ("متوازن", "◆", "⚖")


def analyze(series, prices, now):
    """يُرجع قاموس المنظومة أو None إن لم تكف البيانات (أقل من ثلاث ركائز)."""
    if not series:
        return None
    pil = {}
    infl = pillar_inflation(series)
    if infl:
        pil["inflation"] = infl
    for key, fn in (("labor", lambda: pillar_labor(series)),
                    ("growth", lambda: pillar_growth(series, infl[2]["yoy"] if infl else None)),
                    ("fincond", lambda: pillar_fincond(series)),
                    ("energy", lambda: pillar_energy(prices))):
        r = fn()
        if r:
            pil[key] = r
    tay = taylor(series, infl[2]["yoy"] if infl else None)
    if tay:
        rule, eff = tay
        pil["taylor"] = (clamp((rule - eff) / 1.5), f"القاعدة تقترح {rule:.2f}% مقابل فعلي {eff:.2f}%", {"rule": rule, "effr": eff})
    if len(pil) < 3:
        return None
    wsum = sum(PILLAR_W[k] for k in pil)
    lean = sum(PILLAR_W[k] * pil[k][0] for k in pil) / wsum
    # اتفاق الركائز: نسبة الوزن المتفق مع إشارة الميل (تُهمل الضعيفة)
    strong = {k: v for k, v in pil.items() if abs(v[0]) >= 0.2}
    if strong:
        sg = 1 if lean >= 0 else -1
        agree = sum(PILLAR_W[k] for k, v in strong.items() if v[0] * sg > 0) / sum(PILLAR_W[k] for k in strong)
    else:
        agree = 1.0
    dilemma = (("inflation" in pil and pil["inflation"][0] >= 0.3 and "labor" in pil and pil["labor"][0] <= -0.3) or
               ("inflation" in pil and pil["inflation"][0] <= -0.3 and "labor" in pil and pil["labor"][0] >= 0.3))
    coverage = wsum / sum(PILLAR_W.values())
    conf = "مرتفعة" if agree >= 0.8 and coverage >= 0.8 and not dilemma else "متوسطة" if agree >= 0.6 and coverage >= 0.6 else "منخفضة"
    imp = implied_path(series)
    gap = None
    if imp:
        g = lean - imp["lean"]
        a = abs(g)
        size = "كبيرة" if a >= 0.6 else "متوسطة" if a >= 0.35 else "صغيرة"
        if size == "صغيرة":
            direction = "السوق متسق مع البيانات"
        elif g > 0:
            direction = "السوق يسعّر تيسيراً أكثر مما تبرره البيانات: خطر مفاجأة متشددة"
        else:
            direction = "السوق يسعّر تشدداً أكثر مما تبرره البيانات: خطر مفاجأة متساهلة"
        gap = {"value": round(g, 2), "size": size, "direction": direction}
    d, n = days_to_meeting(now)
    word, arrow, emoji = lean_label(lean)
    view = {
        "lean": round(lean, 2), "label": word, "arrow": arrow, "emoji": emoji,
        "confidence": conf, "agreement": round(agree, 2), "dilemma": bool(dilemma), "coverage": round(coverage, 2),
        "pillars": [{"key": k, "name": PILLAR_NAMES[k], "s": round(v[0], 2), "note": v[1],
                     "arrow": "▲" if v[0] > 0.2 else "▼" if v[0] < -0.2 else "◆"} for k, v in
                    sorted(pil.items(), key=lambda kv: abs(kv[1][0]) * PILLAR_W[kv[0]], reverse=True)],
        "taylor": ({"rule": round(tay[0], 2), "effr": tay[1]} if tay else None),
        "implied": ({k: (round(v, 1) if isinstance(v, float) else v) for k, v in imp.items()} if imp else None),
        "gap": gap, "meeting": ({"date": d, "days": n} if d else None),
        "assumptions": f"افتراضات: r*={R_STAR}% وu*={U_STAR}% وهدف التضخم {TARGET}% (تقديرية)",
    }
    view["summary"] = summarize(view)
    return view


def summarize(v):
    lines = []
    top = [p for p in v["pillars"] if p["arrow"] != "◆"][:2]
    drivers = "، ".join(f"{p['name']} {p['arrow']}" for p in top) or "لا ركيزة حاسمة"
    lines.append(f"ميل الفدرالي من البيانات: {v['label']} (ثقة {v['confidence']}) — أبرز المحركات: {drivers}")
    if v["dilemma"]:
        lines.append("تعارض بين التضخم وسوق العمل: وضع صعب على الفدرالي (قراراته أقل قابلية للتوقع)")
    if v.get("implied"):
        i = v["implied"]
        parts = [f"{lab} {i[k]:+.0f}bp" for k, lab in (("m3", "3 أشهر"), ("m6", "6 أشهر"), ("y1", "سنة")) if k in i]
        lines.append(f"تسعير السوق (فرق العائد عن الفائدة الفعلية {i['effr']:.2f}%): " + " | ".join(parts) + f" ← {i['next']}")
    if v.get("gap"):
        lines.append(f"فجوة التسعير {v['gap']['size']}: {v['gap']['direction']}")
    if v.get("meeting"):
        lines.append(f"اجتماع الفيدرالي القادم: {v['meeting']['date']} (بعد {v['meeting']['days']} يوماً)")
    return lines


def score_fed_system(view):
    """درجة مخاطرة 0-10 للمنظومة: فجوة التسعير × قرب الاجتماع (+ تعارض الركائز)."""
    if not view:
        return None, "بيانات المنظومة الكلية غير متوفرة"
    g = view.get("gap")
    base = 2.0
    note = [f"ميل {view['label']}"]
    if g:
        base += 5.0 * min(1.0, abs(g["value"]) / 0.8)
        note.append(f"فجوة تسعير {g['size']}")
    if view["dilemma"]:
        base += 1.0
        note.append("تعارض تضخم/عمل")
    m = view.get("meeting")
    if m:
        d = m["days"]
        f = 1.15 if d <= 2 else 1.0 if d <= 7 else 0.8 if d <= 21 else 0.55
        base *= f
        note.append(f"الاجتماع بعد {d} يوماً")
    return max(0.0, min(10.0, round(base, 1))), "، ".join(note)
