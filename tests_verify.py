# -*- coding: utf-8 -*-
"""اختبارات وحدة الفحص الحقيقي والجودة والنشر. الاستجابات هنا اصطناعية: تثبت المنطق (المطابقة، الحالات، كشف النسخة القديمة)،
أما صحة الأرقام الحقيقية فلا يثبتها إلا تشغيل `actuals-check` على GitHub Actions."""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import actuals
import collector as c
import dashboard
import events_ctx
import quality
import runner as r
import verify
from tests_actuals import NOW, raw, mk_deps, bls_rows, fred_rows, events_all, run, ALL


def _alfred_fake(values):
    """يبني استجابة ALFRED اصطناعية: values = {sid: [(تاريخ، قيمة)]}، ويُحاكي fetch(url)."""
    def fetch(url):
        sid = url.split("series_id=")[1].split("&")[0]
        return json.dumps({"observations": [{"date": d, "value": str(v)} for d, v in values.get(sid, [])]}).encode()
    return fetch


def test_judge_never_calls_a_difference_a_match():
    assert verify.judge("3.4%", "3.4%") == "مطابق"
    assert verify.judge("3.3%", "3.4%") == "فرق تقريب"
    assert verify.judge("3.0%", "3.4%") == "غير مطابق"
    assert verify.judge("354K", "353K") == "فرق تقريب" and verify.judge("360K", "353K") == "غير مطابق"
    assert verify.judge("", "3.4%") == "لا رقم"


def test_historical_check_uses_production_resolver_and_reports_each_field():
    # CPI NSA: كانون الأول 2023 / كانون الأول 2022 = 3.4% بالضبط
    base = 296.797
    rows = [(f"{y}-{m:02d}-01", base) for y in (2021, 2022) for m in range(1, 13)]
    rows = [(d, 290.0 + i * 0.1) for i, (d, _) in enumerate(rows)]
    dec22 = 296.797
    rows = [r_ for r_ in rows if r_[0] < "2022-12-01"] + [("2022-12-01", dec22)] + [(f"2023-{m:02d}-01", dec22 + m * 0.1) for m in range(1, 12)] + [("2023-12-01", round(dec22 * 1.034, 3))]
    fake = _alfred_fake({"CPIAUCNS": rows})
    recs = [x for x in verify.check_historical("KEY", NOW, fetch=fake) if x["title"] == "CPI y/y" and x["release_time"].startswith("2024-01-11")]
    assert len(recs) == 1
    x = recs[0]
    assert x["value"] == "3.4%" and x["match"] == "مطابق" and x["period"] == "2023-12-01"
    for k in ("source", "release_time", "fetched_at", "official", "official_url", "match"):
        assert x[k]


def test_historical_without_key_or_source_is_reported_not_guessed():
    recs = verify.check_historical("", NOW)
    assert recs and all(x["match"] == "تعذّر الجلب" and x["value"] == "" for x in recs)
    def boom(url):
        raise OSError("down")
    recs = verify.check_historical("KEY", NOW, fetch=boom)
    assert all(x["match"] == "تعذّر الجلب" for x in recs)


def test_historical_wrong_period_is_not_matched():
    # ALFRED لا يحوي فترة كانون الأول 2023 بعد: لا نعرض آخر قراءة على أنها الجديدة
    rows = [(f"2023-{m:02d}-01", 300.0 + m) for m in range(1, 12)] + [(f"2022-{m:02d}-01", 290.0 + m) for m in range(1, 13)]
    rows.sort()
    recs = verify.check_historical("KEY", NOW, fetch=_alfred_fake({"CPIAUCNS": rows}))
    x = next(x for x in recs if x["title"] == "CPI y/y" and x["release_time"].startswith("2024-01-11"))
    assert x["value"] == "" and x["match"] == "لا رقم"


def test_sources_check_detects_fred_lag_and_bls_failure():
    now = NOW
    br = bls_rows()
    post = lambda url, payload: {"status": "REQUEST_SUCCEEDED", "Results": {"series": [
        {"seriesID": sid, "data": [{"year": d[:4], "period": "M" + d[5:7], "value": str(v)} for d, v in br[k]]}
        for k, sid in __import__("indicators").BLS_IDS.items() if k in br]}}
    lagged = lambda need: {k: v[:-1] for k, v in br.items() if k in need}
    recs, st = verify.check_sources(now, None, None, bls_post=post, fred_fetch=lagged)
    assert st["bls"]["ok"] and st["fred"]["ok"]
    assert any("BLS أحدث" in x["match"] for x in recs)           # FRED متأخر شهراً: يُكشف ولا يُسمّى مطابقاً
    def dead(url, payload):
        raise OSError("x")
    recs, st = verify.check_sources(now, None, None, bls_post=dead, fred_fetch=lambda need: {})
    assert not st["bls"]["ok"] and not st["fred"]["ok"] and all(x["match"] == "تعذّر الجلب" for x in recs)


def test_published_page_stale_vs_fresh_detection():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "data.json")
    json.dump({"published_at": "2026-10-14T16:00:00+00:00"}, open(p, "w"))
    slept = []
    stale = lambda url: json.dumps({"published_at": "2026-10-14T15:45:00+00:00"}).encode()
    rec = verify.check_published(p, "https://x.github.io/m/", wait=(0, 1, 1), fetch=stale, sleep=slept.append)
    assert rec["match"] == "نسخة قديمة" and "15:45" in rec["note"] and len(slept) == 3
    calls = {"n": 0}
    def becomes_fresh(url):
        calls["n"] += 1
        assert "?t=" in url                                   # لا يعتمد على كاش المتصفح/CDN
        return json.dumps({"published_at": "2026-10-14T16:00:00+00:00" if calls["n"] >= 2 else "old"}).encode()
    rec = verify.check_published(p, "https://x.github.io/m/", wait=(0, 1, 1), fetch=becomes_fresh, sleep=lambda s: None)
    assert rec["match"] == "مطابق" and calls["n"] == 2
    def down(url):
        raise OSError("x")
    assert verify.check_published(p, "https://x/", wait=(0,), fetch=down, sleep=lambda s: None)["match"] == "تعذّر الجلب"


def _pub(evs, state, now=NOW, docs=None):
    docs = docs or tempfile.mkdtemp()
    rep = {"risk": {"score": 3, "level": "منخفضة", "main_reason": "", "advice": "", "components": []}, "drivers": [], "info": {}, "macro": None}
    q = quality.build(evs, state, now)
    dashboard.publish(rep, evs, now, {}, docs_dir=docs, quality=q)
    return docs, json.load(open(os.path.join(docs, "data.json"), encoding="utf-8"))


def test_publish_writes_fresh_stamp_and_quality_and_replaces_previous_file_atomically():
    state, evs = {}, events_all()
    run(evs, state, mk_deps(bls_rows, fred_rows))
    docs, v1 = _pub(evs, state)
    assert v1["published_at"] == NOW.isoformat() and v1["quality"]["total"] == len(ALL)
    later = NOW + timedelta(minutes=15)
    _, v2 = _pub(evs, state, later, docs)
    assert v2["published_at"] == later.isoformat() != v1["published_at"]          # لا يبقى ختم النسخة القديمة
    assert not [f for f in os.listdir(docs) if f.endswith(".tmp")]


def test_value_reaches_state_then_data_json_and_cross_check_passes():
    state, evs = {}, c.parse_events([raw("Unemployment Rate", 2, forecast="4.2%")])
    run(evs, state, mk_deps(bls_rows))
    rep = {"risk": {"score": 3, "level": "x", "main_reason": "", "advice": "", "components": []}, "drivers": [], "info": {}, "macro": None}
    docs = tempfile.mkdtemp()
    dashboard.publish(rep, evs, NOW, {}, docs_dir=docs, quality=quality.build(evs, state, NOW))
    page = json.load(open(os.path.join(docs, "data.json"), encoding="utf-8"))
    flat = json.dumps(page.get("events_past"), ensure_ascii=False)
    assert "4.3%" in flat
    recs = verify.check_state_vs_page(state, os.path.join(docs, "data.json"), NOW)
    assert recs and recs[0]["match"] == "مطابق" and recs[0]["value"] == "4.3%"
    # القيمة غائبة عن الصفحة → يُكشف
    page["events_past"] = []
    json.dump(page, open(os.path.join(docs, "data.json"), "w", encoding="utf-8"), ensure_ascii=False)
    assert verify.check_state_vs_page(state, os.path.join(docs, "data.json"), NOW)[0]["match"] == "غائب عن الصفحة"


def test_state_survives_restart_through_real_save_and_load():
    state, evs = r.load_state(os.devnull), c.parse_events([raw("Unemployment Rate", 2)])
    run(evs, state, mk_deps(bls_rows))
    p = os.path.join(tempfile.mkdtemp(), "state.json")
    r.save_state(state, p)
    again = r.load_state(p)
    evs2 = c.parse_events([raw("Unemployment Rate", 2)])
    actuals.restore(evs2, again)
    assert evs2[0]["actual"] == "4.3%" and evs2[0]["status"] == "verified_official" and evs2[0]["actual_period"] == "2026-09-01"


def test_quality_counts_reasons_coverage_latency_and_never_counts_news_as_arrived():
    state, evs = {}, events_all(3.5)
    run(evs, state, mk_deps(bls_rows, fred_rows))
    q = quality.build(evs, state, NOW)
    assert q["total"] == len(ALL) and q["arrived"] == q["official"] + q["secondary"] and q["arrived"] >= 10
    assert q["missing"] == q["total"] - q["arrived"] and q["missing"] >= 2
    ism = next(x for x in q["events"] if "Manufacturing" in x["title"])
    assert not ism["verified"] and ism["bucket"] == "unsupported" and "لا مصدر مرخّص" in ism["reason"]
    assert q["coverage_pct"] == round(100 * q["arrived"] / q["total"]) and q["unsupported"] >= 2
    arrived = [x for x in q["events"] if x["verified"]]
    assert all(x["latency_min"] is not None and x["latency_min"] >= 0 for x in arrived)
    assert q["sources"]["bls"]["ok"] is True and q["sources"]["fred"]["ok"] is True
    assert "ISM Manufacturing PMI" in q["unsupported_list"]


def test_quality_headline_only_is_needs_check_and_source_failure_recorded():
    from tests_actuals import claims_ev, deps_news, STALE_FRED
    state, evs = {}, claims_ev()
    run(evs, state, deps_news(STALE_FRED))
    q = quality.build(evs, state, NOW)
    assert q["arrived"] == 0 and q["needs_check"] == 1 and q["coverage_pct"] == 0
    x = q["events"][0]
    assert x["status"] == "needs_check" and x["value"] == "" and x["unverified_value"] == "231K" and "لم يُتحقق" in x["reason"]


def test_source_status_failure_has_reason_and_time():
    state, evs = {}, c.parse_events([raw("Unemployment Rate", 2)])
    def dead(_):
        raise RuntimeError("down")
    run(evs, state, {"fetch_oil": lambda: None, "fetch_auctions": lambda: [], "fetch_bls": dead, "fetch_series": dead})
    ss = state["source_status"]
    assert ss["bls"]["ok"] is False and "خطأ" in ss["bls"]["detail"] and ss["bls"]["at"]
    assert ss["fred"]["ok"] is False


def test_run_check_writes_json_and_markdown_without_network():
    d = tempfile.mkdtemp()
    os.environ.pop("FRED_API_KEY", None)
    os.environ.pop("BLS_API_KEY", None)
    orig = verify.bls.fetch
    verify.bls.fetch = lambda ids, now, key=None, post_fn=None, state=None: ({}, ["BLS: تعذّر الاتصال (OSError)"])
    orig_c = c.fetch_fred
    c.fetch_fred = lambda now, days=45, series=None: ({}, ["لا شبكة"])
    try:
        sm = os.path.join(d, "summary.md")
        recs, st = verify.run_check(NOW, {}, docs_json_path=os.path.join(d, "none.json"), summary_path=sm, out_json=os.path.join(d, "check.json"))
    finally:
        verify.bls.fetch, c.fetch_fred = orig, orig_c
    assert not st["bls"]["ok"] and all(x["match"] in ("تعذّر الجلب",) for x in recs if x["check"] in ("historical", "sources"))
    out = json.load(open(os.path.join(d, "check.json"), encoding="utf-8"))
    assert out["summary"]["تعذّر الجلب"] > 5 and "فحص الأرقام الفعلية" in open(sm, encoding="utf-8").read()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({len(tests)})")
