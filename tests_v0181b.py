# -*- coding: utf-8 -*-
"""اختبارات v0.18.1 (بنود 10 و11): الجدولة والتوقيت الصيفي، تفسير النفط بالسياق، حداثة 2Y، المراقبة بعد الإصدار."""
import os
from datetime import date, datetime, timedelta, timezone

import collector as c
import dashboard
import impact
import runner as r
import schedule
from tests_actuals import NOW, raw, mk_deps, bls_rows, run
import tests_safety as ts


# ───────── 10) الجدولة ─────────
def _crons():
    import yaml
    wf = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), ".github", "workflows", "mirsad.yml"), encoding="utf-8"))
    on = wf.get("on") or wf.get(True)
    return [x["cron"] for x in on["schedule"]]


def test_preopen_is_1430_baghdad_and_cron_maps_to_it():
    crons = _crons()
    assert "30 11 * * 1-5" in crons and "0 12 * * 1-5" not in crons
    t = datetime(2026, 10, 14, 11, 30, tzinfo=timezone.utc)
    assert schedule.to_baghdad(t).strftime("%H:%M") == "14:30"
    txt = open(os.path.join(os.path.dirname(__file__), ".github", "workflows", "mirsad.yml"), encoding="utf-8").read()
    assert '"$SCHEDULE" = "30 11 * * 1-5" ]; then MODE=preopen' in txt


def test_830_et_release_is_1530_baghdad_in_summer_and_1630_in_winter():
    summer, winter = date(2026, 10, 14), date(2026, 11, 18)          # التوقيت الصيفي الأمريكي ينتهي 1 نوفمبر 2026
    s, sb = schedule.post_release_target(summer)
    w, wb = schedule.post_release_target(winter)
    assert (s.hour, s.minute, sb.strftime("%H:%M")) == (12, 31, "15:31")
    assert (w.hour, w.minute, wb.strftime("%H:%M")) == (13, 31, "16:31")
    assert schedule.et_to_utc(date(2026, 11, 1), "08:30").hour == 13      # يوم التحويل نفسه
    assert schedule.et_to_utc(date(2026, 10, 31), "08:30").hour == 12


def test_workflow_has_a_cron_at_minute_31_for_both_dst_regimes_and_regular_polling():
    crons = _crons()
    cov = {schedule.cron_minutes(x) for x in crons}
    for d in (date(2026, 7, 15), date(2026, 12, 15)):
        t, _ = schedule.post_release_target(d)
        assert (t.minute, t.hour) in cov, (d, t, crons)                 # فحص مخصص بعد الإصدار صيفاً وشتاءً
    assert "*/15 * * * 1-5" in crons


def test_event_time_comes_from_calendar_not_fixed_clock():
    # الحدث نفسه 8:30 نيويورك: 12:30 UTC صيفاً و13:30 UTC شتاءً؛ التقويم مطلق UTC فلا افتراض ثابت
    ev_s = c.parse_events([{"title": "CPI m/m", "country": "USD", "impact": "High", "date": "2026-10-14T08:30:00-04:00", "forecast": "", "previous": ""}])[0]
    ev_w = c.parse_events([{"title": "CPI m/m", "country": "USD", "impact": "High", "date": "2026-11-18T08:30:00-05:00", "forecast": "", "previous": ""}])[0]
    assert (ev_s["time"].hour, ev_w["time"].hour) == (12, 13)


def test_watch_waits_for_fresh_release_then_stops_and_gives_up():
    cpi_now = NOW.replace(minute=1)
    mk = lambda: c.parse_events([{"title": "Unemployment Rate", "country": "USD", "impact": "High",
                                  "date": (cpi_now - timedelta(minutes=1)).isoformat(), "forecast": "4.2%", "previous": "4.3%"}])
    calls = {"n": 0, "sleeps": 0}
    stale = lambda: {k: v[:-1] for k, v in bls_rows().items()}

    def bls_fn():
        calls["n"] += 1
        return bls_rows() if calls["n"] >= 4 else stale()

    d = mk_deps(bls_fn, lambda: {})
    d["watch_s"] = 300
    d["sleep"] = lambda s: calls.__setitem__("sleeps", calls["sleeps"] + 1)
    evs, st = mk(), {}
    r.resolve_actuals(evs, cpi_now, st, d)
    assert evs[0]["actual"] == ""
    later = r.watch_releases(evs, cpi_now, st, d)
    assert evs[0]["actual"] == "4.3%" and evs[0]["status"] == "verified_official"
    assert 0 < calls["sleeps"] < 10 and later > cpi_now
    # مصدر لا يصل أبداً: ينتهي عند السقف ولا يدور بلا نهاية
    calls.update(n=-999, sleeps=0)
    evs2 = mk()
    st2 = {}
    r.resolve_actuals(evs2, cpi_now, st2, d)
    r.watch_releases(evs2, cpi_now, st2, d)
    assert calls["sleeps"] == 10 and evs2[0]["actual"] == ""
    d0 = dict(d, watch_s=0)
    calls["sleeps"] = 0
    r.watch_releases(mk(), cpi_now, {}, d0)
    assert calls["sleeps"] == 0                                         # معطّل في الاختبار/الوضع غير الحي


def test_watch_ignores_old_events_and_non_high():
    old = c.parse_events([{"title": "Unemployment Rate", "country": "USD", "impact": "High", "date": (NOW - timedelta(hours=2)).isoformat(), "forecast": "", "previous": ""}])
    n = {"s": 0}
    d = dict(mk_deps(None, lambda: {}), watch_s=300, sleep=lambda s: n.__setitem__("s", n["s"] + 1))
    r.watch_releases(old, NOW, {}, d)
    assert n["s"] == 0


# ───────── 11) النفط والأسواق ─────────
def test_oil_rise_is_not_automatically_negative_and_fall_not_automatically_positive():
    oc = impact.oil_cause
    assert oc(2.0, es_chg=-0.5, vix_chg=5.0, geo_supply=True)[:2] == ("bear", "supply")        # صدمة عرض
    assert oc(2.0, es_chg=0.6, vix_chg=-2.0, dxy_chg=-0.1)[:2] == ("flat", "demand_up")         # تحسن طلب: مختلط
    assert oc(2.0)[:2] == ("flat", "unclear") and oc(2.0, es_chg=-0.5, vix_chg=1.0)[:2] == ("flat", "unclear")   # بلا دليل: مشروط
    assert oc(-2.0, es_chg=-0.8, vix_chg=6.0)[:2] == ("bear", "demand_down")                    # ضعف طلب
    assert oc(-2.0, es_chg=0.5, vix_chg=-1.0)[:2] == ("bull", "relief")
    assert oc(-2.0, geo_relief=True)[:2] == ("bull", "relief")
    assert oc(-2.0)[:2] == ("flat", "unclear")                                                   # هبوط بلا سبب: ليس داعماً آلياً
    assert oc(0.2)[0] == "flat" and oc(None)[0] == "flat"
    assert impact.tone("oil", 5.0) == "flat" and impact.tone("oil", -5.0) == "flat"


def test_missing_evidence_is_not_treated_as_zero_calm():
    # غياب بيانات VIX لا يعني «هدوء»: لا حكم «تحسن طلب» بلا دليل كامل
    assert impact.oil_cause(2.0, es_chg=0.6, vix_chg=None)[1] == "unclear"
    assert impact.oil_cause(-2.0, es_chg=0.6, vix_chg=None)[1] == "unclear"


def test_driver_text_states_cause_and_view_keeps_oil_out_of_pressures_when_unclear():
    p, e, x = ts.demo()
    p["oil"]["chg1"] = 3.0
    p["es"]["chg1"], p["vix"]["chg1"] = -0.4, 1.0
    rep, v = ts.view_for(p)
    d = next(d for d in v["drivers"] if d["key"] == "oil")
    assert d["tone"] == "flat" and "غير واضح" in d["text"]
    assert not any("النفط" in s for s in v["pressures"]["bearish"] + v["pressures"]["bullish"])
    p2, _, _ = ts.demo()
    p2["oil"]["chg1"] = 3.0
    p2["es"]["chg1"], p2["vix"]["chg1"], p2["dxy"]["chg1"] = 0.7, -1.0, -0.1
    _, v2 = ts.view_for(p2)
    assert next(d for d in v2["drivers"] if d["key"] == "oil")["cause"] == "demand_up"


def test_pulse_oil_uses_context_and_2y_daily_is_not_instant_confirmation():
    p, e, x = ts.demo()
    p["oil"]["chg1"] = 2.0
    p["es"]["chg1"], p["vix"]["chg1"], p["dxy"]["chg1"] = 0.6, -1.0, -0.1
    rep, v = ts.view_for(p)
    oil = next(x for x in v["pulse8"] if x["sym"] == "WTI")
    assert oil["tone"] == "flat"                                                                  # تحسن طلب: ليس ضغطاً أحمر
    rep["fred_last"] = {"dgs2": {"date": "2026-10-13", "last": 3.9, "diff1": 0.05}}
    rep["bias"] = {"available": True, "key": "pressure"}
    y2 = next(x for x in dashboard._pulse8(rep) if x["sym"] == "2Y")
    assert y2["src"] == "FRED" and y2["confirm"] == "daily" and y2["time"] == "2026-10-13"


def test_ui_text_explains_oil_cause_daily_2y_and_work_order():
    h = open(os.path.join(os.path.dirname(__file__), "index.html"), encoding="utf-8").read()
    assert "صدمة عرض ضغط" in h and "ليس تأكيداً لحظياً" in h and "الماكرو ← سياق الأسبوع ← إيقاع اليوم ← تدفق الأوامر" in h


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({len(tests)})")
