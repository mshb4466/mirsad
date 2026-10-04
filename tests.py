#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات منطق مِرصاد (دون إنترنت): python tests.py"""
from datetime import datetime, timedelta, timezone

import collector as c

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
BAR = NOW.isoformat()


def px(last, chg1=0.0, chg3=0.0, chg5=0.0, **kw):
    d = {"last": last, "chg1": chg1, "chg3": chg3, "chg5": chg5, "diff1": 0, "bar_time": BAR}
    d.update(kw)
    return d


def calm_prices():
    return {
        "es": px(5900, 0.2, 0.3, 0.8, vol_ratio=1.0), "vix": px(13.0, -1.0), "oil": px(70, 0.3),
        "gold": px(2650, 0.1), "dxy": px(103, 0.0), "y10": px(4.1, 0.0),
    }


def ev_raw(title, impact, hours):
    return {"title": title, "country": "USD", "impact": impact,
            "date": (NOW + timedelta(hours=hours)).isoformat(), "forecast": "", "previous": ""}


def test_classify():
    assert c.classify("Federal Funds Rate") == "FOMC"
    assert c.classify("FOMC Member Bowman Speaks") == "OTHER"   # خطاب عضو ليس قراراً
    assert c.classify("Non-Farm Employment Change") == "NFP"
    assert c.classify("CPI m/m") == "CPI"


def test_calm_day_is_low():
    r = c.build_report(calm_prices(), c.parse_events([ev_raw("Core PCE", "High", 120)]), NOW)
    assert r["risk"]["score"] <= 3, r["risk"]


def test_fomc_stress_day_is_high():
    p = {
        "es": px(5800, -1.1, -2.4, -1.5, vol_ratio=0.6), "vix": px(31, 14), "oil": px(78, 3.0),
        "gold": px(2750, 1.5), "dxy": px(104, 0.5), "y10": px(4.4, 0.0),
    }
    r = c.build_report(p, c.parse_events([ev_raw("Federal Funds Rate", "High", 2)]), NOW)
    assert r["risk"]["score"] >= 7, r["risk"]
    assert abs(sum(x["weight"] for x in r["risk"]["components"]) - 1) < 0.01
    assert "قرار الفائدة" in r["risk"]["main_reason"]


def test_event_weight_rises_near_event():
    p = calm_prices()
    near = c.build_report(p, c.parse_events([ev_raw("Federal Funds Rate", "High", 2)]), NOW)
    far = c.build_report(p, c.parse_events([ev_raw("Federal Funds Rate", "High", 200)]), NOW)
    w = lambda r: next(x["weight"] for x in r["risk"]["components"] if x["key"] == "events")
    assert w(near) > w(far)


def test_missing_data_excluded_and_reported():
    p = calm_prices()
    del p["vix"]
    r = c.build_report(p, c.parse_events([ev_raw("CPI m/m", "High", 30)]), NOW)
    keys = [x["key"] for x in r["risk"]["components"]]
    assert "volatility" not in keys
    assert any("استُبعدت" in x for x in r["problems"])
    assert abs(sum(x["weight"] for x in r["risk"]["components"]) - 1) < 0.01


def test_too_little_data_returns_error():
    r = c.build_report({"es": px(5900)}, [], NOW)
    assert "error" in r


def test_parse_real_feed_shape():
    # عيّنة بنفس شكل الخلاصة الحقيقية التي فُحصت (حقول: title, country, date, impact, forecast, previous)
    raw = [
        {"title": "Core PCE Price Index m/m", "country": "USD", "date": "2026-09-30T08:30:00-04:00",
         "impact": "High", "forecast": "0.3%", "previous": "0.2%"},
        {"title": "CB Consumer Confidence", "country": "USD", "date": "2026-09-29T10:00:00-04:00",
         "impact": "Medium", "forecast": "89.2", "previous": "89.4"},
        {"title": "German Ifo", "country": "EUR", "date": "2026-09-29T04:00:00-04:00",
         "impact": "High", "forecast": "", "previous": ""},
    ]
    ev = c.parse_events(raw)
    assert len(ev) == 2 and ev[0]["title"] == "CB Consumer Confidence"      # تُرتَّب زمنياً وتُستبعد العملات الأخرى
    assert ev[1]["time"].hour == 12 and ev[1]["forecast"] == "0.3%"         # 08:30 نيويورك = 12:30 UTC


def test_vix_term_inversion():
    inv = c.score_vix_term({"vix": px(26), "vix3m": px(23)})
    calm = c.score_vix_term({"vix": px(14), "vix3m": px(17)})
    assert inv[0] >= 7.5 and "مقلوب" in inv[1] and calm[0] <= 3
    assert c.score_vix_term({"vix": px(20)})[0] is None


def test_rates_score():
    spike = c.score_rates({"y10": px(4.4, diff1=0.13)}, {})[0]
    quiet = c.score_rates({"y10": px(4.4, diff1=0.02)}, {})[0]
    with_move = c.score_rates({"y10": px(4.4, diff1=0.02), "move": px(135)}, {})[0]
    assert spike >= 8.5 and quiet == 2.0 and with_move == 4.0
    two_y = c.score_rates({"y10": px(4.4, diff1=0.02)}, {"dgs2": [("a", 4.0), ("b", 4.10)]})[0]
    assert two_y == 3.0


def test_credit_scores():
    wide = c.score_credit({}, {"hy_oas": [("d%d" % i, 3.5 + i * 0.1) for i in range(8)]})[0]   # 4.2% وارتفاع
    tight = c.score_credit({}, {"hy_oas": [("d%d" % i, 2.8) for i in range(8)]})[0]
    assert wide > tight and tight <= 2.0
    proxy = c.score_credit({"hyg": px(77, chg5=-2.0), "ief": px(95, chg5=0.5)}, {})[0]
    assert proxy == 7.0
    stressed = c.score_credit({"hyg": px(77, chg5=0), "ief": px(95, chg5=0), "kre": px(55, chg5=-6)}, {})[0]
    assert stressed == 4.0
    assert c.score_credit({}, {})[0] is None


def test_breadth_signals():
    p = {"es": px(5900, -0.9), "nq": px(20500, -1.9), "spy": px(590, -0.9, chg5=2.0), "rsp": px(170, -0.5, chg5=0.2)}
    s, note = c.score_breadth(p)
    assert s == 7.0 and "ناسداك" in note and "ضيق" in note
    for t, ch in zip(c.MAG7, (-3, -3, -3, -3, -3, -3, -3)):
        p["m_" + t] = px(100, ch)
    assert c.score_breadth(p)[0] == 9.5
    assert c.score_breadth({})[0] is None


def test_global_and_yen():
    s, note = c.score_global({"jpy": px(146, -1.5), "nikkei": px(38000, -2.0)})
    assert s == 7.5 and "الين" in note
    assert c.score_global({"nikkei": px(38000, 0.3)})[0] == 1.5
    assert c.score_global({})[0] is None


def test_calendar_effects():
    at = lambda y, m, d: datetime(y, m, d, 12, 0, tzinfo=timezone.utc)
    assert c.score_calendar(at(2026, 10, 16))[0] == 5.5       # الجمعة الثالثة: خيارات شهرية
    assert c.score_calendar(at(2026, 9, 18))[0] == 7.0        # خيارات فصلية
    assert c.score_calendar(at(2026, 9, 17))[0] == 6.0        # قبلها بيوم
    assert c.score_calendar(at(2026, 9, 30))[0] == 5.0        # نهاية فصل
    assert c.score_calendar(at(2026, 11, 25))[0] == 4.0       # عشية عيد الشكر
    assert c.score_calendar(at(2026, 10, 7))[0] == 1.5


def test_correlation_break_detected():
    import random
    rnd = random.Random(1)
    dates = [(datetime(2026, 7, 1) + timedelta(days=i)).date().isoformat() for i in range(71)]
    es_r = [rnd.uniform(-0.01, 0.01) for _ in range(70)]
    d_r = [(-r if i < 50 else r) for i, r in enumerate(es_r)]            # ارتباط سلبي ثم ينقلب إيجابياً
    es, dx = [100.0], [100.0]
    for a, b in zip(es_r, d_r):
        es.append(es[-1] * (1 + a))
        dx.append(dx[-1] * (1 + b))
    p = {"es": {"closes": list(zip(dates, es))}, "dxy": {"closes": list(zip(dates, dx))}}
    cr = c.compute_correlations(p)["dxy"]
    assert cr["c20"] > 0.9 and cr["c60"] < 0.3
    s, note = c.score_conflict({"es": px(100, 0.0, 0, 0)}, {"dxy": cr})
    assert s >= 3.5 and "الدولار" in note


def test_pearson_basic():
    assert abs(c.pearson([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) - 1) < 1e-9
    assert abs(c.pearson([1, 2, 3, 4, 5], [10, 8, 6, 4, 2]) + 1) < 1e-9
    assert c.pearson([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]) is None


def test_earnings_raise_event_score():
    p = calm_prices()
    ev = c.parse_events([ev_raw("Core PCE", "High", 120)])
    base = c.build_report(p, ev, NOW)
    with_e = c.build_report(p, ev, NOW, extras={"earnings": [("NVDA", NOW.date().isoformat())]})
    sc = lambda r: next(x["score"] for x in r["risk"]["components"] if x["key"] == "events")
    assert sc(with_e) == sc(base) + 1.5
    assert any("NVDA" in x["note"] for x in with_e["risk"]["components"] if x["key"] == "events")
    assert "أرباح خلال 48 ساعة" in with_e["info"]["earnings"]


def test_info_blocks():
    p = calm_prices()
    p["nq"] = px(20500, 0.4)
    for t, ch in zip(c.MAG7, (1.8, 0.2, 0.5, -0.4, 0.1, 0.0, -1.2)):
        p["m_" + t] = px(100, ch)
    for t in c.BANKS:
        p["b_" + t] = px(50, -0.5)
    p["xlf"], p["kre"] = px(45, -0.4), px(55, -1.1)
    r = c.build_report(p, c.parse_events([ev_raw("CPI m/m", "High", 30)]), NOW,
                       extras={"cot": {"date": "2026-10-06", "net_pct": 5.5, "oi": 2000000},
                               "fred": {"t10y2y": [("a", 0.1), ("b", 0.2)]}})
    i = r["info"]
    assert "الأقوى" in i["mag7"] and "AAPL" in i["mag7"] and "TSLA" in i["mag7"]
    assert "XLF" in i["banks"] and "KRE" in i["banks"]
    assert "+5.5%" in i["cot"] and "منحنى 2-10" in i["rates"] and "NQ" in i["tech"]


def test_premium_component_plugs_in():
    p = calm_prices()
    ev = c.parse_events([ev_raw("Core PCE", "High", 120)])
    base = c.build_report(p, ev, NOW)
    keys = lambda r: [x["key"] for x in r["risk"]["components"]]
    assert "news_ai" not in keys(base) and "تفسير الأخبار بنموذج لغوي" in base["planned_inactive"]
    with_ai = c.build_report(p, ev, NOW, extras={"premium": {"news_ai": (9, "تصعيد حاد في الخليج يهدد الإمدادات")}})
    assert "news_ai" in keys(with_ai) and "تفسير الأخبار بنموذج لغوي" not in with_ai["planned_inactive"]
    comp = next(x for x in with_ai["risk"]["components"] if x["key"] == "news_ai")
    assert comp["name"] == "تفسير الأخبار بنموذج لغوي" and comp["score"] == 9.0 and comp["weight"] > 0.05
    assert abs(sum(x["weight"] for x in with_ai["risk"]["components"]) - 1) < 0.01
    assert with_ai["risk"]["score"] > base["risk"]["score"]            # خطر عالٍ من المزوّد يرفع الدرجة


def test_premium_bad_output_is_ignored():
    p = calm_prices()
    ev = c.parse_events([ev_raw("Core PCE", "High", 120)])
    r = c.build_report(p, ev, NOW, extras={"premium": {"gamma": "نص غير صالح", "unknown_key": (5, "x"),
                                                         "sentiment": (None, "لا بيانات")}})
    ks = [x["key"] for x in r["risk"]["components"]]
    assert "gamma" not in ks and "unknown_key" not in ks and "sentiment" not in ks
    assert any("مزوّد مدفوع غير صالح" in x for x in r["problems"])


def test_twelve_components_weights_sum_to_one():
    assert abs(sum(c.BASE_WEIGHTS.values()) - 1) < 1e-9 and len(c.BASE_WEIGHTS) == 17
    assert set(c.BASE_WEIGHTS) == set(c.NAMES)


def test_level_boundaries():
    assert c.level(3)[0] == "منخفضة" and c.level(4)[0] == "متوسطة"
    assert c.level(6)[0] == "متوسطة" and c.level(7)[0] == "عالية"
    assert c.level(8)[0] == "عالية" and c.level(9)[0] == "قصوى"


def test_geopolitics_signals():
    p = calm_prices()
    p["gold"] = px(2700, 1.4)
    p["oil"] = px(75, 2.6)
    p["vix"] = px(20, 12)
    p["es"] = px(5850, -1.0, -1.0, -1.0, vol_ratio=1.0)
    s, _ = c.score_geopolitics(p)
    assert s == 10.0


def test_dollar_and_front_end():
    p = calm_prices()
    p["dxy"] = {"last": 105.0, "chg1": 0.9, "chg3": 1.0, "chg5": 2.2, "diff1": 0.9, "bar_time": "2026-10-07T00:00:00+00:00", "closes": []}
    s, note = c.score_dollar(p)
    assert s >= 8 and "حاد" in note
    p["dxy"] = dict(p["dxy"], chg1=0.1, chg5=0.2)
    assert c.score_dollar(p)[0] <= 2
    assert c.score_dollar({})[0] is None
    cl = [(f"d{i}", 4.0) for i in range(5)] + [("d5", 4.2)]
    p["y5"] = {"last": 4.2, "diff1": 0.12, "closes": cl, "chg1": 3, "chg3": 3, "chg5": 5, "bar_time": ""}
    s, note = c.score_front_end(p, {"dgs2": [("a", 4.0), ("b", 4.05)]})
    assert s >= 8 and "تشدد" in note and "5Y" in note and "2Y" in note
    calm = c.score_front_end({"y5": dict(p["y5"], diff1=0.01, closes=[(f"d{i}", 4.2) for i in range(6)])}, {})[0]
    assert calm <= 2
    assert c.score_front_end({}, {})[0] is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({len(tests)})")
