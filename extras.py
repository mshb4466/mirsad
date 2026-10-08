#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — مصادر مساندة للأرقام الفعلية التي لا يوفرها تقويم الأحداث غالباً (للأحداث منخفضة التصنيف):
مخزونات النفط الخام (FRED، أسبوعية) ونتائج مزادات الخزانة (TreasuryDirect).
كلها فشل ناعم: إن تعذّر المصدر يبقى الحدث بلا رقم فعلي وتقول الواجهة ذلك صراحة.
"""
import json
import re
from datetime import timedelta, timezone

import events_ctx

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001
    ET = timezone.utc

TERMS = {2: "2-Year", 3: "3-Year", 5: "5-Year", 7: "7-Year", 10: "10-Year", 20: "20-Year", 30: "30-Year"}


def oil_change(rows):
    """rows: [(تاريخ ISO، ألف برميل)] أسبوعية. يعيد (تاريخ آخر قراءة، تغير بملايين البراميل) أو None."""
    if not rows or len(rows) < 2:
        return None
    (d1, v1), (_, v0) = rows[-1], rows[-2]
    return d1, (v1 - v0) / 1000.0


def fetch_oil(now, collector):
    data, _ = collector.fetch_fred(now, 40, {"crude": "WCESTUS1"})
    return oil_change((data or {}).get("crude"))


def fetch_auctions(now, collector):
    """نتائج المزادات خلال آخر 4 أيام: [{term, date, yield, btc}]."""
    out = []
    start, end = (now - timedelta(days=4)).date().isoformat(), (now + timedelta(days=1)).date().isoformat()
    for typ in ("Note", "Bond"):
        url = ("https://www.treasurydirect.gov/TA_WS/securities/search?format=json&type=" + typ +
               f"&dateFieldName=auctionDate&startDate={start}&endDate={end}")
        try:
            rows = json.loads(collector._http_get(url, 20).decode("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for r in rows if isinstance(rows, list) else []:
            try:
                y = r.get("highYield") or r.get("highInvestmentRate") or r.get("highDiscountRate")
                btc = r.get("bidToCoverRatio")
                if not y or not btc:
                    continue
                out.append({"term": r.get("securityTerm", ""), "date": str(r.get("auctionDate", ""))[:10],
                            "yield": float(y), "btc": float(btc)})
            except Exception:  # noqa: BLE001
                continue
    return out


def auction_actual(title, ev_time, auctions):
    m = re.search(r"(\d+)-y", (title or "").lower())
    if not m:
        return ""
    term = TERMS.get(int(m.group(1)))
    day = ev_time.astimezone(ET).date().isoformat()
    for a in auctions:
        if a["term"].lower().startswith(term.lower()) and a["date"] == day:
            return f"{a['yield']:.3f}|{a['btc']:.2f}"
    return ""


def apply_actuals(events, now, collector, fetch_oil_fn=None, fetch_auctions_fn=None):
    """يملأ الأرقام الفعلية الناقصة للأحداث الصادرة (نفط، مزادات). يعيد عدد ما ملأ. لا يرفع استثناءً."""
    todo = [e for e in events if not e.get("actual") and now - timedelta(hours=26) <= e["time"] < now]
    if not todo:
        return 0
    n = 0
    oil_res, auc = None, None
    for e in todo:
        kind, _, _ = events_ctx.classify(e.get("title", ""))
        try:
            if kind == "oil":
                if oil_res is None:
                    oil_res = (fetch_oil_fn or (lambda: fetch_oil(now, collector)))() or False
                if oil_res:
                    age = (e["time"].astimezone(ET).date() - __import__("datetime").date.fromisoformat(oil_res[0])).days
                    if 2 <= age <= 9:
                        e["actual"] = f"{oil_res[1]:+.1f}M"
                        n += 1
            elif kind == "auction":
                if auc is None:
                    auc = (fetch_auctions_fn or (lambda: fetch_auctions(now, collector)))() or []
                a = auction_actual(e.get("title", ""), e["time"], auc)
                if a:
                    e["actual"] = a
                    n += 1
        except Exception:  # noqa: BLE001
            continue
    return n
