#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات المنظومة الكلية (دون إنترنت): python tests_macro.py"""
from datetime import datetime, timezone

import collector as c
import macro as m
import runner as r
from tests import calm_prices
from tests_runner import NOW, Box, calm_intraday, deps


def monthly(start_y, start_m, vals):
    out, y, mo = [], start_y, start_m
    for v in vals:
        out.append((f"{y}-{mo:02d}-01", v))
        mo += 1
        if mo == 13:
            y, mo = y + 1, 1
    return out


def level_series(n, start, annual_pct):
    """سلسلة شهرية بنمو سنوي ثابت."""
    g = (1 + annual_pct / 100) ** (1 / 12)
    return [start * g ** i for i in range(n)]


def daily(v, n=5):
    return [(f"2026-10-0{i + 1}", v) for i in range(n)]


def base_series(infl=3.2, u=3.9, effr=4.5, m3=4.5, m6=4.5, y1=4.4, nfci=-0.4, hy=3.0, pay_step=170):
    s = {
        "core_pce": monthly(2025, 1, level_series(20, 120.0, infl)),     # حتى 2026-08
        "unrate": monthly(2025, 1, [u] * 20),
        "payems": monthly(2025, 1, [150000 + pay_step * i for i in range(20)]),
        "claims": [(f"w{i}", 220000.0) for i in range(60)],
        "nfci": daily(nfci), "hy": daily(hy),
        "effr": daily(effr), "m3": daily(m3), "m6": daily(m6), "y1": daily(y1),
    }
    return s


def test_yoy_ann3_and_sahm():
    s = monthly(2025, 1, level_series(20, 100.0, 3.0))
    assert abs(m.yoy(s) - 3.0) < 0.01 and abs(m.ann3(s) - 3.0) < 0.05
    assert m.yoy(s[:10]) is None
    flat = monthly(2024, 1, [4.0] * 16)
    assert abs(m.sahm(flat)) < 1e-9
    rising = monthly(2024, 1, [4.0] * 12 + [4.4, 4.8, 5.0])
    assert m.sahm(rising) >= 0.5


def test_hot_inflation_tight_labor_is_hawkish():
    v = m.analyze(base_series(), calm_prices(), NOW)
    assert v and v["label"] == "متشدد" and v["lean"] > 0.25
    keys = {p["key"]: p for p in v["pillars"]}
    assert keys["inflation"]["arrow"] == "▲" and keys["labor"]["arrow"] == "▲"
    assert v["taylor"]["rule"] > v["taylor"]["effr"]            # القاعدة تقترح فائدة أعلى من الفعلية


def test_cooling_and_weak_labor_is_dovish():
    u = [4.0] * 12 + [4.3, 4.6, 4.9, 5.1, 5.2, 5.3, 5.3, 5.4]
    s = base_series(infl=2.0, nfci=0.4, hy=5.5, pay_step=-5)
    s["unrate"] = monthly(2025, 1, u)
    v = m.analyze(s, calm_prices(), NOW)
    assert v["label"] == "متساهل" and v["lean"] < -0.25


def test_pricing_gap_flags_surprise_direction():
    hawk_data_dovish_market = base_series(m3=4.1, m6=3.8, y1=3.6)     # السوق يسعّر تخفيضات رغم بيانات متشددة
    v = m.analyze(hawk_data_dovish_market, calm_prices(), NOW)
    assert v["gap"]["size"] in ("كبيرة", "متوسطة") and "متشددة" in v["gap"]["direction"]
    aligned = m.analyze(base_series(m3=4.5, m6=4.6, y1=4.6), calm_prices(), NOW)
    assert aligned["gap"]["value"] < v["gap"]["value"]
    s_gap, _ = m.score_fed_system(v)
    s_ok, _ = m.score_fed_system(aligned)
    assert s_gap > s_ok


def test_meeting_proximity_and_dates():
    d, n = m.days_to_meeting(NOW)           # 7 أكتوبر 2026 ← اجتماع 28 أكتوبر
    assert d == "2026-10-28" and n == 21
    v = m.analyze(base_series(m3=4.1, m6=3.8, y1=3.6), calm_prices(), NOW)
    near = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    far = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)
    v_near, v_far = m.analyze(base_series(m3=4.1, m6=3.8, y1=3.6), calm_prices(), near), m.analyze(base_series(m3=4.1, m6=3.8, y1=3.6), calm_prices(), far)
    assert m.score_fed_system(v_near)[0] > m.score_fed_system(v_far)[0]


def test_dilemma_detected():
    u = [4.0] * 12 + [4.3, 4.6, 4.9, 5.1, 5.2, 5.3, 5.3, 5.4]
    s = base_series(infl=3.8, pay_step=-5)
    s["unrate"] = monthly(2025, 1, u)
    v = m.analyze(s, calm_prices(), NOW)
    assert v["dilemma"] and v["confidence"] != "مرتفعة"


def test_insufficient_data_returns_none():
    assert m.analyze({}, calm_prices(), NOW) is None
    assert m.analyze({"effr": daily(4.5)}, calm_prices(), NOW) is None
    assert m.score_fed_system(None)[0] is None


def test_report_and_message_integration():
    rep = c.build_report(calm_prices(), [], NOW, [], {"macro": base_series(m3=4.1, m6=3.8, y1=3.6)})
    keys = [x["key"] for x in rep["risk"]["components"]]
    assert "fed_system" in keys and rep["macro"]["label"] == "متشدد"
    assert abs(sum(x["weight"] for x in rep["risk"]["components"]) - 1) < 0.01
    nom = c.build_report(calm_prices(), [], NOW, [], {})
    assert "fed_system" not in [x["key"] for x in nom["risk"]["components"]] and nom["macro"] is None
    box = Box()
    d = deps([], calm_intraday())
    d["macro"] = lambda now: (base_series(m3=4.1, m6=3.8, y1=3.6), [])
    r.run_preopen(NOW, {"seen_events": [], "last_shock": None}, box, d)
    msg = box.msgs[0]
    assert "المنظومة الكلية" in msg and "ميل الفدرالي" in msg and "فجوة التسعير" in msg and "افتراضات" in msg
    box2 = Box()
    d["macro"] = lambda now: (_ for _ in ()).throw(RuntimeError("حجب"))
    r.run_preopen(NOW, {"seen_events": [], "last_shock": None}, box2, d)
    assert "تعذّر جلب بيانات المنظومة" in box2.msgs[0] and "المخاطرة:" in box2.msgs[0]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({len(tests)})")
