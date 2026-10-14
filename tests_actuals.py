# -*- coding: utf-8 -*-
"""اختبارات خط الأرقام الفعلية (Actual). بيانات المصدر هنا **اصطناعية** بشكل استجابات BLS/FRED: تثبت المنطق (المطابقة، الفترات،
الحالات، التخزين، المراجعة، الفشل) لا أنها جلب حقيقي. الجلب الحقيقي لا يُختبر إلا من تشغيل GitHub."""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import actuals
import bls
import collector as c
import dashboard
import events_ctx
import indicators
import runner as r
from extras import ET
from tests_runner import Box, calm_intraday

NOW = datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc)      # الأربعاء؛ توقيت نيويورك EDT (UTC-4)


def raw(title, hours_ago, impact="High", forecast="0.3%", previous="0.2%", hour_utc=None):
    t = (NOW - timedelta(hours=hours_ago)).isoformat() if hour_utc is None else NOW.replace(hour=hour_utc, minute=30).isoformat()
    return {"title": title, "country": "USD", "impact": impact, "date": t, "forecast": forecast, "previous": previous}


def months(start=(2025, 6), n=16):
    y, m = start
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}-01")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def growth(base, g, n=16):
    return [(d, base * (1 + g) ** i) for i, d in enumerate(months(n=n))]


def bls_rows():
    """صفوف اصطناعية لسلاسل BLS بمفاتيح indicators. آخر شهر = سبتمبر 2026 (يتوافق مع إصدار أكتوبر)."""
    return {"cpi": growth(300, 0.002), "cpi_ny": growth(300, 0.002), "cpilfe": growth(310, 0.003), "cpilfe_ny": growth(310, 0.003),
            "unrate": [(d, 4.3) for d in months()], "payems": [(d, 159000 + 150 * i) for i, d in enumerate(months())],
            "ahe": growth(36, 0.003), "jolts": [(d, 7400) for d in months()]}


def fred_rows():
    return {"claims": [("2026-10-03", 228000.0), ("2026-10-10", 231000.0)], "ppi": growth(140, 0.001), "ppife": growth(141, 0.002),
            "retail": growth(700000, 0.004), "pcelfe": growth(128, 0.002), "gdp": [("2026-04-01", 3.0), ("2026-07-01", 2.1)],
            "indpro": growth(103, 0.001), "umcsent": [("2026-09-01", 55.0)]}


def mk_deps(bls_fn=None, fred_fn=None):
    sid_of = {v: k for k, v in indicators.BLS_IDS.items()}

    def fb(ids):
        rows = bls_fn() if bls_fn else {}
        return {indicators.BLS_IDS[k]: v for k, v in rows.items() if indicators.BLS_IDS.get(k) in ids}, []
    return {"fetch_oil": lambda: None, "fetch_auctions": lambda: [], "fetch_bls": fb,
            "fetch_series": (lambda need: (fred_fn() if fred_fn else {}))}


ALL = [
    ("CPI m/m", "0.2%"), ("Core CPI m/m", "0.3%"), ("CPI y/y", "2.4%"), ("Core CPI y/y", "3.8%"), ("Non-Farm Employment Change", "150K"),
    ("Unemployment Rate", "4.3%"), ("PPI m/m", "0.1%"), ("Core PCE Price Index m/m", "0.2%"), ("ISM Manufacturing PMI", "49.0"),
    ("ISM Services PMI", "52.0"), ("Unemployment Claims", "230K"), ("Advance GDP q/q", "2.0%"), ("Retail Sales m/m", "0.4%"),
]


def events_all(hours_ago=3.5):
    return c.parse_events([raw(t, hours_ago, forecast=f) for t, f in ALL])


def run(events, state, deps, now=NOW):
    r.resolve_actuals(events, now, state, deps)
    return {e["title"]: e for e in events}


def test_actual_appears_for_required_indicators_from_official_then_fred():
    ev = run(events_all(), {}, mk_deps(bls_rows, fred_rows))
    exp_cpi = f"{(bls_rows()['cpi'][-1][1] / bls_rows()['cpi'][-2][1] - 1) * 100:.1f}%"
    assert ev["CPI m/m"]["actual"] == exp_cpi == "0.2%" and "BLS" in ev["CPI m/m"]["actual_note"]
    assert ev["Core CPI m/m"]["actual"] == "0.3%"
    assert ev["CPI y/y"]["actual"] == "2.4%" and ev["Core CPI y/y"]["actual"] == "3.7%"      # سنوي منفصل عن الشهري
    assert ev["Non-Farm Employment Change"]["actual"] == "150K" and "BLS" in ev["Non-Farm Employment Change"]["actual_note"]
    assert ev["Unemployment Rate"]["actual"] == "4.3%"
    assert ev["Unemployment Claims"]["actual"] == "231K" and "FRED" in ev["Unemployment Claims"]["actual_note"]
    assert ev["Advance GDP q/q"]["actual"] == "2.1%"
    assert ev["PPI m/m"]["actual"] == "0.1%" and ev["Retail Sales m/m"]["actual"] == "0.4%" and ev["Core PCE Price Index m/m"]["actual"] == "0.2%"
    for t in ("CPI m/m", "Core CPI m/m", "Non-Farm Employment Change", "Unemployment Claims", "Advance GDP q/q"):
        assert ev[t]["status"] in ("verified_official", "verified_secondary")


def test_ism_has_no_free_source_and_is_never_guessed():
    ev = run(events_all(), {}, mk_deps(bls_rows, fred_rows))
    for t in ("ISM Manufacturing PMI", "ISM Services PMI"):
        assert not ev[t]["actual"] and "ملكية خاصة" in ev[t]["actual_note"] and ev[t]["status"] in ("awaiting", "failed")


def test_upcoming_event_has_no_actual_and_status_upcoming():
    evs = c.parse_events([raw("CPI m/m", -2)])
    ev = run(evs, {}, mk_deps(bls_rows, fred_rows))
    assert ev["CPI m/m"]["actual"] == "" and ev["CPI m/m"]["status"] == "upcoming"


def test_late_release_then_arrives_and_survives_restart():
    state = {}
    stale = lambda: {k: v[:-1] for k, v in bls_rows().items()}          # BLS لم يُحدَّث: ينتهي في أغسطس
    evs = c.parse_events([raw("Unemployment Rate", 0.3)])
    ev = run(evs, state, mk_deps(stale, lambda: {}))
    e = ev["Unemployment Rate"]
    assert e["actual"] == "" and e["status"] == "awaiting" and "لم يُحدَّث" in e["actual_note"]
    later = NOW + timedelta(minutes=20)
    evs2 = c.parse_events([raw("Unemployment Rate", 0.3)])
    ev2 = run(evs2, state, mk_deps(bls_rows, lambda: {}), later)
    assert ev2["Unemployment Rate"]["actual"] == "4.3%" and ev2["Unemployment Rate"]["status"] == "verified_official"
    # إعادة تشغيل: الحالة تُحفظ في JSON، والتقويم الجديد بلا رقم، والمصادر كلها معطّلة: الرقم المحفوظ يبقى
    state2 = json.loads(json.dumps(state))
    def dead(_):
        raise RuntimeError("down")
    evs3 = c.parse_events([raw("Unemployment Rate", 0.3)])
    ev3 = run(evs3, state2, {"fetch_oil": lambda: None, "fetch_auctions": lambda: [], "fetch_bls": dead, "fetch_series": dead}, later + timedelta(minutes=15))
    assert ev3["Unemployment Rate"]["actual"] == "4.3%" and ev3["Unemployment Rate"]["status"] == "verified_official"


def test_revision_detected_and_marked():
    state = {}
    evs = c.parse_events([raw("Unemployment Rate", 0.3)])
    run(evs, state, mk_deps(bls_rows))
    revised = lambda: dict(bls_rows(), unrate=[(d, 4.4) for d in months()])
    later = NOW + timedelta(hours=4)                                    # أكثر من 3 ساعات: يحقّ فحص المراجعة
    evs2 = c.parse_events([raw("Unemployment Rate", 0.3 + 4)])
    ev2 = run(evs2, state, mk_deps(revised), later)
    e = ev2["Unemployment Rate"]
    assert e["actual"] == "4.4%" and e["status"] == "revised" and e["revised_from"] == "4.3%"


def test_dead_source_gives_failed_not_zero_or_dash():
    state = {}
    def dead(_):
        raise RuntimeError("down")
    d = {"fetch_oil": lambda: None, "fetch_auctions": lambda: [], "fetch_bls": dead, "fetch_series": dead}
    evs = c.parse_events([raw("CPI m/m", 0.2)])
    ev = run(evs, state, d)
    assert ev["CPI m/m"]["actual"] == "" and ev["CPI m/m"]["status"] in ("awaiting", "failed")
    evs = c.parse_events([raw("CPI m/m", 0.2)])
    ev = run(evs, state, d, NOW + timedelta(minutes=15))
    e = ev["CPI m/m"]
    assert e["actual"] == "" and e["status"] == "failed" and "تعذّر" in e["actual_note"]
    d2 = events_ctx.describe(e, "15:30")
    assert d2["status_ar"] == "تعذّر جلب البيانات" and d2["surprise"] == "" and d2["surprise_num"] == ""


def test_event_ids_are_stable_and_distinguish_similar_events():
    evs = events_all()
    ids = [actuals.event_id(e) for e in evs]
    assert len(set(ids)) == len(ids)
    assert actuals.event_id(evs[0]) == actuals.event_id(c.parse_events([raw("CPI m/m", 3.5, forecast="9.9%")])[0])   # لا تتأثر بتغيّر التوقع
    by = {e["title"]: actuals.event_id(e) for e in evs}
    assert by["CPI m/m"] != by["Core CPI m/m"] != by["CPI y/y"] and by["CPI m/m"] != by["CPI y/y"]
    assert by["Unemployment Rate"] != by["Unemployment Claims"] and by["PPI m/m"] != by["CPI m/m"]
    assert "|cpi|mm|2026-09|" in by["CPI m/m"] and "|cpi_ny|yy|2026-09|" in by["CPI y/y"]


def test_time_conversion_et_to_utc_and_baghdad():
    e = c.parse_events([{"title": "CPI m/m", "country": "USD", "impact": "High", "date": "2026-10-14T08:30:00-04:00", "forecast": "0.2%", "previous": "0.2%"}])[0]
    assert e["time"].isoformat() == "2026-10-14T12:30:00+00:00"
    assert (e["time"] + timedelta(hours=3)).strftime("%H:%M") == "15:30"           # بغداد UTC+3
    assert e["time"].astimezone(ET).date().isoformat() == "2026-10-14"


def test_release_alert_now_fires_because_actuals_resolve_first():
    """السبب الجذري: التقويم بلا actual فلا يُرسَل تنبيه الصدور. بعد الإصلاح تُحلّ الأرقام قبل due_releases."""
    evs = c.parse_events([raw("CPI m/m", 0.5)])
    assert r.due_releases(evs, NOW, {"seen_events": []}) == []                     # قبل الحل: لا شيء (الخلل الأصلي)
    r.resolve_actuals(evs, NOW, {}, mk_deps(bls_rows))
    got = r.due_releases(evs, NOW, {"seen_events": []})
    assert [e["title"] for e in got] == ["CPI m/m"] and got[0]["actual"] == "0.2%"


def test_run_auto_sends_release_alert_with_actual():
    sent = Box()
    d = {"calendar": lambda now: c.parse_events([raw("CPI m/m", 0.5)]), "prices": lambda now: ({}, []), "intraday": lambda now: calm_intraday(),
         "headlines": lambda now: [], "history_path": os.path.join(tempfile.mkdtemp(), "h.csv"), "docs_dir": tempfile.mkdtemp()}
    d.update(mk_deps(bls_rows))
    try:
        r.run_auto(NOW, {"seen_events": [], "last_shock": None}, sent, d)
    except Exception:  # noqa: BLE001
        pass
    assert any("0.2%" in m and "CPI" in m for m in sent.msgs), sent.msgs


def test_poll_schedule_and_giveup():
    e = c.parse_events([raw("CPI m/m", 0)])[0]
    sp = lambda mins, rec=None: actuals.should_poll(e, rec, e["time"] + timedelta(minutes=mins))
    assert not actuals.should_poll(e, None, e["time"] - timedelta(minutes=1))
    assert sp(0) and sp(15) and sp(89)                                          # كل فحص في أول 90 دقيقة
    last = lambda mins: {"status": "awaiting", "last_attempt": (e["time"] + timedelta(minutes=mins)).isoformat()}
    assert not sp(120, last(100)) and sp(160, last(100))                        # ثم كل ساعة تقريباً
    assert not sp(60 * 24 * 8)                                                  # يتوقف بعد 7 أيام
    v = lambda mins: {"status": "verified_official", "last_attempt": (e["time"] + timedelta(minutes=mins)).isoformat()}
    assert not sp(120, v(100)) and sp(60 * 4, v(10)) and not sp(60 * 50, v(10))


def test_surprise_numeric_and_missing_forecast():
    assert actuals.surprise_value("0.4%", "0.3%")["text"] == "+0.1 نقطة مئوية"
    assert actuals.surprise_value("0.4%", "") is None and actuals.surprise_value("", "0.3%") is None
    assert actuals.surprise_value("150K", "150K")["value"] == 0
    assert events_ctx._surprise_num({"actual": "231K", "forecast": ""}) == ""


def test_calendar_cache_fallback_and_expiry():
    state = {}
    good = c.parse_events([raw("CPI m/m", -2)])
    def cal(now):
        return good
    r.calendar_events(NOW, state, {"calendar": cal})
    def boom(now):
        raise RuntimeError("429")
    probs = []
    ev = r.calendar_events(NOW + timedelta(minutes=30), state, {"calendar": boom}, probs)
    assert ev and ev[0]["title"] == "CPI m/m" and probs and "نسخة محفوظة" in probs[0]
    try:
        r.calendar_events(NOW + timedelta(days=4), state, {"calendar": boom})
        assert False
    except RuntimeError:
        pass


def test_bls_parse_quota_and_failures():
    resp = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [{"seriesID": "LNS14000000", "data": [
        {"year": "2026", "period": "M09", "value": "4.3"}, {"year": "2026", "period": "M08", "value": "4.2"},
        {"year": "2026", "period": "M13", "value": "4.1"}, {"year": "2026", "period": "M07", "value": "-"}]}]}}
    rows, errs = bls.parse(resp)
    assert rows["LNS14000000"] == [("2026-08-01", 4.2), ("2026-09-01", 4.3)] and not errs
    _, errs = bls.parse({"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold reached"]})
    assert errs and "BLS" in errs[0]
    st = {"bls_calls": {NOW.date().isoformat(): 20}}
    rows, errs = bls.fetch(["LNS14000000"], NOW, None, post_fn=lambda u, p: resp, state=st)
    assert not rows and "الحصة" in errs[0]
    st = {}
    rows, errs = bls.fetch(["LNS14000000"], NOW, None, post_fn=lambda u, p: resp, state=st)
    assert rows and st["bls_calls"][NOW.date().isoformat()] == 1
    def boom(u, p):
        raise OSError("net")
    assert bls.fetch(["LNS14000000"], NOW, None, post_fn=boom, state={})[1]


def test_view_shows_status_and_summary_without_fake_values():
    evs = events_all()
    run(evs, {}, mk_deps(bls_rows, fred_rows))
    summ = dashboard._actuals_summary(evs, NOW)
    assert summ["total"] == len(ALL) and 0 < summ["verified"] < summ["total"] and summ["awaiting"] + summ["failed"] + summ["unsupported"] >= 2 and summ["unsupported"] == 2
    ism = next(e for e in evs if "Manufacturing" in e["title"])
    d = events_ctx.describe(ism, "17:00")
    assert d["actual"] == "" and d["status_ar"] in ("صدر وننتظر وصول القيمة", "تعذّر جلب البيانات")


def test_safety_lowers_confidence_when_actual_pending():
    import safety
    evs = c.parse_events([raw("CPI m/m", 0.5)])
    run(evs, {}, {"fetch_oil": lambda: None, "fetch_auctions": lambda: [], "fetch_bls": lambda ids: ({}, ["BLS: down"]), "fetch_series": lambda n: {}})
    assert evs[0]["status"] in ("awaiting", "failed") and not evs[0]["actual"]
    _, issues = safety.check_inputs({}, evs, {}, NOW)
    pend = [i for i in issues if i["code"] == "actual_pending"]
    assert pend and "معلّق" in pend[0]["msg"]
    base = safety.confidence([i for i in issues if i["code"] != "actual_pending"], 1.0)["points"]
    assert safety.confidence(issues, 1.0)["points"] < base          # الثقة تنخفض فعلاً
    ok = c.parse_events([raw("CPI m/m", 0.5)])
    run(ok, {}, mk_deps(bls_rows))
    _, issues2 = safety.check_inputs({}, ok, {}, NOW)
    assert not [i for i in issues2 if i["code"] == "actual_pending"]


# ───────── v0.18: فصل حالات التحقق ─────────
import safety
import health

STALE_FRED = lambda: {"claims": [("2026-09-26", 225000.0), ("2026-10-03", 228000.0)]}      # FRED لم يُحدَّث لأسبوع الإصدار
HEADS = lambda q: ["Initial jobless claims fall to 231,000 in latest week"]


def claims_ev(hours_ago=2):
    return c.parse_events([raw("Unemployment Claims", hours_ago, forecast="230K", previous="228K")])


def deps_news(fred_fn):
    d = mk_deps(None, fred_fn)
    d["fetch_heads_q"] = HEADS
    return d


def test_headline_number_is_never_verified_and_never_acts_as_actual():
    state, evs = {}, claims_ev()
    run(evs, state, deps_news(STALE_FRED))
    e = evs[0]
    assert e["status"] == "needs_check" and e["actual"] == "" and e["actual_unverified"] == "231K"
    d = events_ctx.describe(e, "15:30")
    assert d["actual"] == "" and d["verified"] is False and d["actual_unverified"] == "231K" and d["surprise"] == "" and d["surprise_num"] == ""
    assert d["status_ar"] == "مستخرج من خبر ويحتاج تحققاً"
    assert r.due_releases(evs, NOW, {"seen_events": []}) == []                    # لا تنبيه صدور برقم غير متحقق
    summ = dashboard._actuals_summary(evs, NOW)
    assert summ["verified"] == 0 and summ["needs_check"] == 1
    assert health._events_stats(evs, NOW)[1] == 0                                  # لا يُحسب «متحقق منه» في صحة مرصاد
    _, issues = safety.check_inputs({}, evs, {}, NOW)
    assert [i for i in issues if i["code"] == "actual_pending"]                    # والثقة تبقى مخفّضة كالمعلّق


def test_needs_check_is_upgraded_when_official_source_arrives_and_never_downgraded():
    state = {}
    evs = claims_ev()
    run(evs, state, deps_news(STALE_FRED))
    state = json.loads(json.dumps(state))                                          # إعادة تشغيل: التخزين يستمر
    later = NOW + timedelta(hours=1)
    evs2 = claims_ev(3)
    r.resolve_actuals(evs2, later, state, deps_news(lambda: fred_rows()))
    e = evs2[0]
    assert e["actual"] == "231K" and e["status"] == "verified_secondary"
    assert state["actuals"][actuals.event_id(e)]["trust"] == "secondary"
    # بعد التحقق لا يستبدله خبر لاحق أبداً
    evs3 = claims_ev(5)
    r.resolve_actuals(evs3, later + timedelta(hours=4), state, deps_news(STALE_FRED))
    assert evs3[0]["actual"] == "231K" and evs3[0]["status"] == "verified_secondary"


def test_headline_replaced_by_official_value_when_different():
    state, evs = {}, claims_ev()
    run(evs, state, deps_news(STALE_FRED))
    fred_other = lambda: {"claims": [("2026-10-03", 228000.0), ("2026-10-10", 233000.0)]}
    evs2 = claims_ev(3)
    r.resolve_actuals(evs2, NOW + timedelta(hours=1), state, deps_news(fred_other))
    e = evs2[0]
    assert e["actual"] == "233K" and e["status"] == "verified_secondary" and not e.get("revised_from")   # استبدال لا «مراجعة»


def test_official_bls_status_and_audit_log_fields():
    state, evs = {}, c.parse_events([raw("Unemployment Rate", 2)])
    run(evs, state, mk_deps(bls_rows))
    assert evs[0]["status"] == "verified_official" and evs[0]["actual_source"] == "BLS" and evs[0]["actual_period"] == "2026-09-01"
    lg = state["actuals_log"][-1]
    assert lg["source"] == "BLS" and lg["value"] == "4.3%" and lg["period"] == "2026-09-01" and lg["tier"] == "official"
    assert lg["release_time"] and lg["fetched_at"] and lg["match"]


def test_unknown_provenance_is_treated_as_unverified():
    assert actuals.tier_of({"actual": "1"}) == "news" and not actuals.is_verified({"status": "needs_check", "actual_src": "news"})
    assert actuals.is_verified({"status": "revised", "actual_src": "official", "actual": "1.0%"}) and not actuals.is_verified({"status": "revised", "actual_src": "news", "actual": "1.0%"})
    assert not actuals.is_verified({"status": "verified_official", "actual_src": "official", "actual": ""})          # حالة سليمة بلا قيمة
    assert not actuals.is_verified({"status": "verified_official", "actual_src": "official", "actual": "n/a"})      # قيمة غير مفهومة
    assert not actuals.is_verified({"status": "verified", "actual": "0.2%"})                                        # كلمة verified القديمة بلا trust


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({len(tests)})")
