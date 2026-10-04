#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات تصنيف الأخبار الجيوسياسية (دون إنترنت): python tests_geo.py"""
from datetime import datetime, timedelta, timezone

import collector as c
import geo
import runner as r
from tests import calm_prices
from tests_runner import NOW, Box, calm_intraday, deps

H = lambda h, t: (NOW - timedelta(hours=h), t)


def test_classify():
    a = geo.classify("Iran fires missile at tanker near Strait of Hormuz, two killed")
    assert a and {"military", "energy"} <= set(a["cats"]) and "الشرق الأوسط" in a["regions"] and a["severity"] >= 3
    b = geo.classify("Ceasefire talks resume as Israel and Hamas agree to truce")
    assert b is None or b["deesc"]
    assert geo.classify("Apple unveils new iPhone at September event") is None
    t = geo.classify("US announces new tariffs on Chinese goods")
    assert t and t["cats"] == ["trade"] and "الصين/تايوان" in t["regions"]
    assert geo.classify("هجوم صاروخي على ناقلة في الخليج")["severity"] >= 2


def test_deescalation_lowers_severity():
    hot = geo.classify("Missile attack on Gulf oil facility")
    cool = geo.classify("Missile attack on Gulf oil facility prompts ceasefire talks")
    assert cool["severity"] < hot["severity"] and cool["deesc"]


def test_cluster_merges_same_story_and_counts_sources():
    items = [H(1, "Iran launches missile strike on Israel - Reuters"),
             H(1.2, "Iran missile strike on Israel raises alarm - Bloomberg"),
             H(2, "Iran launches missile strike on Israel, officials say - AP"),
             H(3, "US announces new tariffs on Chinese goods - CNBC")]
    st = geo.cluster(items, NOW)
    assert len(st) == 2 and len(st[0]["sources"]) == 3 and st[0]["value"] > st[1]["value"]


def test_old_news_decays():
    fresh = geo.score_geo_news([H(0.5, "Iran missile strike hits Israel - Reuters")], 6.0, NOW)[0]
    old = geo.score_geo_news([H(23, "Iran missile strike hits Israel - Reuters")], 6.0, NOW)[0]
    assert fresh > old


def test_market_confirmation_changes_score():
    items = [H(0.5, "Iran missile strike hits Israel, dozens killed - Reuters"),
             H(0.6, "Iran missile strike on Israel escalates conflict - AP")]
    confirmed, note1, d1 = geo.score_geo_news(items, 7.75, NOW)
    unconfirmed, note2, d2 = geo.score_geo_news(items, 1.0, NOW)
    assert confirmed > unconfirmed and d1["confirmed"] and not d2["confirmed"]
    assert "يؤكد" in note1 and "لم يؤكد" in note2


def test_unexplained_market_move_flagged():
    s, note, d = geo.score_geo_news([H(2, "Apple unveils new iPhone")], 7.75, NOW)
    assert d["unexplained_market_move"] and "بلا عناوين" in note


def test_no_items_vs_failed_fetch():
    assert geo.score_geo_news([], 1.0, NOW)[0] == 1.0          # جلب ناجح بلا قصص: هادئ
    assert geo.score_geo_news(None, 1.0, NOW)[0] is None       # فشل الجلب: يُستبعد


def test_geo_feeds_risk_report():
    items = [H(0.5, "Iran missile strike hits Israel, dozens killed - Reuters"),
             H(0.6, "Iran missile strike on Israel escalates conflict - AP"),
             H(0.7, "Iran missile strike on Israel: oil jumps - Bloomberg")]
    rep = c.build_report(calm_prices(), [], NOW, [], {"geo": items})
    keys = {x["key"]: x for x in rep["risk"]["components"]}
    assert "geo_news" in keys and keys["geo_news"]["score"] >= 4
    assert rep["geo"]["top"] and abs(sum(x["weight"] for x in rep["risk"]["components"]) - 1) < 0.01
    calm = c.build_report(calm_prices(), [], NOW, [], {"geo": []})
    assert rep["risk"]["score"] >= calm["risk"]["score"]
    nogeo = c.build_report(calm_prices(), [], NOW, [], {})
    assert "geo_news" not in [x["key"] for x in nogeo["risk"]["components"]]


def test_preopen_message_has_geo_block_and_failure_is_soft():
    box = Box()
    d = deps([], calm_intraday())
    d["geo"] = lambda now: [H(0.5, "Iran missile strike hits Israel, dozens killed - Reuters")]
    r.run_preopen(NOW, {"seen_events": [], "last_shock": None}, box, d)
    m = box.msgs[0]
    assert "الجيوسياسة (تصنيف بالقواعد)" in m and "الشرق الأوسط" in m and "تصعيد" in m
    box2 = Box()
    d["geo"] = lambda now: (_ for _ in ()).throw(RuntimeError("حجب"))
    r.run_preopen(NOW, {"seen_events": [], "last_shock": None}, box2, d)
    assert "تعذّر جلب geo" in box2.msgs[0] and "المخاطرة:" in box2.msgs[0]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({len(tests)})")
