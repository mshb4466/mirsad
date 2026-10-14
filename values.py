# -*- coding: utf-8 -*-
"""
مِرصاد — محلّل موحّد للقيمة والوحدة (v0.18.1).

كان الحساب القديم يستخرج أول رقم ويتجاهل اللاحقة: 1M − 900K = −899M. هنا كل قيمة تُحلَّل إلى (رقم دقيق Decimal بالوحدة الأساسية، نوع):
  pct   نسبة مئوية (4.2%)            الفرق بينها «نقطة مئوية» وليس «%» ولا تغيراً نسبياً
  bp    نقاط أساس (3bp)
  count عدد بلاحقة K/M/B/T (231K)     يُوحَّد السلم قبل الطرح: 1M − 900K = +100K
  level مستوى بلا وحدة (49.0)
  المركّب «العائد|نسبة التغطية» (المزادات) يُحلَّل مكوّنين منفصلين: العائد pct والتغطية level.
القواعد: لا يُقارَن نوعان مختلفان (نسبة مع عدد، %، مع bp) → None؛ القيمة الفارغة أو غير المفهومة → None (لا صفر)؛ الصفر والسالب مدعومان.
"""
import re
from decimal import Decimal, InvalidOperation

SCALE = {"": Decimal(1), "K": Decimal(10) ** 3, "M": Decimal(10) ** 6, "B": Decimal(10) ** 9, "T": Decimal(10) ** 12}
_RE = re.compile(r"^\s*([+\-−–]?)\s*(\d+(?:\.\d+)?|\.\d+)\s*(%|bps?|pp)?\s*([KMBT])?\s*$", re.I)


class Val:
    __slots__ = ("n", "kind", "suffix", "raw")

    def __init__(self, n, kind, suffix, raw):
        self.n, self.kind, self.suffix, self.raw = n, kind, suffix, raw


def _clean(s):
    t = str(s).strip().replace("٫", ".").replace("٬", ",")
    return re.sub(r"(?<=\d),(?=\d{3}(\D|$))", "", t)


def parse(s):
    """قيمة مفردة → Val أو None. المركّب (a|b) والفارغ والنص غير المفهوم → None."""
    if s is None or isinstance(s, bool):
        return None
    t = _clean(s)
    if not t or "|" in t:
        return None
    m = _RE.match(t)
    if not m:
        return None
    sign, num, unit, suf = m.group(1), m.group(2), (m.group(3) or "").lower(), (m.group(4) or "").upper()
    try:
        n = Decimal(num)
    except InvalidOperation:
        return None
    if sign in ("-", "−", "–"):
        n = -n
    if unit == "%" or unit == "pp":
        if suf:
            return None
        return Val(n, "pct", "", t)
    if unit in ("bp", "bps"):
        return Val(n, "bp", "", t) if not suf else None
    if suf:
        return Val(n * SCALE[suf], "count", suf, t)
    return Val(n, "level", "", t)


def parse_composite(s):
    """«4.215|2.55» (العائد|التغطية) → [Val pct, Val level] أو None. الجزء الفارغ يُرفض."""
    if not s or "|" not in str(s):
        return None
    parts = [p.strip() for p in _clean(s).split("|")]
    if len(parts) != 2:
        return None
    y, b = parse(parts[0].rstrip("%")), parse(parts[1])
    if y is None or b is None or b.kind != "level":
        return None
    return [Val(y.n, "pct", "", parts[0]), b]


def _fmt(d, places=3):
    q = d.quantize(Decimal(1).scaleb(-places)).normalize()
    t = format(q, "f")
    return "0" if t in ("-0", "") else t


def _components(x, y):
    """[(اسم، Val_x، Val_y)] للمركّب أو المفرد، أو None إن تعذّرت المقارنة."""
    cx, cy = parse_composite(x), parse_composite(y)
    if cx or cy:
        if cx and cy:
            return [("العائد", cx[0], cy[0]), ("التغطية", cx[1], cy[1])]
        one = cx[0] if cx else None                      # مركّب مقابل مفرد: يُقارَن العائد فقط إن كان المفرد نسبة
        other = parse(y if cx else x)
        if other is None or other.kind != "pct":
            return None
        return [("العائد", cx[0], other)] if cx else [("العائد", other, cy[0])]
    a, b = parse(x), parse(y)
    if a is None or b is None or a.kind != b.kind:
        return None
    return [("", a, b)]


def _unit_for(a, b):
    if a.kind == "count":
        sc = min(SCALE[a.suffix], SCALE[b.suffix])
        return next(k for k, v in SCALE.items() if v == sc), sc
    return "", Decimal(1)


def pair(x, y):
    """(رقم_x، رقم_y) بسلم موحّد للمقارنة والإشارة، أو None إن تعذّرت (قيمة ناقصة/وحدتان مختلفتان). المركّب: العائد."""
    comps = _components(x, y)
    if not comps:
        return None
    _, a, b = comps[0]
    _, sc = _unit_for(a, b)
    return float(a.n / sc), float(b.n / sc)


def _part_text(a, b):
    d = a.n - b.n
    if a.kind == "pct":
        return f"{_signed(d)} نقطة مئوية"
    if a.kind == "bp":
        return f"{_signed(d)} نقطة أساس"
    if a.kind == "count":
        suf, sc = _unit_for(a, b)
        return f"{_signed(d / sc)}{suf}"
    return _signed(d)


def _signed(d):
    t = _fmt(d)
    return t if t == "0" else (t if t.startswith("-") else "+" + t)


def diff_text(actual, forecast):
    """نص الفرق الموقَّع (Actual − Forecast) بوحدته الصحيحة، أو '' إن تعذّر. أمثلة: +0.1 نقطة مئوية | +100K | العائد +0.02 نقطة مئوية | التغطية -0.1"""
    comps = _components(actual, forecast)
    if not comps:
        return ""
    outs = [((n + " ") if n else "") + _part_text(a, b) for n, a, b in comps]
    return " | ".join(outs)


def diff_abs_text(actual, forecast):
    """نص الفرق المطلق (للجمل «أعلى بـ …»)."""
    comps = _components(actual, forecast)
    if not comps:
        return ""
    _, a, b = comps[0]
    d = abs(a.n - b.n)
    if a.kind == "pct":
        return f"{_fmt(d)} نقطة مئوية"
    if a.kind == "bp":
        return f"{_fmt(d)} نقطة أساس"
    if a.kind == "count":
        suf, sc = _unit_for(a, b)
        return f"{_fmt(d / sc)}{suf}"
    return _fmt(d)


def sign(actual, forecast):
    """+1 أعلى | 0 مطابق | -1 أدنى | None غير قابل للمقارنة."""
    p = pair(actual, forecast)
    if p is None:
        return None
    return 0 if abs(p[0] - p[1]) < 1e-9 else (1 if p[0] > p[1] else -1)
