# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone
import events_ctx, dashboard, runner

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def ev(title, impact, h, f="", p="", a=""):
    return {"title": title, "impact": impact, "time": NOW + timedelta(hours=h), "forecast": f, "previous": p, "actual": a}


EVS = [ev("Crude Oil Inventories", "Low", 5, "-1.2M", "3.7M"), ev("10-y Bond Auction", "Low", 6, "4.1|2.5", "4.0|2.6"),
       ev("FOMC Member Speaks", "Low", 7), ev("FOMC Meeting Minutes", "Medium", 6.5), ev("FOMC Member Barr Speaks", "Low", 9.5),
       ev("Building Permits", "Low", 3)]


def test_relevance_and_grouping():
    rep = {"error": None}
    view = dashboard.build_view({"risk": {"score": 3, "level": "x", "main_reason": "", "advice": "", "components": []}}, EVS, NOW)
    kinds = [g["kind"] for g in view["events"]]
    # التجميع داخل اليوم نفسه (بتوقيت بغداد): كلمة بعد منتصف الليل تظهر تحت «غداً» لا «اليوم»
    assert kinds.count("speech") == 2, kinds
    assert "oil" in kinds and "auction" in kinds and "housing" not in kinds
    sps = [g for g in view["events"] if g["kind"] == "speech"]
    assert {g["day"] for g in sps} == {"اليوم", "غداً"}
    today = next(g for g in sps if g["day"] == "اليوم")
    assert len(today["items"]) == 2 and len(today["scenarios"]) == 3
    assert all(g["day"] == "اليوم" for g in view["events"] if g["kind"] in ("oil", "auction"))


def test_ratio_auction_polarity():
    d = events_ctx.describe(ev("10-y Bond Auction", "Low", 1, "2.5", "2.6"), "20:00")
    assert d["scenarios"][0]["es"] == "bull"
    d2 = events_ctx.describe(ev("10-y Bond Auction", "Low", 1, "4.1%", "4.0%"), "20:00")
    assert d2["scenarios"][0]["es"] == "bear"


def test_preopen_dedupes_scenarios():
    rep = {"risk": {"score": 3, "emoji": "🟢", "level": "x", "main_reason": "", "advice": "", "components": [], "weights_note": []}, "info": {}, "problems": []}
    msg = runner.format_preopen(rep, EVS, NOW)
    assert msg.count("متشددة=ضغط") == 1


def test_alert_persist_and_pulse():
    st = runner.load_state("/nonexistent.json")
    mv = {"keys": ["hyg"], "alone": ["hyg"], "stats": {}, "ch": {"es": (0.1, 0.2), "hyg": (-0.4, -0.5), "y30": (5.0, 8.0)}}
    runner.push_alert(st, runner.alert_from_move(mv, ["h1"], NOW), NOW)
    runner.push_alert(st, runner.alert_from_move(mv, [], NOW - timedelta(hours=30) + timedelta(hours=31)), NOW)
    assert len(st["alerts"]) == 2 and st["alerts"][0]["rows"][0]["lead"] in (True, False)
    old = {"t": (NOW - timedelta(hours=30)).isoformat()}
    st["alerts"].append(old)
    runner.push_alert(st, runner.alert_from_move(mv, [], NOW), NOW)
    assert all(a["t"] != old["t"] for a in st["alerts"])


def test_actuals_filled_and_speech_tone():
    import extras
    evs = [ev("Crude Oil Inventories", "Low", -4, "-1.2M", "3.7M"), ev("10-y Bond Auction", "Low", -6, "4.1|2.5", "4.0|2.6")]
    day = (NOW - timedelta(hours=6)).astimezone(extras.ET).date().isoformat()
    n = extras.apply_actuals(evs, NOW, None, lambda: ("2026-10-02", -2.4), lambda: [{"type": "Note", "term": "9-Year 11-Month", "years": 10, "weeks": None, "date": day, "yield": 4.062, "btc": 2.55}])
    assert n == 2 and evs[0]["actual"] == "-2.4M" and evs[1]["actual"] == "4.062|2.55"
    assert extras.apply_actuals([ev("Crude Oil Inventories", "Low", -4)], NOW, None, lambda: None, lambda: []) == 0
    assert events_ctx.speech_outcome(["Powell: no rush to cut, inflation remains sticky"], {"y10": 3.0, "dxy": 0.1})[0] == "above"
    assert events_ctx.speech_outcome([], {"y10": -3.0, "dxy": -0.1})[0] == "below"
    assert events_ctx.speech_outcome([], {})[0] == "inline"


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("✔", k)
    print(f"نجحت كل الاختبارات ({n})")
