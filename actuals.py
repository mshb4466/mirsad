# -*- coding: utf-8 -*-
"""
مِرصاد — إدارة الأرقام الفعلية (Actual): معرّف ثابت للحدث، تخزين دائم، حالات صريحة، جدولة إعادة المحاولة، كشف المراجعات.

لماذا: تقويم Forex Factory المجاني لا يرسل actual، وكانت الأرقام تُملأ من مصادر ثانية في كل تشغيل ثم تضيع (لا تخزين)،
وتنبيه الصدور كان يعتمد على الحقل الفارغ. هنا نحفظ كل رقم موثَّق في state.json (يُحفظ في المستودع) مرتبطاً بمعرّف حدث ثابت.

الحالات: upcoming لم يصدر بعد | awaiting صدر وننتظر وصول القيمة | verified استُلمت القيمة من مصدر موثّق |
revised صدرت مراجعة للقيمة | failed تعذّر الجلب (آخر محاولة فشل في الاتصال بالمصدر).
لا نخمّن أي رقم ولا نملأ صفراً. Surprise = Actual − Forecast ولا يُحسب إن غابت إحداهما.
"""
import re
from datetime import timedelta

import events_ctx
import indicators

STATUS_AR = {
    "upcoming": "لم يصدر بعد",
    "awaiting": "صدر وننتظر وصول القيمة",
    "verified": "استُلمت القيمة وتم التحقق منها",
    "revised": "صدرت مراجعة للقيمة",
    "failed": "تعذّر جلب البيانات",
}
KEEP_DAYS = 14
GIVE_UP_DAYS = 7


def _slug(t):
    return re.sub(r"[^a-z0-9]+", "-", (t or "").lower()).strip("-")[:60]


def event_id(ev):
    """معرّف ثابت: الدولة | نوع المؤشر (يفصل CPI عن Core CPI وm/m عن y/y) | فترة التقرير | تاريخ الإصدار UTC.
    لا يعتمد على الاسم النصي وحده: المؤشرات المعروفة تُعرَّف بمفتاحها وفترتها."""
    title = ev.get("title", "")
    t = ev["time"]
    spec = indicators.match(title)
    rel = t.date().isoformat()
    if spec:
        exp = indicators.expected_obs(spec["rule"], t.astimezone(_ET()).date())
        per = exp[1].isoformat()[:7] if exp[0] == "exact" else f"w{exp[2].isoformat()}"
        return f"US|{spec['key']}|{per}|{rel}"
    kind = events_ctx.classify(title)[0] or "other"
    return f"US|{kind}:{_slug(title)}|{rel}|{t.strftime('%H%M')}"


def _ET():
    from extras import ET
    return ET


def _store(state):
    return state.setdefault("actuals", {})


def surprise_value(actual, forecast):
    """Surprise رقمياً = Actual − Forecast، أو None إن غاب أحدهما (لا يُعامل غياب التوقع صفراً)."""
    a, f = events_ctx._num(actual), events_ctx._num(forecast)
    if a is None or f is None:
        return None
    return {"value": round(a - f, 6), "unit": events_ctx._unit(actual), "text": f"{a - f:+g}{events_ctx._unit(actual)}"}


def should_poll(ev, rec, now):
    """هل نحاول جلب الرقم الآن؟ كل فحص (15 د) خلال أول 90 دقيقة من الموعد، ثم كل ساعة حتى 30 ساعة، ثم يومياً حتى 7 أيام.
    الأحداث الموثّقة: فحص مراجعة كل 3 ساعات خلال 48 ساعة. لا ندّعي تحديثاً لحظياً: الدقة = دورة الجدولة."""
    t = ev["time"]
    if t > now:
        return False
    age = now - t
    last = None
    if rec and rec.get("last_attempt"):
        try:
            from datetime import datetime
            last = datetime.fromisoformat(rec["last_attempt"])
        except ValueError:
            last = None
    since = (now - last) if last else None
    if rec and rec.get("status") in ("verified", "revised"):
        return age <= timedelta(hours=48) and (since is None or since >= timedelta(hours=3))
    if age > timedelta(days=GIVE_UP_DAYS):
        return False
    if age <= timedelta(minutes=90):
        return True
    if age <= timedelta(hours=30):
        return since is None or since >= timedelta(minutes=55)
    return since is None or since >= timedelta(hours=23)


def restore(events, state):
    """يعيد الأرقام المحفوظة إلى الأحداث (التقويم لا يحملها) مع حالتها. لا يلمس رقماً موجوداً."""
    st = _store(state)
    for e in events:
        rec = st.get(event_id(e))
        if not rec:
            continue
        if rec.get("actual") and not e.get("actual"):
            e["actual"] = rec["actual"]
            e["actual_note"] = rec.get("note", "")
        for k in ("status", "last_attempt", "received_at", "revised_from", "prev_revised"):
            if rec.get(k):
                e[k] = rec[k]


def wants_number(e):
    """هل ننتظر رقماً فعلياً لهذا الحدث؟ الخطب والعطل لا رقم لها؛ والمؤشرات المعروفة والعالية التأثير ننتظرها."""
    kind = events_ctx.classify(e.get("title", ""))[0]
    if kind in ("speech", "holiday"):
        return False
    return bool(indicators.match(e.get("title", ""))) or kind in ("oil", "auction") or (e.get("impact") == "High" and (e.get("forecast") or e.get("previous")))


def pending(events, state, now):
    """أحداث تستحق محاولة جلب الآن: صدرت خلال 7 أيام، وبلا رقم (أو موثّقة تستحق فحص مراجعة)."""
    st = _store(state)
    out, checks = [], []
    for e in events:
        if e["time"] > now or now - e["time"] > timedelta(days=GIVE_UP_DAYS) or not wants_number(e):
            continue
        rec = st.get(event_id(e))
        if not should_poll(e, rec, now):
            continue
        if e.get("actual"):
            if rec and rec.get("status") in ("verified", "revised"):
                c = dict(e, actual="", actual_note="", _clone_of=e)     # نسخة تُعاد حلّها لمقارنتها بالمحفوظ
                checks.append(c)
        else:
            out.append(e)
    return out, checks


def record(events, checks, polled, state, now):
    """يسجّل نتيجة الجولة: رقم جديد → verified، رقم مختلف عن المحفوظ → revised، لا رقم → awaiting/failed.
    polled: الأحداث التي جرت محاولة لها في هذه الجولة (تتحدّث last_attempt لها فقط)."""
    st = _store(state)
    iso = now.isoformat()
    polled_ids = {id(e) for e in polled}
    for c in checks:                                     # فحص المراجعات
        e = c["_clone_of"]
        rec = st.get(event_id(e))
        if rec is None:
            continue
        rec["last_attempt"] = iso
        new = c.get("actual")
        if new and new != rec["actual"]:
            rec.setdefault("history", []).append({"value": rec["actual"], "until": iso})
            rec["revised_from"] = rec["actual"]
            rec["actual"], rec["note"], rec["status"] = new, c.get("actual_note", ""), "revised"
            e["actual"], e["actual_note"], e["status"], e["revised_from"] = new, rec["note"], "revised", rec["revised_from"]
    for e in events:
        if e["time"] > now or not (e.get("actual") or wants_number(e)):
            continue
        eid = event_id(e)
        rec = st.get(eid)
        pr = e.get("prev_revised")
        if e.get("actual"):
            if rec is None or not rec.get("actual"):
                rec = st[eid] = {"actual": e["actual"], "note": e.get("actual_note", ""), "status": "verified", "received_at": iso,
                                 "last_attempt": iso, "attempts": (rec or {}).get("attempts", 0) + 1, "title": e.get("title", ""),
                                 "time": e["time"].isoformat()}
            if pr:
                rec["prev_revised"] = pr
            e["status"] = rec["status"]
            e["received_at"] = rec.get("received_at", iso)
            e["last_attempt"] = rec.get("last_attempt", iso)
            if rec.get("revised_from"):
                e["revised_from"] = rec["revised_from"]
        elif id(e) in polled_ids or rec:
            note = e.get("actual_note", "") or ""
            failed = bool(re.search(r"تعذّر|لا يوجد|خطأ", note))
            rec = st.setdefault(eid, {"actual": "", "status": "awaiting", "attempts": 0, "title": e.get("title", ""), "time": e["time"].isoformat()})
            if id(e) in polled_ids:
                rec["attempts"] = rec.get("attempts", 0) + 1
                rec["last_attempt"] = iso
            rec["note"] = note
            rec["status"] = "failed" if (failed and rec["attempts"] >= 2) else "awaiting"
            e["status"], e["last_attempt"] = rec["status"], rec.get("last_attempt", "")
        elif not e.get("status"):
            e["status"] = "awaiting"
    for e in events:
        if e["time"] > now:
            e["status"] = "upcoming"
    for k in [k for k, r in st.items() if (r.get("time") or "") < (now - timedelta(days=KEEP_DAYS)).isoformat()]:
        st.pop(k, None)
