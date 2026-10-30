#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — مصادر مساندة للأرقام الفعلية التي لا يوفرها تقويم الأحداث غالباً (للأحداث منخفضة التصنيف):
مخزونات النفط الخام (FRED، أسبوعية) ونتائج مزادات الخزانة (TreasuryDirect).
كلها فشل ناعم: إن تعذّر المصدر يبقى الحدث بلا رقم فعلي وتقول الواجهة ذلك صراحة.
"""
import json
import os
import re
import urllib.error
import urllib.parse
from datetime import date, timedelta, timezone

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


class OilRes(tuple):
    """(تاريخ آخر قراءة، التغير بملايين البراميل) + اسم المصدر الذي جاء منه."""
    src = "FRED"


def fetch_oil_eia(now, collector, key):
    """أرقام مخزون النفط الخام الأسبوعي (WCESTUS1) مباشرة من واجهة EIA الرسمية v2 (تحتاج EIA_API_KEY مجانياً).
    تنشر لحظة الصدور فلا تنتظر FRED. يعيد [(فترة، ألف برميل)] تصاعدياً أو None. الصيغة: data[].period وdata[].value."""
    url = ("https://api.eia.gov/v2/petroleum/stoc/wstk/data/?" + urllib.parse.urlencode({
        "api_key": key, "frequency": "weekly", "data[0]": "value", "facets[series][]": "WCESTUS1",
        "sort[0][column]": "period", "sort[0][direction]": "desc", "length": "4"}))
    obj = json.loads(collector._http_get(url, 25).decode("utf-8"))
    rows = []
    for r in (obj.get("response") or {}).get("data") or []:
        try:
            rows.append((str(r["period"])[:10], float(r["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(rows) or None


def fetch_oil(now, collector):
    """EIA المباشر أولاً (إن وُجد EIA_API_KEY)، وإن تعذّر أو تأخر فـFRED (أبطأ ويتأثر بصيانة موقعه). فشل ناعم."""
    key = os.environ.get("EIA_API_KEY", "").strip()
    if key:
        try:
            res = oil_change(fetch_oil_eia(now, collector, key))
            if res:
                o = OilRes(res)
                o.src = "EIA"
                return o
        except Exception:  # noqa: BLE001
            pass
    data, _ = collector.fetch_fred(now, 40, {"crude": "WCESTUS1"})
    res = oil_change((data or {}).get("crude"))
    return OilRes(res) if res else res


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


def _period(e, note):
    """فترة التقرير المطابقة من نص المصدر (تواريخ المشاهدة) لتوثيقها في سجل الفحص."""
    m = re.search(r"فترة (\d{4}-\d{2}-\d{2})", note or "")
    if m:
        e["actual_period"] = m.group(1)


def _detail(e, det):
    """يحفظ توثيق الحساب على الحدث: معرّف السلسلة، طريقة الحساب، القيمة قبل التقريب، مرحلة الإصدار وهل هي متحقَّقة بدليل."""
    e["actual_series"], e["actual_method"], e["actual_raw"], e["actual_stage"] = det.get("series", ""), det.get("method", ""), det.get("raw"), det.get("stage", "")
    e["actual_stage_ok"] = det.get("stage_ok")


def fetch_gdp_vintage(now, collector, sid, ref, rel_date, key=None):
    """نسخة ALFRED لربع GDP يوم الإصدار: {dates, vdate, value, first_seen}. يلزمه FRED_API_KEY (بدونه None: لا دليل فلا رقم).
    الاشتقاق من طلب واحد لمشاهدات الربع عبر كل النسخ (realtime من 1776-07-04): تاريخ كل نسخة = realtime_start لصف المشاهدة،
    وقيمة نسخة الإصدار = قيمة الصف الذي بدأ ضمن [يوم الإصدار، +3 أيام]. (إصلاح: كان يطلب أيضاً vintagedates بنافذة تنتهي بعد اليوم
    الحالي ثم observations بنافذة تاريخية، فيفشل بـHTTPError ولا يظهر GDP؛ الطلب الآن واحد بلا نافذة مستقبلية، وأي خطأ يُبلَّغ برمزه ونصّه.)
    لم يُختبر حياً من بيئة التطوير (الشبكة محجوبة): يُختبر على GitHub. يرفع RuntimeError برمز HTTP عند فشل الاتصال."""
    key = (key or os.environ.get("FRED_API_KEY", "")).strip()
    if not key:
        return None
    base = "https://api.stlouisfed.org/fred/"

    def q(path, **kw):
        url = base + path + "?" + urllib.parse.urlencode(dict(kw, api_key=key, file_type="json"))
        try:
            raw = collector._http_get(url, 20)
        except urllib.error.HTTPError as ex:   # رمز الخطأ ونص FRED (بلا المفتاح) ليظهرا في التشخيص
            body = ""
            try:
                body = " ".join(ex.read().decode("utf-8", errors="replace").split())[:120]
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError(f"HTTP {ex.code} ({path}) {body}".strip())
        return json.loads(raw.decode("utf-8"))
    obs = q("series/observations", series_id=sid, observation_start=ref.isoformat(), observation_end=ref.isoformat(),
            realtime_start="1776-07-04", realtime_end="9999-12-31").get("observations") or []
    rows = sorted((o for o in obs if o.get("realtime_start")), key=lambda o: o["realtime_start"])
    dates = sorted({o["realtime_start"] for o in rows})
    cand = [d for d in dates if 0 <= (date.fromisoformat(d) - rel_date).days <= 3]
    vdate, value = (cand[0] if cand else None), None
    if vdate:
        for o in rows:
            if o["realtime_start"] == vdate and o.get("value") not in (".", "", None):
                value = float(o["value"])
                break
    first_seen = dates[0] if dates else None
    return {"dates": dates, "vdate": vdate, "value": value, "first_seen": first_seen}


def apply_actuals(events, now, collector, fetch_oil_fn=None, fetch_auctions_fn=None, fetch_heads_fn=None, fetch_series_fn=None, fetch_heads_q_fn=None, fetch_bls_fn=None, fetch_umich_fn=None, window_h=30, diag=None, fetch_vintage_fn=None):
    """يملأ الأرقام الفعلية الناقصة للأحداث الصادرة (نفط، مزادات) ويكتب في e['actual_note'] المصدر أو سبب الغياب.
    يعيد عدد ما ملأ. لا يرفع استثناءً."""
    todo = [e for e in events if not e.get("actual") and now - timedelta(hours=window_h) <= e["time"] < now]
    if not todo:
        return 0
    n = 0
    oil_res, auc, auc_err = None, None, None
    ind_rows, ind_err = None, None
    bls_rows, bls_err = None, None
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
                        _s = getattr(oil_res, "src", "FRED")
                        got, src, tier, sname = (f"{oil_res[1]:+.1f}M", "المصدر: EIA (واجهة رسمية)", "official", "EIA (API)") if _s == "EIA" else (f"{oil_res[1]:+.1f}M", "المصدر: FRED (EIA)", "secondary", "FRED (EIA)")
                        e["actual_period"] = oil_res[0]
                    else:
                        e["actual_note"] = f"FRED لم يُحدَّث بعد (آخر قراءة {oil_res[0]})"
                if got is None and fetch_heads_fn:
                    try:
                        got = oil_from_headlines(fetch_heads_fn())
                        src, tier, sname = "المصدر: عنوان خبر، تحقق منه", "news", "عنوان خبر (Google News)"
                    except Exception:  # noqa: BLE001
                        got = None
                if got:
                    e["actual"], e["actual_note"], e["actual_src"], e["actual_source"] = got, src, tier, sname
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
                    if diag is not None:
                        diag["treasury"] = {"ok": bool(auc) and not auc_err, "detail": auc_err or f"{len(auc)} مزاد"}
                a = auction_actual(e.get("title", ""), e["time"], auc)
                if a:
                    e["actual"], e["actual_note"] = a, "المصدر: TreasuryDirect (العائد|نسبة التغطية)"
                    e["actual_src"], e["actual_source"] = "official", "TreasuryDirect"
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
                if bls_rows is None:
                    bls_rows = {}
                    need_b = indicators.bls_needed(todo)
                    if need_b and fetch_bls_fn:
                        try:
                            by_sid, berrs = fetch_bls_fn(sorted(set(need_b.values())))
                            bls_err = "؛ ".join(berrs) if berrs else None
                            if diag is not None:
                                diag["bls"] = {"ok": bool(by_sid) and not berrs, "detail": bls_err or f"{len(by_sid or {})} سلسلة"}
                            for k, sid in need_b.items():
                                if (by_sid or {}).get(sid):
                                    bls_rows[k] = by_sid[sid]
                        except Exception as ex:  # noqa: BLE001
                            bls_err = f"BLS: خطأ ({type(ex).__name__})"
                            if diag is not None:
                                diag["bls"] = {"ok": False, "detail": bls_err}
                val, bnote = (None, None)
                if spec["key"] in indicators.BLS_IDS and fetch_bls_fn:
                    det = indicators.resolve_detail(e.get("title", ""), e["time"], bls_rows, ET, "BLS", indicators.BLS_IDS, now)
                    val, bnote = det["value"], det["note"]
                    if val:
                        e["actual"], e["actual_note"] = val, bnote + " (سلسلة رسمية من BLS)؛ محسوب من السلسلة ولم يُقارَن بنشرة الإصدار، وقد يختلف عنها بكسر عشري"
                        e["actual_src"], e["actual_source"] = "official", "BLS"
                        _detail(e, det)
                        _period(e, bnote)
                        pr = indicators.previous_revised(e.get("title", ""), e["time"], bls_rows, ET)
                        if pr:
                            e["prev_revised"] = pr
                        n += 1
                        continue
                    if bls_err and not bls_rows:
                        bnote = bls_err
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
                        if diag is not None:
                            diag["fred"] = {"ok": bool(ind_rows), "detail": ind_err or f"{len(ind_rows)} سلسلة"}
                    except Exception as ex:  # noqa: BLE001
                        ind_rows, ind_err = {}, f"تعذّر الاتصال بـ FRED ({type(ex).__name__})"
                        if diag is not None:
                            diag["fred"] = {"ok": False, "detail": ind_err}
                vint = None
                if spec["rule"] == "quarter" and fetch_vintage_fn:      # GDP: نسخة الإصدار التاريخية فقط (لا قراءة FRED الحالية)
                    try:
                        vint = fetch_vintage_fn(spec["sid"], indicators.gdp_ref_quarter(e["time"].astimezone(ET).date()), e["time"].astimezone(ET).date())
                    except Exception as ex:  # noqa: BLE001
                        vint = None
                        if diag is not None:
                            diag["alfred"] = {"ok": False, "detail": f"ALFRED: تعذّر الاتصال ({type(ex).__name__}: {str(ex)[:160]})"}
                det = indicators.resolve_detail(e.get("title", ""), e["time"], ind_rows, ET, "FRED", None, now, vint)
                val, note = det["value"], det["note"]
                if val:
                    e["actual"], e["actual_note"] = val, note + "؛ محسوب من سلسلة FRED ولم يُقارَن بنشرة الإصدار، وقد يختلف عنها بكسر عشري"
                    e["actual_src"], e["actual_source"] = "secondary", ("FRED/ALFRED" if spec["rule"] == "quarter" else "FRED")
                    _detail(e, det)
                    _period(e, note)
                    n += 1
                else:
                    why = ind_err or note or "لا رقم فعلي متاح"
                    if bnote:
                        why = bnote + " | FRED: " + why
                    if fetch_umich_fn and re.search(r"uom consumer sentiment", e.get("title", "").lower()):
                        try:
                            uv, un = indicators.umich_official(fetch_umich_fn(), e["time"], ET)
                        except Exception as ex:  # noqa: BLE001
                            uv, un = None, f"الموقع الرسمي (ميشيغان): تعذّر الاتصال ({type(ex).__name__})"
                        if uv:
                            e["actual"], e["actual_note"] = uv, un + " (FRED: " + why + ")"
                            e["actual_src"], e["actual_source"] = "official", "University of Michigan (الموقع الرسمي)"
                            n += 1
                            continue
                        if un:
                            why = why + " | " + un
                    if fetch_heads_q_fn:
                        hv, hn = indicators.from_headlines(e.get("title", ""), fetch_heads_q_fn)
                        if hv:
                            e["actual"], e["actual_note"] = hv, hn + " (FRED: " + why + ")"
                            e["actual_src"], e["actual_source"] = "news", "عنوان خبر (Google News)"
                            n += 1
                            continue
                        if hn:
                            why = why + " | " + hn
                    e["actual_note"] = why
        except Exception as ex:  # noqa: BLE001
            e["actual_note"] = f"خطأ داخلي: {type(ex).__name__}"
    return n
