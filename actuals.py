# -*- coding: utf-8 -*-
"""
مِرصاد — إدارة الأرقام الفعلية (Actual): معرّف ثابت للحدث، تخزين دائم، حالات صريحة، جدولة إعادة المحاولة، كشف المراجعات.

لماذا: تقويم Forex Factory المجاني لا يرسل actual، وكانت الأرقام تُملأ من مصادر ثانية في كل تشغيل ثم تضيع (لا تخزين)،
وتنبيه الصدور كان يعتمد على الحقل الفارغ. هنا نحفظ كل رقم موثَّق في state.json (يُحفظ في المستودع) مرتبطاً بمعرّف حدث ثابت.

الحالات (v0.18): upcoming لم يصدر بعد | awaiting صدر وننتظر وصول القيمة | verified_official رسمي ومتحقق (BLS، TreasuryDirect) |
verified_secondary مصدر ثانوي موثوق ومتحقق (FRED) | needs_check مستخرج من خبر ويحتاج تحققاً (لا يُعدّ Actual في أي تحليل) |
revised صدرت مراجعة للقيمة (مع trust) | failed تعذّر الجلب.
قاعدة صارمة: نجاح استخلاص رقم من عنوان خبر لا يجعله متحققاً؛ يُحجَر في actual_unverified ولا يدخل Surprise ولا التنبيه ولا الثقة،
ويُعاد فحصه، فإن وصل من BLS/FRED حلّ محلّه وترقّى.
لا نخمّن أي رقم ولا نملأ صفراً. Surprise = Actual − Forecast ولا يُحسب إن غابت إحداهما.
"""
import re
from datetime import timedelta

import events_ctx
import indicators
import values

STATUS_AR = {
    "upcoming": "لم يصدر بعد",
    "awaiting": "صدر وننتظر وصول القيمة",
    "verified_official": "رسمي ومتحقق",
    "verified_secondary": "مصدر ثانوي موثوق ومتحقق",
    "needs_check": "مستخرج من خبر ويحتاج تحققاً",
    "revised": "صدرت مراجعة للقيمة",
    "failed": "تعذّر جلب البيانات",
}
from verification import (TIER_STATUS, TIER_RANK, VERIFIED_STATUSES, ACCEPTED_TIERS, tier_of, is_verified, verified_status,  # noqa: E402
                          valid_value)
LOG_KEEP = 400


def _log(state, e, eid, now, value, tier, source, note, period):
    """سجل تدقيق لكل محاولة: المصدر، معرّف السلسلة، فترة التقرير، طريقة الحساب، القيمة قبل التقريب، وقت الجلب.
    period_check = «مطابقة فترة التقرير» فقط لرقم رسمي/ثانوي طابقت فترةُ سلسلته الفترة المتوقعة من جدول الإصدار؛ وإلا «غير مُتحقَّق».
    bulletin_check: الرقم محسوب من سلسلة، ولا نقارنه بنشرة الإصدار هنا (المقارنة في verify.py) فلا ندّعي المطابقة."""
    lg = state.setdefault("actuals_log", [])
    ok = bool(value) and tier in ACCEPTED_TIERS and bool(period)
    lg.append({"id": eid, "title": e.get("title", ""), "release_time": e["time"].isoformat(), "fetched_at": now.isoformat(),
               "source": source or "", "tier": tier or "", "value": value or "", "period": period or "",
               "series": e.get("actual_series", ""), "method": e.get("actual_method", ""), "raw": e.get("actual_raw"), "stage": e.get("actual_stage", ""),
               "basis": ("محسوب من سلسلة رسمية" if tier == "official" else "محسوب من سلسلة ثانوية" if tier == "secondary" else "مستخرج من خبر") if value else "",
               "forecast": e.get("forecast", ""), "previous": e.get("previous", ""),
               "period_check": "مطابقة فترة التقرير" if ok else ("غير مُتحقَّق" if value else "لا رقم"),
               "bulletin_check": "لم تُقارَن بنشرة الإصدار" if value else "",
               "match": "مطابقة فترة التقرير" if ok else ("غير مُتحقَّق" if value else "لا رقم"), "note": (note or "")[:240]})
    del lg[:-LOG_KEEP]


def quarantine(events):
    """يحجر كل رقم لا يحقق الشرط الموحّد (قيمة صالحة + مصدر مقبول + حالة تحقق صحيحة): ينتقل من actual إلى actual_unverified
    فلا يصل إلى مفاجأة ولا تحليل ولا تنبيه صدور ولا ثقة. يشمل حالات v0.17 القديمة «verified» بلا مصدر موثّق."""
    for e in events:
        if e.get("actual") and not is_verified(e):
            e["actual_unverified"], e["actual"] = e["actual"], ""
            if e.get("status") in ("verified", "verified_official", "verified_secondary", "revised"):
                e["status"] = "needs_check"        # كلمة «verified» وحدها ليست دليلاً


KEEP_DAYS = 14
GIVE_UP_DAYS = 7


def _slug(t):
    return re.sub(r"[^a-z0-9]+", "-", (t or "").lower()).strip("-")[:60]


def event_id(ev):
    """معرّف ثابت v2: US | مفتاح المؤشر | نوع القياس (mm/yy/level…) | فترة التقرير | المرحلة | تاريخ الإصدار UTC.
    هوية المؤشر منفصلة عن سلسلة المصدر: Core PCE شهرياً وسنوياً يشتركان بسلسلة pcelfe لكنهما معرّفان مختلفان.
    المرحلة: GDP (advance/second/third) من جدول BEA؛ وغيره «-». لا يعتمد على الاسم النصي وحده."""
    title = ev.get("title", "")
    t = ev["time"]
    spec = indicators.match(title)
    rel = t.date().isoformat()
    if spec:
        d = t.astimezone(_ET()).date()
        exp = indicators.expected_obs(spec["rule"], d)
        per = exp[1].isoformat()[:7] if exp[0] == "exact" else f"w{exp[2].isoformat()}"
        stage = indicators.gdp_info(title, d)["stage"] if spec["rule"] == "quarter" else "-"
        return f"US|{spec['key']}|{spec['tr']}|{per}|{stage}|{rel}"
    kind = events_ctx.classify(title)[0] or "other"
    return f"US|{kind}:{_slug(title)}|{rel}|{t.strftime('%H%M')}"


def _ET():
    from extras import ET
    return ET


def _store(state):
    return state.setdefault("actuals", {})


def surprise_value(actual, forecast):
    """Surprise رقمياً = Actual − Forecast بوحدة موحّدة، أو None إن غاب أحدهما أو اختلفت الوحدتان (لا يُعامل الغياب صفراً)."""
    sg = values.sign(actual, forecast)
    if sg is None:
        return None
    p = values.pair(actual, forecast)
    return {"value": round(p[0] - p[1], 6), "unit": values.parse(actual).kind if values.parse(actual) else "", "text": values.diff_text(actual, forecast)}


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
    if rec and (rec.get("status") in VERIFIED_STATUSES or (rec.get("status") == "revised" and rec.get("trust") in ("official", "secondary"))):
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
        if rec.get("actual"):
            # سجل بلا trust (v0.17 أو تالف) لا يُصدَّق: يُعامل خبراً يحتاج تحققاً حتى يصل مصدر مقبول
            e["actual_src"], e["actual_source"], e["actual_period"] = tier_of(rec), rec.get("source", ""), rec.get("period", "")
        for k in ("status", "last_attempt", "received_at", "revised_from", "prev_revised"):
            if rec.get(k):
                e[k] = rec[k]
        if rec.get("actual") and not is_verified(e):
            e["status"] = "needs_check" if e.get("status") in (None, "", "verified", "verified_official", "verified_secondary", "revised") else e["status"]


def _ev_fields(e):
    """بيانات الحدث اللازمة لإعادة المحاولة بأمان بعد اختفائه من تقويم الأسبوع (التقويم المجاني thisweek فقط)."""
    return {"impact": e.get("impact", ""), "forecast": e.get("forecast", ""), "previous": e.get("previous", ""), "country": e.get("country", "USD")}


def ghost_events(events, state, now):
    """أحداث محفوظة لا تزال تستحق الجلب أو المراجعة لكنها غابت عن التقويم الحالي (تغيّر الأسبوع). تُبنى من state فقط
    وتحمل _from_state=True. لا يُنشأ حدث لسجل ينقصه الوقت أو العنوان، ولا لحدث مضت عليه مدة الاستسلام."""
    from datetime import datetime
    have = {event_id(e) for e in events}
    out = []
    for eid, rec in _store(state).items():
        if eid in have or not rec.get("title") or not rec.get("time"):
            continue
        try:
            t = datetime.fromisoformat(rec["time"])
        except ValueError:
            continue
        if t > now or now - t > timedelta(days=GIVE_UP_DAYS):
            continue
        e = {"title": rec["title"], "time": t, "impact": rec.get("impact", ""), "forecast": rec.get("forecast", ""),
             "previous": rec.get("previous", ""), "country": rec.get("country", "USD"), "actual": "", "_from_state": True}
        if event_id(e) != eid:           # معرّف السجل لا يطابق ما نعيد بناءه (سجل قديم/تالف): لا نخمّن
            continue
        if rec.get("status") in VERIFIED_STATUSES + ("revised",) and now - t > timedelta(hours=48):
            continue                      # موثّق وانتهت نافذة فحص المراجعة: لا حاجة لإعادة بنائه
        if not wants_number(e):
            continue
        out.append(e)
    return out


def wants_number(e):
    """هل ننتظر رقماً فعلياً لهذا الحدث؟ الخطب والعطل لا رقم لها؛ والمؤشرات المعروفة والعالية التأثير ننتظرها."""
    kind = events_ctx.classify(e.get("title", ""))[0]
    if kind in ("speech", "holiday"):
        return False
    return bool(indicators.match(e.get("title", ""))) or kind in ("oil", "auction") or (e.get("impact") == "High" and (e.get("forecast") or e.get("previous")))


BUCKETS = ("verified", "awaiting", "unsupported", "needs_check", "failed")
BUCKET_AR = {"verified": "وصل ومتحقق", "awaiting": "بانتظار الرقم", "unsupported": "مصدر غير مدعوم حالياً", "needs_check": "يحتاج تحققاً", "failed": "تعذّر الجلب"}


def bucket(e):
    """التصنيف الوحيد لحالة رقم حدث صدر (يعتمده الملخص والجودة وصحة مرصاد): verified | awaiting | unsupported | needs_check | failed.
    None إن كان الحدث لا ينتظر قيمة رقمية أصلاً (خطبة، عطلة…)؛ فلا يُحسب في التغطية ولا في المعلّق."""
    if not wants_number(e):
        return None
    if is_verified(e):
        return "verified"
    if e.get("actual_unverified") or e.get("status") == "needs_check":
        return "needs_check"
    if indicators.no_source_reason(e.get("title", "")):
        return "unsupported"
    return "failed" if e.get("status") == "failed" else "awaiting"


def summary(events, now, hours=48, high_only=True):
    """عدّ موحّد: {total, <bucket>…, coverage_pct, last_attempt}. التغطية = المتحقَّق ÷ كل ما ينتظر قيمة رقمية (غير المدعوم داخل المقام
    صراحةً، ويُعرض منفصلاً)، وsupported_coverage_pct بعد استبعاده. total=0 → coverage_pct=None لا 0 ولا 100."""
    from datetime import timedelta as _td
    cnt = {k: 0 for k in BUCKETS}
    last = ""
    n = 0
    for e in events or []:
        if not (_td(0) <= now - e["time"] <= _td(hours=hours)) or (high_only and e.get("impact") != "High"):
            continue
        b = bucket(e)
        if b is None:
            continue
        n += 1
        cnt[b] += 1
        last = max(last, e.get("last_attempt") or "")
    sup = n - cnt["unsupported"]
    return dict(cnt, total=n, last_attempt=last, coverage_pct=round(100.0 * cnt["verified"] / n) if n else None,
                supported_total=sup, supported_coverage_pct=round(100.0 * cnt["verified"] / sup) if sup else None)


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
            if rec and (rec.get("status") in VERIFIED_STATUSES or rec.get("status") in ("revised", "needs_check")):
                c = dict(e, actual="", actual_note="", _clone_of=e)     # نسخة تُعاد حلّها لمقارنتها بالمحفوظ
                checks.append(c)
        else:
            out.append(e)
    return out, checks


def record(events, checks, polled, state, now):
    """يسجّل نتيجة الجولة. رقم جديد → الحالة حسب درجة المصدر (رسمي/ثانوي/خبر)؛ رقم مختلف عن المحفوظ → revised؛
    رقم خبر محفوظ ثم وصل رسمي/ثانوي → يحلّ محلّه ويترقّى؛ لا رقم → awaiting/failed. لا يُخفَض رقم متحقق برقم خبر أبداً.
    polled: الأحداث التي جرت محاولة لها في هذه الجولة (تتحدّث last_attempt لها فقط). كل محاولة تدخل سجل التدقيق."""
    st = _store(state)
    iso = now.isoformat()
    polled_ids = {id(e) for e in polled}
    for c in checks:                                     # فحص المراجعات وترقية أرقام الأخبار
        e = c["_clone_of"]
        eid = event_id(e)
        rec = st.get(eid)
        if rec is None:
            continue
        rec["last_attempt"] = iso
        new, tier = c.get("actual"), tier_of(c)
        _log(state, e, eid, now, new, tier if new else "", c.get("actual_source"), c.get("actual_note"), c.get("actual_period"))
        if not new:
            continue
        old_tier = rec.get("trust") or "news"
        if TIER_RANK[tier] < TIER_RANK.get(old_tier, 0) or (tier == "news" and old_tier == "news" and new == rec["actual"]):
            continue                                      # لا نستبدل رقماً أوثق برقم أضعف
        changed = new != rec["actual"]
        if changed or tier != old_tier:
            rec.setdefault("history", []).append({"value": rec["actual"], "trust": old_tier, "until": iso})
        if tier == "news":
            status = "needs_check"
        elif old_tier == "news":                          # حلّ رقم رسمي/ثانوي محل رقم الخبر: ليس «مراجعة»
            status = verified_status(tier)
            rec["received_at"] = iso
            rec.pop("revised_from", None)
        elif changed:
            status = "revised"
            rec["revised_from"] = rec["actual"]
        else:
            status = verified_status(tier)
        rec["actual"], rec["note"], rec["trust"], rec["status"] = new, c.get("actual_note", ""), tier, status
        rec["source"], rec["period"] = c.get("actual_source", ""), c.get("actual_period", "")
        e["actual"], e["actual_note"], e["status"] = new, rec["note"], status
        e["actual_src"], e["actual_source"], e["actual_period"] = tier, rec["source"], rec["period"]
        if rec.get("revised_from"):
            e["revised_from"] = rec["revised_from"]
        e["received_at"] = rec.get("received_at", iso)
    for e in events:
        if e["time"] > now or not (e.get("actual") or wants_number(e)):
            continue
        eid = event_id(e)
        rec = st.get(eid)
        pr = e.get("prev_revised")
        if e.get("actual"):
            if rec is None or not rec.get("actual"):
                tier = tier_of(e)
                keep = {k: v for k, v in (rec or {}).items() if k in ("history", "legacy", "migrated")}
                rec = st[eid] = {"actual": e["actual"], "note": e.get("actual_note", ""), "status": verified_status(tier), "trust": tier,
                                 "source": e.get("actual_source", ""), "period": e.get("actual_period", ""), "received_at": iso,
                                 "last_attempt": iso, "attempts": (rec or {}).get("attempts", 0) + 1, "title": e.get("title", ""),
                                 "time": e["time"].isoformat(), "series": e.get("actual_series", ""), "method": e.get("actual_method", ""),
                                 "raw": e.get("actual_raw"), "stage": e.get("actual_stage", ""), **_ev_fields(e), **keep}
                _log(state, e, eid, now, e["actual"], tier, rec["source"], rec["note"], rec["period"])
            if pr:
                rec["prev_revised"] = pr
            e["status"] = rec["status"]
            e["actual_src"] = rec.get("trust", tier_of(e))
            e["received_at"] = rec.get("received_at", iso)
            e["last_attempt"] = rec.get("last_attempt", iso)
            if rec.get("revised_from"):
                e["revised_from"] = rec["revised_from"]
        elif id(e) in polled_ids or rec:
            note = e.get("actual_note", "") or ""
            failed = bool(re.search(r"تعذّر|لا يوجد|خطأ", note))
            rec = st.setdefault(eid, {"actual": "", "status": "awaiting", "attempts": 0, "title": e.get("title", ""), "time": e["time"].isoformat()})
            rec.update(_ev_fields(e))
            if id(e) in polled_ids:
                rec["attempts"] = rec.get("attempts", 0) + 1
                rec["last_attempt"] = iso
                _log(state, e, eid, now, "", "", "", note, "")
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
    cut = (now - timedelta(days=KEEP_DAYS)).isoformat()
    state["actuals_log"] = [x for x in state.get("actuals_log", []) if x.get("fetched_at", "") >= cut]
