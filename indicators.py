# -*- coding: utf-8 -*-
"""
مِرصاد — الأرقام الفعلية للمؤشرات الاقتصادية من FRED (مصدر ثانٍ، لأن تقويم faireconomy المجاني لا يرسل الرقم الفعلي غالباً).

القاعدة الصارمة: لا يُعرض رقم إلا إذا كانت **فترة المشاهدة** في FRED هي الفترة التي صدر عنها الحدث فعلاً.
إن لم تتطابق (FRED لم يُحدَّث بعد) لا نعرض آخر قراءة على أنها الجديدة، بل نكتب السبب في actual_note.
كل شيء فشل ناعم. لا يُختبَر الجلب الحقيقي إلا من تشغيل GitHub.
"""
import re
from datetime import date, timedelta

# (نمط العنوان بحروف صغيرة، مفتاح السلسلة، معرّف FRED، التحويل، قاعدة فترة المشاهدة، تسمية)
SPECS = [
    (r"unemployment claims|jobless claims", "claims", "ICSA", "claims_k", "week", "طلبات إعانة البطالة الأولية"),
    (r"unemployment rate", "unrate", "UNRATE", "level_pct", "month_prev", "معدل البطالة"),
    (r"non-?farm employment change|non-?farm payrolls", "payems", "PAYEMS", "diff_k", "month_prev", "الوظائف غير الزراعية"),
    (r"average hourly earnings m/m", "ahe", "CES0500000003", "mm", "month_prev", "متوسط الأجور بالساعة"),
    (r"uom consumer sentiment", "umcsent", "UMCSENT", "level", "month_same", "ثقة المستهلك (جامعة ميشيغان)"),
    (r"uom inflation expectations", "mich", "MICH", "level_pct", "month_same", "توقعات التضخم لسنة (ميشيغان)"),
    (r"core cpi m/m", "cpilfe", "CPILFESL", "mm", "month_prev", "CPI الأساسي شهرياً"),
    (r"core cpi y/y", "cpilfe_ny", "CPILFENS", "yy", "month_prev", "CPI الأساسي سنوياً"),
    (r"\bcpi m/m", "cpi", "CPIAUCSL", "mm", "month_prev", "CPI شهرياً"),
    (r"\bcpi y/y", "cpi_ny", "CPIAUCNS", "yy", "month_prev", "CPI سنوياً"),
    (r"core pce price index m/m", "pcelfe", "PCEPILFE", "mm", "month_prev", "PCE الأساسي شهرياً"),
    (r"core pce price index y/y", "pcelfe", "PCEPILFE", "yy", "month_prev", "PCE الأساسي سنوياً"),
    (r"core ppi m/m", "ppife", "PPIFES", "mm", "month_prev", "PPI الأساسي شهرياً"),
    (r"\bppi m/m", "ppi", "PPIFIS", "mm", "month_prev", "PPI شهرياً"),
    (r"^retail sales m/m", "retail", "RSAFS", "mm", "month_prev", "مبيعات التجزئة شهرياً"),
    (r"industrial production m/m", "indpro", "INDPRO", "mm", "month_prev", "الإنتاج الصناعي شهرياً"),
    (r"jolts job openings", "jolts", "JTSJOL", "jolts_m", "month_prev2", "الوظائف الشاغرة JOLTS"),
    (r"gdp q/q", "gdp", "A191RL1Q225SBEA", "level_pct", "quarter", "الناتج المحلي (سنوي مُعدَّل)"),
]

# مؤشرات معروفة بلا مصدر مجاني تلقائي: نقول ذلك صراحة بدل الصمت
NO_FREE_SOURCE = [
    (r"cb consumer confidence|conference board", "Conference Board: غير مدعوم حالياً في مرصاد (بياناته ملكية خاصة ولا يحملها FRED، ولا مصدر مرخّص مربوط بعد)"),
    (r"\bism\b|pmi", "ISM/PMI: غير مدعوم حالياً في مرصاد (ملكية خاصة ولا يحملها FRED، ولا مصدر مرخّص مربوط بعد)"),
    (r"adp", "ADP: غير مدعوم حالياً في مرصاد (ملكية خاصة ولا يحملها FRED، ولا مصدر مرخّص مربوط بعد)"),
]

# معرّفات BLS الرسمية (SA = معدّلة موسمياً، NS = غير معدّلة تُستعمل للتغير السنوي). غير المذكور لا مصدر BLS له هنا (يبقى FRED).
BLS_IDS = {
    "unrate": "LNS14000000", "payems": "CES0000000001", "ahe": "CES0500000003",
    "cpi": "CUSR0000SA0", "cpi_ny": "CUUR0000SA0", "cpilfe": "CUSR0000SA0L1E", "cpilfe_ny": "CUUR0000SA0L1E",
    "jolts": "JTS000000000000000JOL",
}

NOTE_LAG = "مراحل التحديث: FRED قد يتأخر ساعات عن الإصدار الرسمي"


def match(title):
    """المواصفة المطابقة لعنوان الحدث أو None."""
    t = (title or "").lower().strip()
    for pat, key, sid, tr, rule, label in SPECS:
        if re.search(pat, t):
            return {"key": key, "sid": sid, "tr": tr, "rule": rule, "label": label}
    return None


def no_source_reason(title):
    t = (title or "").lower()
    for pat, why in NO_FREE_SOURCE:
        if re.search(pat, t):
            return why
    return None


def expected_obs(rule, d):
    """تاريخ المشاهدة المتوقع في FRED لحدث صدر بتاريخ d (بتوقيت نيويورك). للأسبوعي: (أدنى، أعلى) نافذة أيام."""
    if rule == "week":
        return ("week", d - timedelta(days=9), d - timedelta(days=4))
    if rule == "month_same":
        return ("exact", d.replace(day=1))
    if rule == "month_prev":
        first = d.replace(day=1)
        return ("exact", (first - timedelta(days=1)).replace(day=1))
    if rule == "month_prev2":
        first = d.replace(day=1)
        p = (first - timedelta(days=1)).replace(day=1)
        return ("exact", (p - timedelta(days=1)).replace(day=1))
    if rule == "quarter":
        return ("exact", gdp_ref_quarter(d))
    return None


# ───────── GDP: فترة التقرير ومرحلة الإصدار من جدول BEA لا من الشهر السابق ─────────
# BEA تصدر ثلاث تقديرات للربع نفسه في أشهر الربع التالي: الشهر الأول Advance، الثاني Second (Prelim في التقويم)، الثالث Third (Final).
# إذن الربع المقصود = الربع السابق للربع الذي يقع فيه شهر الإصدار (آب/أغسطس 2026 ← الربع الثاني 2026-04-01 لا 2026-07-01).
GDP_STAGES = ("advance", "second", "third")
GDP_STAGE_AR = {"advance": "التقدير المبدئي (Advance)", "second": "التقدير الثاني (Second/Preliminary)", "third": "التقدير الثالث (Third/Final)"}
GDP_PUB_WINDOW_DAYS = 3    # أقصى تأخر لسجل نسخة ALFRED عن يوم الإصدار ليُعدّ دليلاً على أنها نسخة هذا الإصدار


def gdp_ref_quarter(d):
    q_rel = (d.month - 1) // 3
    if q_rel == 0:
        return date(d.year - 1, 10, 1)
    return date(d.year, 3 * (q_rel - 1) + 1, 1)


def gdp_stage_by_schedule(d):
    return GDP_STAGES[(d.month - 1) % 3]


def gdp_stage_from_title(title):
    t = (title or "").lower()
    if "advance" in t:
        return "advance"
    if "prelim" in t or "second" in t:
        return "second"
    if "final" in t or "third" in t:
        return "third"
    return None


def gdp_info(title, d):
    """{ref, stage, ok, why}: للتعريف (معرّف الحدث) والربع المرجعي فقط. المرحلة هنا من العنوان أو جدول BEA: هوية لا دليل.
    «المرحلة المتحقَّقة» لا تُدّعى إلا بدليل نسخة الإصدار (انظر gdp_resolve)."""
    sched = gdp_stage_by_schedule(d)
    ts = gdp_stage_from_title(title)
    if ts and ts != sched:
        return {"ref": gdp_ref_quarter(d), "stage": ts, "ok": False,
                "why": f"مرحلة الإصدار في العنوان ({GDP_STAGE_AR[ts]}) لا توافق جدول BEA لشهر هذا الإصدار ({GDP_STAGE_AR[sched]}): تعذّر تحديد الربع بأمان"}
    return {"ref": gdp_ref_quarter(d), "stage": ts or sched, "ok": True, "why": ""}


def gdp_resolve(title, ev_time, et, vint, sid):
    """GDP من نسخة تاريخية (ALFRED) لا من قراءة FRED الحالية: القيمة الحالية قد تخص تقديراً أحدث من الإصدار الذي نسأل عنه.
    vint = {dates: [تواريخ نسخ السلسلة قرب الإصدار], vdate: تاريخ النسخة المعتمدة، value: قيمة الربع في تلك النسخة،
            first_seen: أول تاريخ ظهر فيه الربع في ALFRED}. الشروط:
    1) دليل نشر: نسخة مسجّلة في [تاريخ الإصدار، +3 أيام] وقيمة الربع كما كانت فيها. بدونه لا رقم.
    2) المرحلة (Advance/Second/Third) لا تُدّعى إلا بدليل: ظهور الربع أول مرة ضمن نافذة الإصدار = Advance؛ أو نص العنوان يصرّح بها
       ويوافق جدول BEA. غير ذلك: القيمة تُعرض (لها دليل نشر) والمرحلة «غير متحققة».
    لا يُستعمل حدّ عمر الحدث دليلاً."""
    out = {"value": None, "raw": None, "series": sid, "source": "FRED/ALFRED", "period": "", "stage": "", "stage_ok": False,
           "method": "قيمة الربع كما كانت في نسخة ALFRED المسجّلة يوم الإصدار", "why": "", "note": ""}
    d = ev_time.astimezone(et).date()
    gi = gdp_info(title, d)
    ref = gi["ref"]
    out["period"] = ref.isoformat()
    if not gi["ok"]:
        out["why"] = out["note"] = gi["why"]
        return out
    if not vint or vint.get("value") is None or not vint.get("vdate"):
        out["why"] = out["note"] = "لا دليل على نسخة الإصدار: لم تُجلب النسخة التاريخية (ALFRED يلزمه FRED_API_KEY)؛ قراءة FRED الحالية قد تخص تقديراً أحدث فلا تُعرض"
        return out
    try:
        vd = date.fromisoformat(str(vint["vdate"])[:10])
    except ValueError:
        out["why"] = out["note"] = "تاريخ النسخة التاريخية غير صالح"
        return out
    if not (0 <= (vd - d).days <= GDP_PUB_WINDOW_DAYS) or str(vd) not in {str(x)[:10] for x in (vint.get("dates") or [])}:
        out["why"] = out["note"] = (f"لا نسخة مسجّلة للسلسلة قرب تاريخ الإصدار {d.isoformat()} (أقربها {vd.isoformat()}): لا دليل على أن القيمة هي هذا التقدير")
        return out
    v = float(vint["value"])
    out.update(value=f"{v:.1f}%", raw=v, why="")
    fs = vint.get("first_seen")
    adv = False
    try:
        adv = fs is not None and 0 <= (date.fromisoformat(str(fs)[:10]) - d).days <= GDP_PUB_WINDOW_DAYS
    except ValueError:
        adv = False
    ts = gdp_stage_from_title(title)
    if adv:
        out["stage"], out["stage_ok"], basis = "advance", True, "ظهر الربع أول مرة في ALFRED يوم الإصدار"
    elif ts and ts == gdp_stage_by_schedule(d):
        out["stage"], out["stage_ok"], basis = ts, True, "المرحلة من عنوان الحدث وتوافق جدول BEA (دون دليل نسخ مستقل)"
    else:
        out["stage"], out["stage_ok"], basis = "", False, "المرحلة غير متحققة: لا دليل مستقل ولا نص صريح في العنوان"
    stg = GDP_STAGE_AR.get(out["stage"], "المرحلة غير متحققة")
    out["note"] = f"المصدر: FRED/ALFRED ({sid}، فترة {ref.isoformat()}، نسخة {vd.isoformat()}) — {stg}؛ {basis}"
    return out


def shift_months(d, k):
    m = d.year * 12 + (d.month - 1) + k
    return date(m // 12, m % 12 + 1, d.day)


def _find(rows, exp):
    """فهرس الصف المطابق للفترة المتوقعة أو None."""
    for i, (dt, _) in enumerate(rows):
        dd = date.fromisoformat(dt[:10])
        if exp[0] == "exact" and dd == exp[1]:
            return i
        if exp[0] == "week" and exp[1] <= dd <= exp[2]:
            return i
    return None


def validate_rows(rows):
    """(صالحة؟، سبب). السلسلة يجب أن تكون مرتبة تصاعدياً بلا تكرار وبقيم عددية منتهية. لا نحسب على سلسلة فاسدة."""
    import math
    prev = None
    for dt, v in rows or []:
        try:
            d = date.fromisoformat(str(dt)[:10])
        except ValueError:
            return False, f"تاريخ غير صالح في السلسلة ({dt})"
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            return False, f"قيمة غير صالحة عند {d}"
        if prev is not None and d == prev:
            return False, f"تاريخ مكرر في السلسلة ({d})"
        if prev is not None and d < prev:
            return False, f"السلسلة غير مرتبة تصاعدياً عند {d}"
        prev = d
    return True, ""


def _row_at(rows, d):
    for dt, v in rows:
        if date.fromisoformat(str(dt)[:10]) == d:
            return v
    return None


METHOD_AR = {
    "claims_k": "القيمة المنشورة مقسومة على 1000", "level": "القيمة المنشورة كما هي", "level_pct": "القيمة المنشورة كما هي (نسبة)",
    "jolts_m": "القيمة المنشورة (ألف) مقسومة على 1000", "diff_k": "فرق المستوى عن الشهر السابق في السلسلة نفسها",
    "mm": "(مؤشر الشهر ÷ مؤشر الشهر السابق − 1) × 100", "yy": "(مؤشر الشهر ÷ مؤشر الشهر نفسه قبل سنة − 1) × 100",
}


def compute_full(tr, rows, i):
    """(نص منسَّق أو None، قيمة خام قبل التقريب أو None، سبب الرفض أو ''). المرجع يُختار بالتاريخ الفعلي لا بموضع الصف:
    غياب الشهر المرجعي يمنع الحساب بدل إنتاج معدل مضلل."""
    ok, why = validate_rows(rows)
    if not ok:
        return None, None, why
    dt, v = rows[i]
    d = date.fromisoformat(str(dt)[:10])
    if tr == "claims_k":
        return f"{v / 1000.0:.0f}K", v / 1000.0, ""
    if tr == "level":
        return f"{v:.1f}", v, ""
    if tr == "level_pct":
        return f"{v:.1f}%", v, ""
    if tr == "jolts_m":
        return f"{v / 1000.0:.2f}M", v / 1000.0, ""
    if tr in ("diff_k", "mm", "yy"):
        ref = shift_months(d, -12 if tr == "yy" else -1)
        rv = _row_at(rows, ref)
        if rv is None:
            return None, None, f"الشهر المرجعي {ref.isoformat()[:7]} غير موجود في السلسلة: رُفض الحساب"
        if tr == "diff_k":
            return f"{v - rv:.0f}K", v - rv, ""
        if not rv:
            return None, None, "قيمة الشهر المرجعي صفر"
        raw = (v / rv - 1) * 100
        return f"{raw:.1f}%", raw, ""
    return None, None, "نوع حساب غير معروف"


def compute(tr, rows, i):
    """الرقم المنسَّق من الصفوف عند الفهرس i، أو None إن نقصت البيانات المرجعية (انظر compute_full)."""
    return compute_full(tr, rows, i)[0]


def resolve_detail(title, ev_time, rows_by_key, et, src="FRED", sid_map=None, now=None, vint=None):
    """تفصيل كامل: {value, raw, note, why, series, period, method, stage}. value=None مع why إن لم يتحقق الربط.
    GDP: يُحلّ من vint (نسخة ALFRED يوم الإصدار) لا من قراءة FRED الحالية؛ بلا دليل نسخة لا رقم (gdp_resolve)."""
    spec = match(title)
    if not spec:
        return {"value": None, "why": no_source_reason(title), "note": no_source_reason(title)}
    sid = (sid_map or {}).get(spec["key"], spec["sid"])
    out = {"value": None, "raw": None, "series": sid, "source": src, "period": "", "method": METHOD_AR.get(spec["tr"], ""), "stage": ""}
    if spec["rule"] == "quarter":                 # GDP لا يعتمد على قراءة FRED الحالية أصلاً
        return gdp_resolve(title, ev_time, et, vint, sid)
    rows = (rows_by_key or {}).get(spec["key"])
    if not rows:
        out["why"] = out["note"] = f"تعذّر جلب {sid} من {src} (لا بيانات)"
        return out
    d = ev_time.astimezone(et).date()
    exp = expected_obs(spec["rule"], d)
    i = _find(rows, exp)
    if i is None:
        last = max((str(r[0])[:10] for r in rows), default="—")
        out["why"] = out["note"] = f"{src} لم يُحدَّث بعد ({sid}: آخر قراءة {last})"
        return out
    text, raw, why = compute_full(spec["tr"], rows, i)
    if text is None:
        out["why"] = out["note"] = why or f"بيانات {sid} غير كافية للحساب"
        return out
    out.update(value=text, raw=raw, period=str(rows[i][0])[:10], why="")
    stg = f" — {GDP_STAGE_AR[out['stage']]}" if out["stage"] else ""
    out["note"] = f"المصدر: {src} ({sid}، فترة {out['period']}) — {spec['label']}{stg}"
    return out


def resolve(title, ev_time, rows_by_key, et, src="FRED", sid_map=None, now=None):
    """(رقم أو None، ملاحظة). rows_by_key: {مفتاح: [(تاريخ، قيمة)]} أو يفتقد المفتاح عند فشل الجلب.
    src: اسم المصدر في الملاحظة ("FRED" أو "BLS"); sid_map: معرّف السلسلة لكل مفتاح عند اختلافه عن FRED."""
    r = resolve_detail(title, ev_time, rows_by_key, et, src, sid_map, now)
    return r["value"], r["note"]


def previous_revised(title, ev_time, rows_by_key, et):
    """قيمة الفترة السابقة كما هي الآن في المصدر (للمقارنة مع «السابق» في التقويم وكشف التعديل). None إن تعذّر.
    الفترة السابقة تُحدَّد بالتاريخ (شهر/أسبوع/ربع قبل) لا بالصف المجاور."""
    spec = match(title)
    rows = (rows_by_key or {}).get(spec["key"]) if spec else None
    if not rows or not validate_rows(rows)[0]:
        return None
    i = _find(rows, expected_obs(spec["rule"], ev_time.astimezone(et).date()))
    if i is None:
        return None
    d = date.fromisoformat(str(rows[i][0])[:10])
    step = {"week": -7, "quarter": -3}.get(spec["rule"], -1)
    pd = d + timedelta(days=-7) if spec["rule"] == "week" else shift_months(d, step)
    j = next((k for k, (dt, _) in enumerate(rows) if date.fromisoformat(str(dt)[:10]) == pd), None)
    return None if j is None else compute(spec["tr"], rows, j)


def bls_needed(events):
    """{مفتاح: معرّف BLS} للأحداث التي لها مصدر BLS."""
    out = {}
    for e in events:
        s = match(e.get("title", ""))
        if s and s["key"] in BLS_IDS:
            out[s["key"]] = BLS_IDS[s["key"]]
    return out


def series_needed(events):
    """{مفتاح: معرّف FRED} للأحداث المطلوبة فقط."""
    out = {}
    for e in events:
        s = match(e.get("title", ""))
        if s:
            out[s["key"]] = s["sid"]
    return out


# ───────── بديل من عناوين الأخبار (للمؤشرات التي يتأخر FRED في نشرها، مثل قراءة ميشيغان الأولية) ─────────
# صيغ صارمة: إن لم يطابق العنوان تماماً لا يُملأ شيء. الرقم المستخرج يُوسَم «تحقق منه».
def _sent(h, prelim):
    low = h.lower()
    if "michigan" not in low or "sentiment" not in low:
        return None
    if prelim and not ("prelim" in low or "early" in low):
        return None
    if not prelim and not ("final" in low or "revised" in low):
        return None
    m = re.search(r"\bto\s+(\d{2,3}(?:\.\d)?)\b", low)
    if m and 30 <= float(m.group(1)) <= 120:
        return f"{float(m.group(1)):.1f}"
    return None


def _expect(h, prelim):
    low = h.lower()
    if "michigan" not in low:
        return None
    m = re.search(r"(?:1-year|one-year|year-ahead|1-yr)[^.]{0,80}?\bto\s+(\d(?:\.\d)?)\s*%", low)
    if m and 0 < float(m.group(1)) < 15:
        return f"{float(m.group(1)):.1f}%"
    return None


def _claims(h, prelim):
    low = h.lower()
    if "claims" not in low or ("initial" not in low and "jobless" not in low):
        return None
    m = re.search(r"claims[^.]{0,80}?\bto\s+(\d{3}),(\d{3})\b", low)
    return f"{int(m.group(1))}K" if m else None


# (نمط عنوان الحدث، استعلام الأخبار، المحلّل، الوصف)
HEAD_SPECS = [
    (r"uom consumer sentiment", "University of Michigan consumer sentiment when:2d", _sent, "ثقة المستهلك (ميشيغان)"),
    (r"uom inflation expectations", "University of Michigan year-ahead inflation expectations when:2d", _expect, "توقعات التضخم (ميشيغان)"),
    (r"unemployment claims|jobless claims", "initial jobless claims when:2d", _claims, "إعانات البطالة"),
]


def from_headlines(title, fetch_q):
    """(رقم أو None، ملاحظة) من عناوين الأخبار. fetch_q(query) -> قائمة عناوين. فشل ناعم."""
    t = (title or "").lower()
    for pat, query, parser, label in HEAD_SPECS:
        if not re.search(pat, t):
            continue
        prelim = ("prelim" in t) or ("revised" not in t and "final" not in t)
        try:
            heads = fetch_q(query) or []
        except Exception as ex:  # noqa: BLE001
            return None, f"تعذّر جلب العناوين ({type(ex).__name__})"
        vals = []
        for h in heads:
            v = parser(h or "", prelim)
            if v and v not in vals:
                vals.append(v)
        if len(vals) == 1:
            return vals[0], f"المصدر: عنوان خبر ({label})، تحقق منه"
        if len(vals) > 1:
            return None, "عناوين متضاربة (" + " / ".join(vals) + ")، لم يُعتمد رقم"
        return None, "لم يُنشر الرقم في عناوين الأخبار بعد"
    return None, None
