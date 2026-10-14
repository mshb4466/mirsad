# -*- coding: utf-8 -*-
"""
مِرصاد — تقرير جودة الأرقام الفعلية (Actual) وتشغيل المنظومة.

يُبنى من state.json (السجل الدائم) والأحداث الحالية فقط: لا أرقام مختلقة. يعرض:
عدد ما وصل رقمه وما لم يصل، سبب التأخر لكل حدث، تغطية المؤشرات المهمة، زمن ما بين الإصدار واستلام الرقم،
حالة BLS وFRED من آخر محاولة فعلية، وآخر نجاح حقيقي للجدولة وللنشر.
الزمن بين الإصدار والاستلام دقته بدقة دورة الجدولة (15 دقيقة) لا لحظية.
"""
from datetime import datetime, timedelta

import actuals
import indicators

WINDOW_DAYS = 7


def _dt(s):
    try:
        return datetime.fromisoformat(s)
    except Exception:  # noqa: BLE001
        return None


def _hhmm(iso):
    d = _dt(iso)
    return (d + timedelta(hours=3)).strftime("%d-%m %H:%M") if d else ""


def _reason(rec, ev_note, status, b=None):
    """سبب عدم وصول الرقم بصياغة قصيرة (من آخر ملاحظة فعلية، لا من التخمين)."""
    if b == "unsupported":
        return "لا مصدر مرخّص مدعوم له في المشروع حالياً (لا يعني أنه لا مصدر له عموماً)"
    if status == "needs_check":
        return "الرقم من خبر أو حالة قديمة بلا مصدر موثّق، ولم يُتحقق منه بعد"
    note = (rec.get("note") if rec else "") or ev_note or ""
    if note:
        return note[:160]
    return "لم يصل الرقم بعد من المصدر"


def _pseudo(rec, t):
    """حدث مُعاد بناؤه من سجل محفوظ (لحساب التصنيف الموحّد نفسه لأحداث غابت عن التقويم)."""
    st = rec.get("status", "awaiting")
    e = {"title": rec.get("title", ""), "time": t, "impact": rec.get("impact", ""), "forecast": rec.get("forecast", ""), "previous": rec.get("previous", ""),
         "status": st, "actual_src": rec.get("trust", ""), "actual": rec.get("actual", "") if st != "needs_check" else ""}
    if st == "needs_check":
        e["actual_unverified"] = rec.get("actual", "")
    if e["actual"] and not actuals.is_verified(e):
        e["actual_unverified"], e["actual"], e["status"] = e["actual"], "", "needs_check"
    return e


def build(events, state, now):
    """تقرير الجودة لأحداث آخر 7 أيام التي تنتظر قيمة رقمية. التصنيف والتغطية من actuals.bucket نفسه الذي يعتمده ملخص الواجهة
    وصحة مرصاد، فلا تختلف الأرقام بين الشاشات. لا يرفع استثناءً."""
    st = (state or {}).get("actuals") or {}
    cut = now - timedelta(days=WINDOW_DAYS)
    rows, seen = [], set()
    for e in events or []:
        if e["time"] > now or e["time"] < cut or not actuals.wants_number(e):
            continue
        eid = actuals.event_id(e)
        seen.add(eid)
        rows.append(_row(eid, e, st.get(eid) or {}, now))
    for eid, rec in st.items():                       # أحداث محفوظة لم تعد في تقويم هذا الأسبوع
        if eid in seen:
            continue
        t = _dt(rec.get("time", ""))
        if not t or t > now or t < cut:
            continue
        e = _pseudo(rec, t)
        if actuals.wants_number(e):
            rows.append(_row(eid, e, rec, now))
    rows.sort(key=lambda r: r["release"], reverse=True)
    cnt = {k: sum(1 for r in rows if r["bucket"] == k) for k in actuals.BUCKETS}
    verified = [r for r in rows if r["bucket"] == "verified"]
    lat = sorted(r["latency_min"] for r in verified if r["latency_min"] is not None)
    n = len(rows)
    sup = n - cnt["unsupported"]
    s = (state or {})
    ss = s.get("source_status") or {}
    return {
        "generated": now.isoformat(), "window_days": WINDOW_DAYS, "schema_version": s.get("schema_version"),
        "total": n, "arrived": cnt["verified"], "official": sum(1 for r in verified if r["trust"] == "official"),
        "secondary": sum(1 for r in verified if r["trust"] == "secondary"), "needs_check": cnt["needs_check"],
        "awaiting": cnt["awaiting"], "unsupported": cnt["unsupported"], "failed": cnt["failed"], "missing": n - cnt["verified"],
        "coverage_pct": round(100.0 * cnt["verified"] / n) if n else None,
        "supported_coverage_pct": round(100.0 * cnt["verified"] / sup) if sup else None,
        "important_total": n, "important_arrived": cnt["verified"],
        "latency_median_min": lat[len(lat) // 2] if lat else None, "latency_max_min": lat[-1] if lat else None,
        "events": rows,
        "sources": {k: ss.get(k) or {"ok": None, "detail": "لم تُجرَ محاولة بعد"} for k in ("bls", "fred", "treasury")},
        "unsupported_notes": sorted({indicators.no_source_reason(r["title"]) or "" for r in rows if r["bucket"] == "unsupported"} - {""}),
        "unsupported_list": sorted({r["title"] for r in rows if r["bucket"] == "unsupported"}),
        "scheduler_last_ok": (s.get("last_run_ok") or {}).get("at", ""), "scheduler_mode": (s.get("last_run_ok") or {}).get("mode", ""),
        "publish_last_ok": s.get("last_publish_ok", ""),
        "scheduler_last_ok_ar": _hhmm((s.get("last_run_ok") or {}).get("at", "")), "publish_last_ok_ar": _hhmm(s.get("last_publish_ok", "")),
        "migration": s.get("migration"),
    }


def _row(eid, e, rec, now):
    t = e["time"]
    b = actuals.bucket(e)
    ver = b == "verified"
    got = _dt(rec.get("received_at", "")) if ver else None
    lat = int((got - t).total_seconds() // 60) if got else None
    status = e.get("status") or rec.get("status") or "awaiting"
    if b == "needs_check":
        status = "needs_check"
    return {"id": eid, "title": e.get("title", ""), "release": t.isoformat(), "release_ar": _hhmm(t.isoformat()), "status": status,
            "bucket": b, "bucket_ar": actuals.BUCKET_AR[b], "status_ar": actuals.STATUS_AR.get(status, status), "verified": ver,
            "trust": (rec.get("trust") or e.get("actual_src") or "") if ver else "", "source": rec.get("source") or e.get("actual_source") or "",
            "period": rec.get("period") or e.get("actual_period") or "", "series": rec.get("series", ""), "method": rec.get("method", ""),
            "value": e.get("actual", "") if ver else "",
            "unverified_value": (e.get("actual_unverified") or (rec.get("actual") if status == "needs_check" else "") or "") if b == "needs_check" else "",
            "latency_min": lat, "attempts": rec.get("attempts", 0), "last_attempt": rec.get("last_attempt", ""),
            "last_attempt_ar": _hhmm(rec.get("last_attempt", "")), "reason": "" if ver else _reason(rec, e.get("actual_note", ""), status, b),
            "important": True}


def render_text(q):
    """نص مختصر للسجل/ملخص GitHub."""
    cov = "غير محسوبة" if q["coverage_pct"] is None else f"{q['coverage_pct']}%"
    L = [f"الأحداث التي تنتظر قيمة رقمية خلال {q['window_days']} أيام: {q['total']}",
         f"وصل ومتحقق: {q['arrived']} (رسمي {q['official']}، ثانوي {q['secondary']})",
         f"بانتظار الرقم: {q['awaiting']} | يحتاج تحققاً: {q['needs_check']} | تعذّر الجلب: {q['failed']} | مصدر غير مدعوم حالياً: {q['unsupported']}",
         f"التغطية: {cov} (المتحقَّق ÷ كل ما ينتظر قيمة رقمية)" + ("" if q.get("supported_coverage_pct") is None else f" — بعد استبعاد غير المدعوم: {q['supported_coverage_pct']}%")]
    if q["latency_median_min"] is not None:
        L.append(f"الزمن بين الإصدار والاستلام: وسيط {q['latency_median_min']} د، أقصى {q['latency_max_min']} د")
    for k, nm in (("bls", "BLS"), ("fred", "FRED"), ("treasury", "TreasuryDirect")):
        s = q["sources"][k]
        L.append(f"{nm}: " + ("تعمل" if s.get("ok") else "فشلت" if s.get("ok") is False else "لم تُجرَّب") + (f" — {s.get('detail')}" if s.get("detail") else ""))
    L.append(f"آخر نجاح للجدولة: {q['scheduler_last_ok_ar'] or 'لا يوجد'} | آخر نشر ناجح: {q['publish_last_ok_ar'] or 'لا يوجد'}")
    for r in q["events"]:
        if not r["verified"]:
            L.append(f"  • {r['title']} ({r['release_ar']}): {r['bucket_ar']} — {r['reason']}")
    return "\n".join(L)
