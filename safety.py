#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — مراقب سلامة التحليل (Analysis Safety Monitor).
يعمل قبل الحساب (فحص المدخلات) وبعده (فحص التناقضات)، ولا يستبدل أي رقم مفقود برقم مفترض.

الدرجات:
  warn     تحذير: لا يمنع الحساب لكنه يخفض الثقة.
  major    خلل مؤثر: مدخل أساسي غير موثوق → يُستبعد المدخل ويُذكر السبب.
  critical خلل حرج: قد يضلّل → يُستبعد المدخل ويُمنع أي تنبيه يعتمد عليه.
"""
from datetime import datetime, timedelta, timezone

WARN, MAJOR, CRITICAL = "warn", "major", "critical"
SEV_AR = {WARN: "تحذير", MAJOR: "خلل مؤثر", CRITICAL: "خلل حرج"}
SEV_ORDER = {WARN: 1, MAJOR: 2, CRITICAL: 3}

INCOMPLETE = "التقييم غير مكتمل — البيانات غير كافية"

# نطاقات منطقية للقيم المطلقة (وحدة كل رمز): خارجها = وحدة أو مصدر خاطئ
RANGE = {
    "y10": (0.2, 15.0), "y5": (0.2, 15.0), "y30": (0.2, 15.0), "irx": (0.0, 15.0),
    "vix": (5.0, 100.0), "vix3m": (5.0, 100.0), "move": (20.0, 300.0), "dxy": (70.0, 130.0),
    "oil": (10.0, 250.0), "gold": (800.0, 10000.0), "es": (1000.0, 20000.0), "nq": (3000.0, 60000.0),
    "jpy": (80.0, 250.0), "spy": (100.0, 2000.0),
}
# أقصى تغير يومي معقول (%) أو (نقطة أساس للعوائد): فوقه يُشتبه بخطأ مصدر
# حد ناعم: غير معتاد جداً (تحذير فقط، لا يُستبعد لأن الأزمات الحقيقية تبلغه) وحد صلب: شبه مستحيل (يُستبعد)
JUMP = {"es": (9.0, 18.0), "nq": (11.0, 22.0), "vix": (70.0, 160.0), "dxy": (3.0, 6.0), "oil": (18.0, 40.0), "gold": (9.0, 18.0), "jpy": (4.0, 9.0)}
JUMP_BP = {"y10": (40.0, 80.0), "y5": (40.0, 80.0), "y30": (40.0, 80.0)}
NAME = {"y10": "عائد 10 سنوات", "y5": "عائد 5 سنوات", "y30": "عائد 30 سنة", "irx": "أذون 13 أسبوعاً", "vix": "VIX",
        "vix3m": "VIX3M", "move": "MOVE", "dxy": "الدولار", "oil": "النفط", "gold": "الذهب", "es": "ES", "nq": "ناسداك",
        "jpy": "الدولار/الين", "spy": "SPY"}
# المكوّنات التي يخرّبها فقدان/إسقاط كل مدخل
AFFECTS = {"vix": ["volatility", "vix_term", "geopolitics", "conflict"], "vix3m": ["vix_term"], "y10": ["rates"], "y30": ["rates"],
           "y5": ["front_end"], "irx": ["front_end"], "move": ["rates"], "dxy": ["dollar"], "oil": ["geopolitics"], "gold": ["geopolitics"],
           "es": ["priced_in", "conflict", "liquidity", "breadth", "geopolitics"], "nq": ["breadth"], "jpy": ["global_mkts"]}
# مكوّنات تتشارك مدخلاً: إن ارتفعا معاً فهما ليسا تأكيداً مستقلاً
SHARED = [("rates", "front_end", "عائد سنتين/معدلات الفائدة"), ("geopolitics", "geo_news", "إشارات التوتر"),
          ("volatility", "vix_term", "VIX"), ("volatility", "conflict", "VIX")]
STRESS = ("volatility", "vix_term", "geopolitics", "geo_news", "rates", "front_end", "credit", "global_mkts", "dollar")


def issue(sev, code, msg, affects=(), key=None):
    return {"sev": sev, "sev_ar": SEV_AR[sev], "code": code, "msg": msg, "affects": list(affects), "key": key}


def _age_days(bar_time, now):
    try:
        t = datetime.fromisoformat(bar_time)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (now - t).total_seconds() / 86400.0
    except Exception:  # noqa: BLE001
        return None


def check_inputs(prices, events, fred, now, holidays_years=(), fomc_years=()):
    """يفحص المدخلات قبل الحساب. يعيد (prices_clean, issues). لا يعدّل القيم؛ يحذف فقط المدخل المعيب ويُفصح."""
    issues, clean = [], dict(prices or {})
    for k, v in list((prices or {}).items()):
        if k.startswith(("m_", "b_")) or not isinstance(v, dict):
            continue
        last = v.get("last")
        rng = RANGE.get(k)
        nm = NAME.get(k, k)
        if rng and (last is None or not (rng[0] <= last <= rng[1])):
            issues.append(issue(CRITICAL, "unit_range", f"{nm}: القيمة {last} خارج النطاق المنطقي {rng[0]}–{rng[1]} (وحدة أو مصدر خاطئ). استُبعد المدخل.",
                                AFFECTS.get(k, []), k))
            clean.pop(k, None)
            continue
        if v.get("scaled"):
            issues.append(issue(WARN, "unit_scaled", f"{nm}: عُدّلت الوحدة تلقائياً (×0.1) لأن المصدر أعاد قيمة مضروبة بـ10؛ راجع المصدر.", [], k))
        age = _age_days(v.get("bar_time", ""), now)
        if age is not None:
            if age > 6:
                issues.append(issue(MAJOR, "stale", f"{nm}: آخر بيان قبل {age:.0f} أيام (قديم). استُبعد المدخل.", AFFECTS.get(k, []), k))
                clean.pop(k, None)
                continue
            if age > 4:
                issues.append(issue(WARN, "stale", f"{nm}: آخر بيان قبل {age:.0f} أيام (عطلة طويلة أو تأخر المصدر).", [], k))
        lim = JUMP.get(k)
        jump = abs(v.get("chg1", 0.0))
        if lim and jump > lim[1]:
            issues.append(issue(CRITICAL, "abnormal_jump", f"{nm}: تغير يومي {v.get('chg1', 0):+.1f}% شبه مستحيل (>{lim[1]:g}%): يُشتبه بخطأ مصدر أو تدوير عقد. استُبعد حتى التحقق.",
                                AFFECTS.get(k, []), k))
            clean.pop(k, None)
            continue
        if lim and jump > lim[0]:
            issues.append(issue(WARN, "big_jump", f"{nm}: تغير يومي {v.get('chg1', 0):+.1f}% غير معتاد جداً (قد يكون حدثاً حقيقياً أو خطأ مصدر)؛ تحقق منه.", [], k))
        limbp = JUMP_BP.get(k)
        bp = abs(v.get("diff1", 0.0)) * 100
        if limbp and bp > limbp[1]:
            issues.append(issue(CRITICAL, "abnormal_jump", f"{nm}: تغير {v.get('diff1', 0) * 100:+.0f}bp في يوم شبه مستحيل (>{limbp[1]:g}bp): يُشتبه بخطأ مصدر. استُبعد حتى التحقق.",
                                AFFECTS.get(k, []), k))
            clean.pop(k, None)
        elif limbp and bp > limbp[0]:
            issues.append(issue(WARN, "big_jump", f"{nm}: تغير {v.get('diff1', 0) * 100:+.0f}bp غير معتاد جداً؛ تحقق منه.", [], k))
    # العقود المستقبلية مقابل النقدي: ES مقابل SPY
    es, spy = clean.get("es"), clean.get("spy")
    if es and spy:
        d = abs(es["chg1"] - spy["chg1"])
        if d >= 2.5:
            issues.append(issue(MAJOR, "futures_spot", f"ES يختلف عن SPY بنحو {d:.1f}% في اليوم نفسه: غالباً تدوير عقد أو اختلاف جلسة. استُبعد ES من الحساب.",
                                AFFECTS["es"], "es"))
            clean.pop("es", None)
        elif d >= 1.0:
            issues.append(issue(WARN, "futures_spot", f"ES يختلف عن SPY بنحو {d:.1f}% (اختلاف جلسة أو فارق عقد)؛ الثقة أقل."))
    # العقود: النفط (تدوير الشهر) — قفزة كبيرة مع غياب أي حركة في الذهب/VIX/ES
    oil = clean.get("oil")
    if oil and abs(oil["chg1"]) >= 8:
        others = [abs(clean[k]["chg1"]) for k in ("gold", "vix", "es") if k in clean]
        if others and max(others) < 0.5 and abs(oil["chg1"]) >= 8:
            issues.append(issue(WARN, "roll", f"النفط {oil['chg1']:+.1f}% بينما بقية الأسواق هادئة: احتمال تدوير عقد؛ لا تُعتمد القفزة وحدها."))
    # التقويم والأحداث
    if not events:
        issues.append(issue(MAJOR, "no_calendar", "التقويم الاقتصادي غير متوفر: مكوّن الأحداث مستبعد.", ["events"]))
    else:
        seen, dup = set(), 0
        for e in events:
            key = (e.get("title"), e.get("time"))
            dup += key in seen
            seen.add(key)
        if dup:
            issues.append(issue(WARN, "dup_events", f"{dup} حدث مكرر في التقويم (عدّ مزدوج محتمل)."))
        bad = [e for e in events if e.get("actual") and e["time"] > now + timedelta(minutes=5)]
        if bad:
            issues.append(issue(MAJOR, "future_actual", f"{len(bad)} حدث له رقم فعلي مع أن موعده لم يحن: بيانات التقويم غير موثوقة."))
    if holidays_years and now.year not in holidays_years:
        issues.append(issue(WARN, "calendar_expired", f"قائمة عطل البورصة لا تغطي سنة {now.year}: حدّثها."))
    if fomc_years and now.year not in fomc_years:
        issues.append(issue(WARN, "fomc_expired", f"مواعيد اجتماعات الفدرالي لا تغطي سنة {now.year}: حدّثها."))
    return clean, issues


def coverage(available, base_weights):
    """حصة الأوزان الأساسية المتوفرة (0–1)."""
    tot = sum(base_weights.values())
    return sum(w for k, w in base_weights.items() if k in set(available)) / tot if tot else 0.0


def check_result(comps, available, base_weights, score, weights=None):
    """فحص بعد الحساب: التناقضات والعد المزدوج وتغطية البيانات."""
    issues = []
    cov = coverage(available, base_weights)
    missing = [k for k in base_weights if k not in set(available)]
    if cov < 0.6:
        issues.append(issue(MAJOR, "coverage", f"{INCOMPLETE}: غُطّي {cov:.0%} فقط من أوزان المقياس.", missing))
    elif cov < 0.85:
        issues.append(issue(WARN, "coverage", f"تغطية البيانات {cov:.0%}: مكوّنات مستبعدة ({len(missing)}).", missing))
    # تناقض: خطر منخفض مع مكوّن ضغط شديد
    stress = [(comps[k][0], k) for k in STRESS if k in available and comps[k][0] is not None]
    top = max(stress) if stress else None
    if top and top[0] >= 8 and score <= 3:
        issues.append(issue(MAJOR, "contradiction", f"تناقض: المخاطرة العامة {score} منخفضة بينما مكوّن «{top[1]}» عند {top[0]:.1f}.", [top[1]]))
    for a, b, what in SHARED:
        if a in available and b in available and comps[a][0] >= 7 and comps[b][0] >= 7:
            issues.append(issue(WARN, "double_count", f"«{a}» و«{b}» مرتفعان معاً ويتشاركان مدخلاً ({what}): ليسا تأكيدين مستقلين."))
    return issues, cov


def worst(issues):
    return max((SEV_ORDER[i["sev"]] for i in issues), default=0)


def state_of(issues, cov):
    """حالة المنظومة: ok / warn / incomplete / major / critical."""
    w = worst(issues)
    if w >= 3:
        return "critical"
    if cov < 0.6:
        return "incomplete"
    if w == 2:
        return "major"
    if w == 1:
        return "warn"
    return "ok"


STATE_AR = {"ok": "يعمل بصورة طبيعية", "warn": "يعمل مع تحذيرات", "incomplete": "بيانات غير مكتملة", "major": "يوجد خلل مؤثر",
            "critical": "يوجد خلل حرج"}


def confidence(issues, cov, macro_conf=None):
    """ثقة المحرك: مرتفعة/متوسطة/منخفضة مع الأسباب. تنخفض بالتحذيرات والاختلالات ونقص التغطية."""
    pts = 100 - 6 * sum(1 for i in issues if i["sev"] == WARN) - 18 * sum(1 for i in issues if i["sev"] == MAJOR) \
        - 35 * sum(1 for i in issues if i["sev"] == CRITICAL) - round(max(0.0, 1 - cov) * 100 * 0.6)
    if macro_conf == "منخفضة":
        pts -= 10
    pts = max(0, pts)
    lab = "مرتفعة" if pts >= 80 else "متوسطة" if pts >= 55 else "منخفضة"
    why = [i["msg"] for i in sorted(issues, key=lambda i: -SEV_ORDER[i["sev"]])][:3]
    return {"label": lab, "points": pts, "why": why}


def valid_quote(key, last):
    """هل سعر لحظي معقول الوحدة؟ يُستعمل لمنع تنبيه مبني على قيمة خاطئة."""
    rng = RANGE.get(key)
    return True if rng is None or last is None else rng[0] <= last <= rng[1]
