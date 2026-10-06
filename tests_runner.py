#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات المشغّل (دون إنترنت): python tests_runner.py"""
import os
import tempfile
from datetime import datetime, timedelta, timezone

import calibrate
import collector as c
import runner as r
from tests import calm_prices

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def ev_raw(title, impact, hours, actual="", forecast="0.3%", previous="0.2%"):
    return {"title": title, "country": "USD", "impact": impact, "actual": actual,
            "date": (NOW + timedelta(hours=hours)).isoformat(), "forecast": forecast, "previous": previous}


def series(prices_by_minute_back):
    """{دقائق للخلف: سعر} -> سلسلة مرتبة زمنياً."""
    return sorted(((NOW - timedelta(minutes=m), p) for m, p in prices_by_minute_back.items()))


def calm_intraday():
    flat = lambda p: series({0: p, 30: p, 65: p, 90: p})
    return {"es": flat(5900), "vix": flat(15), "oil": flat(70), "gold": flat(2650)}


def shock_intraday():
    return {
        "es": series({0: 5840, 65: 5900}),      # -1.02%
        "vix": series({0: 17.0, 65: 15.0}),     # +13%
        "oil": series({0: 71.5, 65: 70.0}),     # +2.1%
        "gold": series({0: 2675, 65: 2650}),    # +0.94%
    }


class Box:
    def __init__(self):
        self.msgs = []

    def __call__(self, text):
        self.msgs.append(text)


def deps(raw_events, intraday, headlines=None):
    return {
        "calendar": lambda now: c.parse_events(raw_events),
        "prices": lambda now: (calm_prices(), []),
        "intraday": lambda now: intraday,
        "headlines": lambda now: headlines or [],
        "history_path": os.path.join(tempfile.mkdtemp(), "history.csv"),
        "docs_dir": tempfile.mkdtemp(),
    }


def new_state():
    return {"seen_events": [], "last_shock": None}


def test_parse_and_surprise():
    assert r.parse_num("220K") == 220000 and r.parse_num("4.50%") == 4.5 and r.parse_num("-0.3%") == -0.3
    assert r.parse_num("") is None and r.parse_num("n/a") is None
    mk = lambda a, f: {"actual": a, "forecast": f}
    assert r.surprise(mk("0.4%", "0.3%")) == "أعلى من المتوقع"
    assert r.surprise(mk("0.2%", "0.3%")) == "أدنى من المتوقع"
    assert r.surprise(mk("0.3%", "0.3%")) == "مطابق للمتوقع"
    assert r.surprise(mk("", "0.3%")) is None


def test_due_releases_filters():
    raw = [
        ev_raw("Core PCE", "High", -0.5, actual="0.4%"),          # صدر قبل نصف ساعة ✔
        ev_raw("Old Data", "High", -6, actual="0.4%"),             # أقدم من النافذة ✘
        ev_raw("No Actual", "High", -0.5, actual=""),              # بلا نتيجة ✘
        ev_raw("Medium Data", "Medium", -0.5, actual="1"),         # ليس عالي التأثير ✘
        ev_raw("Future", "High", 2, actual=""),                    # لم يصدر ✘
    ]
    ev = c.parse_events(raw)
    got = r.due_releases(ev, NOW, new_state())
    assert [e["title"] for e in got] == ["Core PCE"]
    st = new_state()
    st["seen_events"].append(r.event_id(got[0]))
    assert r.due_releases(ev, NOW, st) == []


def test_change_over_and_shock():
    s = series({0: 101, 65: 100})
    assert abs(r.change_over(s, 60) - 1.0) < 1e-9
    assert r.change_over(series({0: 101}), 60) is None             # لا بيانات كافية
    hit, sig = r.detect_shock({"es": -1.02, "vix": 13, "oil": 2.1, "gold": 0.94})
    assert hit and len(sig) == 4
    hit, _ = r.detect_shock({"es": -0.2, "vix": 1, "oil": 0.3, "gold": 0.1})
    assert not hit
    hit, _ = r.detect_shock({"es": -1.2, "vix": 8, "oil": 0, "gold": 0})   # إشارتان مع هبوط ES حاد
    assert hit
    hit, _ = r.detect_shock({"es": -0.7, "vix": 8, "oil": 0, "gold": 0})   # إشارتان بلا هبوط حاد ✘
    assert not hit


def test_auto_release_sent_once():
    box, st = Box(), new_state()
    d = deps([ev_raw("Core PCE Price Index m/m", "High", -0.5, actual="0.4%")], calm_intraday())
    assert r.run_auto(NOW, st, box, d) == 1
    assert "أعلى من المتوقع" in box.msgs[0] and "Core PCE" in box.msgs[0]
    assert r.run_auto(NOW + timedelta(minutes=15), st, box, d) == 0     # لا تكرار
    assert len(box.msgs) == 1


def test_auto_shock_and_cooldown():
    box, st = Box(), new_state()
    d = deps([], shock_intraday(), headlines=["Missile strike reported near Gulf shipping lane"])
    assert r.run_auto(NOW, st, box, d) == 1
    assert "حركة سوق غير معتادة" in box.msgs[0] and "Missile strike" in box.msgs[0]
    assert "ليس تحليلاً مؤكداً" in box.msgs[0]
    assert r.run_auto(NOW + timedelta(minutes=15), st, box, d) == 0     # فترة تهدئة 3 ساعات
    later = NOW + timedelta(hours=4)
    d2 = deps([], {k: [(t + timedelta(hours=4), p) for t, p in v] for k, v in shock_intraday().items()})
    assert r.run_auto(later, st, box, d2) == 1


def rally_oil_drop_intraday():
    return {
        "es": series({0: 5990, 65: 5925, 185: 5900}),     # +1.1% خلال ساعة
        "vix": series({0: 14.0, 65: 15.0, 185: 15.5}),
        "oil": series({0: 67.0, 65: 69.5, 185: 71.0}),    # -3.6% خلال ساعة
        "gold": series({0: 2650, 65: 2652, 185: 2650}),
    }


def test_big_up_move_with_oil_drop_alerts():
    box, st = Box(), new_state()
    d = deps([], rally_oil_drop_intraday(), headlines=["Oil slides as OPEC signals more supply"])
    assert r.run_auto(NOW, st, box, d) == 1
    m = box.msgs[0]
    assert "حركة كبيرة" in m and "النفط يهبط والأسهم تصعد" in m and "OPEC" in m
    assert "ليست تأكيداً للسبب" in m
    assert r.run_auto(NOW + timedelta(minutes=15), st, box, d) == 0     # تهدئة ساعتان لنفس الاتجاه
    assert len(box.msgs) == 1


def test_driver_alone_needs_bigger_move():
    it = calm_intraday()
    it["oil"] = series({0: 68.5, 65: 70.0, 185: 71.0})            # -2.1%: لا يكفي وحده (يلزم 3%)
    assert r.run_auto(NOW, new_state(), Box(), deps([], it)) == 0
    it["oil"] = series({0: 67.0, 65: 70.0, 185: 71.0})            # -4.3%: كافٍ حتى لو ES ثابت
    box = Box()
    assert r.run_auto(NOW, new_state(), box, deps([], it)) == 1
    assert "عامل مؤثر يتحرك بقوة" in box.msgs[0] and "النفط" in box.msgs[0]


def test_yields_move_detected_with_es():
    it = calm_intraday()
    it["y10"] = series({0: 4.40, 65: 4.30, 185: 4.28})            # +10bp
    it["es"] = series({0: 5870, 65: 5900, 185: 5905})             # -0.5% مع صعود العوائد
    box = Box()
    assert r.run_auto(NOW, new_state(), box, deps([], it)) == 1
    assert "عائد 10 سنوات" in box.msgs[0] and "تسعير الفائدة" in box.msgs[0]


def test_calm_market_sends_nothing():
    box = Box()
    assert r.run_auto(NOW, new_state(), box, deps([], calm_intraday())) == 0 and not box.msgs


def test_stale_data_is_not_a_shock():
    stale = {k: [(t - timedelta(hours=10), p) for t, p in v] for k, v in shock_intraday().items()}
    box = Box()
    assert r.run_auto(NOW, new_state(), box, deps([], stale)) == 0


def test_preopen_message():
    box = Box()
    d = deps([ev_raw("Federal Funds Rate", "High", 3, forecast="4.50%", previous="4.75%")], calm_intraday())
    r.run_preopen(NOW, new_state(), box, d)
    m = box.msgs[0]
    assert "قبل افتتاح السوق" in m and "المخاطرة:" in m
    assert "18:00" in m                       # 15:00 UTC = 18:00 بغداد
    assert "Federal Funds Rate" in m and "4.50%" in m


def test_calendar_failure_does_not_crash():
    box = Box()
    d = deps([], calm_intraday())
    d["calendar"] = lambda now: (_ for _ in ()).throw(RuntimeError("شبكة"))
    r.run_preopen(NOW, new_state(), box, d)
    assert "تعذّر جلب التقويم" in box.msgs[0]


def test_preopen_includes_context_and_news():
    box = Box()
    d = deps([ev_raw("Federal Funds Rate", "High", 3)], calm_intraday())
    p = calm_prices()
    p["nq"] = {"last": 20500, "chg1": 0.4, "chg3": 0, "chg5": 0, "diff1": 0, "bar_time": NOW.isoformat()}
    d["prices"] = lambda now: (p, [])
    d["news"] = lambda topic, now: {"banks": ["Goldman raises S&P 500 year-end target"],
                                    "companies": ["Nvidia faces new export probe"],
                                    "policy": []}[topic]
    d["cot"] = lambda now: {"date": "2026-10-06", "net_pct": 4.0, "oi": 2000000}
    d["fred"] = lambda now: ({"t10y2y": [("a", 0.1), ("b", 0.2)]}, [])
    d["earnings"] = lambda now: [("NVDA", NOW.date().isoformat())]
    r.run_preopen(NOW, new_state(), box, d)
    m = box.msgs[0]
    assert "السياق:" in m and "تمركز المضاربين" in m and "منحنى 2-10" in m
    assert "عناوين عن توقعات البنوك" in m and "Goldman raises" in m
    assert "عناوين الشركات الكبرى" in m and "Nvidia faces" in m
    assert "عناوين السياسة" not in m                      # محور فارغ لا يظهر
    assert "أرباح خلال 48 ساعة: NVDA" in m
    assert "آخر شمعة يومية" in m and "دون تفسير" in m


def test_news_or_extras_failure_is_soft():
    box = Box()
    d = deps([], calm_intraday())
    d["news"] = lambda topic, now: (_ for _ in ()).throw(RuntimeError("شبكة"))
    d["cot"] = lambda now: (_ for _ in ()).throw(ValueError("صيغة تغيّرت"))
    d["fred"] = lambda now: (_ for _ in ()).throw(RuntimeError("حجب"))
    r.run_preopen(NOW, new_state(), box, d)
    m = box.msgs[0]
    assert "المخاطرة:" in m and "تعذّر جلب cot" in m and "تعذّر FRED" in m


def test_premium_provider_wiring():
    box = Box()
    d = deps([], calm_intraday())
    d["premium"] = {"news_ai": lambda now: (9, "تصعيد حاد يهدد الإمدادات"),
                    "gamma": lambda now: (_ for _ in ()).throw(RuntimeError("انتهى الاشتراك"))}
    r.run_preopen(NOW, new_state(), box, d)
    m = box.msgs[0]
    assert "تعذّر مزوّد gamma" in m and "المخاطرة:" in m
    rep = r.full_report(NOW, [], d)
    assert "news_ai" in [x["key"] for x in rep["risk"]["components"]]
    assert "gamma" not in [x["key"] for x in rep["risk"]["components"]]


def test_history_log_and_outcome_fill():
    path = os.path.join(tempfile.mkdtemp(), "history.csv")
    rep = {"risk": {"score": 7, "level": "عالية"}}
    bars = [("2026-10-07", 5950.0, 5850.0, 5900.0)]       # NOW = 7 أكتوبر
    pr = {"es": {"last": 5900.0, "bars": bars}}
    r.update_history(rep, pr, NOW, path)                       # يُسجَّل اليوم بلا نتيجة بعد
    rows = r.read_history(path)
    assert len(rows) == 1 and rows[0]["score"] == "7" and rows[0]["outcome_range_pct"] == ""
    r.update_history(rep, pr, NOW, path)                       # لا تكرار لليوم نفسه
    assert len(r.read_history(path)) == 1
    nxt = NOW + timedelta(days=1)
    r.update_history({"risk": {"score": 3, "level": "منخفضة"}}, {"es": {"last": 5910.0, "bars": bars}}, nxt, path)
    rows = r.read_history(path)
    assert len(rows) == 2 and abs(float(rows[0]["outcome_range_pct"]) - 1.695) < 0.01
    assert rows[1]["outcome_range_pct"] == ""
    r.update_history({"error": "x"}, pr, nxt + timedelta(days=1), path)   # تقرير فاشل لا يُسجَّل
    assert len(r.read_history(path)) == 2


def test_calibrate_summary():
    low = [(2, 0.5)] * 6 + [(3, 0.6)] * 6
    high = [(7, 1.4)] * 5 + [(9, 2.2)] * 5
    out = calibrate.summarize(low + high)
    assert "العينة صغيرة" not in out and "منخفضة 0-3: 12 أيام" in out and "قصوى 9-10: 5 أيام" in out
    assert "الارتباط" in out
    assert "العينة صغيرة" in calibrate.summarize(low[:3])


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({len(tests)})")
