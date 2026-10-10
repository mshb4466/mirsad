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
    (r"cb consumer confidence|conference board", "مؤشر Conference Board ملكية خاصة، لا يتوفر مجاناً عبر FRED"),
    (r"\bism\b|pmi", "مؤشرات ISM/PMI ملكية خاصة، لا تتوفر مجاناً عبر FRED"),
    (r"adp", "بيانات ADP لا تتوفر مجاناً عبر FRED"),
]

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
        m = d.month - 1 or 12
        y = d.year if d.month > 1 else d.year - 1
        qm = 3 * ((m - 1) // 3) + 1
        return ("exact", date(y, qm, 1))
    return None


def _find(rows, exp):
    """فهرس الصف المطابق للفترة المتوقعة أو None."""
    for i, (dt, _) in enumerate(rows):
        dd = date.fromisoformat(dt[:10])
        if exp[0] == "exact" and dd == exp[1]:
            return i
        if exp[0] == "week" and exp[1] <= dd <= exp[2]:
            return i
    return None


def compute(tr, rows, i):
    """الرقم المنسَّق من الصفوف عند الفهرس i، أو None إن نقصت البيانات المرجعية."""
    v = rows[i][1]
    if tr == "claims_k":
        return f"{v / 1000.0:.0f}K"
    if tr == "level":
        return f"{v:.1f}"
    if tr == "level_pct":
        return f"{v:.1f}%"
    if tr == "jolts_m":
        return f"{v / 1000.0:.2f}M"
    if tr == "diff_k":
        return None if i < 1 else f"{v - rows[i - 1][1]:.0f}K"
    if tr == "mm":
        return None if i < 1 or not rows[i - 1][1] else f"{(v / rows[i - 1][1] - 1) * 100:.1f}%"
    if tr == "yy":
        return None if i < 12 or not rows[i - 12][1] else f"{(v / rows[i - 12][1] - 1) * 100:.1f}%"
    return None


def resolve(title, ev_time, rows_by_key, et):
    """(رقم أو None، ملاحظة). rows_by_key: {مفتاح: [(تاريخ، قيمة)]} أو يفتقد المفتاح عند فشل الجلب."""
    spec = match(title)
    if not spec:
        return None, no_source_reason(title)
    rows = (rows_by_key or {}).get(spec["key"])
    if not rows:
        return None, f"تعذّر جلب {spec['sid']} من FRED (لا بيانات)"
    d = ev_time.astimezone(et).date()
    exp = expected_obs(spec["rule"], d)
    i = _find(rows, exp)
    if i is None:
        return None, f"FRED لم يُحدَّث بعد ({spec['sid']}: آخر قراءة {rows[-1][0][:10]})"
    val = compute(spec["tr"], rows, i)
    if val is None:
        return None, f"بيانات {spec['sid']} غير كافية للحساب"
    return val, f"المصدر: FRED ({spec['sid']}، فترة {rows[i][0][:10]}) — {spec['label']}"


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
