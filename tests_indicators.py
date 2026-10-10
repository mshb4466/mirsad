# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone
import extras, indicators

ET = extras.ET


def ev(title, when, **k):
    d = {"title": title, "impact": "High", "time": when, "forecast": "", "previous": "", "actual": ""}
    d.update(k)
    return d


NOW = datetime(2026, 10, 9, 16, 0, tzinfo=timezone.utc)


def run(events, rows):
    return extras.apply_actuals(events, NOW, None, fetch_series_fn=lambda need: rows)


def test_match_titles():
    assert indicators.match("Prelim UoM Consumer Sentiment")["sid"] == "UMCSENT"
    assert indicators.match("Prelim UoM Inflation Expectations")["sid"] == "MICH"
    assert indicators.match("Core CPI m/m")["sid"] == "CPILFESL" and indicators.match("CPI m/m")["sid"] == "CPIAUCSL"
    assert indicators.match("CPI y/y")["sid"] == "CPIAUCNS"
    assert indicators.match("Unemployment Claims")["sid"] == "ICSA"
    assert indicators.match("FOMC Member Speaks") is None


def test_michigan_actual_when_period_matches():
    e1 = ev("Prelim UoM Consumer Sentiment", NOW - timedelta(hours=2))
    e2 = ev("Prelim UoM Inflation Expectations", NOW - timedelta(hours=2))
    rows = {"umcsent": [("2026-09-01", 55.1), ("2026-10-01", 57.3)], "mich": [("2026-09-01", 4.6), ("2026-10-01", 4.3)]}
    assert run([e1, e2], rows) == 2
    assert e1["actual"] == "57.3" and e2["actual"] == "4.3%" and "FRED" in e1["actual_note"]


def test_stale_series_never_shown_as_new():
    e = ev("Prelim UoM Consumer Sentiment", NOW - timedelta(hours=2))
    rows = {"umcsent": [("2026-08-01", 54.0), ("2026-09-01", 55.1)]}
    assert run([e], rows) == 0 and not e["actual"] and "لم يُحدَّث" in e["actual_note"] and "2026-09-01" in e["actual_note"]


def test_weekly_claims_and_cpi_computed():
    claims = ev("Unemployment Claims", datetime(2026, 10, 8, 12, 30, tzinfo=timezone.utc))
    rows = {"claims": [("2026-09-26", 218000.0), ("2026-10-03", 225000.0)]}
    now = datetime(2026, 10, 8, 16, 0, tzinfo=timezone.utc)
    assert extras.apply_actuals([claims], now, None, fetch_series_fn=lambda n: rows) == 1 and claims["actual"] == "225K"
    stale = ev("Unemployment Claims", datetime(2026, 10, 8, 12, 30, tzinfo=timezone.utc))
    assert extras.apply_actuals([stale], now, None, fetch_series_fn=lambda n: {"claims": [("2026-09-19", 1.0), ("2026-09-26", 218000.0)]}) == 0
    cpi_t = datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc)
    mm = ev("CPI m/m", cpi_t); yy = ev("CPI y/y", cpi_t)
    sa = [(f"2025-{m:02d}-01", 300.0 + m * 0.3) for m in range(9, 13)] + [(f"2026-{m:02d}-01", 305.0 + m * 0.5) for m in range(1, 10)]
    ns = [(f"2025-{m:02d}-01", 300.0) for m in range(9, 13)] + [(f"2026-{m:02d}-01", 306.0) for m in range(1, 10)]
    ns = [("2025-09-01", 300.0)] + [(f"2025-{m:02d}-01", 301.0) for m in range(10, 13)] + [(f"2026-{m:02d}-01", 309.0) for m in range(1, 10)]
    n = extras.apply_actuals([mm, yy], datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc), None, fetch_series_fn=lambda need: {"cpi": sa, "cpi_ny": ns})
    assert n == 2 and mm["actual"] == f"{(sa[-1][1] / sa[-2][1] - 1) * 100:.1f}%" and yy["actual"] == f"{(309.0 / 300.0 - 1) * 100:.1f}%", (mm, yy)


def test_proprietary_and_failure_reasons_visible():
    cb = ev("CB Consumer Confidence", NOW - timedelta(hours=1))
    assert run([cb], {}) == 0 and "Conference Board" in cb["actual_note"]
    e = ev("Prelim UoM Consumer Sentiment", NOW - timedelta(hours=1))
    n = extras.apply_actuals([e], NOW, None, fetch_series_fn=lambda need: (_ for _ in ()).throw(OSError("x")))
    assert n == 0 and "FRED" in e["actual_note"] and not e["actual"]


def test_headline_fallback_michigan_and_claims():
    heads = {"University of Michigan consumer sentiment when:2d": ["US consumer sentiment rises to 57.3 in preliminary October reading, University of Michigan says"],
             "University of Michigan year-ahead inflation expectations when:2d": ["Michigan survey: year-ahead inflation expectations ease to 4.3% in early October"],
             "initial jobless claims when:2d": ["Initial jobless claims fall to 219,000 last week"]}
    fq = lambda q: heads.get(q, [])
    stale = {"umcsent": [("2026-08-01", 54.0)], "mich": [("2026-08-01", 4.9)]}
    e1 = ev("Prelim UoM Consumer Sentiment", NOW - timedelta(hours=2)); e2 = ev("Prelim UoM Inflation Expectations", NOW - timedelta(hours=2))
    n = extras.apply_actuals([e1, e2], NOW, None, fetch_series_fn=lambda need: stale, fetch_heads_q_fn=fq)
    assert n == 2 and e1["actual"] == "57.3" and e2["actual"] == "4.3%" and "تحقق منه" in e1["actual_note"] and "FRED" in e1["actual_note"]
    c = ev("Unemployment Claims", NOW - timedelta(hours=2))
    assert extras.apply_actuals([c], NOW, None, fetch_series_fn=lambda need: {}, fetch_heads_q_fn=fq) == 1 and c["actual"] == "219K"


def test_headline_fallback_is_strict():
    e = ev("Prelim UoM Consumer Sentiment", NOW - timedelta(hours=2))
    # عنوان نهائي (final) لا يُقبل لحدث أولي، وعناوين متضاربة لا تُعتمد، وغياب العنوان يُذكر
    fq = lambda q: ["Michigan consumer sentiment final reading rises to 58.0"]
    assert extras.apply_actuals([e], NOW, None, fetch_series_fn=lambda n: {}, fetch_heads_q_fn=fq) == 0 and not e["actual"] and "لم يُنشر" in e["actual_note"]
    e2 = ev("Prelim UoM Consumer Sentiment", NOW - timedelta(hours=2))
    fq2 = lambda q: ["Michigan sentiment preliminary reading rises to 57.3", "Michigan sentiment early look falls to 52.0"]
    assert extras.apply_actuals([e2], NOW, None, fetch_series_fn=lambda n: {}, fetch_heads_q_fn=fq2) == 0 and "متضاربة" in e2["actual_note"]
    e3 = ev("Prelim UoM Consumer Sentiment", NOW - timedelta(hours=2))
    def boom(q): raise OSError("x")
    assert extras.apply_actuals([e3], NOW, None, fetch_series_fn=lambda n: {}, fetch_heads_q_fn=boom) == 0 and not e3["actual"]


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("✔", k)
    print(f"نجحت كل الاختبارات ({n})")
