#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — محرك الإثبات (Backtest) على بيانات يومية تاريخية.

يعيد حساب المكوّنات القابلة للحساب من بيانات يومية (السوق فقط) لكل يوم تاريخي **دون نظر إلى المستقبل**،
ثم يقارن الدرجة بمدى ES في اليوم التالي، ويختبرها أمام خطّي أساس صادقين:
  (١) VIX وحده، (٢) مدى ES في اليوم الحالي (استمرار التقلب).
لا يشمل: الأحداث الكبرى، الأخبار، المنظومة الكلية الشهرية (لا بيانات تاريخية مجانية موثوقة لها هنا).
النتيجة تقيس «مكوّنات السوق» فقط، وليست حكماً على التطبيق كاملاً.
"""
import bisect
import json
import math
from datetime import datetime, timezone

import auction
import collector as c

# مكوّنات تُحسب من بيانات يومية فقط
TESTABLE = ["volatility", "vix_term", "geopolitics", "conflict", "liquidity", "rates", "front_end",
            "dollar", "credit", "breadth", "global_mkts", "calendar"]


# ───────────────────────── إحصاء ─────────────────────────

def ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(x, y):
    if len(x) < 10:
        return None
    return c.pearson(ranks(x), ranks(y))


def ols_r2(cols, y):
    """R² لانحدار خطي بمتغيرين أو أكثر (معادلات عادية بحل غاوس)."""
    n, k = len(y), len(cols) + 1
    X = [[1.0] + [col[i] for col in cols] for i in range(n)]
    A = [[sum(X[r][i] * X[r][j] for r in range(n)) for j in range(k)] for i in range(k)]
    b = [sum(X[r][i] * y[r] for r in range(n)) for i in range(k)]
    for i in range(k):
        piv = max(range(i, k), key=lambda r: abs(A[r][i]))
        A[i], A[piv], b[i], b[piv] = A[piv], A[i], b[piv], b[i]
        if abs(A[i][i]) < 1e-12:
            return 0.0
        for r in range(i + 1, k):
            f = A[r][i] / A[i][i]
            for cc in range(i, k):
                A[r][cc] -= f * A[i][cc]
            b[r] -= f * b[i]
    beta = [0.0] * k
    for i in range(k - 1, -1, -1):
        beta[i] = (b[i] - sum(A[i][j] * beta[j] for j in range(i + 1, k))) / A[i][i]
    my = sum(y) / n
    ss_tot = sum((v - my) ** 2 for v in y)
    ss_res = sum((y[r] - sum(beta[j] * X[r][j] for j in range(k))) ** 2 for r in range(n))
    return 1 - ss_res / ss_tot if ss_tot else 0.0


# ───────────────────────── بناء الحالة التاريخية ─────────────────────────

class Hist:
    """hist[key] = [{"d": تاريخ ISO, "c": إغلاق, "h": أعلى, "l": أدنى, "v": حجم}] مرتبة زمنياً."""

    def __init__(self, hist):
        self.h = {k: v for k, v in hist.items() if v}
        self.dates = {k: [r["d"] for r in v] for k, v in self.h.items()}

    def idx(self, key, d):
        """آخر صف بتاريخ ≤ d (بدون نظر للمستقبل)."""
        if key not in self.h:
            return None
        i = bisect.bisect_right(self.dates[key], d) - 1
        return i if i >= 5 else None

    def item(self, key, d):
        i = self.idx(key, d)
        if i is None:
            return None
        rows = self.h[key]
        cl = [r["c"] for r in rows[max(0, i - 69):i + 1]]
        scale = 0.1 if key in ("y10", "y5", "irx") and cl[-1] > 20 else 1.0
        cl = [x * scale for x in cl]
        dates = [r["d"] for r in rows[max(0, i - 69):i + 1]]
        last, prev = cl[-1], cl[-2]
        it = {"symbol": key, "last": last, "chg1": (last / prev - 1) * 100 if prev else 0.0,
              "chg3": (last / cl[-4] - 1) * 100 if cl[-4] else 0.0, "chg5": (last / cl[-6] - 1) * 100 if cl[-6] else 0.0,
              "diff1": last - prev, "bar_time": dates[-1] + "T20:00:00+00:00", "closes": list(zip(dates, cl))}
        if key == "es":
            vols = [r["v"] for r in rows[max(0, i - 21):i + 1] if r.get("v") is not None]
            if len(vols) >= 12 and sum(vols[:-1]) > 0:
                it["vol_ratio"] = vols[-1] / (sum(vols[:-1]) / len(vols[:-1]))
        return it


def fred_upto(fred, d, n=45):
    return {k: [x for x in v if x[0] <= d][-n:] for k, v in (fred or {}).items()}


def day_snapshot(H, fred, d):
    """يحسب الدرجة المركّبة والمكوّنات ليوم تاريخي d. يُرجع (score, comps) أو None."""
    p = {k: H.item(k, d) for k in H.h}
    p = {k: v for k, v in p.items() if v}
    if "es" not in p or "vix" not in p:
        return None
    fr = fred_upto(fred, d)
    now = datetime.fromisoformat(d + "T20:00:00+00:00")
    comps = {
        "volatility": c.score_volatility(p.get("vix")), "vix_term": c.score_vix_term(p),
        "geopolitics": c.score_geopolitics(p), "conflict": c.score_conflict(p, c.compute_correlations(p)),
        "liquidity": c.score_liquidity(p.get("es"), False), "rates": c.score_rates(p, fr),
        "front_end": c.score_front_end(p, fr), "dollar": c.score_dollar(p), "credit": c.score_credit(p, fr),
        "breadth": c.score_breadth(p), "global_mkts": c.score_global(p), "calendar": c.score_calendar(now),
    }
    avail = [k for k in TESTABLE if comps[k][0] is not None]
    if len(avail) < 4 or "volatility" not in avail:
        return None
    w, _ = c.adapt_weights(avail, None, now, p.get("vix"), comps, False)
    score = sum(comps[k][0] * w[k] for k in avail)
    return score, {k: comps[k][0] for k in avail}


def run_backtest(hist, fred=None, min_days=30):
    H = Hist(hist)
    es = H.h.get("es") or []
    rows = []
    for i in range(70, len(es) - 1):
        d = es[i]["d"]
        snap = day_snapshot(H, fred, d)
        if not snap:
            continue
        nxt = es[i + 1]
        if not nxt.get("c"):
            continue
        rng_next = (nxt["h"] - nxt["l"]) / nxt["c"] * 100
        rng_today = (es[i]["h"] - es[i]["l"]) / es[i]["c"] * 100
        vix = H.item("vix", d)["last"]
        rows.append({"d": d, "score": snap[0], "comps": snap[1], "next": rng_next, "today": rng_today, "vix": vix,
                     "next_abs_ret": abs(nxt["c"] / es[i]["c"] - 1) * 100})
    if len(rows) < min_days:
        return {"error": f"أيام غير كافية للاختبار ({len(rows)})", "n": len(rows)}
    sc, nx = [r["score"] for r in rows], [r["next"] for r in rows]
    out = {"n": len(rows), "from": rows[0]["d"], "to": rows[-1]["d"],
           "rho_score": spearman(sc, nx), "rho_vix": spearman([r["vix"] for r in rows], nx),
           "rho_today": spearman([r["today"] for r in rows], nx), "rho_ret": spearman(sc, [r["next_abs_ret"] for r in rows])}
    base = ols_r2([[r["today"] for r in rows], [r["vix"] for r in rows]], nx)
    full = ols_r2([[r["today"] for r in rows], [r["vix"] for r in rows], sc], nx)
    out["r2_base"], out["r2_full"], out["r2_gain"] = base, full, full - base
    # شرائح الدرجة (خُمسيات) ومتوسط المدى التالي
    order = sorted(rows, key=lambda r: r["score"])
    q = len(order) // 5
    out["quintiles"] = []
    for i in range(5):
        part = order[i * q:(i + 1) * q] if i < 4 else order[4 * q:]
        out["quintiles"].append({"q": i + 1, "avg_next_range": sum(r["next"] for r in part) / len(part),
                                 "avg_score": sum(r["score"] for r in part) / len(part)})
    out["tilt"] = tilt_test(hist)
    out["by_component"] = {k: spearman([r["comps"][k] for r in rows if k in r["comps"]], [r["next"] for r in rows if k in r["comps"]])
                           for k in TESTABLE if sum(1 for r in rows if k in r["comps"]) >= 30}
    return out


def tilt_test(hist, min_days=60):
    """هل يتنبأ «الميل السياقي اليومي» باتجاه الجلسة العادية (SPY: افتتاح ← إغلاق)؟
    العوامل من إغلاق اليوم السابق + فجوة الافتتاح الفعلية. الأساس: نسبة الأيام الصاعدة."""
    H = Hist(hist)
    spy = H.h.get("spy") or []
    rows = []
    for i in range(70, len(spy)):
        d, prev = spy[i]["d"], spy[i - 1]
        if not spy[i].get("o") or not prev["c"]:
            continue
        dprev = prev["d"]
        f = {"gap_pct": (spy[i]["o"] / prev["c"] - 1) * 100}
        if prev["h"] > prev["l"]:
            f["clv"] = (prev["c"] - prev["l"]) / (prev["h"] - prev["l"])
        vix, es, nq, dxy = (H.item(k, dprev) for k in ("vix", "es", "nq", "dxy"))
        if vix:
            f["vix_chg1"] = vix["chg1"]
        if es:
            f["chg5"] = es["chg5"]
        if es and nq:
            f["nq_minus_es"] = nq["chg1"] - es["chg1"]
        if dxy:
            f["dxy_chg1"] = dxy["chg1"]
        sc, parts = auction.tilt(f)
        if sc is None:
            continue
        ret = (spy[i]["c"] / spy[i]["o"] - 1) * 100
        rows.append({"tilt": sc, "parts": parts, "ret": ret, "up": ret > 0})
    if len(rows) < min_days:
        return {"error": f"أيام غير كافية للميل اليومي ({len(rows)})", "n": len(rows)}
    n = len(rows)
    base = sum(r["up"] for r in rows) / n

    def hit(sel):
        s = [r for r in sel if r["tilt"] != 0]
        return (sum((r["tilt"] > 0) == r["up"] for r in s) / len(s), len(s)) if s else (None, 0)
    strong = [r for r in rows if abs(r["tilt"]) >= 0.25]
    h_all, n_all = hit(rows)
    h_str, n_str = hit(strong)
    comp = {}
    for k in auction.TILT_W:
        sel = [r for r in rows if k in r["parts"] and r["parts"][k] != 0]
        if len(sel) >= 30:
            comp[k] = {"hit": sum((r["parts"][k] > 0) == r["up"] for r in sel) / len(sel),
                       "rho": spearman([r["parts"][k] for r in sel], [r["ret"] for r in sel]), "n": len(sel)}
    return {"n": n, "base_up": base, "hit_all": h_all, "n_all": n_all, "hit_strong": h_str, "n_strong": n_str,
            "rho": spearman([r["tilt"] for r in rows], [r["ret"] for r in rows]), "components": comp}


def tilt_verdict(t):
    if "error" in t:
        return t["error"]
    h, base = t["hit_strong"], max(t["base_up"], 1 - t["base_up"])
    if h is None or t["n_strong"] < 40:
        return "عدد الأيام القوية قليل؛ لا يمكن الحكم على الميل اليومي"
    if h - base >= 0.04 and t["rho"] and t["rho"] > 0.05:
        return "الميل اليومي يتفوق على الأساس؛ ما زال داخل العينة فيُختبر على بيانات حية قبل الاعتماد عليه"
    return "لا دليل كافٍ على أن الميل اليومي يتنبأ بالاتجاه؛ يُعامل كسياق لا كإشارة، وتُراجع أوزانه"


def verdict(res):
    if "error" in res:
        return res["error"]
    g, r = res["r2_gain"], res["rho_score"]
    if r is None:
        return "لا يمكن الحكم"
    if r >= 0.3 and g >= 0.01:
        return "المقياس (جزء السوق) يضيف قيمة فعلية فوق VIX ومدى اليوم."
    if r >= 0.2:
        return "المقياس يرتبط بالتقلب القادم، لكن إضافته فوق VIX ومدى اليوم صغيرة؛ يلزم ضبط الأوزان."
    return "ارتباط ضعيف: الأوزان تحتاج إعادة نظر قبل الاعتماد عليه."


def format_result(res):
    if "error" in res:
        return "🧪 مِرصاد — اختبار بأثر رجعي\n⚠ " + res["error"]
    f = lambda x: "—" if x is None else f"{x:+.2f}"
    lines = [f"🧪 مِرصاد — اختبار بأثر رجعي ({res['n']} يوماً: {res['from']} → {res['to']})",
             "المقصود: هل تتنبأ درجة «مكوّنات السوق» بمدى ES في اليوم التالي؟ (دون الأحداث والأخبار والمنظومة الكلية)", "",
             f"ارتباط الدرجة بالمدى التالي: {f(res['rho_score'])}",
             f"للمقارنة — VIX وحده: {f(res['rho_vix'])} | مدى اليوم: {f(res['rho_today'])}",
             f"القدرة التفسيرية R²: أساس (VIX + مدى اليوم) {res['r2_base']:.3f} ← مع الدرجة {res['r2_full']:.3f} (إضافة {res['r2_gain']:+.3f})",
             "", "متوسط مدى ES التالي بحسب خُمس الدرجة (1 أدنى ← 5 أعلى):"]
    lines += [f"  {x['q']}) درجة {x['avg_score']:.1f} ← مدى {x['avg_next_range']:.2f}%" for x in res["quintiles"]]
    comp = sorted(((v, k) for k, v in res["by_component"].items() if v is not None), reverse=True)
    if comp:
        lines += ["", "ارتباط كل مكوّن بالمدى التالي: " + "، ".join(f"{c.name_of(k).split(' (')[0]} {v:+.2f}" for v, k in comp)]
    t = res.get("tilt")
    if t:
        if "error" in t:
            lines += ["", "الميل اليومي: " + t["error"]]
        else:
            pc = lambda x: "—" if x is None else f"{x * 100:.1f}%"
            lines += ["", f"الميل السياقي اليومي (SPY افتتاح←إغلاق، {t['n']} يوماً): نسبة الأيام الصاعدة {pc(t['base_up'])}",
                      f"• إصابة الاتجاه كل الأيام {pc(t['hit_all'])} ({t['n_all']}) | الميل القوي |≥0.25| {pc(t['hit_strong'])} ({t['n_strong']}) | ارتباط {f(t['rho'])}"]
            if t["components"]:
                lines.append("• إصابة كل عامل: " + "، ".join(f"{auction.TILT_NAMES[k]} {pc(v['hit'])}" for k, v in t["components"].items()))
            lines.append("• " + tilt_verdict(t))
    lines += ["", "الخلاصة: " + verdict(res),
              "ملاحظة: اختبار داخل العينة بأوزان تقديرية؛ ارتباط الدرجة بالمدى لا يعني ربحية تداول."]
    return "\n".join(lines)


# ───────────────────────── جلب البيانات (يحتاج الإنترنت) ─────────────────────────

def fetch_history(years=5):
    import yfinance as yf
    hist, problems = {}, []
    for key, sym in c.SYMBOLS.items():
        if key.startswith(("m_", "b_")):
            continue
        try:
            h = yf.Ticker(sym).history(period=f"{years}y", interval="1d", auto_adjust=False).dropna(subset=["Close"])
            hist[key] = [{"d": ts.to_pydatetime().date().isoformat(), "c": float(r["Close"]), "o": float(r.get("Open", r["Close"])), "h": float(r.get("High", r["Close"])),
                          "l": float(r.get("Low", r["Close"])), "v": float(r["Volume"]) if "Volume" in h else None}
                         for ts, r in h.iterrows()]
        except Exception as e:  # noqa: BLE001
            problems.append(f"{key}: {e}")
    return hist, problems
