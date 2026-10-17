# -*- coding: utf-8 -*-
"""
مِرصاد — أثر الإصدارات الاقتصادية الموثّقة على التقييم الحالي (v0.19).

المشكلة: كان الانحياز الماكروي يعتمد على عوامل بطيئة (ميل الفدرالي، العوائد لـ 20 يوماً…) فلا يتغير حين تأتي مفاجأة CPI كبيرة.
هنا كل إصدار موثّق (رسمي/ثانوي فقط؛ رقم الخبر لا يدخل أبداً) يتحول إلى مساهمة موزونة تدخل الانحياز كمكوّن «الإصدارات».

القواعد (كلها قابلة للمراجعة وتقديرية غير معايَرة، وتُعرض في الواجهة):
1) المفاجأة = الفعلي − المتوقع بوحدة موحّدة (values)، تُقاس بمقياس «مفاجأة معتادة» لكل مؤشر (SD)؛ |z| = 2 → أثر كامل.
2) اتجاه الأثر على ES من جدول events_ctx.EFFECT حسب ميل الفدرالي (متشدد/غيره): CPI أعلى ليس ضاغطاً تلقائياً؛ يتوقف على النوع والسياق.
3) الوزن = أهمية النوع × (عالي/متوسط) × عامل السياق (مفاجأة تدفع في اتجاه ميل الفدرالي ×1.25، عكسه ×0.85) × تلاشي زمني
   (1 حتى 6 ساعات، ثم يتناقص إلى 0.4 عند 24 ساعة و0.2 عند 48 ثم يسقط).
4) المراجعة: إن عُدّل «السابق» تُضاف إشارة صغيرة (حدّها ±0.3) بالاتجاه نفسه.
5) لا عدّ مزدوج: إصدار واحد = صوت واحد. CPI شهري + سنوي + أساسي في اليوم نفسه يُجمَعون في مجموعة واحدة (أقوى إشارة إن اتفقوا، متوسطها إن اختلفوا)،
   ووزن المجموعة = أعلى أهمية فيها لا مجموعها. ويُخصم نصف وزن الأحداث من وزن «ميل الفدرالي» لأن ركائزه (التضخم/العمل/النمو) تقرأ البيانات نفسها.
6) تأكيد السوق منفصل عن أثر الخبر الأولي: ES وعائد 10 سنوات والدولار منذ لحظة الإصدار، بشرط بيانات حديثة (≤ 45 دقيقة).
   تؤكد → ×1.15، ترفض → ×0.5، غير حاسمة → ×1، لا بيانات → «تقييم أولي — تأكيد السوق غير متاح بعد» ×1.
7) الإصدار الذي صدر ولم يصل رقمه الموثّق يُسجَّل في pending ويُظهر «لم يُدمج الإصدار بعد»؛ لا يُعاد تقديم التقييم السابق كأنه محدّث.
8) (v0.19.1) وحدة قياسية لكل سلسلة (CANON): Actual وForecast وPrevious والمراجعة تُحوَّل إليها قبل الحساب، ومقياس SD بالوحدة نفسها؛
   فلا تتغير النتيجة بطريقة كتابة المصدر (7.5M أو 7500K أو 7500000). عدم تطابق الأنواع أو فرق مقدار مستحيل (>200×) يُسقط الإصدار بدل تخمين وحدة.
9) (v0.19.1) التغير عن السابق (المعدَّل) يُفسَّر دائماً مستقلاً عن المفاجأة. لا يُضاف إلى الإشارة حين يوجد توقع، لأن (الفعلي − السابق) = (المتوقع − السابق)
   [مُسعَّر في التوقع] + المفاجأة، فإضافته عدٌّ مزدوج. عند غياب التوقع تُستخدم المقارنة بالسابق وحدها بنصف الوزن. المكوّنات الداخلية غير متاحة
   في بيانات الحدث وتُذكر كذلك صراحة. اختلاف Core وHeadline يُحسم بمتوسط مرجّح بالأهمية (الأساسي أثقل) ويُشرح، لا بتعادل آلي.
"""
from datetime import timedelta
from decimal import Decimal

import actuals
import events_ctx
import indicators
import values
from verification import is_verified

# وحدة قياسية لكل سلسلة: (نوع، المقسوم عليه من الوحدة الأساسية، لاحقة العرض). الباقي كله نقاط مئوية (pct).
CANON = {"claims": ("count", 1000, "K"), "payems": ("count", 1000, "K"), "jolts": ("count", 1000000, "M"), "umcsent": ("level", 1, "")}
MAX_RATIO = 200          # فرق مقدار أكبر من هذا بين رقمين من نوع «عدد» = وحدتان غير متطابقتين (150 مقابل 150K) فيُسقَط الإصدار
# مفاجأة معتادة (SD) بالوحدة القياسية أعلاه: نقطة مئوية، أو K للمطالبات والوظائف، أو M للوظائف الشاغرة، أو نقطة للمستوى
SD = {"claims": 12.0, "unrate": 0.1, "payems": 75.0, "ahe": 0.1, "cpi": 0.1, "cpilfe": 0.1, "cpi_ny": 0.1, "cpilfe_ny": 0.1,
      "pcelfe": 0.1, "ppi": 0.2, "ppife": 0.2, "retail": 0.4, "indpro": 0.2, "jolts": 0.3, "gdp": 0.4, "umcsent": 2.5, "mich": 0.3}
SD_KIND = {"rate": 0.25}                 # قرار الفائدة: فرق عن المتوقع بالنقطة المئوية
IMPORTANCE = {"rate": 1.0, "infl": 0.9, "labor": 0.85, "unemp": 0.5, "growth": 0.6, "sent": 0.35}
CORE_BOOST = {"cpilfe": 1.0, "cpilfe_ny": 1.0, "pcelfe": 1.0, "ppife": 0.9, "payems": 1.0}
MAX_WEIGHT = 0.20                        # أقصى حصة للإصدارات من الانحياز
FRESH_MIN = 45


def _decay(age_h):
    if age_h < 0:
        return 0.0
    if age_h <= 6:
        return 1.0
    if age_h <= 24:
        return 1.0 - 0.6 * (age_h - 6) / 18.0
    if age_h <= 48:
        return 0.4 - 0.2 * (age_h - 24) / 24.0
    return 0.0


def _move(series, t0, unit="pct"):
    """تغير الأصل من لحظة الإصدار حتى آخر سعر؛ None إن غابت بيانات بعد الإصدار."""
    if not series:
        return None
    before = [p for t, p in series if t <= t0]
    after = [p for t, p in series if t > t0]
    if not before or not after or not before[-1]:
        return None
    return round((series[-1][1] - before[-1]) * 100, 1) if unit == "bp" else round((series[-1][1] / before[-1] - 1) * 100, 2)


def market_check(series, t0, now, d_es, hawk_push):
    """تأكيد السوق لإصدار: (key, label, detail). key: na | confirm | reject | mixed | flat.
    d_es: اتجاه الأثر المتوقع على ES (+1/-1/0). hawk_push: +1 الإصدار يدفع نحو التشدد (عوائد/دولار أعلى)، -1 نحو التيسير."""
    series = series or {}

    def fresh(k):
        s = series.get(k)
        return bool(s) and (now - s[-1][0]) <= timedelta(minutes=FRESH_MIN)
    mv = {"es": _move(series.get("es"), t0) if fresh("es") else None,
          "y10": _move(series.get("y10"), t0, "bp") if fresh("y10") else None,
          "dxy": _move(series.get("dxy"), t0) if fresh("dxy") else None}
    if all(v is None for v in mv.values()):
        return "na", "تقييم أولي — تأكيد السوق غير متاح بعد", {}
    thr = {"es": 0.05, "y10": 2.0, "dxy": 0.1}
    agree = oppose = 0
    parts = []
    names = {"es": "ES", "y10": "عائد 10س", "dxy": "الدولار"}
    for k, v in mv.items():
        if v is None:
            continue
        unit = "bp" if k == "y10" else "%"
        parts.append(f"{names[k]} {'▲' if v > 0 else '▼' if v < 0 else '◆'} {v:+g}{unit}")
        if abs(v) < thr[k]:
            continue
        exp = d_es if k == "es" else hawk_push
        if not exp:
            continue
        if (v > 0) == (exp > 0):
            agree += 1
        else:
            oppose += 1
    txt = "، ".join(parts)
    if agree == 0 and oppose == 0:
        return "flat", f"السوق لم يتحرك بوضوح منذ الإصدار ({txt})", mv
    if agree > oppose:
        return "confirm", f"السوق يؤكد السيناريو ({txt})", mv
    if oppose > agree:
        return "reject", f"السوق يرفض السيناريو ({txt})", mv
    return "mixed", f"تأكيد السوق غير حاسم ({txt})", mv


def canon_value(spec, s):
    """قيمة بالوحدة القياسية للسلسلة (float) أو None إن تعذّر التحويل. لا يعتمد على طريقة كتابة المصدر (K/M/الأساسية)."""
    ck, div, _ = CANON.get(spec["key"] if spec else "", ("pct", 1, ""))
    p = values.parse(s)
    if p is None:
        return None
    if ck == "count":
        return float(p.n / Decimal(div)) if p.kind in ("count", "level") else None
    if ck == "level":
        return float(p.n) if p.kind == "level" else None
    return float(p.n) if p.kind == "pct" else None


def canon_pair(spec, x, y):
    """(x، y) بالوحدة القياسية أو None؛ يرفض وحدتين متعارضتين (فرق مقدار > 200× في الأعداد)."""
    a, b = canon_value(spec, x), canon_value(spec, y)
    if a is None or b is None:
        return None
    if CANON.get(spec["key"] if spec else "", ("pct",))[0] == "count" and a and b and max(abs(a), abs(b)) / min(abs(a), abs(b)) > MAX_RATIO:
        return None
    return a, b


def _unit_ar(spec):
    ck, _, suf = CANON.get(spec["key"] if spec else "", ("pct", 1, ""))
    return "نقطة مئوية" if ck == "pct" else (suf or "نقطة")


def _scale(spec, kind):
    if spec and spec["key"] in SD:
        return SD[spec["key"]]
    return SD_KIND.get(kind)


def trend_view(ev, spec, kind, sd):
    """تفسير التغير عن السابق (المعدَّل إن وُجد) مستقلاً عن المفاجأة: (نص، حالة). الحالة: accel|decel|flat|None.
    لا يدخل الإشارة حين يوجد توقع (مُسعَّر فيه)؛ يُعرض ويُعلَّل كي لا يضيع عن القارئ."""
    prev_s = ev.get("prev_revised") or ev.get("previous")
    if not prev_s:
        return "التغير عن السابق: غير متاح (لا قراءة سابقة)", None
    lab = "السابق المعدَّل" if ev.get("prev_revised") else "السابق"
    pa = canon_pair(spec, ev.get("actual"), prev_s)
    if pa is None:
        return "التغير عن السابق: غير قابل للمقارنة (وحدتان مختلفتان)", None
    chg = pa[0] - pa[1]
    if abs(chg) < 0.5 * sd:
        return f"مستقر قرب {lab} ({prev_s})", "flat"
    up = chg > 0
    word = ("تسارع" if up else "تباطؤ") if kind == "infl" else ("ارتفاع" if up else "انخفاض")
    txt = f"{word} عن {lab} ({prev_s}) بـ {values.diff_abs_text(ev['actual'], prev_s)}"
    fc = canon_pair(spec, ev.get("forecast"), prev_s) if ev.get("forecast") else None
    if fc is not None:
        exp = fc[0] - fc[1]
        if abs(exp) >= 0.5 * sd and (exp > 0) == up:
            txt += "؛ وكان متوقعاً ومُسعَّراً في التوقع فلا يضيف مفاجأة"
        elif abs(exp) < 0.5 * sd:
            txt += "؛ بينما كان التوقع استقراراً فهو جزء من المفاجأة نفسها"
        else:
            txt += "؛ بعكس اتجاه التغير المتوقع"
    return txt, ("accel" if up else "decel")


def item_for(ev, now, macro_label, lean, series):
    """مساهمة إصدار واحد، أو None إن لم يكن موثّقاً أو لا يُقاس عددياً. لا يرفع استثناءً."""
    if not is_verified(ev):
        return None
    kind, name, _ = events_ctx.classify(ev.get("title", ""))
    if kind not in IMPORTANCE:
        return None
    spec = indicators.match(ev.get("title", ""))
    sd = _scale(spec, kind)
    if not sd:
        return None
    pf = canon_pair(spec, ev.get("actual"), ev.get("forecast")) if ev.get("forecast") else None
    prev_s = ev.get("prev_revised") or ev.get("previous")
    pp = canon_pair(spec, ev.get("actual"), prev_s) if prev_s else None
    if pf is not None:
        diff, basis, wscale = pf[0] - pf[1], "forecast", 1.0
    elif pp is not None:
        diff, basis, wscale = pp[0] - pp[1], "previous", 0.5          # بلا توقع: المقارنة بالسابق وحدها وبنصف الوزن
    else:
        return None
    age_h = (now - ev["time"]).total_seconds() / 3600.0
    decay = _decay(age_h)
    if decay <= 0:
        return None
    z = max(-3.0, min(3.0, diff / sd))
    hawk = "متشدد" in (macro_label or "")
    eff = events_ctx.EFFECT.get(kind, (("neu",) * 3,) * 2)[0 if hawk else 1]
    idx = 1 if abs(z) < 1e-9 else (0 if z > 0 else 2)
    d = {"bull": 1, "bear": -1}.get(eff[idx], 0)
    mag = min(1.0, abs(z) / 2.0)
    signal = d * mag * wscale
    push = (1 if z > 0 else -1 if z < 0 else 0) * events_ctx.HAWK_DIR.get(kind, 1)
    rev_txt = ""
    if ev.get("prev_revised") and ev.get("previous"):
        rp = canon_pair(spec, ev["prev_revised"], ev["previous"])
        if rp and abs(rp[0] - rp[1]) > 1e-9:
            rz = max(-3.0, min(3.0, (rp[0] - rp[1]) / sd))
            rdir = {"bull": 1, "bear": -1}.get(eff[0 if rz > 0 else 2], 0)
            signal += rdir * min(0.3, abs(rz) / 2.0 * 0.5)
            rev_txt = f"السابق عُدّل من {ev['previous']} إلى {ev['prev_revised']}"
    signal = max(-1.0, min(1.0, signal))
    ctxf = 1.0
    if push and abs(lean or 0) > 0.15:
        ctxf = 1.25 if (push > 0) == ((lean or 0) > 0) else 0.85
    mk_key, mk_label, mv = market_check(series, ev["time"], now, d, push)
    mult = {"confirm": 1.15, "reject": 0.5}.get(mk_key, 1.0)
    importance = IMPORTANCE[kind] * (1.0 if ev.get("impact") == "High" else 0.6) * CORE_BOOST.get(spec["key"] if spec else "", 0.8 if kind == "infl" else 1.0)
    final = signal * ctxf * mult
    sur = events_ctx.surprise(ev.get("actual"), ev.get("forecast")) if basis == "forecast" else ""
    eff_ar = {1: "داعم", -1: "ضاغط", 0: "محدود"}[d]
    trend_txt, trend_state = trend_view(ev, spec, kind, sd)
    if basis == "forecast":
        head = sur or "مطابق للتوقع"
    else:
        head = (events_ctx.vs_previous(ev.get("actual"), prev_s) or "نفس السابق") + " (بلا توقع: المقارنة بالسابق فقط وبنصف الوزن)"
    initial = f"{name}: {head} ← أثر أولي {eff_ar} على ES"
    if ctxf != 1.0:
        initial += " (يتوافق مع ميل الفدرالي فيقوى)" if ctxf > 1 else " (عكس ميل الفدرالي فيخفّ)"
    if basis == "forecast" and trend_state in ("accel", "decel"):
        initial += f"؛ {trend_txt}"
    why_signal = ("الإشارة من المفاجأة (الفعلي − المتوقع) وحدها؛ التغير عن السابق مُسعَّر في التوقع فلا يُعدّ مرتين" if basis == "forecast"
                  else "الإشارة من المقارنة بالسابق بنصف وزن لغياب التوقع")
    explain = {"surprise": head, "trend": trend_txt, "revision": rev_txt or "لا مراجعة للسابق", "why_signal": why_signal,
               "unavailable": "المكوّنات الداخلية (مثل الإسكان/الخدمات داخل CPI) والاتجاه التاريخي: غير متاحة في بيانات الحدث"}
    return {"id": actuals.event_id(ev), "title": ev.get("title", ""), "name": name, "kind": kind, "date": ev["time"].date().isoformat(),
            "time": ev["time"].isoformat(), "actual": ev.get("actual", ""), "forecast": ev.get("forecast", ""), "previous": ev.get("previous", ""),
            "source": ev.get("actual_source", ""), "trust": ev.get("actual_src", ""), "status": ev.get("status", ""),
            "z": round(z, 2), "basis": basis, "unit": _unit_ar(spec), "effect": {1: "bull", -1: "bear", 0: "neu"}[d], "signal": round(signal, 3),
            "ctx_factor": ctxf, "decay": round(decay, 2), "importance": round(importance, 2), "final": round(final, 3),
            "initial": initial, "revision": rev_txt, "trend": trend_txt, "trend_state": trend_state, "explain": explain,
            "market": {"key": mk_key, "label": mk_label, "mult": mult, "move": mv if isinstance(mv, dict) else {}},
            "hawk_push": push}


def pending(events, now):
    """إصدارات عالية الأهمية صدرت (≤ 12 ساعة) ولم يصل رقمها الموثّق: «لم يُدمج الإصدار بعد»."""
    out = []
    for e in events or []:
        if e.get("impact") != "High" or not (timedelta(0) <= now - e["time"] <= timedelta(hours=12)) or not actuals.wants_number(e):
            continue
        if events_ctx.classify(e.get("title", ""))[0] in ("speech", "holiday"):
            continue
        if is_verified(e):
            continue
        unsupported = bool(indicators.no_source_reason(e.get("title", "")))
        out.append({"id": actuals.event_id(e), "title": e.get("title", ""), "name": events_ctx.classify(e.get("title", ""))[1] or e.get("title", ""),
                    "time": e["time"].isoformat(), "status": e.get("status", "awaiting"),
                    "status_ar": events_ctx.STATUS_AR.get(e.get("status", "awaiting"), ""), "unsupported": unsupported,
                    "unverified_value": e.get("actual_unverified", "")})
    return out


def build(events, now, macro_view=None, series=None):
    """ملخص أثر الإصدارات: {items, groups, signal, weight, fed_discount, pending, market, note}. signal في [-1,1] موجب = داعم لـ ES."""
    m = macro_view or {}
    lean, label = m.get("lean"), m.get("label", "")
    items = []
    for e in sorted(events or [], key=lambda x: x["time"]):
        if e["time"] > now:
            continue
        try:
            it = item_for(e, now, label, lean, series)
        except Exception:  # noqa: BLE001
            it = None
        if it:
            items.append(it)
    groups = {}
    for it in items:
        groups.setdefault((it["kind"], it["date"]), []).append(it)
    gl = []
    side = lambda v: "داعم" if v >= 0.2 else "ضاغط" if v <= -0.2 else "محدود الأثر"
    for (kind, day), mem in groups.items():
        sig = [x["final"] for x in mem]
        conflict = ""
        if all(s_ >= 0 for s_ in sig) or all(s_ <= 0 for s_ in sig):
            val = max(sig, key=abs)                       # اتفقوا: أقوى إشارة، لا مجموعها
            mode = "أقوى إشارة (لا مجموع)"
        else:
            ws = [x["importance"] * x["decay"] for x in mem]
            val = sum(x["final"] * w_ for x, w_ in zip(mem, ws)) / (sum(ws) or 1.0)       # اختلفوا: متوسط مرجّح بالأهمية (الأساسي أثقل) لا تعادل آلي
            mode = "متوسط مرجّح بالأهمية (إشارات متعاكسة)"
            pos, neg = max(mem, key=lambda x: x["final"]), min(mem, key=lambda x: x["final"])
            heavy = max(mem, key=lambda x: x["importance"] * x["decay"])
            conflict = (f"اختلاف داخل الإصدار نفسه: {pos['title']} داعم بينما {neg['title']} ضاغط؛ رُجّح {heavy['title']} لأنه الأهم، "
                        f"فالمحصلة {side(val)} ({val:+.2f}) وليست تعادلاً آلياً")
        imp = max(x["importance"] * x["decay"] for x in mem)
        lead = max(mem, key=lambda x: abs(x["final"]))
        gl.append({"kind": kind, "date": day, "ids": [x["id"] for x in mem], "titles": [x["title"] for x in mem], "value": round(val, 3),
                   "importance": round(imp, 3), "mode": mode, "lead": lead["title"], "initial": lead["initial"], "market": lead["market"],
                   "revision": next((x["revision"] for x in mem if x["revision"]), ""), "effect": lead["effect"], "conflict": conflict,
                   "explain": lead["explain"], "trend": lead["trend"]})
    pend = pending(events, now)
    out = {"items": items, "groups": gl, "pending": pend, "signal": None, "weight": 0.0, "fed_discount": 0.0,
           "market": None, "note": "", "verified_count": len(items)}
    if not gl:
        return out
    tw = sum(g["importance"] for g in gl)
    out["signal"] = round(max(-1.0, min(1.0, sum(g["value"] * g["importance"] for g in gl) / tw)), 3) if tw else 0.0
    out["weight"] = round(min(MAX_WEIGHT, 0.10 * tw), 3)
    out["fed_discount"] = round(0.5 * out["weight"], 3)
    top = max(gl, key=lambda g: abs(g["value"]) * g["importance"])
    out["market"] = top["market"]
    sd_ = side(out["signal"])
    out["note"] = (f"الإصدارات الموثّقة: {top['lead']} — {sd_}" + (f"؛ {top['conflict']}" if top.get("conflict") else "")
                   + (f"؛ {top['trend']}" if top.get("trend") and "مستقر" not in top["trend"] and "غير" not in top["trend"][:20] else "")
                   + (f"؛ {top['market']['label']}" if top["market"] else ""))
    return out
