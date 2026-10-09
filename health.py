#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — تقرير صحة المنظومة («صحة مرصاد»).
يُبنى من نتائج فحص حقيقية في الدورة الحالية: لا يعرض حالة «سليمة» إن لم يُجرَ الفحص.
آخر نجاح لكل مصدر يُحفظ في state.json بين الدورات.
"""
import os
from datetime import timedelta

import events_ctx
import safety

STATE_AR = {"ok": "يعمل بصورة طبيعية", "warn": "يعمل مع تحذيرات", "incomplete": "بيانات غير مكتملة", "major": "يوجد خلل مؤثر",
            "unchecked": "لم يُجرَ الفحص"}
NEEDNUM = ("oil", "auction", "infl", "labor", "unemp", "growth", "sent", "rate")
BAGHDAD_H = 3


def _sources(report, events, now):
    """حالة كل مصدر من نتائج الدورة: [{key,name,ok,detail}]. ok: True/False. لا يخمّن: يعتمد على غياب البيانات والمشكلات المسجلة."""
    probs = [str(p) for p in (report.get("problems") or [])]
    import collector as c
    total = len(c.SYMBOLS)
    fails = sum(1 for p in probs if p.startswith("تعذّر جلب") and "(" in p and ")" in p.split(":")[0])
    yahoo_ok = (report.get("data") or {})
    yahoo = {"key": "yahoo", "name": "أسعار Yahoo", "ok": fails == 0 and bool(yahoo_ok),
             "detail": f"{max(0, total - fails)}/{total} رمزاً" + (f" — تعذّر {fails}" if fails else "")}
    fred_bad = [p for p in probs if "FRED" in p]
    macro_ok = bool(report.get("macro"))
    fred = {"key": "fred", "name": "FRED (عوائد/ائتمان/اقتصاد كلي)", "ok": not fred_bad and macro_ok,
            "detail": ("؛ ".join(fred_bad)[:160] if fred_bad else ("المنظومة الكلية تعمل" if macro_ok else "بيانات المنظومة الكلية غير متوفرة"))}
    cal = {"key": "calendar", "name": "تقويم الأحداث", "ok": bool(events), "detail": f"{len(events or [])} حدثاً" if events else "لا أحداث (تعذّر الجلب؟)"}
    rel = [e for e in events or [] if events_ctx.relevant(e) and now - timedelta(hours=30) <= e["time"] < now]
    auc = [e for e in rel if events_ctx.classify(e.get("title", ""))[0] == "auction"]
    oil = [e for e in rel if events_ctx.classify(e.get("title", ""))[0] == "oil"]
    miss_a, miss_o = [e for e in auc if not e.get("actual")], [e for e in oil if not e.get("actual")]
    tr = {"key": "auctions", "name": "نتائج المزادات (TreasuryDirect)", "ok": not miss_a,
          "detail": ("لا مزادات صدرت مؤخراً" if not auc else f"{len(auc) - len(miss_a)}/{len(auc)} مزاد وصلت نتيجته"
                     + (": " + (miss_a[0].get("actual_note") or "لم تصل") if miss_a else ""))}
    oi = {"key": "oil", "name": "مخزونات النفط (FRED/EIA)", "ok": not miss_o,
          "detail": ("لا إصدار مؤخراً" if not oil else f"{len(oil) - len(miss_o)}/{len(oil)} وصل" + (": " + (miss_o[0].get("actual_note") or "لم يصل") if miss_o else ""))}
    news = {"key": "news", "name": "الأخبار (Google News)", "ok": bool(report.get("news") or report.get("geo")),
            "detail": "عناوين متوفرة" if (report.get("news") or report.get("geo")) else "لا عناوين"}
    cot = {"key": "cot", "name": "تمركز CFTC", "ok": "cot" in (report.get("info") or {}), "detail": "متوفر" if "cot" in (report.get("info") or {}) else "غير متوفر"}
    return [yahoo, fred, cal, tr, oi, news, cot]


def _events_stats(events, now):
    rel = [e for e in events or [] if events_ctx.relevant(e) and now - timedelta(hours=24) <= e["time"] < now]
    verified = unanalysed = 0
    for e in rel:
        kind = events_ctx.classify(e.get("title", ""))[0]
        if kind in NEEDNUM:
            if e.get("actual"):
                verified += 1
            else:
                unanalysed += 1
    return len(rel), verified, unanalysed


def bump(state, key, now, n=1):
    """عدّاد يومي (بتوقيت بغداد) للتنبيهات المرسلة والمكررة الممنوعة."""
    day = (now + timedelta(hours=BAGHDAD_H)).date().isoformat()
    st = state.setdefault("stats", {})
    if st.get("date") != day:
        st.clear()
        st["date"] = day
    st[key] = st.get(key, 0) + n


def build(report, events, now, state, error=None):
    """يبني عرض الصحة ويحدّث state['health']. error: نص إن فشل بناء التقرير نفسه (لا تُعرض حالة سليمة)."""
    hs = state.setdefault("health", {"sources": {}})
    srcs_hist = hs.setdefault("sources", {})
    checked = now.isoformat()
    if error or not isinstance(report, dict) or "error" in report:
        sf = (report or {}).get("safety") if isinstance(report, dict) else None
        view = {"state": "unchecked" if not isinstance(report, dict) else "incomplete", "label": STATE_AR["unchecked" if not isinstance(report, dict) else "incomplete"],
                "checked_at": checked, "sources": [], "issues": (sf or {}).get("issues", []),
                "todo": [error or (report or {}).get("error") or "تعذّر بناء التقرير"], "coverage": 0.0}
        view["issues"] = [{"sev": i["sev"], "sev_ar": i["sev_ar"], "msg": i["msg"]} for i in view["issues"]]
        hs["last"] = {"state": view["state"], "at": checked}
        return view
    srcs = _sources(report, events, now)
    for s in srcs:
        h = srcs_hist.setdefault(s["key"], {})
        h["last_try"] = checked
        if s["ok"]:
            h["ok_at"] = checked
        s["ok_at"] = h.get("ok_at")
    sf = report.get("safety") or {}
    st = sf.get("state", "ok")
    down = [s for s in srcs if not s["ok"]]
    state_key = {"critical": "major"}.get(st, st)
    if state_key == "ok" and down:
        state_key = "warn"
    n_rel, n_ver, n_un = _events_stats(events, now)
    stats = state.get("stats") or {}
    issues = [{"sev": i["sev"], "sev_ar": i["sev_ar"], "msg": i["msg"]} for i in sf.get("issues", [])]
    todo = [i["msg"] for i in issues if i["sev"] != safety.WARN] + [f"{s['name']}: {s['detail']}" for s in down]
    conf = report.get("confidence") or {}
    view = {
        "state": state_key, "label": STATE_AR[state_key], "checked_at": checked,
        "sources_ok": sum(1 for s in srcs if s["ok"]), "sources_total": len(srcs), "sources": srcs,
        "coverage": sf.get("coverage"), "events_checked": n_rel, "events_verified": n_ver, "events_unanalysed": n_un,
        "conflicts": sum(1 for i in issues if i["sev"] != safety.WARN), "issues": issues,
        "alerts_sent": stats.get("sent", 0), "alerts_suppressed": stats.get("suppressed", 0),
        "engine": {"risk": (report.get("risk") or {}).get("score"), "level": (report.get("risk") or {}).get("level"),
                   "confidence": conf.get("label"), "regime": (report.get("regime") or {}).get("text"),
                   "incomplete": bool((report.get("risk") or {}).get("incomplete"))},
        "todo": todo,
    }
    hs["last"] = {"state": state_key, "at": checked}
    return view


def material(view):
    """هل يستحق الخلل إشعاراً؟ (خلل مؤثر أو حرج فقط)."""
    return view.get("state") == "major"


def should_notify(view, state, now, cooldown_h=12):
    """إشعار الخلل المؤثر مرة كل cooldown_h ساعة لنفس مجموعة المشكلات. لا إشعار يومي ما لم يفعّله المستخدم."""
    if not material(view):
        return False
    sig = "|".join(sorted(i["msg"][:60] for i in view.get("issues", []) if i["sev"] != safety.WARN))
    hs = state.setdefault("health", {})
    last = hs.get("notified") or {}
    try:
        from datetime import datetime
        recent = last.get("sig") == sig and now - datetime.fromisoformat(last["at"]) < timedelta(hours=cooldown_h)
    except Exception:  # noqa: BLE001
        recent = False
    if recent:
        return False
    hs["notified"] = {"sig": sig, "at": now.isoformat()}
    return True


def daily_enabled():
    return os.environ.get("MIRSAD_DAILY_HEALTH", "").strip() in ("1", "true", "yes")


def format_message(view):
    lines = [f"🩺 صحة مِرصاد: {view['label']}"]
    if view.get("sources"):
        lines.append(f"المصادر العاملة {view['sources_ok']}/{view['sources_total']} | تغطية البيانات {round((view.get('coverage') or 0) * 100)}%")
    for t in (view.get("todo") or [])[:5]:
        lines.append(f"• {t}")
    return "\n".join(lines)
