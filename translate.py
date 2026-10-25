"""ترجمة عناوين الأخبار الجيوسياسية إلى العربية (اختيارية وناعمة الفشل: بدونها يبقى العنوان الأصلي).
تعمل أثناء الجمع فقط (GitHub Actions). لا مفاتيح ولا أسرار. أول فشل يوقف بقية المحاولات لعدم تعطيل الجمع."""
import json
import os
import urllib.parse
import urllib.request

URL = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ar&dt=t&q="
_CACHE = {}


def _is_arabic(s):
    return sum(1 for c in s if "؀" <= c <= "ۿ") > len(s) * 0.4


def translate_ar(text, timeout=6, opener=None):
    """يعيد النص بالعربية أو None عند الفشل. النص العربي أصلاً يُعاد كما هو."""
    t = (text or "").strip()
    if not t:
        return None
    if _is_arabic(t):
        return t
    if t in _CACHE:
        return _CACHE[t]
    if os.environ.get("MIRSAD_NO_NET"):
        return None
    try:
        op = opener or urllib.request.urlopen
        req = urllib.request.Request(URL + urllib.parse.quote(t), headers={"User-Agent": "Mozilla/5.0"})
        with op(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        out = "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()
        out = out or None
    except Exception:  # noqa: BLE001
        return None
    _CACHE[t] = out
    return out


def add_ar(items, translate=translate_ar):
    """يضيف title_ar لكل عنصر (حقل title). عند أول فشل يتوقف عن المحاولة (بقية العناصر بلا ترجمة)."""
    ok = True
    for it in items or []:
        if not ok:
            it["title_ar"] = None
            continue
        ar = translate(it.get("title", ""))
        it["title_ar"] = ar
        ok = ar is not None
    return items
