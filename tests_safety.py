# -*- coding: utf-8 -*-
"""اختبارات المرحلتين 2–3: اتجاه التأثير، مراقب السلامة، الصحة، المزادات، تصنيف اليوم. بلا إنترنت."""
import copy
from datetime import datetime, timedelta, timezone

import collector as c
import dashboard
import events_ctx
import extras
import health
import impact
import safety

NOW = datetime(2026, 10, 8, 13, 14, tzinfo=timezone.utc)   # 16:14 بتوقيت بغداد (حالة المستخدم)


def demo():
    p, e, x = c.demo_inputs(NOW)
    return copy.deepcopy(p), e, x


def view_for(prices, events=None, extras_=None):
    p, e, x = demo()
    rep = c.build_report(prices, e if events is None else events, NOW, [], extras_ or x)
    return rep, dashboard.build_view(rep, e if events is None else events, NOW)


# ───── اتجاه التأثير ─────
def test_tone_rules():
    assert impact.tone("dxy", 0.5) == "bear" and impact.tone("dxy", -0.5) == "bull" and impact.tone("dxy", 0.05) == "flat"
    assert impact.tone("y10", 5) == "bear" and impact.tone("y10", -5) == "bull"
    assert impact.tone("oil", 1.0) == "bear" and impact.tone("oil", -1.0) == "bull"
    assert impact.tone("vix", 10) == "bear" and impact.tone("vix", -10) == "bull"
    assert impact.tone("net_liq", 1.0) == "bull" and impact.tone("net_liq", -1.0) == "bear"
    assert impact.tone("unknown", 5) == "flat" and impact.tone("dxy", None) == "flat"


def test_dollar_rise_is_never_supportive():
    """الخطأ المبلّغ عنه: ارتفاع الدولار كان يظهر ضمن «الداعمة» لأن حركته صغيرة (هادئة)."""
    for chg in (0.2, 0.3, 0.6, 1.2):
        p, e, x = demo()
        p["dxy"]["chg1"] = chg
        for k in ("y10", "oil"):
            p[k]["chg1"], p[k]["diff1"] = 0.0, 0.0
        rep, v = view_for(p)
        assert not any("الدولار" in s for s in v["pressures"]["bullish"]), (chg, v["pressures"])
        assert any("الدولار" in s for s in v["pressures"]["bearish"]), (chg, v["pressures"])


def test_falling_dollar_yield_oil_are_supportive():
    p, e, x = demo()
    p["dxy"]["chg1"] = -0.5
    p["y10"]["diff1"] = -0.08
    p["oil"]["chg1"] = -2.0
    rep, v = view_for(p)
    bull = " ".join(v["pressures"]["bullish"])
    assert "الدولار" in bull and "عائد 10 سنوات" in bull and "النفط" in bull
    tones = {d["key"]: d["tone"] for d in v["drivers"]}
    assert tones["dxy"] == tones["y10"] == tones["oil"] == "bull"


def test_calm_is_not_support():
    p, e, x = demo()
    p["dxy"]["chg1"] = 0.02                  # هادئ جداً
    rep, v = view_for(p)
    assert not any("الدولار" in s for s in v["pressures"]["bullish"])
    assert "calm" in v["pressures"]


def test_liquidity_meaning_and_tone():
    inj = impact.liquidity_view({"net_bn": 5100, "chg_pct": 2.0, "as_of": "2026-10-01"})
    wd = impact.liquidity_view({"net_bn": 5100, "chg_pct": -2.0, "as_of": "2026-10-01"})
    fl = impact.liquidity_view({"net_bn": 5100, "chg_pct": 0.1, "as_of": "2026-10-01"})
    assert inj["tone"] == "bull" and inj["word"] == "ضخّ" and "يدعم" in inj["meaning"]
    assert wd["tone"] == "bear" and wd["word"] == "سحب" and "يضغط" in wd["meaning"]
    assert fl["tone"] == "flat" and impact.liquidity_view(None) is None


def test_regime_and_intensity():
    m = {"pillars": [{"key": "inflation", "s": 0.5}, {"key": "labor", "s": -0.5}]}
    assert impact.regime(m)["key"] == "stagflation"
    m = {"pillars": [{"key": "inflation", "s": 0.5}, {"key": "labor", "s": 0.5}]}
    assert impact.regime(m)["key"] == "overheating"
    assert impact.regime({"pillars": []}) is None
    weak = impact.intensity([{"strength": 1.0, "tone": "bear"}])
    strong = impact.intensity([{"strength": 4.0, "tone": "bear"}, {"strength": 4.0, "tone": "bull"}])
    assert strong > weak and impact.intensity([]) == 0.0 and impact.intensity([{"strength": 5, "tone": "flat"}]) == 0.0


# ───── مراقب السلامة ─────
def test_wrong_unit_dropped_not_substituted():
    p, e, x = demo()
    p["y10"]["last"] = 41.0
    clean, issues = safety.check_inputs(p, e, x["fred"], NOW)
    assert "y10" not in clean                       # استُبعد، لم يُستبدل برقم مفترض
    i = next(i for i in issues if i["key"] == "y10")
    assert i["sev"] == safety.CRITICAL and "rates" in i["affects"]


def test_stale_and_abnormal_jump_tiers():
    p, e, x = demo()
    p["gold"]["bar_time"] = (NOW - timedelta(days=9)).isoformat()
    clean, issues = safety.check_inputs(p, e, x["fred"], NOW)
    assert "gold" not in clean and any(i["code"] == "stale" and i["sev"] == safety.MAJOR for i in issues)
    p, e, x = demo()
    p["vix"]["chg1"] = 100.0                        # بين الحدين: حدث حقيقي محتمل → تحذير فقط، لا استبعاد
    clean, issues = safety.check_inputs(p, e, x["fred"], NOW)
    assert "vix" in clean and any(i["code"] == "big_jump" and i["sev"] == safety.WARN for i in issues)
    p["vix"]["chg1"] = 400.0                        # شبه مستحيل → يُستبعد
    clean, issues = safety.check_inputs(p, e, x["fred"], NOW)
    assert "vix" not in clean and any(i["sev"] == safety.CRITICAL for i in issues)


def test_futures_vs_spot_divergence():
    p, e, x = demo()
    p["es"]["chg1"], p["spy"]["chg1"] = -3.0, 0.2
    clean, issues = safety.check_inputs(p, e, x["fred"], NOW)
    assert "es" not in clean and any(i["code"] == "futures_spot" for i in issues)
    p, e, x = demo()
    p["es"]["chg1"], p["spy"]["chg1"] = -1.2, 0.0
    clean, issues = safety.check_inputs(p, e, x["fred"], NOW)
    assert "es" in clean and any(i["code"] == "futures_spot" and i["sev"] == safety.WARN for i in issues)


def test_events_sanity_and_expired_lists():
    p, e, x = demo()
    bad = [dict(e[0], actual="4.5%", time=NOW + timedelta(hours=5))]
    _, issues = safety.check_inputs(p, bad + bad, x["fred"], NOW)
    codes = {i["code"] for i in issues}
    assert "future_actual" in codes and "dup_events" in codes
    _, issues = safety.check_inputs(p, e, x["fred"], datetime(2027, 3, 1, tzinfo=timezone.utc), {2026}, {2026})
    assert {"calendar_expired", "fomc_expired"} <= {i["code"] for i in issues}
    _, issues = safety.check_inputs(p, [], x["fred"], NOW)
    assert any(i["code"] == "no_calendar" and i["sev"] == safety.MAJOR for i in issues)


def test_incomplete_assessment_state():
    comps = {"volatility": (3.0, ""), "events": (2.0, ""), "calendar": (1.5, "")}
    issues, cov = safety.check_result(comps, list(comps), c.BASE_WEIGHTS, 2)
    assert cov < 0.6 and any(i["code"] == "coverage" and i["sev"] == safety.MAJOR for i in issues)
    assert safety.state_of(issues, cov) == "incomplete"
    assert safety.confidence(issues, cov)["label"] == "منخفضة"
    full, cov2 = safety.check_result({k: (2.0, "") for k in c.BASE_WEIGHTS}, list(c.BASE_WEIGHTS), c.BASE_WEIGHTS, 2)
    assert cov2 == 1.0 and safety.state_of(full, cov2) == "ok" and safety.confidence(full, cov2)["label"] == "مرتفعة"


def test_contradiction_and_double_count_detected():
    comps = {k: (2.0, "") for k in c.BASE_WEIGHTS}
    comps["geopolitics"] = (9.5, "")
    issues, _ = safety.check_result(comps, list(comps), c.BASE_WEIGHTS, 2)
    assert any(i["code"] == "contradiction" for i in issues)
    comps = {k: (2.0, "") for k in c.BASE_WEIGHTS}
    comps["rates"] = comps["front_end"] = (8.0, "")
    issues, _ = safety.check_result(comps, list(comps), c.BASE_WEIGHTS, 5)
    assert any(i["code"] == "double_count" for i in issues)


def test_dominant_component_floor_in_report():
    p, e, x = demo()
    # كل شيء هادئ ما عدا توتر سوقي شديد (ذهب+نفط+VIX+ES معاً) → المتوسط وحده كان سيخفّف
    calm = {"es": {"last": 5900, "chg1": -0.9, "chg3": 0, "chg5": 0, "diff1": 0, "bar_time": NOW.isoformat(), "vol_ratio": 1.0}}
    comps = {k: (1.5, "") for k in c.BASE_WEIGHTS}
    comps["geopolitics"] = (10.0, "")
    floor, key = c.dominant_floor(comps, list(comps))
    assert floor == 6 and key == "geopolitics"
    comps["geopolitics"] = (8.2, "")
    assert c.dominant_floor(comps, list(comps))[0] == 5
    comps["geopolitics"] = (6.0, "")
    assert c.dominant_floor(comps, list(comps))[0] is None
    comps = {k: (1.5, "") for k in c.BASE_WEIGHTS}
    comps["events"] = (9.0, "")                       # الأحداث/التقويم لا ترفع الحد الأدنى
    assert c.dominant_floor(comps, list(comps))[0] is None


def test_report_has_safety_fields_and_blocks_bad_input():
    p, e, x = demo()
    p["y10"]["last"] = 41.0
    rep = c.build_report(p, e, NOW, [], x)
    assert rep["safety"]["state"] in ("critical", "major", "warn", "ok") and rep["safety"]["issues"]
    assert any("خلل حرج" in s for s in rep["problems"])
    assert not any(cmp["key"] == "rates" for cmp in rep["risk"]["components"])
    for k in ("drivers", "regime", "intensity", "confidence", "liquidity"):
        assert k in rep


# ───── الصحة ─────
def test_health_never_green_without_check():
    st = {}
    v = health.build(None, [], NOW, st, error="boom")
    assert v["state"] == "unchecked" and v["label"] == "لم يُجرَ الفحص" and v["checked_at"]
    v2 = health.build({"error": "x"}, [], NOW, st)
    assert v2["state"] == "incomplete"


def test_health_view_and_source_history():
    p, e, x = demo()
    rep = c.build_report(p, e, NOW, [], x)
    st = {}
    v = health.build(rep, e, NOW, st)
    assert v["checked_at"] == NOW.isoformat() and v["sources_total"] == 8
    assert v["state"] in ("ok", "warn", "incomplete", "major")
    cal = next(s for s in v["sources"] if s["key"] == "calendar")
    assert cal["ok"] and cal["ok_at"] == NOW.isoformat()
    later = NOW + timedelta(minutes=15)
    v2 = health.build(rep, [], later, st)                     # التقويم غاب
    cal2 = next(s for s in v2["sources"] if s["key"] == "calendar")
    assert not cal2["ok"] and cal2["ok_at"] == NOW.isoformat()  # آخر نجاح محفوظ
    assert v2["state"] != "ok"


def test_alert_counters_and_notify_cooldown():
    st = {}
    health.bump(st, "sent", NOW)
    health.bump(st, "suppressed", NOW, 2)
    assert st["stats"]["sent"] == 1 and st["stats"]["suppressed"] == 2
    health.bump(st, "sent", NOW + timedelta(days=1))
    assert st["stats"]["sent"] == 1 and "suppressed" not in st["stats"]     # يوم جديد
    bad = {"state": "major", "issues": [{"sev": "major", "sev_ar": "خلل مؤثر", "msg": "m1"}]}
    assert health.should_notify(bad, st, NOW) is True
    assert health.should_notify(bad, st, NOW + timedelta(hours=1)) is False
    assert health.should_notify(bad, st, NOW + timedelta(hours=13)) is True
    assert health.should_notify({"state": "warn", "issues": []}, st, NOW) is False


# ───── المزادات والتصنيف اليومي ─────
def _auc(typ, term, date="2026-10-08", y=4.1, btc=2.6):
    return {"type": typ, "term": term, "years": extras._term_years(term), "weeks": extras._term_weeks(term), "date": date, "yield": y, "btc": btc}


def test_auction_names_include_term_and_type():
    assert "10 سنوات" in events_ctx.auction_name("10-y Bond Auction") and "Notes" in events_ctx.auction_name("10-y Bond Auction")
    assert "30 سنوات" in events_ctx.auction_name("30-y Bond Auction") and "Bonds" in events_ctx.auction_name("30-y Bond Auction")
    assert "TIPS" in events_ctx.auction_name("10-y TIPS Auction")
    assert "13" in events_ctx.auction_name("13-Week Bill Auction") and "Bills" in events_ctx.auction_name("13-Week Bill Auction")
    d = events_ctx.describe({"title": "30-y Bond Auction", "impact": "Low", "time": NOW}, "20:00")
    assert d["kind"] == "auction" and "30 سنوات" in d["name"]


def test_auction_reopening_and_type_matching():
    t = datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc)
    aucs = [_auc("Note", "9-Year 11-Month", y=4.20, btc=2.51), _auc("TIPS", "9-Year 11-Month", y=1.9, btc=2.9),
            _auc("Bond", "29-Year 10-Month", y=4.8, btc=2.3), _auc("Bill", "13-Week", y=3.9, btc=3.1)]
    assert extras.auction_actual("10-y Bond Auction", t, aucs) == "4.200|2.51"          # إعادة الإصدار تُطابَق
    assert extras.auction_actual("10-y TIPS Auction", t, aucs) == "1.900|2.90"          # TIPS لا يختلط بالاسمي
    assert extras.auction_actual("30-y Bond Auction", t, aucs) == "4.800|2.30"
    assert extras.auction_actual("13-Week Bill Auction", t, aucs) == "3.900|3.10"
    assert extras.auction_actual("20-y Bond Auction", t, aucs) == ""                     # لا مزاد 20 سنة اليوم
    assert extras.auction_actual("10-y Bond Auction", t + timedelta(days=1), aucs) == ""   # تاريخ آخر


def test_auction_failure_reason_visible():
    evs = [{"title": "10-y Bond Auction", "impact": "Low", "time": NOW - timedelta(hours=3), "forecast": "", "previous": "", "actual": ""}]

    def boom():
        raise OSError("blocked")
    extras.apply_actuals(evs, NOW, None, lambda: None, boom)
    assert "TreasuryDirect" in evs[0]["actual_note"] and "OSError" in evs[0]["actual_note"]
    evs[0]["actual_note"] = ""
    extras.apply_actuals(evs, NOW, None, lambda: None, lambda: [])
    assert "لم يعد" in evs[0]["actual_note"] or "تعذّر" in evs[0]["actual_note"]


def _evt(title, t, impact="High", actual=""):
    return {"title": title, "impact": impact, "time": t, "forecast": "220K", "previous": "219K", "actual": actual}


def test_today_vs_yesterday_split_by_baghdad_date():
    """الحالة المبلّغ عنها: طلبات إعانة البطالة صدرت اليوم 15:30 بغداد ولا يجوز أن تُحسب «أمس»."""
    claims_today = _evt("Unemployment Claims", datetime(2026, 10, 8, 12, 30, tzinfo=timezone.utc), actual="223K")
    claims_prev = _evt("Unemployment Claims", datetime(2026, 10, 1, 12, 30, tzinfo=timezone.utc), actual="218K")   # خارج 24س
    yesterday = _evt("10-y Bond Auction", datetime(2026, 10, 7, 17, 0, tzinfo=timezone.utc), "Low")
    yesterday2 = _evt("Core PPI m/m", datetime(2026, 10, 7, 13, 30, tzinfo=timezone.utc), "High", "0.2%")
    p, e, x = demo()
    rep = c.build_report(p, e, NOW, [], x)
    v = dashboard.build_view(rep, [claims_today, claims_prev, yesterday, yesterday2], NOW)
    past = v["events_past"]
    by_day = {}
    for g in past:
        by_day.setdefault(g["day"], []).append(g["kind"])
    assert "unemp" in by_day["اليوم"] and "unemp" not in by_day.get("أمس", [])
    assert "auction" in by_day["أمس"] and "infl" in by_day["أمس"]
    assert [g["day"] for g in past] == sorted([g["day"] for g in past], key=lambda d: 0 if d == "اليوم" else 1)


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    n = 0
    for t in TESTS:
        t()
        n += 1
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({n})")
