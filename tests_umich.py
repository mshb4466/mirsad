# -*- coding: utf-8 -*-
"""اختبارات قراءة ميشيغان من الموقع الرسمي. الصفحات هنا **اصطناعية** على هيئة ما وُصف للصفحة الحقيقية (جدول + قائمة تقارير)،
وليست جلباً حقيقياً: الجلب الحقيقي لا يُختبر إلا من تشغيل GitHub. التشغيل: python3 tests_umich.py"""
import sys
from datetime import datetime, timezone

import extras
import indicators
from extras import ET

ok = 0


def chk(c, m):
    global ok
    print(("PASS " if c else "FAIL ") + m)
    if not c:
        sys.exit(1)
    ok += 1


def page(results="October 2026", dates=("October 23, 2026", "October 9, 2026", "September 25, 2026"), value="48.0", extra=""):
    rows = "".join(f"<tr><td>{d}</td><td><a href='x'>Report</a></td></tr>" for d in dates)
    return (f"<html><head><script>var d='Results for August 2020';</script><style>.a{{}}</style></head><body><h3>Reports</h3><table>{rows}</table>"
            f"<p>Results for {results}</p><table><tr><td>The Index of Consumer Sentiment</td><td><b>{value}</b></td></tr>"
            f"<tr><td>Current Economic Conditions</td><td>50.9</td></tr></table>{extra}</body></html>")


EV = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
v, n = indicators.umich_official(page(), EV, ET)
chk(v == "48.0" and "الموقع الرسمي" in n and "2026-10-23" in n, "matching month and release date -> 48.0 with official-source note")
v, n = indicators.umich_official(page(results="September 2026"), EV, ET)
chk(v is None and "September 2026" in n, "page shows another month -> no number, reason given")
v, n = indicators.umich_official(page(dates=("September 25, 2026", "September 11, 2026")), EV, ET)
chk(v is None and "2026-09-25" in n, "latest report date differs from release date -> no number (may be another release)")
v, n = indicators.umich_official(page(dates=("October 30, 2026", "October 23, 2026")), EV, ET)
chk(v is None, "a newer release already replaced the page -> no number (cannot be proven to be this release)")
v, n = indicators.umich_official(page(value="148.0"), EV, ET)
chk(v is None and "خارج النطاق" in n, "out-of-range value rejected")
v, n = indicators.umich_official(page(value="n/a"), EV, ET)
chk(v is None and "لم أجد قيمة" in n, "missing value -> no number")
v, n = indicators.umich_official("", EV, ET)
chk(v is None and "فارغة" in n, "empty page")
v, n = indicators.umich_official("<html>maintenance</html>", EV, ET)
chk(v is None and "تغيّر شكل الصفحة" in n, "layout change -> no number, says so")
v, n = indicators.umich_official(page(dates=()), EV, ET)
chk(v is None and "لا تواريخ" in n, "no report dates -> no proof -> no number")
chk(indicators.umich_official("Reports October 23, 2026 Results for October 2026 The Index of Consumer Sentiment | 48.0", EV, ET)[0] == "48.0", "plain-text form (pipe separated) also parses")
# script/style content never leaks into the parse
v, n = indicators.umich_official(page(results="October 2026"), EV, ET)
chk(v == "48.0", "text inside <script> ('Results for August 2020') is ignored")

# تكامل: FRED متأخر + الموقع الرسمي يملأ الرقم
ev = {"title": "Revised UoM Consumer Sentiment", "time": EV, "impact": "High", "forecast": "46.3", "previous": "46.3", "country": "USD"}
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


class C:
    pass


rows = {"UMCSENT": [("2026-08-01", 58.2), ("2026-09-01", 48.1)]}
n = extras.apply_actuals([ev], NOW, C(), fetch_series_fn=lambda need: rows, fetch_umich_fn=lambda: page(), window_h=24 * 7 + 1)
chk(n == 1 and ev["actual"] == "48.0" and ev["actual_src"] == "official", "end-to-end: FRED stale -> official page fills 48.0 (src=official)")
ev2 = {"title": "Revised UoM Consumer Sentiment", "time": EV, "impact": "High", "forecast": "46.3", "previous": "46.3", "country": "USD"}
def boom():
    raise OSError("blocked")
n = extras.apply_actuals([ev2], NOW, C(), fetch_series_fn=lambda need: rows, fetch_umich_fn=boom, window_h=24 * 7 + 1)
chk(n == 0 and not ev2.get("actual") and "تعذّر الاتصال (OSError)" in ev2.get("actual_note", ""), "site unreachable -> no number, error type shown, no crash")
ev3 = {"title": "Revised UoM Consumer Sentiment", "time": EV, "impact": "High", "forecast": "46.3", "previous": "46.3", "country": "USD"}
n = extras.apply_actuals([ev3], NOW, C(), fetch_series_fn=lambda need: rows, fetch_umich_fn=lambda: page(results="September 2026"), window_h=24 * 7 + 1)
chk(n == 0 and not ev3.get("actual"), "mismatching page -> stays awaiting (no wrong number)")
print("DONE", ok)
