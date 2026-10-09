# -*- coding: utf-8 -*-
"""
المرحلة 3 — اختبارات تحقق ببيانات اصطناعية (لا إنترنت هنا). تقيس سلوك المنطق، لا دقته على السوق الحقيقي.
python tests_validation.py
"""
import random
from datetime import datetime, timedelta, timezone

import geo
import runner

NOW = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)
SIG = {"es": 0.0007, "nq": 0.0009, "vix": 0.012, "oil": 0.0013, "gold": 0.0006, "dxy": 0.0003, "jpy": 0.0004,
       "y10": 0.0003, "y5": 0.0003, "y30": 0.0003, "hyg": 0.0002, "kre": 0.0012}      # تقلب شمعة 5 دقائق تقريبي (افتراض)
YIELDS = ("y10", "y5", "y30")


def noise_trial(seed):
    r = random.Random(seed)
    fresh, vols = {}, {}
    for k, s in SIG.items():
        p = 4.2 if k in YIELDS else 100.0
        ser, vv = [], []
        for i in range(120, -1, -1):
            t = NOW - timedelta(minutes=5 * i)
            p = p + r.gauss(0, s * 100) / 100 if k in YIELDS else p * (1 + r.gauss(0, s))
            ser.append((t, p))
            vv.append((t, 1000 * r.lognormvariate(0, 0.5)))
        fresh[k] = ser
        if k in runner.VOLUME_KEYS:
            vols[k] = vv
    return runner.detect_move(fresh, vols)


def move_trial(seed, pct, volx=2.2):
    r = random.Random(10_000 + seed)
    fresh, vols = {}, {}
    for k in ("es", "nq"):
        p, ser, vv = 100.0, [], []
        for i in range(120, -1, -1):
            t = NOW - timedelta(minutes=5 * i)
            p *= 1 + ((pct / 12) if i < 12 else 0.0) + r.gauss(0, SIG[k] * 0.5)
            ser.append((t, p))
            vv.append((t, 1000 * r.lognormvariate(0, 0.3) * (volx if i < 6 else 1.0)))
        fresh[k], vols[k] = ser, vv
    return runner.detect_move(fresh, vols)


def test_false_alarm_rate_on_pure_noise():
    """قياس: نسبة الفحوص التي تُنبّه على ضجيج عشوائي بحت (قيمة القياس ≈1.1% في 1500 تجربة؛ الحد هنا 3%)."""
    n = 600
    rate = sum(1 for i in range(n) if noise_trial(i)) / n
    assert rate < 0.03, rate


def test_detects_injected_strong_moves():
    n = 150
    d6 = sum(1 for i in range(n) if move_trial(i, 0.006)) / n
    d9 = sum(1 for i in range(n) if move_trial(i, 0.009)) / n
    assert d9 >= 0.95 and d6 >= 0.8, (d6, d9)


def test_move_without_volume_support_is_not_confirmed():
    n = 150
    hits = sum(1 for i in range(n) if move_trial(i, 0.009, volx=0.6))
    assert hits / n < 0.2, hits / n


H = lambda h, t: (NOW - timedelta(hours=h), t)


def test_conflicting_geo_news():
    atk = [H(5, "Missile attack on Gulf oil facility, two killed - Reuters"), H(5, "Iran missile attack hits Gulf oil facility - AP")]
    cf = [H(1, "Ceasefire agreed in Gulf after missile attack - BBC"), H(1, "Truce holds in Gulf, talks continue to ease tension - FT")]
    s_atk = geo.score_geo_news(atk, None, NOW)[0]
    s_mix, note, d = geo.score_geo_news(atk + cf, None, NOW)
    assert s_mix <= s_atk and d["conflict"] and "متعارضة" in note           # كانت 5.9 > 3.4 قبل الإصلاح
    s_cf = geo.score_geo_news(cf, None, NOW)[0]
    assert s_cf < s_atk                                                       # تهدئة وحدها أقل خطراً
    again = geo.score_geo_news(cf + [H(0.2, "Missile attack on Gulf oil facility again, three killed - Reuters")], None, NOW)[0]
    assert again > s_cf                                                       # تصعيد جديد أحدث يعيد الخطر


def test_market_confirmation_logic():
    atk = [H(2, "Missile attack on Gulf oil facility, two killed - Reuters")]
    unconfirmed = geo.score_geo_news(atk, 2.0, NOW)[0]
    confirmed = geo.score_geo_news(atk, 7.0, NOW)[0]
    assert confirmed > unconfirmed


def test_known_cases_risk_levels():
    """حالات معروفة: يوم هادئ ≤3، يوم FOMC مع تقلب مرتفع ≥7، وهبوط حاد مع VIX>30 لا يقل عن «متوسطة»."""
    import collector as c
    from tests import calm_prices, ev_raw, NOW as TNOW, px
    calm = c.build_report(calm_prices(), c.parse_events([ev_raw("Core PCE", "High", 120)]), TNOW)
    assert calm["risk"]["score"] <= 3, calm["risk"]["score"]
    p = calm_prices()
    p.update({"vix": px(31, 15.0), "vix3m": px(27), "es": px(5700, -2.4, -3.5, -4.0, vol_ratio=1.8), "gold": px(2700, 1.6), "oil": px(78, 3.0)})
    hot = c.build_report(p, c.parse_events([ev_raw("Federal Funds Rate", "High", 2)]), TNOW)
    assert hot["risk"]["score"] >= 7, hot["risk"]["score"]
    p2 = calm_prices()
    p2.update({"vix": px(32, 5.0), "vix3m": px(29)})
    stressed = c.build_report(p2, c.parse_events([ev_raw("Core PCE", "High", 120)]), TNOW)
    assert stressed["risk"]["score"] >= 5, stressed["risk"]["score"]


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
if __name__ == "__main__":
    for t in TESTS:
        t()
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({len(TESTS)})")
