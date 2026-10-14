# -*- coding: utf-8 -*-
"""اختبارات v0.18.1: كل اختبار هنا يعيد إنتاج خطأً مؤكداً في v0.17/v0.18 (يفشل على الكود القديم) وينجح بعد الإصلاح.
البيانات اصطناعية بشكل استجابات BLS/FRED: تثبت المنطق لا صحة الأرقام الحقيقية (هذه في verify.py على GitHub)."""
import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone

import actuals
import collector as c
import dashboard
import events_ctx
import health
import indicators
import migrate
import quality
import runner as r
import values
from extras import ET
from tests_actuals import NOW, raw, mk_deps, bls_rows, fred_rows, growth, months, run
from tests_runner import Box, calm_intraday

DEAD = {"fetch_oil": lambda: None, "fetch_auctions": lambda: [], "fetch_bls": lambda ids: (_ for _ in ()).throw(RuntimeError("down")),
        "fetch_series": lambda need: (_ for _ in ()).throw(RuntimeError("down"))}


def roundtrip(state):
    return json.loads(json.dumps(state))


# ───────── 1) Core PCE شهري/سنوي ─────────
def pce_events(order=(0, 1)):
    evs = [raw("Core PCE Price Index m/m", 3, forecast="0.3%", previous="0.2%"), raw("Core PCE Price Index y/y", 3, forecast="2.5%", previous="2.3%")]
    return c.parse_events([evs[i] for i in order])


PCE_FRED = lambda: {"pcelfe": growth(128, 0.002)}


def vals(ev):
    return {e["title"][-3:]: e["actual"] for e in ev.values()} if isinstance(ev, dict) else {e["title"][-3:]: e["actual"] for e in ev}


def test_pce_monthly_and_yearly_have_distinct_ids_and_stay_separate_after_restart():
    evs = pce_events()
    assert len({actuals.event_id(e) for e in evs}) == 2
    st = {}
    run(evs, st, mk_deps(None, PCE_FRED))
    assert vals(evs) == {"m/m": "0.2%", "y/y": "2.4%"}
    st2 = roundtrip(st)                                                # حفظ وإعادة تشغيل والمصادر معطّلة
    evs2 = pce_events()
    r.resolve_actuals(evs2, NOW + timedelta(minutes=20), st2, DEAD)
    assert vals(evs2) == {"m/m": "0.2%", "y/y": "2.4%"}                # الخطأ القديم: y/y يصبح 0.2%
    evs3 = pce_events((1, 0))                                          # وبعكس ترتيب الحدثين
    r.resolve_actuals(evs3, NOW + timedelta(minutes=40), roundtrip(st2), DEAD)
    assert vals(evs3) == {"m/m": "0.2%", "y/y": "2.4%"}


def test_pce_reverse_order_first_run_and_no_cross_forecast_or_revision():
    evs = pce_events((1, 0))
    st = {}
    run(evs, st, mk_deps(None, PCE_FRED))
    assert vals(evs) == {"m/m": "0.2%", "y/y": "2.4%"}
    by = {e["title"][-3:]: e for e in evs}
    assert by["m/m"]["forecast"] == "0.3%" and by["y/y"]["forecast"] == "2.5%"
    recs = st["actuals"]
    assert len(recs) == 2 and {x["forecast"] for x in recs.values()} == {"0.3%", "2.5%"}
    mid = next(k for k, v in recs.items() if "|mm|" in k)
    recs[mid]["revised_from"] = "0.1%"                                  # مراجعة تخص الشهري فقط
    evs2 = pce_events()
    r.resolve_actuals(evs2, NOW + timedelta(minutes=20), roundtrip(st), DEAD)
    yy = next(e for e in evs2 if e["title"].endswith("y/y"))
    assert not yy.get("revised_from") and not yy.get("prev_revised")


def test_event_id_carries_measure_period_and_stage():
    e = c.parse_events([raw("Core PCE Price Index y/y", 3)])[0]
    eid = actuals.event_id(e)
    assert eid.split("|")[1:5] == ["pcelfe", "yy", "2026-09", "-"]


# ───────── 2) الترحيل ─────────
def v017_state(value="4.3%", status="verified"):
    t = (NOW - timedelta(hours=3)).isoformat()
    old_id = "US|unrate|2026-09|2026-10-14"
    return {"seen_events": [], "actuals": {old_id: {"actual": value, "note": "المصدر: عنوان خبر، تحقق منه", "status": status, "attempts": 1,
                                                     "title": "Unemployment Rate", "time": t, "received_at": t, "last_attempt": t}}}


def test_v017_headline_value_is_quarantined_not_shown_as_verified():
    st = v017_state()
    rep = migrate.migrate(st, NOW)
    assert rep["quarantined"] == 1 and st["schema_version"] == 2
    evs = c.parse_events([raw("Unemployment Rate", 3, forecast="4.2%")])
    r.resolve_actuals(evs, NOW, st, DEAD)                                # كل المصادر معطلة: لا شيء يرقّي الرقم
    e = evs[0]
    assert e["actual"] == "" and e["actual_unverified"] == "4.3%" and e["status"] == "needs_check"
    d = events_ctx.describe(e, "15:30")
    assert d["verified"] is False and d["surprise"] == "" and d["surprise_num"] == "" and d["actual"] == ""
    assert r.due_releases(evs, NOW, {"seen_events": []}) == []
    assert actuals.bucket(e) == "needs_check" and dashboard._actuals_summary(evs, NOW)["verified"] == 0
    assert quality.build(evs, st, NOW)["arrived"] == 0


def test_v017_quarantined_value_is_replaced_by_official_and_history_kept():
    st = v017_state()
    migrate.migrate(st, NOW)
    evs = c.parse_events([raw("Unemployment Rate", 3)])
    run(evs, st, mk_deps(bls_rows))
    e = evs[0]
    assert e["actual"] == "4.3%" and e["status"] == "verified_official"
    rec = st["actuals"][actuals.event_id(e)]
    assert rec["legacy"] and rec["legacy"][0]["value"] == "4.3%" and rec["legacy"][0]["reason"]
    assert any(h.get("value") == "4.3%" for h in rec["history"])          # التاريخ لم يُمحَ


def test_v017_state_without_migration_is_still_defensively_unverified():
    st = v017_state()                                                    # لا migrate: restore وحده يجب ألا يصدّق
    evs = c.parse_events([raw("Unemployment Rate", 3)])
    r.resolve_actuals(evs, NOW, st, DEAD)
    assert evs[0]["actual"] == "" and r.due_releases(evs, NOW, {"seen_events": []}) == []


def test_migration_is_idempotent_and_writes_backup_once():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "state.json")
    st = v017_state()
    json.dump(st, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    s1, rep1 = migrate.load_and_migrate(p, NOW)
    bak = p + ".bak-v1"
    assert os.path.exists(bak) and json.load(open(bak, encoding="utf-8")) == st and rep1["quarantined"] == 1
    json.dump(s1, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    s2, rep2 = migrate.load_and_migrate(p, NOW + timedelta(hours=1))
    assert rep2["skipped"] and s2 == s1                                  # التكرار لا يغيّر شيئاً
    assert json.load(open(bak, encoding="utf-8")) == st                  # النسخة الاحتياطية الأصلية لم تُستبدل


def test_v018_official_record_is_renamed_and_kept_verified():
    t = (NOW - timedelta(hours=3)).isoformat()
    st = {"actuals": {"US|unrate|2026-09|2026-10-14": {"actual": "4.3%", "status": "verified_official", "trust": "official", "source": "BLS",
                                                         "period": "2026-09-01", "title": "Unemployment Rate", "time": t, "received_at": t}}}
    rep = migrate.migrate(st, NOW)
    assert rep["renamed"] == 1 and rep["kept"] == 1 and rep["quarantined"] == 0
    (k, rec), = st["actuals"].items()
    assert k == "US|unrate|level_pct|2026-09|-|2026-10-14" and rec["status"] == "verified_official"


def test_old_colliding_pce_and_gdp_records_are_quarantined_not_guessed():
    t = (NOW - timedelta(hours=3)).isoformat()
    base = {"status": "verified_secondary", "trust": "secondary", "source": "FRED", "time": t, "received_at": t}
    st = {"actuals": {"US|pcelfe|2026-09|2026-10-14": dict(base, actual="0.2%", title="Core PCE Price Index m/m"),
                      "US|gdp|2026-07|2026-10-14": dict(base, actual="2.1%", title="Advance GDP q/q")}}
    rep = migrate.migrate(st, NOW)
    assert rep["quarantined"] == 2
    assert all(x["status"] == "needs_check" and x["trust"] == "news" for x in st["actuals"].values())
    evs = pce_events()
    r.resolve_actuals(evs, NOW, st, DEAD)
    assert all(e["actual"] == "" for e in evs)                           # لا قيمة تُنسب لأي من المؤشرين


# ───────── 3) GDP ─────────
def test_gdp_reference_quarter_and_stage_by_release_month():
    f = indicators.gdp_ref_quarter
    assert f(date(2026, 8, 27)) == date(2026, 4, 1)                       # الخطأ القديم: 2026-07-01
    assert f(date(2026, 7, 30)) == date(2026, 4, 1) and f(date(2026, 9, 25)) == date(2026, 4, 1)
    assert f(date(2026, 10, 29)) == date(2026, 7, 1) and f(date(2026, 12, 20)) == date(2026, 7, 1)
    assert f(date(2027, 1, 28)) == date(2026, 10, 1) and f(date(2027, 3, 26)) == date(2026, 10, 1)   # عبور السنة
    assert [indicators.gdp_stage_by_schedule(date(2026, m, 15)) for m in (7, 8, 9)] == ["advance", "second", "third"]
    assert indicators.gdp_stage_by_schedule(date(2027, 1, 28)) == "advance"


def gdp_ev(title, when_utc):
    return c.parse_events([{"title": title, "country": "USD", "impact": "High", "date": when_utc, "forecast": "2.0%", "previous": "3.0%"}])[0]


def test_gdp_never_uses_a_different_quarter_or_a_later_revision():
    rows = [("2026-01-01", 1.5), ("2026-04-01", 3.0), ("2026-07-01", 2.1)]      # الربع الثالث موجود لكنه ليس المقصود في أغسطس
    t = datetime(2026, 8, 27, 12, 30, tzinfo=timezone.utc)
    res = indicators.resolve_detail("GDP q/q", t, {"gdp": rows}, ET, "FRED", None, t + timedelta(hours=2))
    assert res["value"] == "3.0%" and res["period"] == "2026-04-01" and res["stage"] == "second"
    late = indicators.resolve_detail("GDP q/q", t, {"gdp": rows}, ET, "FRED", None, t + timedelta(days=25))
    assert late["value"] is None and "مراجَعة" in late["why"]                    # بعد 20 يوماً لا نعرضها كأنها الأصلية
    miss = indicators.resolve_detail("GDP q/q", t, {"gdp": [("2026-01-01", 1.5), ("2026-07-01", 2.1)]}, ET, "FRED", None, t)
    assert miss["value"] is None and miss["why"]                              # الربع الصحيح غائب: غير متاح مع السبب


def test_gdp_stage_in_title_must_match_bea_schedule_and_ids_differ_by_stage():
    t = datetime(2026, 8, 27, 12, 30, tzinfo=timezone.utc)
    bad = indicators.resolve_detail("Advance GDP q/q", t, {"gdp": [("2026-04-01", 3.0)]}, ET, "FRED", None, t)
    assert bad["value"] is None and "لا توافق جدول BEA" in bad["why"]
    ok = indicators.resolve_detail("Prelim GDP q/q", t, {"gdp": [("2026-04-01", 3.0)]}, ET, "FRED", None, t)
    assert ok["value"] == "3.0%" and ok["stage"] == "second"
    ids = {actuals.event_id(gdp_ev("GDP q/q", f"2026-{m:02d}-27T12:30:00+00:00")) for m in (7, 8, 9)}
    assert len(ids) == 3 and all("|gdp|level_pct|2026-04|" in i for i in ids)
    jan = indicators.resolve_detail("Advance GDP q/q", datetime(2027, 1, 28, 13, 30, tzinfo=timezone.utc), {"gdp": [("2026-10-01", 2.8)]}, ET, "FRED", None, None)
    assert jan["value"] == "2.8%" and jan["period"] == "2026-10-01" and jan["stage"] == "advance"


# ───────── 4) الوحدات والمفاجأة ─────────
def test_units_normalised_before_subtracting():
    assert values.diff_text("1M", "900K") == "+100K"                          # الخطأ القديم: −899M
    assert values.diff_text("0.4%", "0.3%") == "+0.1 نقطة مئوية"
    assert values.diff_text("231K", "230K") == "+1K" and values.diff_text("150K", "150K") == "0K"
    assert values.diff_text("-0.3%", "0.1%") == "-0.4 نقطة مئوية"
    assert values.diff_text("0%", "0.1%") == "-0.1 نقطة مئوية" and values.diff_text("0.0%", "0%") == "0 نقطة مئوية"
    assert values.diff_text("0.4%", "") == "" and values.diff_text("", "0.3%") == "" and values.diff_text(None, "1") == ""
    assert values.sign("1M", "900K") == 1 and values.sign("-5K", "-6K") == 1 and values.sign("0", "0") == 0


def test_incompatible_units_are_refused_not_zeroed():
    assert values.sign("3bp", "0.03%") is None and values.diff_text("3bp", "0.03%") == ""
    assert values.sign("5%", "5K") is None and values.sign("n/a", "1%") is None and values.sign("--", "--") is None
    assert actuals.surprise_value("1.2M", "1.2%") is None
    assert values.diff_text("4bp", "3bp") == "+1 نقطة أساس"


def test_auction_composite_keeps_yield_and_coverage_separate():
    assert values.diff_text("4.215|2.60", "4.115|2.70") == "العائد +0.1 نقطة مئوية | التغطية -0.1"
    ev = {"title": "10-y Bond Auction", "actual": "4.2|2.6", "forecast": "4.1|2.7", "previous": "4.0|2.5"}
    assert events_ctx._surprise_num(ev) == "العائد +0.1 نقطة مئوية | التغطية -0.1"


def test_surprise_used_everywhere_cpi_example_and_alert_text():
    assert events_ctx.surprise("0.4%", "0.3%") == "أعلى من المتوقع بـ 0.1 نقطة مئوية"
    assert events_ctx.surprise("1M", "900K") == "أعلى من المتوقع بـ 100K"
    assert r.surprise({"actual": "1M", "forecast": "900K"}) == "أعلى من المتوقع"
    assert "899" not in events_ctx.surprise("1M", "900K")
    assert events_ctx.expectation("4.3%", "4.1%") == "السوق يتوقع قراءة أعلى من السابق بـ 0.2 نقطة مئوية"
    assert events_ctx.surprise("", "0.3%") == "" and events_ctx.vs_previous("0.2%", "") == ""


# ───────── 5) فجوات السلاسل ─────────
def test_missing_reference_month_blocks_mm_and_yy():
    gap = [("2026-07-01", 100.0), ("2026-09-01", 103.0)]
    assert indicators.compute_full("mm", gap, 1)[0] is None                    # الخطأ القديم: 3.0%
    assert "غير موجود" in indicators.compute_full("mm", gap, 1)[2]
    full = [(d, 100.0 + i) for i, d in enumerate(months(n=16))]
    gappy = [x for x in full if x[0] != "2025-09-01"]                          # يغيب الشهر نفسه قبل سنة
    i = next(k for k, (d, _) in enumerate(gappy) if d == "2026-09-01")
    assert indicators.compute_full("yy", gappy, i)[0] is None
    j = next(k for k, (d, _) in enumerate(full) if d == "2026-09-01")
    assert indicators.compute_full("yy", full, j)[0] == f"{(full[j][1] / full[j - 12][1] - 1) * 100:.1f}%"
    assert indicators.compute_full("diff_k", [("2026-07-01", 150000.0), ("2026-09-01", 150200.0)], 1)[0] is None


def test_invalid_series_are_rejected():
    dup = [("2026-08-01", 100.0), ("2026-08-01", 101.0), ("2026-09-01", 102.0)]
    uns = [("2026-09-01", 102.0), ("2026-08-01", 100.0)]
    bad = [("2026-08-01", float("nan")), ("2026-09-01", 102.0)]
    for rows in (dup, uns, bad):
        assert not indicators.validate_rows(rows)[0]
        assert indicators.compute_full("mm", rows, len(rows) - 1)[0] is None
    res = indicators.resolve_detail("CPI m/m", datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc), {"cpi": [("2026-07-01", 100.0), ("2026-09-01", 103.0)]}, ET)
    assert res["value"] is None and "غير موجود" in res["why"]


def test_gap_in_source_gives_no_actual_end_to_end():
    rows = [(d, v) for d, v in growth(300, 0.002) if d != "2026-08-01"]
    st, evs = {}, c.parse_events([raw("CPI m/m", 3)])
    run(evs, st, mk_deps(lambda: {"cpi": rows}, lambda: {"cpi": rows}))
    assert evs[0]["actual"] == "" and evs[0]["status"] in ("awaiting", "failed")


# ───────── 7) التغطية الموحدة ─────────
def test_speech_does_not_count_as_pending_actual_or_lower_coverage():
    base = [raw("CPI m/m", 3), raw("Unemployment Rate", 3)]
    speech = raw("FOMC Member Powell Speaks", 3, forecast="", previous="")
    a = c.parse_events(base)
    b = c.parse_events(base + [speech])
    for evs in (a, b):
        run(evs, {}, mk_deps(bls_rows, fred_rows))
    sa, sb = dashboard._actuals_summary(a, NOW), dashboard._actuals_summary(b, NOW)
    assert sa == sb and sb["total"] == 2 and sb["coverage_pct"] == 100 and sb["awaiting"] == 0       # الخطأ القديم: يزيد المعلّق
    st = {}
    run(b, st, mk_deps(bls_rows, fred_rows))
    q = quality.build(b, st, NOW)
    assert q["total"] == 2 and q["coverage_pct"] == 100 and q["awaiting"] == 0
    assert health._events_stats(b, NOW)[1:] == (2, 0)


def test_one_definition_across_summary_quality_and_health_with_all_buckets():
    evs = c.parse_events([raw("CPI m/m", 3), raw("ISM Manufacturing PMI", 3), raw("Unemployment Claims", 3), raw("Retail Sales m/m", 3),
                          raw("Advance GDP q/q", 3)])
    st = {}
    r.resolve_actuals(evs, NOW, st, {"fetch_oil": lambda: None, "fetch_auctions": lambda: [], "fetch_bls": lambda ids: ({}, ["BLS: خطأ"]),
                                     "fetch_series": lambda need: {"claims": [("2026-09-26", 225000.0)]}, "fetch_heads_q": lambda q: ["US jobless claims rise to 231,000"] if "jobless" in q.lower() else []})
    sm = dashboard._actuals_summary(evs, NOW)
    q = quality.build(evs, st, NOW)
    assert sm["unsupported"] == q["unsupported"] == 1 and sm["needs_check"] == q["needs_check"] == 1
    assert sm["verified"] == q["arrived"] == 0 and sm["coverage_pct"] == q["coverage_pct"] == 0
    assert sm["awaiting"] == q["awaiting"] and sm["failed"] == q["failed"]
    assert sm["total"] == q["total"] == 5 and health._events_stats(evs, NOW)[1] == 0


def test_empty_coverage_is_none_not_zero_or_hundred():
    assert dashboard._actuals_summary([], NOW)["coverage_pct"] is None
    assert quality.build([], {}, NOW)["coverage_pct"] is None


# ───────── 8) الوصول المتأخر وتغير الأسبوع ─────────
def auto_deps(cal, bls_fn):
    d = {"calendar": cal, "prices": lambda now: ({}, []), "intraday": lambda now: calm_intraday(), "headlines": lambda now: [],
         "history_path": os.path.join(tempfile.mkdtemp(), "h.csv"), "docs_dir": tempfile.mkdtemp()}
    d.update(mk_deps(bls_fn))
    return d


def stale_bls():
    return {k: v[:-1] for k, v in bls_rows().items()}


def run_auto(now, st, box, d):
    try:
        return r.run_auto(now, st, box, d)
    except Exception:  # noqa: BLE001
        return 0


def test_late_arrival_alert_once_then_revision_alert_distinct_and_survives_restart():
    box, st = Box(), {"seen_events": [], "last_shock": None}
    cal = lambda now: c.parse_events([raw("Unemployment Rate", 4, forecast="4.2%", previous="4.3%")])        # صدر قبل 4 ساعات (خارج نافذة 3س)
    d = auto_deps(cal, stale_bls)
    run_auto(NOW, st, box, d)
    assert not any("الفعلي" in m for m in box.msgs)                                                          # لم يصل رقم بعد
    d2 = auto_deps(cal, bls_rows)
    run_auto(NOW + timedelta(hours=1), st, box, d2)       # جدولة الجلب: بعد 90 دقيقة من الصدور كل ساعة
    late = [m for m in box.msgs if "وصلت البيانات متأخرة" in m]
    assert len(late) == 1 and "4.3%" in late[0] and "BLS" in late[0] and "منذ الصدور غير محسوبة" in late[0]
    run_auto(NOW + timedelta(hours=1, minutes=15), st, box, d2)
    assert len([m for m in box.msgs if "وصلت البيانات متأخرة" in m]) == 1                                    # لا تكرار
    st2 = roundtrip(st)
    run_auto(NOW + timedelta(hours=1, minutes=30), st2, box, d2)
    assert len([m for m in box.msgs if "وصلت البيانات متأخرة" in m]) == 1                                    # ولا بعد إعادة التشغيل
    rev = lambda: dict(bls_rows(), unrate=[(dd, 4.4) for dd, _ in bls_rows()["unrate"]])
    d3 = auto_deps(cal, rev)
    run_auto(NOW + timedelta(hours=5), st2, box, d3)
    revs = [m for m in box.msgs if "مراجعة بيانات" in m]
    assert len(revs) == 1 and "من 4.3% إلى 4.4%" in revs[0] and "ليست إصداراً جديداً" in revs[0]
    run_auto(NOW + timedelta(hours=9), st2, box, d3)
    assert len([m for m in box.msgs if "مراجعة بيانات" in m]) == 1


def test_normal_release_in_window_is_not_late_and_revision_is_not_first_arrival():
    box, st = Box(), {"seen_events": [], "last_shock": None}
    cal = lambda now: c.parse_events([raw("Unemployment Rate", 0.5, forecast="4.2%")])
    d = auto_deps(cal, bls_rows)
    run_auto(NOW, st, box, d)
    assert len([m for m in box.msgs if "صدرت بيانات" in m]) == 1 and not [m for m in box.msgs if "متأخرة" in m]


def test_event_missing_from_new_week_calendar_is_still_retried_and_alerted():
    box, st = Box(), {"seen_events": [], "last_shock": None}
    cal1 = lambda now: c.parse_events([raw("Unemployment Rate", 2, forecast="4.2%", previous="4.3%")])
    run_auto(NOW, st, box, auto_deps(cal1, stale_bls))
    rec = next(iter(st["actuals"].values()))
    assert rec["status"] == "awaiting" and rec["forecast"] == "4.2%" and rec["previous"] == "4.3%" and rec["impact"] == "High"   # بيانات إعادة المحاولة محفوظة
    st2 = roundtrip(st)
    cal2 = lambda now: []                                                                                     # الأسبوع تغيّر: الحدث غاب عن thisweek
    run_auto(NOW + timedelta(hours=26), st2, box, auto_deps(cal2, bls_rows))
    rec2 = next(iter(st2["actuals"].values()))
    assert rec2["actual"] == "4.3%" and rec2["status"] == "verified_official"
    late = [m for m in box.msgs if "وصلت البيانات متأخرة" in m]
    assert len(late) == 1 and "المتوقع: 4.2%" in late[0]


def test_ghost_events_are_not_created_for_expired_or_broken_records():
    t = (NOW - timedelta(days=9)).isoformat()
    st = {"actuals": {"x": {"title": "Unemployment Rate", "time": t, "status": "awaiting"}, "y": {"status": "awaiting"},
                      "z": {"title": "Unemployment Rate", "time": (NOW - timedelta(hours=5)).isoformat(), "status": "awaiting"}}}
    assert actuals.ghost_events([], st, NOW) == []                           # قديم، ناقص، ومعرّف لا يطابق: لا نخمّن


# ───────── 9) توثيق المصدر ─────────
def test_audit_log_documents_method_series_raw_and_never_claims_unverified_match():
    st, evs = {}, c.parse_events([raw("CPI m/m", 3), raw("Unemployment Claims", 3)])
    run(evs, st, mk_deps(bls_rows, fred_rows))
    lg = {x["title"]: x for x in st["actuals_log"] if x["value"]}
    x = lg["CPI m/m"]
    assert x["series"] == "CUSR0000SA0" and "مؤشر الشهر" in x["method"] and isinstance(x["raw"], float) and x["basis"] == "محسوب من سلسلة رسمية"
    assert x["period_check"] == "مطابقة فترة التقرير" and x["bulletin_check"] == "لم تُقارَن بنشرة الإصدار"
    assert lg["Unemployment Claims"]["basis"] == "محسوب من سلسلة ثانوية" and lg["Unemployment Claims"]["series"] == "ICSA"
    st2, e2 = {}, c.parse_events([raw("Unemployment Claims", 2)])
    r.resolve_actuals(e2, NOW, st2, {"fetch_oil": lambda: None, "fetch_auctions": lambda: [], "fetch_bls": lambda ids: ({}, []),
                                     "fetch_series": lambda need: {"claims": [("2026-09-26", 225000.0)]}, "fetch_heads_q": lambda q: ["US jobless claims rise to 231,000"]})
    nl = [x for x in st2["actuals_log"] if x["value"]]
    assert nl and all(x["period_check"] == "غير مُتحقَّق" and x["basis"] == "مستخرج من خبر" for x in nl)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({len(tests)})")
