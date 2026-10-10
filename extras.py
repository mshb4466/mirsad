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
import indicators

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


def _term_years(term):
    """«9-Year 11-Month» → 10 ، «29-Year 10-Month» → 30 ، «10-Year» → 10. None إن لم يُفهم."""
    m = re.match(r"\s*(\d+)-Year(?:\s+(\d+)-Month)?", term or "", re.I)
    if not m:
        return None
    return round(int(m.group(1)) + (int(m.group(2) or 0)) / 12.0)


def _term_weeks(term):
    m = re.match(r"\s*(\d+)-Week", term or "", re.I)
    return int(m.group(1)) if m else None


def fetch_auctions(now, collector, errors=None):
    """نتائج المزادات خلال آخر 4 أيام: [{type, term, years, weeks, date, yield, btc}]. أسباب الفشل تُضاف إلى errors إن مُرِّرت."""
    out = []
    start, end = (now - timedelta(days=4)).date().isoformat(), (now + timedelta(days=1)).date().isoformat()
    for typ in ("Note", "Bond", "TIPS", "Bill"):
        url = ("https://www.treasurydirect.gov/TA_WS/securities/search?format=json&type=" + typ +
               f"&dateFieldName=auctionDate&startDate={start}&endDate={end}")
        try:
            rows = json.loads(collector._http_get(url, 20).decode("utf-8"))
        except Exception as ex:  # noqa: BLE001
            if errors is not None:
                errors.append(f"{typ}: {type(ex).__name__}")
            continue
        for r in rows if isinstance(rows, list) else []:
            try:
                y = r.get("highYield") or r.get("highInvestmentRate") or r.get("highDiscountRate")
                btc = r.get("bidToCoverRatio")
                if not y or not btc:
                    continue
                term = r.get("securityTerm", "")
                out.append({"type": r.get("securityType") or typ, "term": term, "years": _term_years(term), "weeks": _term_weeks(term),
                            "date": str(r.get("auctionDate", ""))[:10], "yield": float(y), "btc": float(btc)})
            except Exception:  # noqa: BLE001
                continue
    return out


def auction_actual(title, ev_time, auctions):
    """العائد|نسبة التغطية لمزاد العنوان، بمطابقة المدة (تشمل إعادات الإصدار مثل 9-Year 11-Month = 10 سنوات) والنوع (TIPS منفصل)."""
    t = (title or "").lower()
    want_tips = "tips" in t
    ym = re.search(r"(\d+)\s*-?\s*(?:y|yr|year)", t)
    wm = re.search(r"(\d+)\s*-?\s*(?:w|wk|week)", t)
    day = ev_time.astimezone(ET).date().isoformat()
    for a in auctions:
        if a["date"] != day or (a["type"].upper() == "TIPS") != want_tips:
            continue
        if wm and ("bill" in t or not ym):
            if a.get("weeks") == int(wm.group(1)):
                return f"{a['yield']:.3f}|{a['btc']:.2f}"
        elif ym and a.get("years") == int(ym.group(1)):
            return f"{a['yield']:.3f}|{a['btc']:.2f}"
    return ""


CRUDE_RE = re.compile(r"crude[^.,;]{0,25}?(?:stocks|inventories|stockpiles|supplies)[^.,;]{0,25}?\b(rose|fell|rise|fall|drew|jumped|climbed|dropped|declined|increased|decreased|build|draw)\b[^.,;]{0,25}?([\d.]+)\s*million", re.I)
UP = ("rose", "rise", "jumped", "climbed", "increased", "build")


def oil_from_headlines(heads):
    """احتياط: رقم تغير مخزون الخام من عنوان خبر (صيغة صارمة). يعيد '+X.XM' أو None. يحتاج تحققاً بصرياً."""
    for t in heads or []:
        m = CRUDE_RE.search(t or "")
        if m:
            v = float(m.group(2))
            return f"{v if m.group(1).lower() in UP else -v:+.1f}M"
    return None


def apply_actuals(events, now, collector, fetch_oil_fn=None, fetch_auctions_fn=None, fetch_heads_fn=None, fetch_series_fn=None):
    """يملأ الأرقام الفعلية الناقصة للأحداث الصادرة (نفط، مزادات) ويكتب في e['actual_note'] المصدر أو سبب الغياب.
    يعيد عدد ما ملأ. لا يرفع استثناءً."""
    todo = [e for e in events if not e.get("actual") and now - timedelta(hours=30) <= e["time"] < now]
    if not todo:
        return 0
    n = 0
    oil_res, auc, auc_err = None, None, None
    ind_rows, ind_err = None, None
    for e in todo:
        kind, _, _ = events_ctx.classify(e.get("title", ""))
        try:
            if kind == "oil":
                if oil_res is None:
                    try:
                        oil_res = (fetch_oil_fn or (lambda: fetch_oil(now, collector)))() or False
                    except Exception as ex:  # noqa: BLE001
                        oil_res = False
                        e["actual_note"] = f"تعذّر الاتصال بـ FRED ({type(ex).__name__})"
                got = None
                if oil_res:
                    age = (e["time"].astimezone(ET).date() - __import__("datetime").date.fromisoformat(oil_res[0])).days
                    if 2 <= age <= 9:
                        got, src = f"{oil_res[1]:+.1f}M", "المصدر: FRED (EIA)"
                    else:
                        e["actual_note"] = f"FRED لم يُحدَّث بعد (آخر قراءة {oil_res[0]})"
                if got is None and fetch_heads_fn:
                    try:
                        got = oil_from_headlines(fetch_heads_fn())
                        src = "المصدر: عنوان خبر، تحقق منه"
                    except Exception:  # noqa: BLE001
                        got = None
                if got:
                    e["actual"], e["actual_note"] = got, src
                    n += 1
                elif not e.get("actual_note"):
                    e["actual_note"] = "لم يصل الرقم من FRED بعد"
            elif kind == "auction":
                if auc is None:
                    errs = []
                    try:
                        auc = (fetch_auctions_fn or (lambda: fetch_auctions(now, collector, errs)))() or []
                        if errs and not auc:
                            auc_err = "تعذّر الاتصال بـ TreasuryDirect (" + "، ".join(errs) + ")"
                    except Exception as ex:  # noqa: BLE001
                        auc, auc_err = [], f"تعذّر الاتصال بـ TreasuryDirect ({type(ex).__name__})"
                a = auction_actual(e.get("title", ""), e["time"], auc)
                if a:
                    e["actual"], e["actual_note"] = a, "المصدر: TreasuryDirect (العائد|نسبة التغطية)"
                    n += 1
                else:
                    e["actual_note"] = auc_err or ("TreasuryDirect لم يعد نتيجة هذا المزاد بعد" if auc else "TreasuryDirect لم يعد أي مزاد (تعذّر الجلب أو لم يُنشر)")
            else:
                spec = indicators.match(e.get("title", ""))
                if not spec:
                    why = indicators.no_source_reason(e.get("title", ""))
                    if why:
                        e["actual_note"] = why
                    continue
                if ind_rows is None:
                    need = indicators.series_needed(todo)
                    try:
                        if fetch_series_fn:
                            ind_rows = fetch_series_fn(need) or {}
                        else:
                            ind_rows, _p = collector.fetch_fred(now, 460, need)
                            ind_rows = ind_rows or {}
                        if not ind_rows:
                            ind_err = "تعذّر الاتصال بـ FRED"
                    except Exception as ex:  # noqa: BLE001
                        ind_rows, ind_err = {}, f"تعذّر الاتصال بـ FRED ({type(ex).__name__})"
                val, note = indicators.resolve(e.get("title", ""), e["time"], ind_rows, ET)
                if val:
                    e["actual"], e["actual_note"] = val, note + "؛ محسوب من السلسلة وقد يختلف عن القراءة الرسمية بكسر عشري"
                    n += 1
                else:
                    e["actual_note"] = ind_err or note or "لا رقم فعلي متاح"
        except Exception as ex:  # noqa: BLE001
            e["actual_note"] = f"خطأ داخلي: {type(ex).__name__}"
    return n
