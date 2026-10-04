#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات محرك الإثبات (بيانات اصطناعية، دون إنترنت): python tests_backtest.py"""
import random
from datetime import date, timedelta

import backtest as b


def bdays(n, start=date(2023, 1, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def synth(n=420, seed=7, link=True, tail_override=None):
    """سوق اصطناعي: «ضغط» كامن يرفع VIX والمدى التالي معاً."""
    rnd = random.Random(seed)
    days = bdays(n)
    stress, hist = 0.0, {k: [] for k in ["es", "vix", "vix3m", "nq", "gold", "oil", "dxy", "y10", "y5", "irx", "jpy", "spy", "rsp", "hyg", "ief", "xlf", "kre", "nikkei"]}
    px = {k: 100.0 for k in hist}
    px["vix"], px["vix3m"], px["y10"], px["y5"], px["irx"] = 16.0, 18.0, 4.0, 3.9, 4.2
    for i, d in enumerate(days):
        stress = 0.85 * stress + rnd.gauss(0, 1)
        for k in hist:
            if k in ("vix", "vix3m"):
                base = 16 + 3 * stress if link else 16 + rnd.gauss(0, 3)
                px[k] = max(9.0, base + (2 if k == "vix3m" else 0) + rnd.gauss(0, 0.4))
            elif k in ("y10", "y5", "irx"):
                px[k] = max(0.5, px[k] + rnd.gauss(0, 0.03))
            else:
                px[k] *= 1 + rnd.gauss(0, 0.006 + (0.002 * abs(stress) if k in ("es", "nq", "gold", "oil") else 0))
        # المدى التالي يتبع الضغط الحالي
        nxt_rng = 0.6 + (0.35 * max(0.0, stress) if link else rnd.random() * 0.5) + abs(rnd.gauss(0, 0.1))
        for k, rows in hist.items():
            c = px[k]
            hi, lo = (c * (1 + nxt_rng / 200), c * (1 - nxt_rng / 200)) if k == "es" else (c, c)
            rows.append({"d": d, "c": c, "o": c / (1 + rnd.gauss(0, 0.004)), "h": hi, "l": lo, "v": 1e6 * (1 + rnd.random() * 0.2)})
    # المدى في اليوم i هو دالة ضغط اليوم i-1: نزيح ليكون المدى التالي مرتبطاً بالدرجة
    es = hist["es"]
    for i in range(len(es) - 1, 0, -1):
        es[i]["h"], es[i]["l"] = es[i - 1]["h"], es[i - 1]["l"]
    return hist


def test_stats_helpers():
    assert abs(b.spearman(list(range(20)), [x * x for x in range(20)]) - 1) < 1e-9
    assert b.spearman([1, 2], [2, 1]) is None
    x = [float(i) for i in range(40)]
    y = [2 * v + 1 for v in x]
    assert b.ols_r2([x], y) > 0.999
    noise = [((i * 7919) % 13) / 13 for i in range(40)]
    assert b.ols_r2([noise], y) < 0.2


def test_no_lookahead():
    h = synth()
    H1 = b.Hist(h)
    d = h["es"][200]["d"]
    s1 = b.day_snapshot(H1, None, d)
    h2 = {k: [dict(r) for r in v] for k, v in h.items()}
    for k, rows in h2.items():                       # نغيّر المستقبل بعد d تغييراً كبيراً
        for r in rows:
            if r["d"] > d:
                r["c"] *= 3
                r["h"] *= 3
                r["l"] *= 3
    s2 = b.day_snapshot(b.Hist(h2), None, d)
    assert s1 is not None and abs(s1[0] - s2[0]) < 1e-9


def test_predictive_market_is_detected():
    res = b.run_backtest(synth(link=True))
    assert res["n"] > 250 and res["rho_score"] > 0.3
    assert res["quintiles"][4]["avg_next_range"] > res["quintiles"][0]["avg_next_range"]
    assert res["r2_full"] >= res["r2_base"] - 1e-9


def test_random_market_shows_no_edge():
    res = b.run_backtest(synth(link=False, seed=11))
    assert res["rho_score"] < 0.25
    assert "ضعيف" in b.verdict({"r2_gain": 0.0, "rho_score": 0.05}) or "صغيرة" in b.verdict({"r2_gain": 0.0, "rho_score": 0.22})


def test_too_little_data_and_format():
    res = b.run_backtest(synth(n=90))
    assert "error" in res and "غير كافية" in b.format_result(res)
    ok = b.run_backtest(synth())
    txt = b.format_result(ok)
    assert "ارتباط الدرجة" in txt and "VIX وحده" in txt and "الخلاصة" in txt and "خُمس" in txt
    assert len(ok["quintiles"]) == 5


def test_runner_backtest_mode_sends_summary():
    import runner as r
    box = []
    res = r.run_backtest(box.append, {"history": lambda: (synth(), ["بعض الرموز فشلت"]), "fred": lambda now: ({}, [])})
    assert res["n"] > 250 and "ارتباط الدرجة" in box[0] and "⚠ بعض الرموز فشلت" in box[0]


def test_tilt_test_runs_and_is_honest():
    res = b.run_backtest(synth(n=600))
    t = res["tilt"]
    assert "error" not in t and t["n"] > 300 and 0.3 < t["base_up"] < 0.7
    assert t["hit_all"] is not None and set(t["components"]) <= set(b.auction.TILT_W)
    assert "لا دليل" in b.tilt_verdict(t) or "يتفوق" in b.tilt_verdict(t)
    # سوق عشوائي: لا يُفترض أن يتفوق الميل
    assert abs(t["hit_all"] - 0.5) < 0.1
    assert "الميل السياقي اليومي" in b.format_result(res)
    short = b.tilt_test(synth(n=100))
    assert "error" in short


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({len(tests)})")
