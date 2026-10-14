# -*- coding: utf-8 -*-
"""
مِرصاد — فحص الأرقام الفعلية على بيانات حقيقية (يُشغَّل من GitHub Actions؛ شبكة بيئة التطوير محجوبة).

ثلاثة فحوص مستقلة، ولكل نتيجة سجل: المصدر، توقيت الإصدار، القيمة المستلمة، وقت الجلب، فترة التقرير، نتيجة المطابقة:
1) التاريخي: إصدارات معروفة (CPI/NFP/البطالة/طلبات الإعانة/PPI/PCE/GDP/التجزئة) تُحسب بنفس شيفرة الإنتاج من
   نسخة ALFRED الأصلية يوم الإصدار (realtime_start=realtime_end=يوم الإصدار) = القيمة كما نُشرت أول مرة، لا بعد المراجعات،
   وتُقارَن بالرقم الرسمي المنشور (القيم المرجعية أدناه كتبتُها من النشرات الرسمية ويجب أن تتأكد منها بالروابط المرفقة).
2) المصدران: BLS مقابل FRED لآخر فترة متاحة (يكشف تأخر FRED وأي خطأ في معرّفات السلاسل).
3) النشر: بعد نشر GitHub Pages يُجلب data.json المنشور ويُقارَن بالمحلي (published_at) لكشف نسخة قديمة.
نتائج المطابقة: مطابق | فرق تقريب (≤0.1، من حساب النسبة من مؤشر مقرَّب) | غير مطابق | تعذّر الجلب. لا نُسمّي فرقاً «مطابقاً».
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

import bls
import indicators
from extras import ET

# (عنوان الحدث كما في التقويم، وقت الإصدار UTC، القيمة الرسمية المنشورة أول مرة، رابط للمقارنة اليدوية)
GOLDEN = [
    ("CPI y/y", "2024-01-11T13:30", "3.4%", "https://www.bls.gov/news.release/archives/cpi_01112024.htm"),
    ("Core CPI y/y", "2024-01-11T13:30", "3.9%", "https://www.bls.gov/news.release/archives/cpi_01112024.htm"),
    ("CPI m/m", "2024-01-11T13:30", "0.3%", "https://www.bls.gov/news.release/archives/cpi_01112024.htm"),
    ("Core CPI m/m", "2024-01-11T13:30", "0.3%", "https://www.bls.gov/news.release/archives/cpi_01112024.htm"),
    ("CPI y/y", "2024-04-10T12:30", "3.5%", "https://www.bls.gov/news.release/archives/cpi_04102024.htm"),
    ("Core CPI y/y", "2024-04-10T12:30", "3.8%", "https://www.bls.gov/news.release/archives/cpi_04102024.htm"),
    ("Non-Farm Employment Change", "2024-02-02T13:30", "353K", "https://www.bls.gov/news.release/archives/empsit_02022024.htm"),
    ("Unemployment Rate", "2024-02-02T13:30", "3.7%", "https://www.bls.gov/news.release/archives/empsit_02022024.htm"),
    ("Non-Farm Employment Change", "2024-04-05T12:30", "303K", "https://www.bls.gov/news.release/archives/empsit_04052024.htm"),
    ("Unemployment Rate", "2024-04-05T12:30", "3.8%", "https://www.bls.gov/news.release/archives/empsit_04052024.htm"),
    ("Unemployment Claims", "2024-01-11T13:30", "202K", "https://www.dol.gov/ui/data.pdf"),
    ("PPI m/m", "2024-01-12T13:30", "-0.1%", "https://www.bls.gov/news.release/archives/ppi_01122024.htm"),
    ("Retail Sales m/m", "2024-01-17T13:30", "0.6%", "https://www.census.gov/retail/sales.html"),
    ("Core PCE Price Index m/m", "2024-01-26T13:30", "0.2%", "https://www.bea.gov/data/personal-consumption-expenditures-price-index"),
    ("Core PCE Price Index y/y", "2024-01-26T13:30", "2.9%", "https://www.bea.gov/data/personal-consumption-expenditures-price-index"),
    ("Advance GDP q/q", "2024-01-25T13:30", "3.3%", "https://www.bea.gov/data/gdp/gross-domestic-product"),
]
# عناوين التقويم التي لا تحتويها SPECS كما هي (التقويم يسمّي GDP «Advance GDP q/q»): نطابقها بنمط gdp q/q


def _tz_utc(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _num(v):
    try:
        return float(str(v).replace("%", "").replace("K", "").replace("M", ""))
    except ValueError:
        return None


def judge(got, official):
    """نتيجة المطابقة بين القيمة المستلمة والرسمية. «فرق تقريب» فقط إن كان الفرق ≤ 0.1 (أو 1K) ولا يُسمّى مطابقاً."""
    if not got:
        return "لا رقم"
    if got == official:
        return "مطابق"
    a, b = _num(got), _num(official)
    if a is not None and b is not None:
        tol = 1.0 if official.endswith("K") else 0.1
        if abs(a - b) <= tol + 1e-9:
            return "فرق تقريب"
    return "غير مطابق"


def _alfred(sid, as_of, key, fetch=None):
    """قيم السلسلة كما كانت معروفة يوم as_of (ALFRED). [(تاريخ، قيمة)]."""
    start = f"{int(as_of[:4]) - 3}-01-01"
    url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={sid}&api_key={key}&file_type=json"
           f"&realtime_start={as_of}&realtime_end={as_of}&observation_start={start}")
    raw = (fetch or _get)(url)
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    return [(o["date"], float(o["value"])) for o in data.get("observations", []) if o.get("value") not in (".", "", None)]


def _get(url):
    import collector as c
    return c._http_get(url, 30)


def check_historical(key, now, fetch=None):
    """الفحص 1: إصدارات تاريخية معروفة من نسخة ALFRED الأصلية. يعيد قائمة سجلات."""
    out, cache = [], {}
    for title, rel, official, url in GOLDEN:
        t = _tz_utc(rel)
        rec = {"check": "historical", "title": title, "source": "ALFRED (FRED، نسخة يوم الإصدار)", "release_time": t.isoformat(),
               "official": official, "official_url": url, "fetched_at": datetime.now(timezone.utc).isoformat(), "value": "", "period": "", "match": "", "note": ""}
        spec = indicators.match(title if "gdp" not in title.lower() else "GDP q/q")
        if not spec:
            rec.update(match="تعذّر الجلب", note="العنوان غير معرَّف في indicators"); out.append(rec); continue
        if not key:
            rec.update(match="تعذّر الجلب", note="FRED_API_KEY غير متوفر: لا وصول إلى ALFRED"); out.append(rec); continue
        try:
            ck = (spec["sid"], t.date().isoformat())
            if ck not in cache:
                cache[ck] = _alfred(spec["sid"], t.date().isoformat(), key, fetch)
            rows = cache[ck]
            val, note = indicators.resolve(title if "gdp" not in title.lower() else "GDP q/q", t, {spec["key"]: rows}, ET)
            rec.update(value=val or "", note=note or "", match=judge(val, official))
            if note and "فترة" in note:
                rec["period"] = note.split("فترة")[1].split(")")[0].strip()
        except Exception as e:  # noqa: BLE001
            rec.update(match="تعذّر الجلب", note=f"{type(e).__name__}")
        out.append(rec)
    return out


def check_sources(now, bls_key=None, fred_key=None, bls_post=None, fred_fetch=None):
    """الفحص 2: BLS مقابل FRED لآخر فترة متاحة لكل مؤشر له سلسلة BLS. يعيد (سجلات، حالة_المصدرين)."""
    out, status = [], {"bls": {"ok": False, "detail": ""}, "fred": {"ok": False, "detail": ""}}
    ids = sorted(set(indicators.BLS_IDS.values()))
    state = {}
    by_sid, errs = bls.fetch(ids, now, bls_key, post_fn=bls_post, state=state)
    status["bls"] = {"ok": bool(by_sid) and not errs, "detail": "؛ ".join(errs) or f"{len(by_sid)}/{len(ids)} سلسلة", "calls": state.get("bls_calls")}
    import collector as c
    need = {s["key"]: s["sid"] for s in (indicators.match(t) for t in ("Unemployment Rate", "Non-Farm Employment Change", "CPI m/m", "CPI y/y",
                                                                       "Core CPI m/m", "Core CPI y/y", "Average Hourly Earnings m/m", "JOLTS Job Openings")) if s}
    try:
        if fred_fetch:
            fred, ferrs = fred_fetch(need), []
        else:
            fred, ferrs = c.fetch_fred(now, 1500, need)
    except Exception as e:  # noqa: BLE001
        fred, ferrs = {}, [type(e).__name__]
    status["fred"] = {"ok": bool(fred) and not ferrs, "detail": "؛ ".join(map(str, ferrs))[:200] or f"{len(fred)}/{len(need)} سلسلة"}
    for pat_title, k in (("Unemployment Rate", "unrate"), ("Non-Farm Employment Change", "payems"), ("CPI m/m", "cpi"), ("CPI y/y", "cpi_ny"),
                         ("Core CPI m/m", "cpilfe"), ("Core CPI y/y", "cpilfe_ny"), ("Average Hourly Earnings m/m", "ahe"), ("JOLTS Job Openings", "jolts")):
        spec = indicators.match(pat_title)
        rec = {"check": "sources", "title": pat_title, "fetched_at": datetime.now(timezone.utc).isoformat(), "official": "", "official_url": "https://www.bls.gov/"}
        rb = by_sid.get(indicators.BLS_IDS.get(k, ""))
        rf = fred.get(spec["key"]) if spec else None
        vb = vf = None
        pb = pf = ""
        if rb and spec:
            i = len(rb) - 1
            vb, pb = indicators.compute(spec["tr"], rb, i), rb[i][0]
        if rf and spec:
            j = len(rf) - 1
            vf, pf = indicators.compute(spec["tr"], rf, j), rf[j][0]
        rec.update(source="BLS", value=vb or "", period=pb[:10], note=f"FRED: {vf or '—'} (آخر فترة {pf[:10] or '—'})")
        if not rb:
            rec["match"] = "تعذّر الجلب"
        elif not rf:
            rec["match"] = "BLS فقط"
        elif pb != pf:
            rec["match"] = f"فترتان مختلفتان: {'BLS أحدث' if pb > pf else 'FRED أحدث'}"
        else:
            rec["match"] = judge(vf, vb) if vb and vf else "لا رقم"
        out.append(rec)
    return out, status


def check_published(local_path, url, wait=(0, 30, 30, 30, 30, 30, 30, 30), fetch=None, sleep=time.sleep):
    """الفحص 3: هل الصفحة المنشورة تحمل أحدث data.json؟ يعيد سجلاً. يعيد المحاولة لأن CDN قد يتأخر دقائق."""
    with open(local_path, encoding="utf-8") as f:
        mine = json.load(f)
    want = mine.get("published_at")
    rec = {"check": "published", "title": "data.json المنشور", "source": url, "official": want or "", "fetched_at": "", "value": "", "match": "", "note": ""}
    if not want or not url:
        rec.update(match="تعذّر الجلب", note="لا published_at محلي أو لا رابط للصفحة")
        return rec
    seen = ""
    for i, w in enumerate(wait):
        sleep(w)
        try:
            raw = (fetch or _fetch_nocache)(url.rstrip("/") + "/data.json?t=" + str(int(time.time())))
            seen = json.loads(raw.decode("utf-8")).get("published_at", "")
        except Exception as e:  # noqa: BLE001
            seen = f"خطأ {type(e).__name__}"
        rec["fetched_at"] = datetime.now(timezone.utc).isoformat()
        rec["value"] = seen
        if seen == want:
            rec.update(match="مطابق", note=f"تطابق بعد {i + 1} محاولة")
            return rec
    rec.update(match="نسخة قديمة" if seen and not seen.startswith("خطأ") else "تعذّر الجلب", note=f"المنشور: {seen or '—'} | المتوقع: {want}")
    return rec


def _fetch_nocache(url):
    req = urllib.request.Request(url, headers={"User-Agent": "mirsad-verify/1.0", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def check_state_vs_page(state, docs_json_path, now):
    """الفحص 4: كل رقم متحقق في state.json خلال 48 ساعة يجب أن يظهر في data.json (events_past) بنفس القيمة."""
    from datetime import timedelta
    try:
        with open(docs_json_path, encoding="utf-8") as f:
            page = json.load(f)
    except Exception as e:  # noqa: BLE001
        return [{"check": "state_vs_page", "title": "data.json", "match": "تعذّر الجلب", "note": type(e).__name__}]
    shown = {}
    for sec in ("events", "events_past", "events_next"):
        for g in page.get(sec) or []:
            for it in ([g] + (g.get("items") or [])):
                if it.get("title") and it.get("actual"):
                    shown[it["title"]] = it
    out = []
    for eid, rec in ((state or {}).get("actuals") or {}).items():
        t = rec.get("time", "")
        if not rec.get("actual") or rec.get("status") not in ("verified_official", "verified_secondary", "revised"):
            continue
        try:
            if now - datetime.fromisoformat(t) > timedelta(hours=48):
                continue
        except ValueError:
            continue
        it = shown.get(rec.get("title", ""))
        out.append({"check": "state_vs_page", "title": rec.get("title", ""), "source": rec.get("source", ""), "release_time": t, "value": rec["actual"],
                    "period": rec.get("period", ""), "fetched_at": rec.get("received_at", ""), "official": it.get("actual", "") if it else "",
                    "match": "مطابق" if it and it.get("actual") == rec["actual"] else "غائب عن الصفحة" if not it else "غير مطابق",
                    "note": "القيمة في state.json مقابل القيمة في data.json"})
    return out


def summarize(records):
    cnt = {}
    for r in records:
        cnt[r["match"]] = cnt.get(r["match"], 0) + 1
    return cnt


def to_markdown(records, status, quality_text=""):
    L = ["## فحص الأرقام الفعلية — مِرصاد", ""]
    L.append("الملخص: " + "، ".join(f"{k}: {v}" for k, v in sorted(summarize(records).items())))
    L.append(f"BLS: {'تعمل' if status['bls']['ok'] else 'فشلت'} — {status['bls']['detail']} | FRED: {'تعمل' if status['fred']['ok'] else 'فشلت'} — {status['fred']['detail']}")
    L += ["", "| الفحص | المؤشر | المصدر | وقت الإصدار (UTC) | الفترة | المستلم | الرسمي/المقابل | النتيجة | وقت الجلب | ملاحظة |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in records:
        L.append("| " + " | ".join(str(r.get(k, "")).replace("|", "/") for k in
                 ("check", "title", "source", "release_time", "period", "value", "official", "match", "fetched_at", "note")) + " |")
    if quality_text:
        L += ["", "### جودة التشغيل", "```", quality_text, "```"]
    return "\n".join(L)


def run_check(now, state, docs_json_path="docs/data.json", send=None, summary_path=None, out_json="docs/actuals-check.json"):
    """يشغّل الفحوص 1 و2 و4 ويكتب JSON وملخصاً (GITHUB_STEP_SUMMARY). يعيد (سجلات، حالة). فشل ناعم."""
    fred_key = os.environ.get("FRED_API_KEY", "").strip()
    bls_key = os.environ.get("BLS_API_KEY", "").strip() or None
    recs = check_historical(fred_key, now)
    r2, status = check_sources(now, bls_key, fred_key)
    recs += r2 + check_state_vs_page(state, docs_json_path, now)
    try:
        os.makedirs(os.path.dirname(out_json) or ".", exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump({"generated": now.isoformat(), "summary": summarize(recs), "status": status, "records": recs}, f, ensure_ascii=False, indent=1)
    except Exception as e:  # noqa: BLE001
        print("تعذّر كتابة نتائج الفحص:", e)
    import quality
    md = to_markdown(recs, status, quality.render_text(quality.build([], state, now)))
    summary_path = summary_path or os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    print(md)
    if send:
        c = summarize(recs)
        send("🔎 مِرصاد — فحص الأرقام الفعلية\n" + "\n".join(f"{k}: {v}" for k, v in sorted(c.items())) + "\nالتفاصيل في ملخص تشغيل GitHub Actions.")
    return recs, status


if __name__ == "__main__":
    # python verify.py published <local data.json> <page url>  → رمز خروج 1 إن كانت الصفحة قديمة
    if len(sys.argv) >= 4 and sys.argv[1] == "published":
        rec = check_published(sys.argv[2], sys.argv[3])
        md = to_markdown([rec], {"bls": {"ok": True, "detail": "—"}, "fred": {"ok": True, "detail": "—"}})
        sp = os.environ.get("GITHUB_STEP_SUMMARY")
        if sp:
            with open(sp, "a", encoding="utf-8") as f:
                f.write(md + "\n")
        print(md)
        sys.exit(0 if rec["match"] == "مطابق" else 1)
