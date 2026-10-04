#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — سياق المزاد للمتداول اليومي (Auction Market Theory) بالقواعد.

من شموع ES كل 5 دقائق يحسب: قيمة الجلسة السابقة (VAH/VAL/POC)، مدى الجلسة الليلية (Globex) ومخزونها،
موقع السعر الحالي من القيمة، الفجوة، والمدى المتوقع من VIX. ثم «ميل سياقي» تجريبي من عوامل يومية.
الميل **غير مُثبت**: يُقاس في backtest.py (نسبة إصابة الاتجاه مقابل نسبة الأساس) وتُعدَّل أوزانه بحسب النتيجة.
ليس إشارة دخول؛ التنفيذ وقراءة تدفق الأوامر لك.
"""
import math
from datetime import date, datetime, time, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001
    ET = timezone(timedelta(hours=-4))

TICK = 0.25
RTH_OPEN, RTH_CLOSE = time(9, 30), time(16, 0)


def clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def et(t):
    return t.astimezone(ET)


def split_sessions(bars, now):
    """bars: [{"t": UTC datetime بداية الشمعة، "o","h","l","c","v"}].
    يُرجع (شموع الجلسة العادية السابقة، شموع الجلسة الليلية حتى الآن، تاريخ الجلسة الحالية ET)."""
    nowe = et(now)
    today = nowe.date() if nowe.time() < RTH_CLOSE else nowe.date() + timedelta(days=1)
    # الجلسة العادية السابقة: آخر تاريخ ET < today فيه شموع RTH
    rth = {}
    for b in bars:
        e = et(b["t"])
        if RTH_OPEN <= e.time() < RTH_CLOSE and e.date() < today and e.weekday() < 5:
            rth.setdefault(e.date(), []).append(b)
    if not rth:
        return [], [], today
    prior_day = max(rth)
    prior = sorted(rth[prior_day], key=lambda b: b["t"])
    end_prior = et(prior[-1]["t"]) + timedelta(minutes=5)
    on = [b for b in bars if et(b["t"]) >= end_prior and b["t"] <= now and
          not (et(b["t"]).date() == today and et(b["t"]).time() >= RTH_OPEN)]
    return prior, sorted(on, key=lambda b: b["t"]), today


def volume_profile(bars):
    """ملف حجم تقريبي: يُوزَّع حجم كل شمعة بالتساوي على مستوياتها (خطوة 0.25). يُرجع POC وVAH وVAL (70%)."""
    vol = {}
    for b in bars:
        lo, hi = round(b["l"] / TICK), round(b["h"] / TICK)
        n = hi - lo + 1
        v = (b.get("v") or 0.0) / n
        for k in range(lo, hi + 1):
            vol[k] = vol.get(k, 0.0) + v
    total = sum(vol.values())
    if not vol or total <= 0:
        return None
    poc = max(vol, key=lambda k: (vol[k], -abs(k - sum(vol) / len(vol))))
    lo_k = hi_k = poc
    acc = vol[poc]
    levels = sorted(vol)
    kmin, kmax = levels[0], levels[-1]
    while acc / total < 0.70 and (lo_k > kmin or hi_k < kmax):
        up = sum(vol.get(hi_k + i, 0.0) for i in (1, 2)) if hi_k < kmax else -1
        dn = sum(vol.get(lo_k - i, 0.0) for i in (1, 2)) if lo_k > kmin else -1
        if up >= dn:
            for i in (1, 2):
                if hi_k < kmax:
                    hi_k += 1
                    acc += vol.get(hi_k, 0.0)
        else:
            for i in (1, 2):
                if lo_k > kmin:
                    lo_k -= 1
                    acc += vol.get(lo_k, 0.0)
    return {"poc": poc * TICK, "vah": hi_k * TICK, "val": lo_k * TICK}


def context(bars, now, vix=None):
    prior, on, today = split_sessions(bars, now)
    if len(prior) < 20:
        return None
    prof = volume_profile(prior)
    if not prof:
        return None
    ph, pl, pc = max(b["h"] for b in prior), min(b["l"] for b in prior), prior[-1]["c"]
    last = (on[-1]["c"] if on else pc)
    out = {"date": str(today), "prior": {"high": ph, "low": pl, "close": pc, "open": prior[0]["o"], **prof}}
    if on:
        onh, onl = max(b["h"] for b in on), min(b["l"] for b in on)
        inv = (last - onl) / (onh - onl) if onh > onl else 0.5
        out["overnight"] = {"high": onh, "low": onl, "last": last, "range": onh - onl, "inventory": inv,
                            "inventory_label": "مخزون شرائي (قرب قمة الليل)" if inv >= 0.7 else
                            "مخزون بيعي (قرب قاع الليل)" if inv <= 0.3 else "مخزون متوازن"}
    out["gap"] = {"points": last - pc, "pct": (last / pc - 1) * 100}
    if last > prof["vah"]:
        loc = "above_value"
    elif last < prof["val"]:
        loc = "below_value"
    else:
        loc = "inside_value"
    out["location"] = loc
    out["outside_prior_range"] = last > ph or last < pl
    if vix:
        sigma = last * (vix / 100.0) / math.sqrt(252.0)
        out["expected"] = {"sigma_pts": sigma, "range_pts": 1.6 * sigma,
                           "note": "VIX يميل لتضخيم الحركة الفعلية؛ المدى الحقيقي كثيراً ما يكون أقل"}
    out["playbook"] = playbook(out)
    return out


LOC_AR = {"above_value": "أعلى قيمة الأمس", "below_value": "أسفل قيمة الأمس", "inside_value": "داخل قيمة الأمس"}


def playbook(ctx):
    """وصف سياقي بلغة المزاد (قواعد شائعة للفرز، لا توصية دخول)."""
    loc, g = ctx["location"], ctx["gap"]
    p, lines = ctx["prior"], []
    if loc == "inside_value":
        lines.append("الافتتاح داخل قيمة الأمس: يُرجَّح التوازن والتأرجح بين VAL وVAH ما لم تظهر مبادرة")
    else:
        side = "أعلى" if loc == "above_value" else "أسفل"
        edge = p["vah"] if loc == "above_value" else p["val"]
        other = p["val"] if loc == "above_value" else p["vah"]
        lines.append(f"الافتتاح {side} القيمة: القبول خارجها (استقرار 2 من فترات 30د) يدعم الاستمرار؛ "
                     f"العودة وقبولها داخل القيمة تفتح قاعدة الـ80% نحو {other:.2f} (قاعدة شائعة تحتاج تأكيدك)")
        lines.append(f"المستوى الفاصل: {edge:.2f}")
    if ctx.get("outside_prior_range"):
        lines.append("السعر خارج مدى الأمس كاملاً: فجوة بمبادرة؛ راقب هل يُرفض أم يُقبل")
    if "overnight" in ctx:
        o = ctx["overnight"]
        lines.append(f"الليل: {o['inventory_label']}؛ مخزون أحادي الاتجاه يزيد قابلية التصحيح عند الافتتاح")
    return lines


# ───────────────────────── الميل السياقي اليومي (تجريبي) ─────────────────────────

TILT_W = {"gap": 0.20, "clv": 0.15, "vix": 0.20, "tech": 0.10, "dxy": 0.10, "trend": 0.10}
TILT_NAMES = {"gap": "فجوة الافتتاح", "clv": "إغلاق الأمس ضمن مداه", "vix": "تغير VIX", "tech": "ناسداك مقابل ES",
              "dxy": "الدولار", "trend": "اتجاه 5 أيام"}


def tilt(f, weights=None):
    """f: gap_pct, clv(0..1), vix_chg1, nq_minus_es, dxy_chg1, chg5 — أي عامل مفقود يُهمل. يُرجع (ميل -1..+1، تفاصيل)."""
    w = weights or TILT_W
    raw = {
        "gap": clamp(f["gap_pct"] / 0.6) if f.get("gap_pct") is not None else None,
        "clv": clamp((f["clv"] - 0.5) * 2) if f.get("clv") is not None else None,
        "vix": -clamp(f["vix_chg1"] / 8.0) if f.get("vix_chg1") is not None else None,
        "tech": clamp(f["nq_minus_es"] / 0.5) if f.get("nq_minus_es") is not None else None,
        "dxy": -clamp(f["dxy_chg1"] / 0.6) if f.get("dxy_chg1") is not None else None,
        "trend": clamp(f["chg5"] / 2.0) if f.get("chg5") is not None else None,
    }
    use = {k: v for k, v in raw.items() if v is not None}
    if len(use) < 3:
        return None, {}
    ws = sum(w[k] for k in use)
    score = sum(w[k] * v for k, v in use.items()) / ws
    return score, {k: round(v, 2) for k, v in use.items()}


def tilt_label(s):
    return ("ميل صاعد", "▲") if s >= 0.25 else ("ميل هابط", "▼") if s <= -0.25 else ("محايد", "◆")


def tilt_features(prices, ctx=None):
    es, nq, vix, dxy = prices.get("es"), prices.get("nq"), prices.get("vix"), prices.get("dxy")
    f = {}
    if ctx and ctx.get("gap"):
        f["gap_pct"] = ctx["gap"]["pct"]
    bars = (es or {}).get("bars") or []
    if bars:
        _, hi, lo, cl = bars[-1]
        if hi > lo:
            f["clv"] = (cl - lo) / (hi - lo)
    if vix:
        f["vix_chg1"] = vix["chg1"]
    if es and nq:
        f["nq_minus_es"] = nq["chg1"] - es["chg1"]
    if dxy:
        f["dxy_chg1"] = dxy["chg1"]
    if es:
        f["chg5"] = es["chg5"]
    return f


def lines(ctx, tilt_res):
    """أسطر رسالة تيليجرام."""
    out = []
    if ctx:
        p = ctx["prior"]
        out.append(f"🎯 سياق المزاد (ES) — جلسة {ctx['date']}")
        out.append(f"• قيمة الأمس: VAL {p['val']:.2f} | POC {p['poc']:.2f} | VAH {p['vah']:.2f} (مدى {p['low']:.2f}–{p['high']:.2f}، إغلاق {p['close']:.2f})")
        if "overnight" in ctx:
            o = ctx["overnight"]
            out.append(f"• الليل: {o['low']:.2f}–{o['high']:.2f} (مدى {o['range']:.1f} نقطة) | الآن {o['last']:.2f} | {o['inventory_label']}")
        g = ctx["gap"]
        out.append(f"• الموقع: {LOC_AR[ctx['location']]} | الفجوة {g['points']:+.2f} ({g['pct']:+.2f}%)")
        if "expected" in ctx:
            e = ctx["expected"]
            out.append(f"• المدى المتوقع من VIX: ±{e['sigma_pts']:.0f} نقطة (1σ)، مدى الجلسة ≈{e['range_pts']:.0f} نقطة (غالباً أقل فعلياً)")
        out += [f"• {x}" for x in ctx["playbook"]]
    if tilt_res and tilt_res[0] is not None:
        s, parts = tilt_res
        lab, arrow = tilt_label(s)
        top = sorted(parts.items(), key=lambda kv: abs(kv[1]) * TILT_W[kv[0]], reverse=True)[:3]
        why = "، ".join(f"{TILT_NAMES[k]} {'▲' if v > 0.15 else '▼' if v < -0.15 else '◆'}" for k, v in top)
        out.append(f"{arrow} الميل السياقي اليومي: {lab} ({s:+.2f}) — {why} — تجريبي لم يُثبت بعد")
    return out
