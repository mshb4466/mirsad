# -*- coding: utf-8 -*-
import bias


def px(key, a, b, n=25):
    step = (b - a) / (n - 1)
    return {key: {"closes": [(f"2026-09-{i+1:02d}", a + step * i) for i in range(n)]}}


def full(lean=0.0, gap=0.0, y=(4.0, 4.0), dxy=(100, 100), oil=(70, 70), liq=0.0, oas=3.2, rk="mixed"):
    p = {}
    for k, v in (("y10", y), ("dxy", dxy), ("oil", oil)):
        p.update(px(k, *v))
    m = {"lean": lean, "label": "x", "gap": {"value": gap, "size": "صغيرة"}, "net_liquidity": {"chg_pct": liq}}
    f = {"hy_oas": [(f"d{i}", oas) for i in range(8)]}
    return m, p, f, {"key": rk, "text": rk}


def test_signs_support_vs_pressure():
    sup = bias.compute(*full(lean=-0.6, gap=-0.4, y=(4.2, 3.9), dxy=(103, 100), oil=(80, 70), liq=2.5, oas=2.8, rk="goldilocks"))
    pre = bias.compute(*full(lean=0.6, gap=0.5, y=(3.9, 4.3), dxy=(100, 103), oil=(70, 82), liq=-2.5, oas=5.0, rk="stagflation"))
    assert sup["available"] and sup["label"] == "داعم" and sup["score"] > 0.25
    assert pre["available"] and pre["label"] == "ضاغط" and pre["score"] < -0.25


def test_each_component_direction():
    c = {x["key"]: x["signal"] for x in bias.compute(*full(lean=0.6, y=(4.0, 4.3), dxy=(100, 103), oil=(70, 80), liq=-3))["components"]}
    assert c["fed"] < 0 and c["y10"] < 0 and c["dxy"] < 0 and c["oil"] < 0 and c["liq"] < 0


def test_neutral_when_flat():
    b = bias.compute(*full())
    assert b["label"] == "محايد" and abs(b["score"]) < 0.25


def test_unavailable_when_coverage_low():
    b = bias.compute(None, {}, {"hy_oas": [(f"d{i}", 3.0) for i in range(8)]}, None)
    assert not b["available"] and b["label"] == "غير متاح" and "score" not in b


def test_contributions_sum_to_score_and_missing_listed():
    m, p, f, r = full(lean=0.3, y=(4.0, 4.2))
    p.pop("oil")
    b = bias.compute(m, p, f, r)
    assert abs(sum(c["contribution"] for c in b["components"]) - b["score"]) < 0.02
    assert any("النفط" in x for x in b["missing"])


def test_short_history_not_used():
    assert bias._chg({"dxy": {"closes": [("a", 1), ("b", 2)]}}, "dxy") is None


def test_confirm_yes_no_and_na():
    d_bull = [{"tone": "bull", "strength": 3}, {"tone": "bull", "strength": 2}]
    d_bear = [{"tone": "bear", "strength": 3}]
    sup = bias.compute(*full(lean=-0.6, gap=-0.4, y=(4.2, 3.9), dxy=(103, 100), liq=2.5, oas=2.8, rk="goldilocks"), drivers=d_bull)
    assert sup["confirm"]["key"] == "yes"
    assert bias.compute(*full(lean=-0.6, gap=-0.4, y=(4.2, 3.9), dxy=(103, 100), liq=2.5, oas=2.8, rk="goldilocks"), drivers=d_bear)["confirm"]["key"] == "no"
    assert bias.compute(*full(lean=-0.6, y=(4.2, 3.9)), drivers=[])["confirm"]["key"] == "na"
    assert bias.compute(None, {}, {}, None)["confirm"]["key"] == "na"


if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1
    print(f"{n} اختبارات نجحت")
