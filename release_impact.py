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
"""
from datetime import timedelta

import actuals
import events_ctx
import indicators
import values
from verification import is_verified

# مفاجأة معتادة (SD) بوحدة الرقم كما يخرج من values.pair: نقطة مئوية، أو ألف (K) للأعداد، أو مليون للوظائف الشاغرة
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


def _scale(spec, kind):
    if spec and spec["key"] in SD:
        return SD[spec["key"]]
    return SD_KIND.get(kind)


def item_for(ev, now, macro_label, lean, series):
    """مساهمة إصدار واحد، أو None إن لم يكن موثّقاً أو لا يُقاس عددياً. لا يرفع استثناءً."""
    if not is_verified(ev):
        return None
    kind, name, _ = events_ctx.classify(ev.get("title", ""))
    if kind not in IMPORTANCE:
        return None
    spec = indicators.match(ev.get("title", ""))
    sd = _scale(spec, kind)
    pr = values.pair(ev.get("actual"), ev.get("forecast"))
    if not sd or not pr:
        return None
    age_h = (now - ev["time"]).total_seconds() / 3600.0
    decay = _decay(age_h)
    if decay <= 0:
        return None
    z = max(-3.0, min(3.0, (pr[0] - pr[1]) / sd))
    hawk = "متشدد" in (macro_label or "")
    eff = events_ctx.EFFECT.get(kind, (("neu",) * 3,) * 2)[0 if hawk else 1]
    idx = 1 if abs(z) < 1e-9 else (0 if z > 0 else 2)
    d = {"bull": 1, "bear": -1}.get(eff[idx], 0)
    mag = min(1.0, abs(z) / 2.0)
    signal = d * mag
    push = (1 if z > 0 else -1 if z < 0 else 0) * events_ctx.HAWK_DIR.get(kind, 1)
    rev_txt = ""
    if ev.get("prev_revised") and ev.get("previous"):
        rp = values.pair(ev["prev_revised"], ev["previous"])
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
    sur = events_ctx.surprise(ev.get("actual"), ev.get("forecast"))
    eff_ar = {1: "داعم", -1: "ضاغط", 0: "محدود"}[d]
    initial = f"{name}: {sur or 'مطابق للتوقع'} ← أثر أولي {eff_ar} على ES"
    if ctxf != 1.0:
        initial += " (يتوافق مع ميل الفدرالي فيقوى)" if ctxf > 1 else " (عكس ميل الفدرالي فيخفّ)"
    return {"id": actuals.event_id(ev), "title": ev.get("title", ""), "name": name, "kind": kind, "date": ev["time"].date().isoformat(),
            "time": ev["time"].isoformat(), "actual": ev.get("actual", ""), "forecast": ev.get("forecast", ""), "previous": ev.get("previous", ""),
            "source": ev.get("actual_source", ""), "trust": ev.get("actual_src", ""), "status": ev.get("status", ""),
            "z": round(z, 2), "effect": {1: "bull", -1: "bear", 0: "neu"}[d], "signal": round(signal, 3), "ctx_factor": ctxf,
            "decay": round(decay, 2), "importance": round(importance, 2), "final": round(final, 3),
            "initial": initial, "revision": rev_txt, "market": {"key": mk_key, "label": mk_label, "mult": mult, "move": mv if isinstance(mv, dict) else {}},
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
    for (kind, day), mem in groups.items():
        sig = [x["final"] for x in mem]
        if all(s >= 0 for s in sig) or all(s <= 0 for s in sig):
            val = max(sig, key=abs)                       # اتفقوا: أقوى إشارة، لا مجموعها
            mode = "أقوى إشارة (لا مجموع)"
        else:
            val = sum(sig) / len(sig)                      # اختلفوا: يتعادلان جزئياً
            mode = "متوسط (إشارات متعاكسة)"
        imp = max(x["importance"] * x["decay"] for x in mem)
        lead = max(mem, key=lambda x: abs(x["final"]))
        gl.append({"kind": kind, "date": day, "ids": [x["id"] for x in mem], "titles": [x["title"] for x in mem], "value": round(val, 3),
                   "importance": round(imp, 3), "mode": mode, "lead": lead["title"], "initial": lead["initial"], "market": lead["market"],
                   "revision": next((x["revision"] for x in mem if x["revision"]), ""), "effect": lead["effect"]})
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
    side = "داعم" if out["signal"] >= 0.2 else "ضاغط" if out["signal"] <= -0.2 else "محدود الأثر"
    out["note"] = f"الإصدارات الموثّقة: {top['lead']} — {side}" + (f"؛ {top['market']['label']}" if top["market"] else "")
    return out
