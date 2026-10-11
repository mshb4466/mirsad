# -*- coding: utf-8 -*-
"""
مِرصاد — مصدر رسمي للأرقام الفعلية: واجهة BLS العامة (Public Data API).

لماذا: تقويم Forex Factory المجاني لا يرسل الرقم الفعلي أبداً، وFRED يتأخر عن الإصدار الرسمي. BLS هو المصدر الأصلي
لأرقام البطالة والوظائف والأجور وCPI وJOLTS، ويُحدَّث عند الإصدار.

حدود (من صفحة BLS الرسمية): بلا مفتاح (v1): 25 استعلاماً يومياً و25 سلسلة للاستعلام و10 سنوات. بمفتاح مسجّل (v2): 500 استعلام
و50 سلسلة. التسجيل مطلوب لـ v2 ويُجدَّد سنوياً (BLS_API_KEY سر اختياري في GitHub). الشيفرة تعدّ الاستعلامات وتتوقف قبل الحد.

لا يُختبَر الجلب الحقيقي إلا من تشغيل GitHub (شبكة بيئة التطوير محجوبة). معرّفات السلاسل أدناه من توثيق BLS المعروف ويجب
التحقق منها في أول تشغيل (health يعرض سبب أي فشل). كل شيء فشل ناعم.
"""
import json
import urllib.request

V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
DAILY_LIMIT_V1 = 25
SAFETY_MARGIN = 5          # نترك هامشاً من الحصة اليومية


def _post(url, payload, timeout=25):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "User-Agent": "mirsad/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def parse(resp):
    """({معرّف: [(YYYY-MM-01, قيمة)] تصاعدياً}, أخطاء). تتجاوز المتوسط السنوي M13 والقيم الناقصة «-»."""
    out, errs = {}, []
    if not isinstance(resp, dict):
        return out, ["استجابة غير صالحة من BLS"]
    if resp.get("status") != "REQUEST_SUCCEEDED":
        errs.append("BLS: " + "؛ ".join(resp.get("message") or [str(resp.get("status"))]))
    for s in ((resp.get("Results") or {}).get("series") or []):
        rows = []
        for d in s.get("data", []):
            per = d.get("period", "")
            if not per.startswith("M") or per == "M13":
                continue
            try:
                rows.append((f"{int(d['year']):04d}-{int(per[1:]):02d}-01", float(d["value"])))
            except (ValueError, KeyError):
                continue            # «-» أي لا رقم: لا نخمّن
        rows.sort()
        if rows:
            out[s.get("seriesID")] = rows
    return out, errs


def quota_ok(state, today, has_key):
    """هل بقيت حصة استعلام؟ (بلا مفتاح فقط). state['bls_calls'] = {تاريخ: عدد}."""
    if has_key:
        return True
    return (state.get("bls_calls") or {}).get(today, 0) < DAILY_LIMIT_V1 - SAFETY_MARGIN


def fetch(series_ids, now, key=None, post_fn=None, state=None):
    """({معرّف: صفوف}, أخطاء). استعلام واحد مجمّع لكل السلاسل. لا يرفع استثناءً."""
    ids = sorted(set(series_ids))
    if not ids:
        return {}, []
    today = now.date().isoformat()
    st = state if state is not None else {}
    if not quota_ok(st, today, bool(key)):
        return {}, ["BLS: اقتربت الحصة اليومية (25 استعلاماً بلا مفتاح). أضف BLS_API_KEY أو انتظر الغد"]
    payload = {"seriesid": ids[:25 if not key else 50], "startyear": str(now.year - 2), "endyear": str(now.year)}
    if key:
        payload["registrationkey"] = key
    try:
        resp = (post_fn or _post)(V2 if key else V1, payload)
    except Exception as e:  # noqa: BLE001
        return {}, [f"BLS: تعذّر الاتصال ({type(e).__name__})"]
    calls = st.setdefault("bls_calls", {})
    calls[today] = calls.get(today, 0) + 1
    for d in [d for d in calls if d != today]:
        calls.pop(d, None)
    return parse(resp)
