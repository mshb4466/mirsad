#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — قراءة الأحداث الاقتصادية بالقواعد: ماذا يقيس الحدث، ماذا يتوقع السوق مقارنة بالسابق،
وماذا يعني (أعلى / مطابق / أقل) من المتوقع لـ ES. قواعد عامة تقريبية وليست توقعاً مضمونا؛
ردّ فعل السوق الفعلي يعتمد على السياق ودرجة المفاجأة.
"""
import re

# (نمط بالعنوان, النوع, الاسم العربي, ماذا يقيس)
RULES = [
    (r"federal funds rate|fomc statement|interest rate decision", "rate", "قرار الفائدة (FOMC)", "قرار الفدرالي بشأن سعر الفائدة وبيانه"),
    (r"fomc press conference|powell", "speech", "مؤتمر/كلمة رئيس الفدرالي", "نبرة الفدرالي ومسار الفائدة القادم"),
    (r"fomc.*minutes|minutes", "speech", "محضر اجتماع الفدرالي", "تفاصيل نقاش الفدرالي ونبرته"),
    (r"fed .*speak|speaks|speech|testif", "speech", "كلمة مسؤول في الفدرالي", "إشارات حول الفائدة من مسؤول الفدرالي"),
    (r"core pce", "infl", "PCE الأساسي", "مقياس التضخم المفضّل لدى الفدرالي (دون الغذاء والطاقة)"),
    (r"pce", "infl", "مؤشر PCE", "التضخم حسب إنفاق المستهلك، مقياس الفدرالي المفضّل"),
    (r"core cpi", "infl", "CPI الأساسي", "تضخم أسعار المستهلك دون الغذاء والطاقة"),
    (r"\bcpi\b", "infl", "مؤشر أسعار المستهلك CPI", "التضخم على مستوى المستهلك"),
    (r"core ppi", "infl", "PPI الأساسي", "تضخم أسعار المنتجين دون الغذاء والطاقة"),
    (r"\bppi\b", "infl", "مؤشر أسعار المنتجين PPI", "التضخم على مستوى المنتجين"),
    (r"average hourly earnings|employment cost", "infl", "نمو الأجور", "ضغوط الأجور وتأثيرها على التضخم"),
    (r"non-?farm|nfp", "labor", "الوظائف غير الزراعية NFP", "عدد الوظائف المضافة في الاقتصاد الأمريكي"),
    (r"adp", "labor", "وظائف القطاع الخاص ADP", "تقدير مسبق لوظائف القطاع الخاص"),
    (r"jolts|job openings", "labor", "الوظائف الشاغرة JOLTS", "طلب الشركات على العمالة"),
    (r"unemployment rate", "unemp", "معدل البطالة", "نسبة العاطلين عن العمل"),
    (r"jobless claims|unemployment claims", "unemp", "طلبات إعانة البطالة", "عدد المسرَّحين الجدد أسبوعياً"),
    (r"gdp", "growth", "الناتج المحلي GDP", "نمو الاقتصاد الأمريكي"),
    (r"retail sales", "growth", "مبيعات التجزئة", "قوة إنفاق المستهلك"),
    (r"ism|pmi|empire state|philly fed|durable goods|industrial production", "growth", "مؤشر نشاط اقتصادي", "قوة النشاط الصناعي/الخدمي"),
    (r"consumer (sentiment|confidence)|michigan", "sent", "ثقة المستهلك", "تفاؤل المستهلك وتوقعاته للتضخم"),
    (r"crude oil inventor|crude oil stocks|eia crude|oil inventor", "oil", "مخزونات النفط الخام", "تغير مخزون النفط الأمريكي، يحرك أسعار الطاقة ومنها توقعات التضخم"),
    (r"treasury.*auction|bond auction|note auction|bill auction|tips auction|frn auction|\d+-y(?:ear)? (?:note|bond|tips)|\d+-w(?:eek)? bill", "auction", "مزاد سندات الخزانة", "الطلب على الدين الأمريكي وتأثيره على العوائد (خصوصاً الطرف الطويل)"),
    (r"housing|home sales|building permits", "housing", "بيانات الإسكان", "حالة قطاع العقار وحساسيته للفائدة"),
]

TEXT = {
    "infl": ("تضخم أعند، ترتفع توقعات التشديد والعوائد والدولار، والمعتاد ضغط على ES وخاصة التقنية.",
             "تأثير محدود غالباً، والسوق يقرأ التفاصيل (الأساسي والخدمات والإسكان).",
             "يخفف ضغط الفائدة وتنخفض العوائد، والمعتاد دعم لـ ES.",
             "تضخم أعلى = سلبي لـ ES عادة"),
    "labor": ("سوق عمل قوي يرفع العوائد وقد يؤخر خفض الفائدة، فيضغط على ES إن كان الفدرالي متشدداً.",
              "تأثير محدود، والانتباه للأجور ومراجعات الأشهر السابقة.",
              "تُرجَّح الفائدة الأقل فيرتاح ES أولاً، لكن الضعف الكبير يثير قلق الركود فينقلب الاتجاه.",
              "قوي = عوائد أعلى، ضعف كبير = قلق ركود"),
    "unemp": ("ضعف في سوق العمل، يدعم خفض الفائدة وقد يرفع قلق الركود.",
              "تأثير محدود.",
              "سوق عمل متماسك، عوائد أعلى وفائدة أعلى لفترة أطول، وقد يضغط على ES إن كان الفدرالي متشدداً.",
              "رقم أعلى = سوق عمل أضعف"),
    "growth": ("نمو جيد يدعم الأرباح، لكنه قد يرفع العوائد فيكون الأثر مختلطاً على ES.",
               "تأثير محدود.",
               "يغذي توقعات خفض الفائدة، لكن الضعف الحاد يقلق السوق من تباطؤ الاقتصاد.",
               "قوي = أرباح أفضل لكن عوائد أعلى"),
    "sent": ("تفاؤل المستهلك يدعم الإنفاق، وانتبه لتوقعات التضخم داخل المؤشر.",
             "تأثير محدود.",
             "قلق على الإنفاق، وإن انخفضت توقعات التضخم فالصورة أهدأ للفائدة.",
             "تأثير متوسط، وتوقعات التضخم أهم"),
    "rate": ("ضغط واضح على ES وتقلب عالٍ.",
             "يتحرك السوق على نبرة البيان والمؤتمر الصحفي وتوقعات الاجتماعات التالية.",
             "دعم لـ ES، لكن انتبه لسبب التيسير إن كان خوفاً من تباطؤ.",
             "حدث الأعلى تأثيراً، والتقلب حوله مرتفع"),
    "speech": ("ضغط على ES وارتفاع العوائد.",
               "تأثير محدود.",
               "دعم لـ ES.",
               "الأثر يعتمد على النبرة لا على رقم"),
    "auction": ("ضغط على الأسهم.",
                "تأثير محدود.",
                "يريح الأسهم.",
                "مزاد الخزانة يؤثر عبر العوائد"),
    "oil": ("بناء مخزون أكبر من المتوقع يضغط على النفط، وهبوط النفط يخفف توقعات التضخم ويدعم ES عادة (مع ضعف قطاع الطاقة).",
            "تأثير محدود.",
            "سحب أكبر من المتوقع يدعم النفط، وصعوده يرفع توقعات التضخم والعوائد فيضغط على ES.",
            "أثره على ES غير مباشر: عبر النفط ثم التضخم والعوائد"),
    "housing": ("قطاع العقار يتحمل الفائدة، تأثير محدود على ES.",
                "تأثير محدود.",
                "أثر محدود غالباً على ES.",
                "حدث ثانوي لـ ES عادة"),
}
SHORT = {
    "infl": ("أعلى=ضغط على ES", "أقل=دعم"), "labor": ("أقوى=عوائد أعلى (ضغط محتمل)", "أضعف=دعم أولاً ثم قلق ركود"),
    "unemp": ("أعلى=ضعف عمل، دعم للفائدة الأقل", "أقل=عوائد أعلى"), "growth": ("أقوى=مختلط", "أضعف=دعم للفائدة الأقل"),
    "sent": ("أعلى=إيجابي", "أقل=سلبي"), "rate": ("أشد تشدداً=ضغط", "أكثر تيسيراً=دعم"),
    "speech": ("متشددة=ضغط", "تيسيرية=دعم"), "auction": ("طلب ضعيف=ضغط", "طلب قوي=دعم"), "housing": ("ثانوي", "ثانوي"),
    "oil": ("بناء مخزون=نفط أضعف (دعم لـ ES)", "سحب مخزون=نفط أقوى (ضغط تضخمي)"),
}


def _num(s):
    if not s:
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(s).replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def _unit(s):
    m = re.search(r"[%KMBT]", str(s or ""))
    return m.group(0) if m else ""


def _fmt(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _is_ratio(ev):
    """مزاد تُقاس نتيجته بنسبة التغطية (بدون %)، فالأعلى أفضل للأسهم، عكس العائد."""
    for k in ("actual", "forecast", "previous"):
        v = str(ev.get(k) or "")
        if v:
            return "%" not in v and "|" not in v
    return False


def classify(title):
    t = (title or "").lower()
    for pat, kind, name, what in RULES:
        if re.search(pat, t):
            return kind, name, what
    return None, None, None


def expectation(forecast, previous):
    f, p = _num(forecast), _num(previous)
    if f is None or p is None:
        return ""
    u = _unit(forecast) or _unit(previous)
    d = f - p
    if abs(d) < 1e-9:
        return "السوق يتوقع نفس قراءة السابق"
    return f"السوق يتوقع قراءة {'أعلى' if d > 0 else 'أقل'} من السابق بـ {_fmt(abs(d))}{u}"


def surprise(actual, forecast):
    a, f = _num(actual), _num(forecast)
    if a is None or f is None:
        return ""
    if abs(a - f) < 1e-9:
        return "مطابق للتوقع"
    return ("أعلى" if a > f else "أقل") + f" من المتوقع بـ {_fmt(abs(a - f))}{_unit(actual)}"


def vs_previous(actual, previous):
    a, p = _num(actual), _num(previous)
    if a is None or p is None:
        return ""
    if abs(a - p) < 1e-9:
        return "نفس قراءة السابق"
    return f"{'أعلى' if a > p else 'أقل'} من السابق بـ {_fmt(abs(a - p))}{_unit(actual)}"


def combined(actual, forecast, previous):
    """قراءة مشتركة: الفعلي مقابل المتوقع ومقابل السابق معاً."""
    a, f, p = _num(actual), _num(forecast), _num(previous)
    if a is None or f is None or p is None:
        return ""
    sf = 0 if abs(a - f) < 1e-9 else (1 if a > f else -1)
    sp = 0 if abs(a - p) < 1e-9 else (1 if a > p else -1)
    if sf > 0 and sp > 0:
        return "الفعلي فوق المتوقع وفوق السابق: مفاجأة مع اتجاه متصاعد، فالأثر في اتجاه «أعلى من المتوقع» أقوى من المعتاد."
    if sf < 0 and sp < 0:
        return "الفعلي دون المتوقع ودون السابق: مفاجأة مع اتجاه متراجع، فالأثر في اتجاه «أقل من المتوقع» أقوى من المعتاد."
    if sf > 0 and sp <= 0:
        return "الفعلي فوق المتوقع لكنه لم يتجاوز السابق: السوق كان يتوقع تراجعاً أكبر، فالمفاجأة موجودة لكن الاتجاه العام لم ينقلب، والأثر أخف."
    if sf < 0 and sp >= 0:
        return "الفعلي دون المتوقع لكنه لم ينزل عن السابق: خيبة نسبية فقط، والأثر أخف من مفاجأة سلبية كاملة."
    if sf == 0 and sp != 0:
        return "مطابق للمتوقع، والتغير عن السابق كان مسعَّراً مسبقاً، فرد الفعل غالباً محدود."
    return "لا مفاجأة ولا تغيير ملحوظ، رد الفعل غالباً محدود."


# السيناريو الأخطر على ES حسب نوع الحدث (hawk = ميل الفدرالي متشدد)
WORST = {"infl": ("above", "above"), "labor": ("above", "below"), "unemp": ("below", "above"),
         "growth": ("above", "below"), "rate": ("above", "above"), "speech": ("above", "above"), "auction": ("above", "above"),
         "oil": ("below", "below")}


PILLARS = {"infl": ["inflation", "taylor"], "labor": ["labor"], "unemp": ["labor"], "growth": ["growth", "fincond"],
           "rate": ["dots", "taylor"], "speech": ["dots"], "auction": ["fincond"], "sent": ["inflation"], "oil": ["energy", "inflation"]}
# أي اتجاه (أعلى من المتوقع) يدفع نحو التشدد؟ +1 نعم، -1 يدفع نحو التيسير
HAWK_DIR = {"infl": 1, "labor": 1, "unemp": -1, "growth": 1, "rate": 1, "speech": 1, "auction": 1, "sent": 1, "oil": -1}


# أثر كل سيناريو (أعلى، مطابق، أقل) على ES: bear ضغط، bull دعم، neu محايد — (حالة متشدد، غير متشدد)
EFFECT = {"infl": (("bear", "neu", "bull"),) * 2, "labor": (("bear", "neu", "bull"), ("bull", "neu", "bear")),
          "unemp": (("bull", "neu", "bear"), ("bear", "neu", "bull")), "growth": (("bear", "neu", "bull"), ("bull", "neu", "bear")),
          "rate": (("bear", "neu", "bull"),) * 2, "speech": (("bear", "neu", "bull"),) * 2, "auction": (("bear", "neu", "bull"),) * 2,
          "sent": (("bull", "neu", "bear"),) * 2, "oil": (("bull", "neu", "bear"),) * 2, "housing": (("neu", "neu", "neu"),) * 2}


def build_ctx(report):
    """يستخرج سياق المنظومة من التقرير: الفدرالي، المخاطرة، التقلب، موقع السعر من المزاد."""
    report = report or {}
    risk, au = report.get("risk") or {}, report.get("auction") or {}
    return {"macro": report.get("macro") or {}, "score": risk.get("score"), "level": risk.get("level"),
            "vix": ((report.get("data") or {}).get("vix") or {}).get("last"), "loc": au.get("location")}


def system_lines(kind, ev, ctx):
    """يربط الحدث بالمنظومة الكلية وبحالة ES الآن. يعيد (سطور السياق, سطر الأثر بعد الصدور)."""
    ctx = ctx or {}
    m = ctx.get("macro") or {}
    lines, effect = [], ""
    if not m or kind not in PILLARS:
        return lines, effect
    by = {p["key"]: p for p in m.get("pillars", [])}
    for k in PILLARS[kind]:
        p = by.get(k)
        if p:
            lines.append(f"{p['name']} الآن {p['arrow']}: {p['note']}")
    lines.append(f"ميل الفدرالي العام: {m.get('label', '')} (ثقة {m.get('confidence', '—')})"
                 + (" مع تعارض بين التضخم والعمل، فالقرارات أقل قابلية للتوقع" if m.get("dilemma") else ""))
    gap = m.get("gap")
    g = (gap or {}).get("value")
    if gap and gap.get("size") != "صغيرة":
        lines.append("فجوة التسعير: " + gap["direction"])
    mt = m.get("meeting")
    if mt:
        lines.append(f"الاجتماع القادم بعد {mt['days']} يوماً ({mt['date']}): هذه البيانات تدخل في حسابه")
    es = []
    if ctx.get("score") is not None:
        es.append(f"مخاطرة السوق {ctx['score']} ({ctx.get('level') or '—'})")
    if ctx.get("vix"):
        es.append(f"VIX {ctx['vix']:.1f}")
    loc = {"above_value": "ES فوق قيمة الأمس", "below_value": "ES تحت قيمة الأمس", "inside_value": "ES داخل قيمة الأمس"}.get(ctx.get("loc"))
    if loc:
        es.append(loc)
    if es:
        lines.append("حالة ES الآن: " + "، ".join(es))
    # أثر النتيجة على المنظومة بعد الصدور
    a, f = _num(ev.get("actual")), _num(ev.get("forecast"))
    if a is not None and f is not None and abs(a - f) > 1e-9:
        hawk = (1 if a > f else -1) * HAWK_DIR.get(kind, 1) * (-1 if kind == 'auction' and _is_ratio(ev) else 1)
        side = "متشدد" if hawk > 0 else "متساهل"
        cur = m.get("lean", 0)
        if (cur > 0.15 and hawk > 0) or (cur < -0.15 and hawk < 0):
            effect = f"النتيجة تدفع في اتجاه {side} وهو نفس ميل المنظومة الحالي، فتزيد قناعة السوق بهذا المسار."
        elif (cur > 0.15 and hawk < 0) or (cur < -0.15 and hawk > 0):
            effect = f"النتيجة تدفع في اتجاه {side} عكس ميل المنظومة الحالي ({m.get('label', '')})، فتخفف الميل لكنها وحدها لا تقلبه."
        else:
            effect = f"النتيجة تدفع في اتجاه {side} والمنظومة محايدة نسبياً، فقد تكون هذه البيانات مرجّحة للاتجاه القادم."
        if g is not None and gap.get("size") != "صغيرة":
            if g > 0 and hawk > 0:
                effect += " والسوق مسعّر للتيسير أكثر من المبرَّر، فهذه المفاجأة المتشددة أخطر من المعتاد."
            elif g < 0 and hawk < 0:
                effect += " والسوق مسعّر للتشدد أكثر من المبرَّر، فهذه المفاجأة المتساهلة قد تحرك السوق أكثر من المعتاد."
    return lines, effect


AUCTION_KIND = (("tips", "سندات محمية من التضخم (TIPS)"), ("frn", "سندات بفائدة عائمة (FRN)"))


def auction_name(title):
    """اسم مزاد الخزانة مع مدته ونوعه: «مزاد 10 سنوات — سندات متوسطة الأجل (Note)». None إن لم يُتعرَّف عليه."""
    t = (title or "").lower()
    kind = next((ar for k, ar in AUCTION_KIND if k in t), None)
    m = re.search(r"(\d+)\s*-?\s*(?:y|yr|year)", t)
    w = re.search(r"(\d+)\s*-?\s*(?:w|wk|week)", t)
    if w and ("bill" in t or not m):
        return f"مزاد أذون خزانة {int(w.group(1))} أسبوعاً — قصيرة الأجل (Bills)"
    if not m:
        return None
    n = int(m.group(1))
    if kind is None:
        # التقويم يسمّي الجميع «Bond Auction»؛ التصنيف الرسمي بالمدة: 2–10 سنوات Notes، و20/30 Bonds
        kind = "سندات متوسطة الأجل (Notes)" if n <= 10 else "سندات طويلة الأجل (Bonds)"
    return f"مزاد {n} سنوات — {kind}"


def describe(ev, hhmm_baghdad, macro_label="", ctx=None):
    kind, name, what = classify(ev.get("title", ""))
    if kind == "auction":
        name = auction_name(ev.get("title", "")) or name
    d = {"kind": kind or "", "actual_note": ev.get("actual_note", ""), "time": hhmm_baghdad, "title": ev.get("title", ""), "high": ev.get("impact") == "High",
         "forecast": ev.get("forecast", ""), "previous": ev.get("previous", ""), "actual": ev.get("actual", ""),
         "name": name or ev.get("title", ""), "what": what or "", "expect": expectation(ev.get("forecast"), ev.get("previous")),
         "surprise": surprise(ev.get("actual"), ev.get("forecast")) if ev.get("actual") else "", "scenarios": [], "note": "", "short": "", "vs_prev": vs_previous(ev.get("actual"), ev.get("previous")) if ev.get("actual") else "",
         "likely": "", "worst": "",
         "system": [], "system_effect": "",
         "combined": combined(ev.get("actual"), ev.get("forecast"), ev.get("previous")) if ev.get("actual") else ""}
    if ctx is not None:
        d["system"], d["system_effect"] = system_lines(kind, ev, ctx)
        m = (ctx or {}).get("macro") or {}
        by = {p["key"]: p for p in m.get("pillars", [])}
        pk = next((by[k] for k in PILLARS.get(kind, []) if k in by), None)
        if m and pk:
            d["chain"] = [{"t": name or ev.get("title", ""), "s": "الحدث"}, {"t": f"{pk['name']} {pk['arrow']}", "s": "الركيزة الآن"},
                          {"t": m.get("label", ""), "s": "ميل الفدرالي"}]
    if kind in TEXT:
        up, mid, down, note = TEXT[kind]
        d["scenarios"] = [{"k": "above", "label": "أعلى من المتوقع", "text": up},
                          {"k": "inline", "label": "مطابق", "text": mid},
                          {"k": "below", "label": "أقل من المتوقع", "text": down}]
        d["note"] = note
        d["short"] = " | ".join(SHORT[kind])
        if kind == "speech":
            for sc, lab in zip(d["scenarios"], ("نبرة متشددة", "نبرة محايدة", "نبرة تيسيرية")):
                sc["label"] = lab
        if kind == "auction" and _is_ratio(ev):
            d["scenarios"] = [{"k": "above", "label": "أعلى من المتوقع", "text": "طلب أقوى على السندات (نسبة التغطية أعلى)، يريح العوائد ويدعم الأسهم."},
                              {"k": "inline", "label": "مطابق", "text": "تأثير محدود."},
                              {"k": "below", "label": "أقل من المتوقع", "text": "طلب أضعف، ترتفع العوائد وتضغط على الأسهم."}]
            d["short"] = "تغطية أعلى=دعم | أضعف=ضغط"
        hawk = "متشدد" in (macro_label or "")
        eff = EFFECT.get(kind, (("neu",) * 3,) * 2)[0 if hawk else 1]
        if kind == "auction" and _is_ratio(ev):
            eff = ("bull", "neu", "bear")
        for sc, ef in zip(d["scenarios"], eff):
            sc["es"] = ef
        if kind in WORST:
            d["worst"] = WORST[kind][0 if hawk else 1]
        fv, pv = _num(ev.get("forecast")), _num(ev.get("previous"))
        d["likely"] = "inline"
        gap = ""
        if fv is not None and pv is not None and pv != 0 and abs(fv - pv) / abs(pv) >= 0.25:
            gap = "الفجوة بين التوقع والسابق كبيرة، فاحتمال المفاجأة أعلى من المعتاد."
        d["likely_note"] = ("الأرجح أن يأتي الرقم قريباً من المتوقع لأنه متوسط تقديرات المحللين، "
                            "لكن تأثير السوق الأكبر يأتي من المفاجأة. " + gap).strip()
        if ev.get("actual"):
            a, f = _num(ev.get("actual")), fv
            if a is not None and f is not None:
                d["hit"] = "inline" if abs(a - f) < 1e-9 else ("above" if a > f else "below")
        if "متشدد" in (macro_label or "") and kind in ("labor", "growth", "unemp"):
            d["note"] += " — الفدرالي الآن ميله متشدد، فالأرقام القوية أميل لأن تُقرأ سلبية للأسهم."
        elif "متساهل" in (macro_label or "") and kind in ("labor", "growth"):
            d["note"] += " — ميل الفدرالي متساهل، فالأرقام القوية أقل ضغطاً."
    elif ev.get("impact") == "High":
        d["note"] = "حدث عالي التأثير بلا قاعدة محددة؛ راقب رد فعل السعر والعوائد بعد الصدور."
    return d


def interpret_release(ev, macro_label="", ctx=None):
    """بعد الصدور: نص المفاجأة ومعناها المعتاد لـ ES (قاعدة عامة)."""
    d = describe(ev, "", macro_label, ctx)
    a, f = _num(ev.get("actual")), _num(ev.get("forecast"))
    key = None
    if a is not None and f is not None:
        key = "inline" if abs(a - f) < 1e-9 else ("above" if a > f else "below")
    meaning = next((s["text"] for s in d["scenarios"] if s["k"] == key), "")
    return {"surprise": d["surprise"], "vs_prev": d["vs_prev"], "combined": d["combined"], "system": d["system"], "system_effect": d["system_effect"], "meaning": meaning, "note": d["note"], "name": d["name"]}


GROUP_NAME = {"speech": "الفدرالي: محضر وكلمات", "auction": "مزادات سندات الخزانة", "oil": "مخزونات النفط الخام",
              "infl": "التضخم", "labor": "سوق العمل", "unemp": "البطالة", "growth": "النمو", "sent": "ثقة المستهلك",
              "rate": "قرار الفائدة", "housing": "الإسكان"}
ALWAYS = ("oil", "auction", "speech")


def relevant(ev):
    """الأحداث المهمة لـ ES: العالية والمتوسطة، إضافة إلى النفط والمزادات والفدرالي حتى لو صُنّفت منخفضة."""
    if ev.get("impact") in ("High", "Medium"):
        return True
    kind, _, _ = classify(ev.get("title", ""))
    return kind in ALWAYS


ITEM_KEYS = ("day", "time", "title", "name", "high", "forecast", "previous", "actual", "surprise", "vs_prev", "combined", "hit", "actual_note")


def group(descs):
    """يجمع الأحداث من نفس النوع: الشرح والسيناريوهات مرة واحدة، وتبقى أرقام كل حدث منفصلة."""
    order, groups = [], {}
    for i, d in enumerate(descs):
        k = d.get("kind") or f"_{i}"
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(d)
    out = []
    for k in order:
        ds = groups[k]
        if len(ds) == 1:
            g = dict(ds[0])
            g["items"] = []
            out.append(g)
            continue
        g = dict(ds[0])
        g["name"] = GROUP_NAME.get(ds[0].get("kind"), ds[0]["name"])
        g["time"] = ds[0]["time"]
        g["high"] = any(x["high"] for x in ds)
        for key in ("forecast", "previous", "actual", "surprise", "vs_prev", "combined", "expect"):
            g[key] = ""
        g.pop("hit", None)
        g["items"] = [{kk: x.get(kk) for kk in ITEM_KEYS if kk in x} for x in ds]
        out.append(g)
    return out


HAWK_WORDS = ("hawkish", "higher for longer", "no rush to cut", "rate hike", "raise rates", "more tightening", "inflation risk",
              "inflation remains", "sticky inflation", "restrictive", "not ready to cut", "fewer cuts", "slow the pace of cuts", "upside risks to inflation")
DOVE_WORDS = ("dovish", "rate cut", "cut rates", "cuts rates", "further cuts", "ease policy", "easing", "labor market weak", "weakening labor",
              "downside risks", "slowdown", "lower rates", "support the labor market", "more cuts", "reduce rates")


def fed_tone(headlines):
    """نبرة تقريبية من عناوين الأخبار بقائمة كلمات: (hawk|dove|unclear، عدد الإشارات). ليست فهماً للنص."""
    h = d = 0
    for t in headlines or []:
        low = (t or "").lower()
        h += sum(1 for w in HAWK_WORDS if w in low)
        d += sum(1 for w in DOVE_WORDS if w in low)
    if h > d:
        return "hawk", h - d
    if d > h:
        return "dove", d - h
    return "unclear", 0


def market_tone(react):
    """قراءة استقبال السوق من العوائد والدولار بعد الحدث: ارتفاعهما معاً = متشددة، انخفاضهما = تيسيرية."""
    y, x = (react or {}).get("y10"), (react or {}).get("dxy")
    if y is None or x is None:
        return "unclear"
    if y >= 2 and x >= 0.05:
        return "hawk"
    if y <= -2 and x <= -0.05:
        return "dove"
    return "unclear"


def speech_outcome(headlines, react):
    """يجمع نبرة العناوين واستقبال السوق: يعيد (k: above|inline|below، شرح قصير)."""
    ht, _ = fed_tone(headlines)
    mt = market_tone(react)
    tone = mt if mt != "unclear" else ht
    if mt != "unclear" and ht != "unclear" and mt != ht:
        tone = mt            # السوق أصدق من العناوين
    k = {"hawk": "above", "dove": "below"}.get(tone, "inline")
    basis = []
    if ht != "unclear":
        basis.append("عناوين " + ("متشددة" if ht == "hawk" else "تيسيرية"))
    if mt != "unclear":
        basis.append("العوائد والدولار " + ("ارتفعا" if mt == "hawk" else "انخفضا"))
    return k, "، ".join(basis) or "لا إشارة واضحة من العناوين ولا من العوائد والدولار"
