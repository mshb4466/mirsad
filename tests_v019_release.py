# -*- coding: utf-8 -*-
"""اختبارات v0.19 — ربط الإصدارات الموثّقة بالتقييم الرئيسي (بند 2). بيانات اصطناعية: تثبت المنطق لا صحة الأرقام الحقيقية."""
from datetime import datetime, timedelta, timezone

import bias
import release_impact
import verdict
from tests_bias import full

NOW = datetime(2026, 10, 14, 13, 50, tzinfo=timezone.utc)


def cpi(actual, fc="0.3%", prev="0.3%", title="CPI m/m", trust="official", status="verified_official", minutes=20, **kw):
    e = {"title": title, "time": NOW - timedelta(minutes=minutes), "impact": "High", "forecast": fc, "previous": prev, "actual": actual,
         "actual_src": trust, "status": status, "actual_source": "BLS", "country": "USD"}
    e.update(kw)
    return e


def series(es=0.0, y10=0.0, dxy=0.0, age=5):
    t0 = NOW - timedelta(minutes=20)
    mk = lambda p0, p1: [(t0 - timedelta(minutes=5), p0), (t0 + timedelta(minutes=5), p0 + (p1 - p0) / 2), (NOW - timedelta(minutes=age), p1)]
    return {"es": mk(6000.0, 6000.0 * (1 + es / 100)), "y10": mk(4.20, 4.20 + y10 / 100), "dxy": mk(100.0, 100.0 * (1 + dxy / 100))}


def bias_with(events, ser=None, lean=0.0):
    m, p, f, rg = full(lean=lean)
    m["label"] = "متشدد" if lean > 0.15 else "محايد"
    rel = release_impact.build(events, NOW, m, ser)
    return bias.compute(m, p, f, rg, None, rel), rel


def test_two_opposite_cpi_surprises_change_contribution_and_explanation():
    hot, rh = bias_with([cpi("0.5%")])
    cold, rc = bias_with([cpi("0.1%")])
    ch = next(x for x in hot["components"] if x["key"] == "events")
    cc = next(x for x in cold["components"] if x["key"] == "events")
    assert ch["contribution"] < 0 < cc["contribution"]
    assert ch["note"] != cc["note"] and "ضاغط" in rh["items"][0]["initial"] and "داعم" in rc["items"][0]["initial"]
    assert hot["score"] < cold["score"]


def test_in_line_cpi_is_not_an_automatic_bearish_bias():
    b, rel = bias_with([cpi("0.3%")])
    assert rel["items"][0]["effect"] == "neu" and rel["items"][0]["signal"] == 0
    assert b["label"] != "ضاغط"


def test_high_cpi_alone_does_not_flip_a_supportive_background():
    m, p, f, rg = full(lean=-0.6, gap=-0.4, y=(4.2, 3.9), dxy=(103, 100), liq=2.5, oas=2.8, rk="goldilocks")
    m["label"] = "تيسيري"
    base = bias.compute(m, p, f, rg)
    rel = release_impact.build([cpi("0.4%")], NOW, m, None)
    b = bias.compute(m, p, f, rg, None, rel)
    assert base["label"] == "داعم" and b["label"] == "داعم" and b["score"] < base["score"]


def test_no_documented_release_means_not_integrated_yet():
    e = cpi("", status="awaiting", trust="")
    b, rel = bias_with([e])
    assert rel["pending"] and not rel["items"] and "events" not in {x["key"] for x in b["components"]}
    assert b["pending_release"][0]["name"]
    nr = verdict.build({"bias": b, "releases": rel, "risk": {}}, NOW)
    assert "لم يُدمج الإصدار بعد" in nr["news"]["text"]


def test_headline_number_never_enters():
    e = cpi("0.6%", trust="news", status="needs_check")
    b, rel = bias_with([e])
    assert not rel["items"] and rel["signal"] is None


def test_market_confirmation_is_separate_and_reevaluates():
    ev = [cpi("0.5%")]
    _, r0 = bias_with(ev, None)
    assert r0["market"]["key"] == "na" and "تأكيد السوق غير متاح بعد" in r0["market"]["label"]
    _, rc = bias_with(ev, series(es=-0.4, y10=+6, dxy=+0.3))
    _, rr = bias_with(ev, series(es=+0.4, y10=-6, dxy=-0.3))
    assert rc["market"]["key"] == "confirm" and rr["market"]["key"] == "reject"
    assert abs(rc["items"][0]["final"]) > abs(r0["items"][0]["final"]) > abs(rr["items"][0]["final"])


def test_stale_market_data_is_not_confirmation():
    _, rel = bias_with([cpi("0.5%")], series(es=-0.4, y10=6, dxy=0.3, age=120))
    assert rel["market"]["key"] == "na"


def test_same_day_cpi_family_counts_once():
    evs = [cpi("0.5%"), cpi("0.5%", title="Core CPI m/m"), cpi("3.4%", fc="3.1%", prev="3.1%", title="CPI y/y")]
    _, rel = bias_with(evs)
    assert len(rel["items"]) == 3 and len(rel["groups"]) == 1
    one = release_impact.build([cpi("0.5%")], NOW, {}, None)
    assert abs(rel["signal"]) <= abs(one["signal"]) + 0.2          # لا تتضاعف بتعدد صيغ الإصدار نفسه


def test_fed_weight_is_discounted_when_events_enter():
    m, p, f, rg = full(lean=0.6)
    base = bias.compute(m, p, f, rg)
    rel = release_impact.build([cpi("0.5%")], NOW, m, None)
    b = bias.compute(m, p, f, rg, None, rel)
    w0 = next(x["weight"] for x in base["components"] if x["key"] == "fed")
    w1 = next(x["weight"] for x in b["components"] if x["key"] == "fed")
    assert w1 < w0


def test_old_release_fades_out():
    rel = release_impact.build([cpi("0.5%", minutes=60 * 50)], NOW, {}, None)
    assert not rel["items"]


def test_verdict_explains_news_vs_overall_relation():
    m, p, f, rg = full(lean=-0.6, gap=-0.4, y=(4.2, 3.9), dxy=(103, 100), liq=2.5, oas=2.8, rk="goldilocks")
    m["label"] = "تيسيري"
    rel = release_impact.build([cpi("0.5%")], NOW, m, None)
    b = bias.compute(m, p, f, rg, None, rel)
    v = verdict.build({"bias": b, "releases": rel, "risk": {}, "intensity": 5.0}, NOW)
    assert v["advice"].startswith("النصيحة الآن:") and "الخبر" in v["news_relation"]


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("✔", k)
    print(f"نجحت كل الاختبارات ({n})")
