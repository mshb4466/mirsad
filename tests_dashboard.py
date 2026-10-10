# -*- coding: utf-8 -*-
import json
import os
import tempfile

import dashboard
import runner as r
import tests_auction as ta
import tests_macro as tm
from tests_runner import Box, calm_intraday, deps, ev_raw


def run_with_docs():
    d = deps([ev_raw("Federal Funds Rate", "High", 3, forecast="4.50%", previous="4.75%")], calm_intraday())
    d["es5m"] = lambda now: ta.synthetic(ta.PRIOR, ta.TODAY, on_drift=+30.0)
    d["macro"] = lambda now: (tm.base_series(m3=4.1, m6=3.8, y1=3.6), [])
    r.run_preopen(ta.NOW, {"seen_events": [], "last_shock": None}, Box(), d)
    return json.load(open(os.path.join(d["docs_dir"], "data.json"), encoding="utf-8")), d


def test_view_has_all_sections_and_rounded_prices():
    v, _ = run_with_docs()
    assert v["live"] and v["risk"]["real"] and 0 <= v["risk"]["score"] <= 10
    assert abs(sum(c["weight"] for c in v["risk"]["components"]) - 1) < 0.02
    assert v["macro"]["label"] == "متشدد" and v["macro"]["pillars"] and v["macro"]["meet"]
    a = v["auction"]
    assert a["prior"]["vah"] == round(a["prior"]["vah"], 2) and a["chips"] and a["tilt"]["word"]
    assert v["events"] and v["events"][0]["high"]


def test_view_without_optional_parts():
    d = deps([], calm_intraday())
    r.run_preopen(ta.NOW, {"seen_events": [], "last_shock": None}, Box(), d)
    v = json.load(open(os.path.join(d["docs_dir"], "data.json"), encoding="utf-8"))
    assert v["auction"] is None and v["macro"] is None and v["risk"]["components"]


def test_publish_failure_is_soft():
    box = Box()
    d = deps([], calm_intraday())
    d["docs_dir"] = "/proc/forbidden/docs"
    r.run_preopen(ta.NOW, {"seen_events": [], "last_shock": None}, box, d)
    assert "المخاطرة:" in box.msgs[0] and "تعذّر تحديث صفحة الواجهة" in box.msgs[0]


def test_reason_label_matches_level():
    v, _ = run_with_docs()
    r = v["risk"]
    assert r["reason_label"] == "السبب" or r["score"] <= 3
    if r["score"] <= 3 and r["main_reason"] != "ظروف هادئة نسبياً":
        assert "الخطر العام منخفض" in r["reason_label"]


def test_page_url(monkeypatch=None):
    old = os.environ.get("GITHUB_REPOSITORY")
    os.environ["GITHUB_REPOSITORY"] = "MSHB4466/mirsad"
    try:
        assert dashboard.page_url() == "https://mshb4466.github.io/mirsad/"
    finally:
        if old is None:
            os.environ.pop("GITHUB_REPOSITORY")
        else:
            os.environ["GITHUB_REPOSITORY"] = old


def test_week_groups_by_baghdad_day_and_marks_released():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)
    mk = lambda title, h, **k: dict({"title": title, "impact": "High", "time": now + timedelta(hours=h), "forecast": "", "previous": "", "actual": ""}, **k)
    evs = [mk("Unemployment Claims", -1.5, forecast="230K", previous="225K", actual="219K"), mk("CPI m/m", 24, forecast="0.3%"),
           mk("Building Permits", 2, impact="Low"), mk("Non-Farm Employment Change", -30, actual="")]
    wk = dashboard._week(evs, now, {"risk": {}})
    assert [d["rel"] for d in wk] == ["أمس", "اليوم", "غداً"], wk
    today = next(d for d in wk if d["today"])
    assert today["items"][0]["released"] and today["items"][0]["actual"] == "219K"
    assert all("Permits" not in i["title"] for d in wk for i in d["items"])


def test_week_news_dedupe_cache_and_view():
    from datetime import datetime, timedelta, timezone
    import runner
    now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    rows = [(now - timedelta(hours=2), "Fed holds rates steady", "Reuters"), (now - timedelta(hours=3), "FED HOLDS RATES STEADY!", "AP"),
            (now - timedelta(days=2), "Powell signals patience", "CNBC")]
    calls = []
    def fake(n, q):
        calls.append(q)
        if "Apple" in q:
            raise OSError("down")
        return rows
    data, failed = runner.fetch_week_news(now, "es", fake)
    assert [i["title"] for i in data["fed"]["items"]] == ["Fed holds rates steady", "Powell signals patience"]   # التكرار حُذف والأحدث أولاً
    assert failed == ["الشركات الكبرى والأرباح"] and "companies" not in data
    st = {}
    deps = {"week_news": lambda n, a: (data, failed)}
    r1 = runner.get_week_news(now, deps, st)
    r2 = runner.get_week_news(now + timedelta(minutes=30), {"week_news": lambda n, a: (_ for _ in ()).throw(AssertionError("لا طلب جديد"))}, st)
    assert r2["at"] == r1["at"]
    assert runner.get_week_news(now, {}, {}) is None
    v = dashboard._week_news(r1, now)
    assert v["topics"][0]["items"][0]["when"].startswith("اليوم") and v["failed"] == failed


def test_week_earnings_marks_mag7():
    w = dashboard._week_earnings({"earnings_week": [["2026-10-14", ["NVDA", "JPM"]]]})
    assert w[0]["label"].startswith("الأربعاء") and w[0]["items"][0] == {"t": "NVDA", "name": "إنفيديا", "mag7": True} and w[0]["items"][1]["mag7"] is False
    assert dashboard._week_earnings({}) == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({len(tests)})")
