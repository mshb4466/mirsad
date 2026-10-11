# -*- coding: utf-8 -*-
"""
مِرصاد — الانحياز الماكروي لـ ES (قاعدي شفاف، منفصل عن مقياس المخاطر).

ما هو: متوسط مرجَّح لإشارات ماكروية، كل إشارة في [-1, +1] حيث موجب = داعم لـ ES وسالب = ضاغط.
ما ليس هو: ليس نموذجاً إحصائياً مُدرَّباً ولا توقعاً لاتجاه اليوم. الأوزان وحدود التطبيع **أحكام تقديرية غير معايَرة**
ولم تُختبر على بيانات تاريخية. الغرض: خلاصة مفهومة قابلة للتفكيك (كل مكوّن يظهر بمساهمته).
إن نقصت التغطية عن الحد الأدنى يُرجع «غير متاح» بدل رقم مضلّل.
لا يغيّر معادلات المخاطر. فشل ناعم.
"""

MIN_COVERAGE = 0.5      # أدنى وزن متاح (من 1.0) لإصدار انحياز
LABEL_T = 0.25          # حدّ الداعم/الضاغط

# الوزن، ثم الاسم
W = {
    "fed": (0.25, "ميل الفدرالي من البيانات"),
    "gap": (0.15, "تسعير السوق للفائدة مقابل البيانات"),
    "y10": (0.15, "العائد 10 سنوات (20 يوماً)"),
    "credit": (0.15, "الائتمان (فروق السندات عالية المخاطر)"),
    "dxy": (0.10, "الدولار (20 يوماً)"),
    "liq": (0.10, "السيولة الصافية (4 أسابيع)"),
    "oil": (0.05, "النفط (20 يوماً)"),
    "regime": (0.05, "النظام الاقتصادي"),
}
REGIME_S = {"goldilocks": 0.6, "slowdown": 0.1, "mixed": 0.0, "transition": 0.0, "overheating": -0.5, "stagflation": -1.0}


def clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _chg(prices, key, n=20, pct=True):
    """تغيّر آخر n يوم تداول من closes: نسبة % أو فرق مطلق. None إن قصرت البيانات."""
    cl = ((prices or {}).get(key) or {}).get("closes") or []
    if len(cl) < max(10, n // 2 + 1):
        return None
    k = min(n, len(cl) - 1)
    a, b = cl[-1][1], cl[-1 - k][1]
    if not b:
        return None
    return (a / b - 1) * 100 if pct else (a - b)


def signals(macro_view, prices, fred, regime):
    """{مفتاح: (إشارة [-1,1], ملاحظة)} للمتاح فقط."""
    out = {}
    m = macro_view or {}
    if m.get("lean") is not None:
        out["fed"] = (clip(-m["lean"]), f"ميل الفدرالي {m.get('label', '')} ({m['lean']:+.2f})")
    g = (m.get("gap") or {}).get("value")
    if g is not None:
        # فجوة موجبة = السوق يسعّر تيسيراً أكثر من البيانات = خطر مفاجأة متشددة = ضاغط
        out["gap"] = (clip(-g / 0.8), f"فجوة التسعير {g:+.2f} ({(m.get('gap') or {}).get('size', '')})")
    y = _chg(prices, "y10", 20, pct=False)
    if y is not None:
        bp = y * 100
        out["y10"] = (clip(-bp / 40.0), f"العائد 10س {bp:+.0f} نقطة أساس خلال 20 يوماً")
    d = _chg(prices, "dxy", 20)
    if d is not None:
        out["dxy"] = (clip(-d / 3.0), f"الدولار {d:+.1f}% خلال 20 يوماً")
    o = _chg(prices, "oil", 20)
    if o is not None:
        out["oil"] = (clip(-o / 15.0), f"النفط {o:+.1f}% خلال 20 يوماً")
    nl = m.get("net_liquidity")
    if nl and nl.get("chg_pct") is not None:
        out["liq"] = (clip(nl["chg_pct"] / 3.0), f"السيولة الصافية {nl['chg_pct']:+.1f}% خلال 4 أسابيع")
    oas = (fred or {}).get("hy_oas")
    if oas:
        lvl = oas[-1][1]
        s = 0.6 if lvl < 3 else 0.2 if lvl < 3.75 else -0.2 if lvl < 4.5 else -0.6 if lvl < 5.5 else -1.0
        note = f"فروق الائتمان {lvl:.2f}%"
        if len(oas) >= 6:
            w = lvl - oas[-6][1]
            if w >= 0.3:
                s -= 0.4
                note += f"، اتسعت {w:+.2f} خلال 5 أيام"
            elif w <= -0.3:
                s += 0.2
                note += f"، ضاقت {w:+.2f} خلال 5 أيام"
        out["credit"] = (clip(s), note)
    rk = (regime or {}).get("key")
    if rk in REGIME_S:
        out["regime"] = (REGIME_S[rk], (regime or {}).get("text") or rk)
    return out


def confirm(b, drivers):
    """هل تتفق حركة الأسواق الفعلية الآن (اتجاه العوامل) مع الانحياز؟ تأكيد/تعارض/غير حاسم/غير متاح."""
    ds = [d for d in (drivers or []) if d.get("tone") in ("bull", "bear")]
    if not b or not b.get("available") or not ds:
        return {"key": "na", "label": "غير متاح", "why": "لا يوجد انحياز أو لا توجد حركة اتجاهية كافية للمقارنة"}
    bull = sum(float(d.get("strength", 1) or 1) for d in ds if d["tone"] == "bull")
    bear = sum(float(d.get("strength", 1) or 1) for d in ds if d["tone"] == "bear")
    mk = (bull - bear) / (bull + bear)
    mt = "bull" if mk >= 0.25 else "bear" if mk <= -0.25 else "flat"
    bt = {"support": "bull", "pressure": "bear", "neutral": "flat"}[b["key"]]
    if bt == "flat" or mt == "flat":
        k, l = "mixed", "غير حاسم"
        w = "الانحياز محايد" if bt == "flat" else "حركة الأسواق مختلطة"
    elif bt == mt:
        k, l, w = "yes", "الأسواق تؤكد", "حركة الدولار والعوائد والنفط وغيرها تسير في اتجاه الانحياز نفسه"
    else:
        k, l, w = "no", "الأسواق تعارض", "حركة الأسواق الآن عكس الانحياز الماكروي"
    return {"key": k, "label": l, "why": w, "market": round(mk, 2)}


def compute(macro_view, prices, fred, regime, drivers=None):
    """قاموس الانحياز. available=False عند ضعف التغطية."""
    sig = signals(macro_view, prices, fred, regime)
    tot = sum(v[0] for v in W.values())
    wsum = sum(W[k][0] for k in sig)
    cov = wsum / tot if tot else 0.0
    base = {"available": False, "coverage": round(cov, 2), "method": "قاعدي شفاف: متوسط مرجَّح لإشارات ماكروية؛ الأوزان تقديرية غير معايَرة ولم تُختبر تاريخياً"}
    if cov < MIN_COVERAGE:
        base["label"] = "غير متاح"
        base["why"] = f"البيانات الماكروية غير كافية (التغطية {cov:.0%} < {MIN_COVERAGE:.0%})"
        base["components"] = []
        base["confirm"] = confirm(base, drivers)
        return base
    score = sum(W[k][0] * sig[k][0] for k in sig) / wsum
    strong = [k for k in sig if abs(sig[k][0]) >= 0.2]
    sg = 1 if score >= 0 else -1
    agree = (sum(W[k][0] for k in strong if sig[k][0] * sg > 0) / sum(W[k][0] for k in strong)) if strong else 1.0
    if score >= LABEL_T:
        label, arrow, key = "داعم", "▲", "support"
    elif score <= -LABEL_T:
        label, arrow, key = "ضاغط", "▼", "pressure"
    else:
        label, arrow, key = "محايد", "◆", "neutral"
    conf = "مرتفعة" if cov >= 0.8 and agree >= 0.75 else "متوسطة" if cov >= 0.6 and agree >= 0.55 else "منخفضة"
    comps = []
    for k in sorted(sig, key=lambda k: abs(W[k][0] * sig[k][0]), reverse=True):
        s = sig[k][0]
        comps.append({"key": k, "name": W[k][1], "signal": round(s, 2), "weight": W[k][0],
                      "contribution": round(W[k][0] * s / wsum, 3),
                      "arrow": "▲" if s >= 0.2 else "▼" if s <= -0.2 else "◆",
                      "tone": "support" if s >= 0.2 else "pressure" if s <= -0.2 else "flat", "note": sig[k][1]})
    missing = [W[k][1] for k in W if k not in sig]
    top = [c for c in comps if c["tone"] != "flat"][:2]
    why = "؛ ".join(f"{c['name']} {c['arrow']}" for c in top) or "لا عامل حاسم"
    base.update({"available": True, "score": round(score, 2), "label": label, "key": key, "arrow": arrow,
                 "confidence": conf, "agreement": round(agree, 2), "components": comps,
                 "missing": missing, "why": why})
    base["confirm"] = confirm(base, drivers)
    return base
