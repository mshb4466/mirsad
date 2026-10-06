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
    (r"treasury.*auction|bond auction|note auction", "auction", "مزاد سندات الخزانة", "الطلب على الدين الأمريكي وتأثيره على العوائد"),
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


# السيناريو الأخطر على ES حسب نوع الحدث (hawk = ميل الفدرالي متشدد)
WORST = {"infl": ("above", "above"), "labor": ("above", "below"), "unemp": ("below", "above"),
         "growth": ("above", "below"), "rate": ("above", "above"), "speech": ("above", "above"), "auction": ("above", "above")}


def describe(ev, hhmm_baghdad, macro_label=""):
    kind, name, what = classify(ev.get("title", ""))
    d = {"time": hhmm_baghdad, "title": ev.get("title", ""), "high": ev.get("impact") == "High",
         "forecast": ev.get("forecast", ""), "previous": ev.get("previous", ""), "actual": ev.get("actual", ""),
         "name": name or ev.get("title", ""), "what": what or "", "expect": expectation(ev.get("forecast"), ev.get("previous")),
         "surprise": surprise(ev.get("actual"), ev.get("forecast")) if ev.get("actual") else "", "scenarios": [], "note": "", "short": "", "vs_prev": vs_previous(ev.get("actual"), ev.get("previous")) if ev.get("actual") else "",
         "likely": "", "worst": ""}
    if kind in TEXT:
        up, mid, down, note = TEXT[kind]
        d["scenarios"] = [{"k": "above", "label": "أعلى من المتوقع", "text": up},
                          {"k": "inline", "label": "مطابق", "text": mid},
                          {"k": "below", "label": "أقل من المتوقع", "text": down}]
        d["note"] = note
        d["short"] = " | ".join(SHORT[kind])
        hawk = "متشدد" in (macro_label or "")
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


def interpret_release(ev, macro_label=""):
    """بعد الصدور: نص المفاجأة ومعناها المعتاد لـ ES (قاعدة عامة)."""
    d = describe(ev, "", macro_label)
    a, f = _num(ev.get("actual")), _num(ev.get("forecast"))
    key = None
    if a is not None and f is not None:
        key = "inline" if abs(a - f) < 1e-9 else ("above" if a > f else "below")
    meaning = next((s["text"] for s in d["scenarios"] if s["k"] == key), "")
    return {"surprise": d["surprise"], "vs_prev": d["vs_prev"], "meaning": meaning, "note": d["note"], "name": d["name"]}
