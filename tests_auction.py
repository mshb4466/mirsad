#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات سياق المزاد (دون إنترنت): python tests_auction.py"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import auction as a

ET = ZoneInfo("America/New_York")


def mk(day, hh, mm, o, h, l, c, v=1000):
    t = datetime(day.year, day.month, day.day, hh, mm, tzinfo=ET).astimezone(timezone.utc)
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}


def synthetic(prior_day, today, on_drift=+10.0):
    """جلسة سابقة تتركز حجمها حول 5900 ثم ليل يرتفع."""
    bars = []
    t = datetime(prior_day.year, prior_day.month, prior_day.day, 9, 30, tzinfo=ET)
    i = 0
    while t.hour < 16:
        base = 5900 + (3 if (i // 10) % 2 else -3)
        heavy = 5 if 5896 <= base <= 5904 else 1
        bars.append({"t": t.astimezone(timezone.utc), "o": base, "h": base + 4, "l": base - 4, "c": base + 1, "v": 1000 * heavy})
        t += timedelta(minutes=5)
        i += 1
    # ليل: من 18:00 ET (اليوم السابق) حتى 08:00 ET
    t = datetime(prior_day.year, prior_day.month, prior_day.day, 18, 0, tzinfo=ET)
    end = datetime(today.year, today.month, today.day, 8, 0, tzinfo=ET)
    base0 = bars[-1]["c"]
    n = int((end - t).total_seconds() // 300)
    k = 0
    while t < end:
        px = base0 + on_drift * k / n
        bars.append({"t": t.astimezone(timezone.utc), "o": px, "h": px + 1, "l": px - 1, "c": px, "v": 300})
        t += timedelta(minutes=5)
        k += 1
    return bars


from datetime import date
PRIOR, TODAY = date(2026, 10, 6), date(2026, 10, 7)
NOW = datetime(2026, 10, 7, 8, 0, tzinfo=ET).astimezone(timezone.utc)


def test_volume_profile_value_area():
    p = a.volume_profile(synthetic(PRIOR, TODAY)[:78])
    assert 5896 <= p["poc"] <= 5905 and p["val"] < p["poc"] < p["vah"]
    assert p["vah"] - p["val"] < 20                               # القيمة ضيقة لأن الحجم متركز
    flat = a.volume_profile([{"l": 100.0, "h": 101.0, "v": 1000}])
    assert flat["val"] <= flat["poc"] <= flat["vah"]
    assert a.volume_profile([]) is None


def test_session_split():
    bars = synthetic(PRIOR, TODAY)
    prior, on, today = a.split_sessions(bars, NOW)
    assert today == TODAY and len(prior) == 78 and len(on) > 100
    assert all(a.et(b["t"]).date() == PRIOR for b in prior)
    assert a.et(on[0]["t"]).time().hour == 18 and a.et(on[-1]["t"]).hour < 9


def test_context_above_value_and_gap():
    ctx = a.context(synthetic(PRIOR, TODAY, on_drift=+30.0), NOW, vix=18.0)
    assert ctx["location"] == "above_value" and ctx["gap"]["points"] > 20
    assert ctx["outside_prior_range"]
    assert ctx["overnight"]["inventory"] > 0.7 and "شرائي" in ctx["overnight"]["inventory_label"]
    assert ctx["expected"]["sigma_pts"] > 0 and 55 < ctx["expected"]["sigma_pts"] < 80      # 5930*0.18/√252 ≈ 67
    assert any("80%" in x for x in ctx["playbook"])


def test_context_inside_value():
    ctx = a.context(synthetic(PRIOR, TODAY, on_drift=-4.0), NOW)
    assert ctx["location"] == "inside_value" and any("توازن" in x for x in ctx["playbook"])
    assert "expected" not in ctx


def test_not_enough_data():
    assert a.context([], NOW) is None
    assert a.context(synthetic(PRIOR, TODAY)[:10], NOW) is None


def test_tilt():
    bull = {"gap_pct": 0.5, "clv": 0.9, "vix_chg1": -6, "nq_minus_es": 0.4, "dxy_chg1": -0.4, "chg5": 2}
    bear = {"gap_pct": -0.5, "clv": 0.1, "vix_chg1": 8, "nq_minus_es": -0.4, "dxy_chg1": 0.5, "chg5": -2}
    sb, _ = a.tilt(bull)
    se, _ = a.tilt(bear)
    assert sb > 0.5 and se < -0.5 and a.tilt_label(sb)[1] == "▲" and a.tilt_label(se)[1] == "▼"
    assert a.tilt({"gap_pct": 0.1, "clv": 0.5})[0] is None                       # أقل من 3 عوامل
    part, d = a.tilt({"gap_pct": 0.3, "vix_chg1": -3, "chg5": 1})
    assert part > 0 and set(d) == {"gap", "vix", "trend"}


def test_lines_render():
    ctx = a.context(synthetic(PRIOR, TODAY, on_drift=+30.0), NOW, vix=18.0)
    t = a.tilt({"gap_pct": 0.4, "clv": 0.8, "vix_chg1": -5, "chg5": 1.5})
    txt = "\n".join(a.lines(ctx, t))
    assert "سياق المزاد" in txt and "VAH" in txt and "الميل السياقي" in txt and "لم يُثبت" in txt
    assert a.lines(None, (None, {})) == []


def test_preopen_message_integration():
    import runner as r
    from tests_runner import Box, calm_intraday, deps
    box = Box()
    d = deps([], calm_intraday())
    d["es5m"] = lambda now: synthetic(PRIOR, TODAY, on_drift=+30.0)
    when = NOW
    r.run_preopen(when, {"seen_events": [], "last_shock": None}, box, d)
    m = box.msgs[0]
    assert "سياق المزاد" in m and "VAH" in m and "المدى المتوقع" in m
    box2 = Box()
    d["es5m"] = lambda now: (_ for _ in ()).throw(RuntimeError("حجب"))
    r.run_preopen(when, {"seen_events": [], "last_shock": None}, box2, d)
    assert "تعذّر سياق المزاد" in box2.msgs[0] and "المخاطرة:" in box2.msgs[0]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({len(tests)})")
