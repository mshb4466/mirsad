#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — اتجاه التأثير على الأسهم (ES).
درجات المكوّنات في collector تقيس «حجم» الحركة (خطر)، أما هنا فنحدد «اتجاه» الأثر:
ارتفاع الدولار أو العوائد أو النفط أو VIX أو فروق الائتمان = ضغط على الأسهم (أحمر)، وانخفاضها = دعم (أخضر).
السيولة: ضخّ = داعم، سحب = ضاغط.

قاعدة صريحة: «الهدوء» ليس «دعماً». الدعم لا يُدرَج إلا لعامل اتجاهه فعلاً في صالح الأسهم.
هذه قاعدة اقتصادية عامة (ليست تنبؤاً)، وقد تنقلب في ظروف خاصة (مثلاً ارتفاع العوائد لأسباب نمو قوي)،
لذلك نصفها بـ«الأثر المعتاد».
"""

# مفتاح: (قطبية الارتفاع على الأسهم: -1 ضغط / +1 دعم, نطاق «لا تغيير» بوحدة التغير, الوحدة, الاسم)
POLARITY = {
    "dxy": (-1, 0.15, "pct", "الدولار"),
    "y10": (-1, 2.0, "bp", "عائد 10 سنوات"),
    "y30": (-1, 2.0, "bp", "عائد 30 سنة"),
    "y5": (-1, 2.0, "bp", "عائد 5 سنوات"),
    "y2": (-1, 2.0, "bp", "عائد سنتين"),
    "oil": (0, 0.5, "pct", "النفط"),      # قطبية 0: لا اتجاه آلي للنفط؛ يُحدَّد بالسياق في oil_cause()
    "vix": (-1, 3.0, "pct", "VIX"),
    "hy_oas": (-1, 0.05, "pt", "فروق الائتمان"),
    "net_liq": (+1, 0.5, "pct", "السيولة الصافية"),
    "jpy": (+1, 0.25, "pct", "الدولار/الين"),   # هبوط الدولار/ين = قوة الين = خطر تفكك تجارة الفائدة
    "hyg": (+1, 0.1, "pct", "سندات عالية العائد"),
    "kre": (+1, 0.3, "pct", "البنوك الإقليمية"),
    "es": (+1, 0.1, "pct", "ES"),
    "nq": (+1, 0.1, "pct", "ناسداك"),
}

OIL_BAND = 0.5


def oil_cause(oil_chg, es_chg=None, dxy_chg=None, vix_chg=None, geo_supply=False, geo_relief=False):
    """اتجاه أثر النفط على الأسهم بحسب السبب، لا بحسب الاتجاه وحده. (tone, cause, text). قواعد صريحة وليست نموذجاً إحصائياً:
    - ارتفاع + أخبار إمداد/طاقة جيوسياسية والأسهم لا ترتفع = صدمة عرض → ضاغط.
    - ارتفاع مع صعود الأسهم دون صعود VIX أو الدولار = يشبه تحسن الطلب → مختلط.
    - ارتفاع بلا دليل = مشروط.
    - هبوط مع هبوط الأسهم وصعود VIX = ضعف طلب/تجنب مخاطرة → ضاغط.
    - هبوط مع تهدئة جيوسياسية أو مع صعود الأسهم دون صعود VIX = يخفف ضغط التكلفة → داعم.
    - هبوط بلا دليل = مشروط. الناقص من الأدلة (None) لا يُعامل صفراً: يمنع الحكم القاطع."""
    if oil_chg is None:
        return "flat", "na", ""
    if abs(oil_chg) <= OIL_BAND:
        return "flat", "flat", "تغير طفيف"
    es_up = es_chg is not None and es_chg > 0.1
    es_dn = es_chg is not None and es_chg < -0.1
    vix_up = vix_chg is not None and vix_chg > 3.0
    vix_ok = vix_chg is not None and vix_chg <= 3.0
    dxy_up = dxy_chg is not None and dxy_chg > 0.15
    if oil_chg > 0:
        if geo_supply and not es_up:
            return "bear", "supply", "صعود النفط مع أخبار إمداد/طاقة: صدمة عرض تضغط على الأسهم"
        if es_up and vix_ok and not dxy_up:
            return "flat", "demand_up", "صعود النفط مع صعود الأسهم: يشبه تحسن الطلب، أثره مختلط"
        return "flat", "unclear", "صعود النفط بسبب غير واضح: أثره مشروط بالسبب"
    if es_dn and vix_up:
        return "bear", "demand_down", "هبوط النفط مع هبوط الأسهم وصعود VIX: ضعف طلب/تجنب مخاطرة"
    if geo_relief or (es_up and vix_ok):
        return "bull", "relief", "هبوط النفط مع تهدئة أو صعود الأسهم: يخفف ضغط التكلفة"
    return "flat", "unclear", "هبوط النفط بسبب غير واضح: أثره مشروط بالسبب"


def geo_flags(geo):
    """(إمداد/طاقة، تهدئة) من تفاصيل الجيوسياسة الحية. geo = report['geo'] أو None."""
    top = (geo or {}).get("top") or []
    supply = any("energy" in (t.get("cats") or []) or "طاقة" in (t.get("cats") or []) for t in top if not t.get("deesc"))
    relief = bool(top) and top[0].get("deesc") is True
    return supply, relief


TONE_AR = {"bear": "ضغط على الأسهم", "bull": "دعم للأسهم", "flat": "أثر محدود"}


def tone(key, change):
    """'bear' ضغط، 'bull' دعم، 'flat' لا أثر يُذكر. المفتاح غير المعروف أو التغير None → 'flat'."""
    spec = POLARITY.get(key)
    if spec is None or change is None:
        return "flat"
    pol, band, _, _ = spec
    eff = pol * change
    if eff > band:
        return "bull"
    if eff < -band:
        return "bear"
    return "flat"


def arrow(change, band=0.0):
    if change is None or abs(change) <= band:
        return "◆"
    return "▲" if change > 0 else "▼"


def strength(key, change):
    """كم ضعف نطاق «لا تغيير» تحركت القيمة (مقصوص عند 5)."""
    spec = POLARITY.get(key)
    if spec is None or change is None:
        return 0.0
    return min(5.0, abs(change) / spec[1])


def _fmt(unit, v):
    if unit == "bp":
        return f"{v:+.0f}bp"
    if unit == "pt":
        return f"{v:+.2f}"
    return f"{v:+.2f}%"


def drivers(p, fred=None, macro_view=None, geo=None):
    """عوامل ذات اتجاه واضح: [{key,name,val,tone,arrow,strength,text}] مرتبة بالقوة. لا تُبنى إلا من بيانات حقيقية متاحة."""
    p = p or {}
    out = []

    def add(key, change, last_txt=""):
        spec = POLARITY[key]
        t = tone(key, change)
        out.append({"key": key, "name": spec[3], "val": _fmt(spec[2], change), "tone": t, "arrow": arrow(change, spec[1]),
                    "strength": round(strength(key, change), 2), "last": last_txt,
                    "text": f"{last_txt + ' ' if last_txt else ''}{arrow(change, spec[1])} {_fmt(spec[2], change)} — {TONE_AR[t]}"})

    d = p.get("dxy")
    if d:
        add("dxy", d["chg1"], f"{d['last']:.2f}")
    for k, nm in (("y10", "10Y"), ("y30", "30Y")):
        y = p.get(k)
        if y:
            add(k, y["diff1"] * 100, f"{y['last']:.2f}%")
    o = p.get("oil")
    if o:
        gs, gr = geo_flags(geo)
        t, cause, why = oil_cause(o["chg1"], (p.get("es") or {}).get("chg1"), (p.get("dxy") or {}).get("chg1"),
                                  (p.get("vix") or {}).get("chg1"), gs, gr)
        ch = o["chg1"]
        out.append({"key": "oil", "name": "النفط", "val": _fmt("pct", ch), "tone": t, "arrow": arrow(ch, OIL_BAND), "cause": cause,
                    "strength": round(min(5.0, abs(ch) / OIL_BAND) if t != "flat" else 0.0, 2), "last": f"{o['last']:.2f}$",
                    "text": f"{o['last']:.2f}$ {arrow(ch, OIL_BAND)} {_fmt('pct', ch)} — {why or TONE_AR[t]}"})
    v = p.get("vix")
    if v:
        add("vix", v["chg1"], f"{v['last']:.1f}")
    oas = (fred or {}).get("hy_oas")
    if oas and len(oas) >= 6:
        add("hy_oas", oas[-1][1] - oas[-6][1], f"{oas[-1][1]:.2f}%")
    nl = (macro_view or {}).get("net_liquidity")
    if nl:
        add("net_liq", nl["chg_pct"], f"{nl['net_bn']:,.0f}B$")
    out.sort(key=lambda d: -d["strength"])
    return out


def liquidity_view(nl):
    """شرح السيولة الصافية (WALCL − TGA − RRP) واتجاهها وتأثيرها على الأسهم."""
    if not nl:
        return None
    c = nl["chg_pct"]
    t = tone("net_liq", c)
    meaning = {
        "bull": ("ضخّ سيولة: ازداد النقد المتاح في النظام المالي خلال 4 أسابيع (الفدرالي يوسّع ميزانيته، أو الخزانة تنفق من حسابها، "
                 "أو تنخفض أموال RRP). عادةً يدعم الأصول عالية المخاطر ومنها الأسهم."),
        "bear": ("سحب سيولة: انكمش النقد المتاح في النظام المالي خلال 4 أسابيع (الفدرالي يقلّص ميزانيته، أو الخزانة تجمع النقد في حسابها، "
                 "أو ترتفع أموال RRP). عادةً يضغط على الأصول عالية المخاطر ومنها الأسهم."),
        "flat": "السيولة شبه ثابتة خلال 4 أسابيع: لا ضخّ ولا سحب يُذكر.",
    }[t]
    word = {"bull": "ضخّ", "bear": "سحب", "flat": "ثابتة"}[t]
    return {"tone": t, "word": word, "arrow": arrow(c, POLARITY["net_liq"][1]), "chg": round(c, 2),
            "net_bn": round(nl["net_bn"]), "meaning": meaning, "as_of": nl.get("as_of", "")}


def regime(m):
    """النظام الاقتصادي السائد من ركائز المنظومة (التضخم، العمل، النمو). None إن لم تكف الركائز.
    السهم ▲ في ركيزة = ضغط متشدد (تضخم مرتفع / عمل قوي...)، ▼ = متساهل. وصف تقريبي وليس نموذجاً إحصائياً."""
    if not m:
        return None
    by = {x["key"]: x for x in m.get("pillars", [])}
    infl, lab, gro = by.get("inflation"), by.get("labor"), by.get("growth")
    if not infl or not lab:
        return None
    i, l = infl["s"], lab["s"]
    g = gro["s"] if gro else 0.0
    if i >= 0.3 and l <= -0.3:
        k, txt = "stagflation", "تضخم عنيد مع ضعف في سوق العمل (أقرب لركود تضخمي): أصعب بيئة للفدرالي"
    elif i >= 0.3 and l >= 0.3:
        k, txt = "overheating", "اقتصاد ساخن: تضخم مرتفع وسوق عمل قوي، فالميل للتشدد أو تأجيل التيسير"
    elif i <= -0.3 and l <= -0.3:
        k, txt = "slowdown", "تباطؤ مع تراجع التضخم: بيئة داعمة لخفض الفائدة"
    elif i <= -0.3 and l >= 0.3:
        k, txt = "goldilocks", "تضخم يهدأ مع سوق عمل متماسك: أقرب لهبوط ناعم"
    elif abs(i) < 0.3 and abs(l) < 0.3:
        k, txt = "mixed", "إشارات اقتصادية مختلطة بلا نظام سائد واضح"
    else:
        k, txt = "transition", "بيئة انتقالية: ركيزة واحدة فقط تميل بوضوح"
    return {"key": k, "text": txt, "inflation": round(i, 2), "labor": round(l, 2), "growth": round(g, 2)}


def intensity(drv):
    """حدة الاتجاه (0-10) = متوسط قوة أقوى 3 عوامل اتجاهية × 2 (القوة مقصوصة عند 5). تقدير تجريبي غير معايَر."""
    top = sorted((d["strength"] for d in drv if d["tone"] != "flat"), reverse=True)[:3]
    if not top:
        return 0.0
    return round(min(10.0, sum(top) / len(top) * 2.0), 1)
