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


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({len(tests)})")
