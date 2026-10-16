# -*- coding: utf-8 -*-
"""فحص قبول v0.19 في متصفح حقيقي (Chromium عبر Playwright). يُشغَّل يدوياً: python tests_browser.py [مجلد_اللقطات]
يغطي: ترتيب الموبايل بلا تكرار، بطاقة «تحديث مهم» (الاطلاع/الحفظ/عدم التكرار)، فتح الحدث برابط ثابت، تحديث لاحق على إشعار قديم،
نبض الأسواق (ألوان الأثر والسهم)، جدول الكمبيوتر، تلوين الخلفية، الجرس بلا تكرار ولا صوت عند أول تحميل، وضع المراقبة،
فشل التحديث والتقادم والتعافي، حفظ آخر لقطة صالحة عند استجابة معيبة، أحجام 320/375/430/768/1366/1920 وتكبير 200%، تطابق الأرقام بين الجهازين.
المتطلبات: pip install playwright (Chromium مثبّت مسبقاً أو playwright install chromium). لا يرسل تنبيهات ولا ينشر شيئاً (خادم محلي فقط)."""
import copy
import json
import os
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)


def build_fixture():
    """data.json حقيقي البنية من المسار الكامل (محاكاة مصادر): موثق رسمي وثانوي، خبر غير موثق، غير مدعوم، بانتظار."""
    import runner as r
    import tests_auction as ta
    import tests_macro as tm
    from tests_actuals import mk_deps, bls_rows, fred_rows
    from tests_runner import Box, calm_intraday, deps
    now = ta.NOW

    def raw(title, h, forecast="0.3%", previous="0.2%", impact="High"):
        return {"title": title, "country": "USD", "impact": impact, "date": (now - timedelta(hours=h)).isoformat(), "forecast": forecast, "previous": previous}
    evs = [raw("Unemployment Rate", 3, "4.2%", "4.3%"), raw("CPI m/m", 3), raw("Unemployment Claims", 3, "230K", "225K"),
           raw("ISM Manufacturing PMI", 3, "49.0", "48.5"), raw("Retail Sales m/m", 3), raw("Advance GDP q/q", 3, "2.0%", "3.0%"),
           raw("Fed Chair Powell Speaks", 2, "", "")]
    d = deps(evs, calm_intraday())
    d.update(mk_deps(bls_rows, lambda: {"claims": [("2026-09-26", 225000.0)], **{k: v for k, v in fred_rows().items() if k not in ("claims", "retail")}}))
    d["fetch_heads_q"] = lambda q: ["US jobless claims rise to 231,000 in latest week"] if "jobless" in q.lower() or "claims" in q.lower() else []
    d["es5m"] = lambda n: ta.synthetic(ta.PRIOR, ta.TODAY, on_drift=+30.0)
    d["macro"] = lambda n: (tm.base_series(m3=4.1, m6=3.8, y1=3.6), [])
    r.run_preopen(now, {"seen_events": [], "last_shock": None}, Box(), d)
    v = json.load(open(os.path.join(d["docs_dir"], "data.json"), encoding="utf-8"))
    for e in v.get("events_past", []):                      # حالة «مراجَع» (لا تُنتج بسهولة من التشغيل الواحد)
        for it in (e.get("items") or [e]):
            if it.get("title") == "CPI m/m":
                it["status"], it["status_ar"], it["revised_from"] = "revised", "صدرت مراجعة للقيمة", "0.3%"
    v["published_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    return v




def rich(fx):
    """نسخة غنية من اللقطة: انحياز متاح، تحديث مهم غير مقروء، حركة أقدم، خبر قادم، نبض متعدد الألوان. أرقام المحاكاة فقط."""
    import copy
    from datetime import datetime, timedelta, timezone
    v = copy.deepcopy(fx)
    now = datetime.now(timezone.utc)
    iso = lambda m: (now - timedelta(minutes=m)).isoformat()
    v["published_at"] = now.isoformat()
    v["updated"] = (now + timedelta(hours=3)).strftime("%H:%M")
    comps = [{"key": "fed", "name": "ميل الفدرالي", "arrow": "▼", "tone": "pressure", "note": "متشدد (ثقة متوسطة)", "contribution": -0.12},
             {"key": "events", "name": "الإصدارات الموثّقة", "arrow": "▼", "tone": "pressure", "note": "CPI أعلى من المتوقع بـ 0.2 نقطة مئوية ← أثر أولي ضاغط", "contribution": -0.10},
             {"key": "credit", "name": "الائتمان", "arrow": "▲", "tone": "support", "note": "الفروق هادئة", "contribution": 0.06}]
    v["bias"] = dict(v.get("bias") or {}, available=True, coverage=0.8, label="مختلط", key="neutral", arrow="◆", components=comps, missing=[],
                     confirm={"key": "mixed", "label": "مختلط", "why": "الدولار يؤكد والعوائد لا تؤكد"})
    v["verdict"] = {
        "available": True, "advice": "النصيحة الآن: الخلفية مختلطة: لا ميزة ماكروية واضحة، فاعتمد على السياق الأسبوعي والإيقاع اليومي وتدفق الأوامر.",
        "lean": {"key": "up", "label": "صعودي", "basis": "ES فوق قيمة الأمس (قراءة تجريبية)"},
        "bias": {"key": "neutral", "label": "مختلط", "arrow": "◆", "available": True},
        "relation": "أحدهما محايد، فلا تعارض لكن لا قناعة كاملة باتجاه واحد.",
        "news_relation": "الخبر (CPI m/m) ضاغط، لكن التقييم العام ما زال مختلطًا لأن الائتمان هادئ وميل الفدرالي لم يتغير.",
        "confidence": "متوسطة", "intensity": {"score": 5, "word": "متوسطة"}, "reason": "ميل الفدرالي ▼؛ الإصدارات الموثّقة ▼",
        "drivers": [{"name": c["name"], "arrow": c["arrow"], "tone": c["tone"], "note": c["note"], "contribution": c["contribution"]} for c in comps],
        "confirms": ["CPI أعلى من المتوقع ← أثر أولي ضاغط", "تأكيد السوق: العوائد ترتفع"], "invalidates": ["تراجع العوائد والدولار مع استعادة ES قيمة الأمس"],
        "news": {"state": "integrated", "text": "أُخذ آخر خبر مهم بالحسبان: CPI m/m", "ids": ["US|cpi|2026-09|2026-10-14"]}, "change": None,
        "market": {"key": "na", "label": "تقييم أولي — تأكيد السوق غير متاح بعد", "mult": 1.0, "move": {}},
        "assessed_at": now.isoformat(), "assessed_at_ar": "15:00", "last_ok_at": now.isoformat(), "last_ok_at_ar": "15:00",
        "signature": {"bias": "neutral", "bias_label": "مختلط", "lean": "up", "at": now.isoformat(), "ok_at": now.isoformat(), "change": None},
        "method": "قواعد شفافة غير معايَرة؛ ليست توصية.", "workflow": "ماكرو ← سياق أسبوعي ← إيقاع يومي ← تدفق الأوامر"}
    v["safety"] = {"state": "ok", "label": "يعمل بصورة طبيعية", "issues": []}
    v["alerts"] = [
        {"id": "US|cpi|2026-09|2026-10-14", "t": iso(12), "kind": "release", "icon": "📥", "important": True, "rev": 0, "title": "التضخم (CPI)",
         "what": "صدر CPI m/m: الفعلي 0.5% مقابل المتوقع 0.3%", "surprise": "أعلى من المتوقع بـ 0.2 نقطة مئوية",
         "why": "تضخم أعلى يرفع احتمال بقاء الفائدة مرتفعة فيضغط على تقييمات الأسهم.",
         "numbers": {"actual": "0.5%", "forecast": "0.3%", "previous": "0.3%", "revised_from": "", "prev_revised": ""},
         "source": "BLS (رسمي)", "trust": "official", "period": "2026-09", "status": "verified_official", "verification": "استُلمت القيمة من مصدر رسمي",
         "reaction": 0.12, "assessment": {"before": "داعم", "after": "مختلط", "changed": True, "text": "الإصدار ضاغط لكن الخلفية لم تنقلب كلياً.", "market": "تقييم أولي — تأكيد السوق غير متاح بعد", "market_key": "na"}, "updates": []},
        {"id": "move|202610140900|es-oil", "t": iso(300), "kind": "move", "icon": "📉", "important": True, "rev": 0, "title": "حركة كبيرة في السوق (النفط)",
         "what": "حركة كبيرة في السوق (النفط)", "why": "النفط يهبط مع ارتفاع ES", "rows": [{"name": "النفط", "c60": "-0.9%", "c180": "-1.3%", "lead": True}],
         "confirm": ["الزخم والحجم متوافقان"], "pattern": [], "headlines": []},
        {"id": "late|old1", "t": iso(2000), "kind": "late", "icon": "📥", "important": True, "rev": 1, "title": "مبيعات التجزئة", "what": "وصل متأخراً: مبيعات التجزئة 0.4%",
         "why": "", "numbers": {"actual": "0.4%", "forecast": "0.3%", "previous": "0.2%"}, "source": "FRED (ثانوي)", "verification": "استُلمت من مصدر ثانوي",
         "updates": [{"t": iso(1500), "text": "مراجعة: الفعلي من 0.2% إلى 0.4%", "kind": "revision"}], "updated_at": iso(1500)}]
    at = now + timedelta(minutes=95)
    v["next_event"] = {"name": "محضر اجتماع الفدرالي", "time": (at + timedelta(hours=3)).strftime("%H:%M"), "day": "اليوم", "high": True, "importance": "High", "at": at.isoformat(), "in_min": 95,
                       "forecast": "", "previous": "", "what": "تفاصيل نقاش الفدرالي حول الفائدة",
                       "scenarios": [{"k": "above", "label": "نبرة متشددة", "es": "bear", "text": ""}, {"k": "below", "label": "نبرة تيسيرية", "es": "bull", "text": ""}]}
    mk = lambda sym, name, key, last, chg, unit, color, eff, tier, new=False, w=None: {"sym": sym, "name": name, "key": key, "available": True, "last": last, "chg": chg, "unit": unit,
          "arrow": "▲" if chg > 0 else "▼" if chg < 0 else "◆", "tone": "", "color": color, "effect": eff, "confirm": "yes", "tier": tier, "window": "منذ إغلاق أمس", "time": "15:00", "src": "Yahoo", "windows": w, "new": new}
    v["pulse8"] = [mk("DXY", "الدولار (DXY)", "dxy", 104.3, 0.45, "pct", "pressure", "يضغط على ES", 2, True, {"c15": "+0.10%", "c60": "+0.30%", "c180": "+0.45%", "confirmed": True, "why": ""}),
                   mk("10Y", "عائد 10 سنوات", "y10", 4.31, 6, "bp", "pressure", "يضغط على ES", 2), mk("WTI", "النفط (WTI)", "oil", 69.5, -1.3, "pct", "mixed", "أثر مختلط/مشروط: (تفسير مرجَّح)", 1),
                   mk("ES", "عقود S&P (ES)", "es", 5900, 0.2, "pct", "support", "حركة ES نفسه: صاعد", 1), mk("Gold", "الذهب", "gold", 2650, -0.4, "pct", "support", "يدعم ES", 0),
                   mk("VIX", "مؤشر التقلب VIX", "vix", 13, -1, "pct", "calm", "هادئ — أثر محدود", 0), mk("2Y", "عائد سنتين", "y2", 4.5, 0, "bp", "calm", "هادئ — أثر محدود", 0),
                   {"sym": "NQ", "name": "ناسداك (NQ)", "key": "nq", "available": False, "color": "na", "effect": "غير متاح", "tier": -1, "new": False}]
    v["events_past"] = [{"time": "15:30", "day": "اليوم", "title": "CPI m/m", "name": "التضخم (CPI)", "high": True, "released": True, "actual": "0.5%", "forecast": "0.3%", "previous": "0.3%", "surprise": "أعلى من المتوقع بـ 0.2", "surprise_num": "+0.2pp",
                         "source": "BLS (رسمي)", "trust": "official", "status": "verified_official", "verified": True, "revision": "", "verdict": {"es": "bear", "k": "above", "label": "أعلى من المتوقع", "effect": "ضغط على ES"}, "items": []},
                        {"time": "15:30", "day": "اليوم", "title": "Retail Sales m/m", "name": "مبيعات التجزئة", "high": True, "released": True, "actual": "", "forecast": "0.3%", "previous": "0.2%", "status": "awaiting", "items": []}]
    return v


def fresh_alert(v, aid="release|new1", rev=0, text="صدر PCE: الفعلي 0.3%"):
    from datetime import datetime, timezone
    v["alerts"] = [{"id": aid, "t": datetime.now(timezone.utc).isoformat(), "kind": "release", "icon": "📥", "important": True, "rev": rev, "title": "PCE", "what": text, "why": "x",
                    "numbers": {"actual": "0.3%", "forecast": "0.3%", "previous": "0.2%"}, "source": "BLS", "verification": "مُتحقَّق", "assessment": None, "updates": []}] + v["alerts"]
    return v


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def main(shots):
    import copy
    import urllib.parse
    from playwright.sync_api import sync_playwright
    base = build_fixture()
    fx = rich(base)
    os.makedirs(shots, exist_ok=True)
    root = tempfile.mkdtemp()
    for f in ("index.html", "manifest.webmanifest"):
        open(os.path.join(root, f), "wb").write(open(f, "rb").read())
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    mode = {"m": "good", "data": fx}
    fails, log = [], []

    def check(cond, msg):
        log.append(("✔ " if cond else "✘ ") + msg)
        if not cond:
            fails.append(msg)

    def handler(route):
        m = mode["m"]
        if m == "good":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(mode["data"], ensure_ascii=False))
        elif m == "404":
            route.fulfill(status=404, body="nf")
        elif m == "500":
            route.fulfill(status=500, body="err")
        elif m == "badjson":
            route.fulfill(status=200, content_type="application/json", body="{not json")
        elif m == "error":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"live": True, "updated": "x", "error": "بيانات غير كافية لحساب مقياس موثوق"}, ensure_ascii=False))
        elif m == "abort":
            route.abort()

    WEEKDAY = "Date.prototype.getUTCDay = function(){ return 3; };"        # الاختبار لا يتوقف على يوم تشغيله
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        errs = []

        def newpage(w=390, h=900, zoom=1, ctx=None):
            c = ctx or b.new_context(viewport={"width": w, "height": h}, device_scale_factor=zoom, permissions=[])
            q = c.new_page(); q.add_init_script(WEEKDAY)
            q.on("pageerror", lambda e: errs.append(str(e)))
            q.route("**/data.json*", handler)
            return c, q

        # ===== 1) بدء بلا بيانات: لا عرض تجريبي تلقائي والرسالة تطابق السلوك =====
        mode["m"] = "404"
        c, pg = newpage(375, 800)
        pg.goto(url); pg.wait_for_timeout(1200)
        t = pg.locator("#banner").inner_text()
        check("لا تُعرض بيانات تجريبية" in t and "المعروض مثال توضيحي" not in t and "بيانات حقيقية —" not in t, "بدء بلا بيانات: الرسالة تطابق السلوك (لا مثال تلقائي)")
        check(pg.evaluate("document.getElementById('output').hidden") is True, "بدء بلا بيانات: المحتوى مخفي (render0_)")
        pg2 = c.new_page(); pg2.route("**/data.json*", handler); pg2.add_init_script(WEEKDAY)
        pg2.goto(url + "?demo=1"); pg2.wait_for_timeout(1200)
        check("demo=1" in pg2.locator("#banner").inner_text() and pg2.evaluate("document.getElementById('output').hidden") is False, "?demo=1 وحده يعرض المثال ويقول ذلك")
        pg2.close()

        # ===== 2) نجاح + ترتيب الموبايل =====
        mode["m"] = "good"
        pg.click("#refreshBtn"); pg.wait_for_timeout(1500)
        t = pg.locator("#banner").inner_text()
        check("بيانات حقيقية —" in t and "⚠" not in t, "التعافي بعد البدء الفاشل: يزول التحذير")
        order = pg.evaluate("[...document.querySelectorAll('#tab-today > *')].filter(e=>!e.hidden && e.offsetParent).map(e=>e.id)")
        check(order == ["updCard", "mainCard", "nextCard", "pulseSec", "toDetails"], f"ترتيب الموبايل: تحديث، تقرير، خبر قادم، نبض، تفاصيل — {order}")
        gone = pg.evaluate("['top3Card','moveCard','pulseCard','alertCard','pulse8Card','secCard'].filter(i=>document.querySelector('#tab-today #'+i))")
        check(not gone, f"لا أقسام مكررة في اليوم (ماذا تغيّر/الحركات/النبض القديم) {gone}")
        check(pg.locator("#pcards .pc").count() == 8, "نبض الأسواق: بطاقة واحدة لكل مؤشر (8)")
        check(pg.locator("#ntab").is_visible() is False, "جدول الأخبار العريض غير ظاهر على الموبايل")
        adv = pg.locator("#mAdvice").inner_text()
        check(adv.startswith("النصيحة الآن:"), "التقرير يبدأ بـ «النصيحة الآن:»")
        mt = pg.locator("#mainCard").inner_text()
        for needle, name in (("الميل", "الميل"), ("الانحياز الماكروي", "الانحياز"), ("الثقة", "الثقة"), ("الحدة", "الحدة"), ("يؤكّد السيناريو", "يؤكد"), ("يُبطله", "يبطل"),
                             ("آخر تقييم ناجح", "وقت آخر تقييم"), ("أُخذ آخر خبر مهم بالحسبان", "حالة آخر خبر"), ("الخبر (CPI m/m) ضاغط، لكن التقييم العام ما زال مختلطًا لأن", "علاقة الخبر بالتقييم")):
            check(needle in mt, f"التقرير الرئيسي يعرض: {name}")
        check(pg.locator("#mDrivers li").count() <= 3, "أهم العوامل: ثلاثة كحد أقصى")
        check(pg.locator("#updCard").is_visible() and "CPI" in pg.locator("#updTitle").inner_text() and "+1 غير مقروء" in pg.locator("#updCount").inner_text(), "تحديث مهم: الأهم أولاً مع عدد غير المقروء")
        ut = pg.locator("#updCard").inner_text()
        for needle in ("ماذا حدث؟", "لماذا يهم ES؟", "ما الذي تغيّر في التقييم؟", "التقييم السابق لم يعد صالحًا — تغيّر الانحياز من داعم إلى مختلط", "0.5%", "BLS", "حالة التحقق"):
            check(needle in ut, f"تحديث مهم يتضمن: {needle}")
        check("اليوم" in pg.locator("#updMeta").inner_text() or "بتوقيت بغداد" in pg.locator("#updMeta").inner_text(), "تحديث مهم: وقته بتوقيت بغداد")

        # ===== 3) الاطلاع والحفظ وعدم التكرار =====
        pg.wait_for_timeout(2500)
        check(pg.locator("#updCard").is_visible(), "البطاقة لا تختفي بمؤقت قبل الاطلاع")
        pg.click("#updRead"); pg.wait_for_timeout(200)
        t2 = pg.locator("#updTitle").inner_text() if pg.locator("#updCard").is_visible() else ""
        check(pg.locator("#updCard").is_visible() and "النفط" in t2, "بعد «اطّلعت» يظهر التالي غير المقروء (الحركة)")
        pg.click("#updRead"); pg.wait_for_timeout(200)
        check(not pg.locator("#updCard").is_visible(), "بعد قراءة الكل تختفي البطاقة من المقدمة")
        pg.evaluate("showTab('details')")
        check(pg.locator("#logList .lrow").count() == 3 and pg.locator("#logList .lrow.unread").count() == 0, "السجل يحتفظ بالأحداث الثلاثة وكلها مقروءة")
        pg.evaluate("showTab('today')")
        pg.reload(); pg.wait_for_timeout(1200)
        check(not pg.locator("#updCard").is_visible(), "بعد إعادة الفتح لا يُقدَّم الحدث القديم كأنه جديد")
        pg.click("#refreshBtn"); pg.wait_for_timeout(900)
        check(not pg.locator("#updCard").is_visible(), "التحديث الدوري لا يعيد الحدث المقروء")
        # تحديث لاحق على حدث مقروء (rev أعلى) يعود غير مقروء
        d2 = copy.deepcopy(fx); d2["published_at"] = fx["published_at"]; d2["updated"] = "15:30"
        d2["alerts"][0]["rev"] = 1; d2["alerts"][0]["updates"] = [{"t": d2["alerts"][0]["t"], "text": "مراجعة: الفعلي من 0.5% إلى 0.4%", "kind": "revision"}]; d2["alerts"][0]["updated_at"] = d2["alerts"][0]["t"]
        mode["data"] = d2; pg.click("#refreshBtn"); pg.wait_for_timeout(1000)
        check(pg.locator("#updCard").is_visible() and "تحديث لاحق" in pg.locator("#updMeta").inner_text(), "مراجعة لاحقة تعيد الحدث غير مقروء مع وسم «تحديث لاحق»")
        pg.click("#updOpen"); pg.wait_for_timeout(300)
        dtxt = pg.locator("#evBody").inner_text()
        check(pg.locator("#evDlg").evaluate("d=>d.open") and "ثم حدث بعده ما يلي" in dtxt and "من 0.5% إلى 0.4%" in dtxt, "فتح الحدث يعرض تصحيحه اللاحق مع توقيت الإشعار الأصلي")
        pg.click("#evClose"); pg.wait_for_timeout(100)
        check(not pg.locator("#updCard").is_visible(), "فتح التفاصيل يُعدّ اطلاعاً")
        mode["data"] = fx

        # ===== 4) رابط ثابت من إشعار =====
        c3, q3 = newpage(390, 900)
        aid = urllib.parse.quote("US|cpi|2026-09|2026-10-14", safe="")
        q3.goto(url + "#e=" + aid); q3.wait_for_timeout(1500)
        check(q3.locator("#evDlg").evaluate("d=>d.open") and "صدر CPI m/m" in q3.locator("#evBody").inner_text(), "الإشعار يفتح الحدث نفسه مباشرة بمعرّفه الثابت")
        check("0.5%" in q3.locator("#evBody").inner_text() and "BLS" in q3.locator("#evBody").inner_text(), "نافذة الحدث تحمل الأرقام والمصدر")
        q3.click("#evClose"); q3.wait_for_timeout(100)
        check("#e=" not in q3.url, "إغلاق الحدث ينظف الرابط")
        q3.goto(url + "#e=" + urllib.parse.quote("nope|x", safe="")); q3.wait_for_timeout(1200)
        check("غير موجود في السجل" in q3.locator("#evBody").inner_text(), "معرّف غير معروف: رسالة صريحة")
        q3.goto(url + "#e=" + urllib.parse.quote("late|old1", safe="")); q3.wait_for_timeout(1200)
        ot = q3.locator("#evBody").inner_text()
        check("هذا تنبيه أُرسل الساعة" in ot and "مراجعة: الفعلي من 0.2% إلى 0.4%" in ot, "إشعار قديم: يعرض توقيته وتصحيحه اللاحق")
        c3.close()

        # ===== 5) نبض الأسواق: الألوان والأسهم =====
        pg.evaluate("localStorage.clear()"); pg.reload(); pg.wait_for_timeout(1200)
        cls = pg.evaluate("Object.fromEntries([...document.querySelectorAll('#pcards .pc')].map(e=>[e.querySelector('.n').textContent, e.className]))")
        check("pressure" in cls["الدولار (DXY)"] and "isnew" in cls["الدولار (DXY)"], "الدولار الصاعد: إطار أحمر (ضاغط) لا أخضر، وعليه «تغيّر جديد»")
        check("support" not in cls["الدولار (DXY)"], "ارتفاع الدولار ليس أخضر")
        check("mixed" in cls["النفط (WTI)"] and "support" in cls["الذهب"] and "na" in cls["ناسداك (NQ)"], "كهرماني للمشروط/أخضر للداعم/رمادي لغير المتاح")
        first = pg.evaluate("document.querySelector('#pcards .pc .n').textContent")
        check(first == "الدولار (DXY)", "الأكثر تأثيراً أولاً")
        check("calm" not in cls["مؤشر التقلب VIX"] and "support" not in cls["مؤشر التقلب VIX"] and "pressure" not in cls["مؤشر التقلب VIX"], "الهدوء بلا لون دعم أو ضغط")
        dx = pg.locator("#pcards .pc").first
        check("▲" in dx.inner_text() and "تغيّر جديد" in dx.inner_text(), "السهم يعكس حركة المؤشر نفسه + وسم تغيّر جديد")
        dx.locator(".pcb").click(); pg.wait_for_timeout(100)
        check("المقارنة الزمنية" in dx.inner_text() and "15 د" in dx.inner_text() and "المصدر" in dx.inner_text(), "الضغط على البطاقة يفتح المصدر والمقارنات الزمنية")
        check(pg.evaluate("getComputedStyle(document.querySelector('#pcards .pc.isnew')).animationName") in ("none", ""), "لا وميض على البطاقة الجديدة")

        # ===== 6) السجل والتفاصيل =====
        pg.evaluate("showTab('details')"); pg.wait_for_timeout(100)
        check(pg.locator("#logList .lrow").count() == 3 and pg.locator("#logList .lrow.unread").count() >= 1, "السجل: ثلاثة أحداث بعد مسح التخزين (غير المقروء أحدثها)")
        pg.screenshot(path=os.path.join(shots, "details_log_375.png"))
        pg.evaluate("showTab('today')")

        # ===== 7) فشل التحديث/استجابة معيبة تحافظ على آخر لقطة صالحة =====
        good_time = pg.evaluate("loadedAt"); adv0 = pg.locator("#mAdvice").inner_text()
        for m, kind in (("500", "الخادم رفض"), ("abort", "لا اتصال"), ("badjson", "تالف"), ("error", "المصدر أبلغ")):
            mode["m"] = m
            pg.click("#refreshBtn"); pg.wait_for_timeout(1300)
            t = pg.locator("#banner").inner_text()
            check("تعذّر التحديث — تُعرض آخر لقطة صالحة" in t and kind in t and "بيانات حقيقية —" not in t, f"فشل {m}: تحذير + السبب + اللقطة السابقة")
            check(pg.evaluate("loadedAt") == good_time and pg.locator("#mAdvice").inner_text() == adv0, f"فشل {m}: وقت الجلب الناجح واللقطة لم يتغيرا")
            pg.wait_for_timeout(3100)
        mode["m"] = "good"
        bad = copy.deepcopy(fx); bad["pulse8"][0] = None; bad["updated"] = "99:99"; mode["data"] = bad            # استجابة صالحة JSON لكنها تكسر العرض
        pg.click("#refreshBtn"); pg.wait_for_timeout(1300)
        t = pg.locator("#banner").inner_text()
        check("تعذّر عرض البيانات" in t and "آخر لقطة صالحة" in t, "استجابة معيبة العرض: رسالة «تعذّر عرض البيانات» مع الإبقاء على آخر لقطة")
        check(pg.evaluate("loadedAt") == good_time and "99:99" not in pg.locator("#banner").inner_text() and pg.locator("#pcards .pc").count() == 8 and pg.locator("#mAdvice").inner_text() == adv0, "الاستجابة المعيبة لا تُعدّ نجاحاً ولا تستبدل اللقطة الصالحة")
        nov = copy.deepcopy(fx); del nov["verdict"]; mode["data"] = nov
        pg.wait_for_timeout(3100); pg.click("#refreshBtn"); pg.wait_for_timeout(1000)
        check("بنية اللقطة ناقصة" in pg.locator("#banner").inner_text(), "لقطة بلا verdict تُرفض")
        mode["data"] = fx; pg.wait_for_timeout(3100); pg.click("#refreshBtn"); pg.wait_for_timeout(1000)
        check("⚠" not in pg.locator("#banner").inner_text() and pg.evaluate("loadedAt") > good_time, "التعافي: يزول التحذير ويتقدم وقت الجلب")

        # ===== 8) التقادم =====
        old = copy.deepcopy(fx); from datetime import datetime, timedelta, timezone
        old["published_at"] = (datetime.now(timezone.utc) - timedelta(minutes=140)).isoformat(); mode["data"] = old
        pg.click("#refreshBtn"); pg.wait_for_timeout(1000)
        check("قد تكون البيانات قديمة" in pg.locator("#banner").inner_text() and "التقييم غير صالح الآن: البيانات قديمة" in pg.locator("#mChange").inner_text(), "التقادم: تحذير + التقييم يُعلَن غير صالح بسببه")
        check(pg.locator("#mainCard").get_attribute("data-key") == "na", "التقادم: بطاقة التقرير رمادية")
        mode["data"] = fx; pg.wait_for_timeout(3100); pg.click("#refreshBtn"); pg.wait_for_timeout(1000)
        check(pg.locator("#mainCard").get_attribute("data-key") == "mixed" and not pg.locator("#mChange").is_visible(), "التعافي من التقادم")

        # ===== 9) سطح المكتب: جدول، تلوين، جرس، مراقبة =====
        cd, dp = newpage(1366, 800)
        dp.goto(url); dp.wait_for_timeout(1500)
        order = dp.evaluate("[...document.querySelectorAll('#tab-today > *')].filter(e=>!e.hidden && e.offsetParent).map(e=>e.id)")
        check(order[:2] == ["updCard", "mainCard"] and "newsTable" in order and "pulseSec" in order, f"الكمبيوتر: تحديث ثم تقرير ثم نبض وجدول {order}")
        r = dp.evaluate("(()=>{const a=document.getElementById('mainCard').getBoundingClientRect(), n=document.getElementById('nextCard').getBoundingClientRect(), p=document.getElementById('pulseSec').getBoundingClientRect(); return [a.top, n.top, a.width, p.width, document.getElementById('pcards').children.length, getComputedStyle(document.getElementById('pcards')).gridTemplateColumns.split(' ').length]})()")
        check(abs(r[0] - r[1]) < 40 and r[3] > r[2] and r[5] == 4, f"الكمبيوتر: التقرير والخبر القادم جنباً إلى جنب والنبض بعرض كامل في 4 أعمدة {r}")
        hdr = dp.evaluate("[...document.querySelectorAll('#ntab th')].map(t=>t.textContent)")
        check(hdr == ["الوقت", "الحدث", "Actual", "Forecast", "Previous", "Revision", "Surprise", "المصدر"], f"جدول الأخبار: الأعمدة المطلوبة {hdr}")
        check("0.5%" in dp.locator("#ntbody").inner_text() and "BLS" in dp.locator("#ntbody").inner_text() and "بانتظار الرقم" in dp.locator("#ntbody").inner_text(), "جدول الأخبار: أرقام وصدر وبانتظار")
        check(dp.locator("#moreNews").is_visible() is False, "الكمبيوتر: لا قائمة موبايل مكررة")
        check(dp.locator(".scch").is_visible() and dp.locator("#mConfirms").is_visible() and dp.locator("#mInvalid").is_visible(), "السيناريو وعلامات التأكيد والإبطال ظاهرة")
        dp.screenshot(path=os.path.join(shots, "desktop_1366.png"))
        # تلوين
        dp.evaluate("showTab('settings')")
        bg0 = dp.evaluate("getComputedStyle(document.body).backgroundColor")
        dp.check("#tintOpt"); dp.wait_for_timeout(100)
        check(dp.evaluate("document.body.classList.contains('tint-mixed')") and dp.evaluate("getComputedStyle(document.body).backgroundColor") != bg0, "تلوين الخلفية: مختلط = كهرماني")
        pr = copy.deepcopy(fx); pr["verdict"]["bias"] = {"key": "pressure", "label": "ضاغط", "arrow": "▼", "available": True}; mode["data"] = pr
        dp.click("#refreshBtn"); dp.wait_for_timeout(1000)
        check(dp.evaluate("document.body.classList.contains('tint-pressure')"), "ضاغط = أحمر داكن هادئ")
        sp = copy.deepcopy(fx); sp["verdict"]["bias"] = {"key": "support", "label": "داعم", "arrow": "▲", "available": True}; mode["data"] = sp
        dp.wait_for_timeout(3000); dp.click("#refreshBtn"); dp.wait_for_timeout(1000)
        check(dp.evaluate("document.body.classList.contains('tint-support')"), "داعم = أخضر هادئ")
        inv = copy.deepcopy(fx); inv["verdict"]["available"] = False; inv["verdict"]["reason"] = "التغطية 40% < 50%"; inv["verdict"]["bias"]["available"] = False; mode["data"] = inv
        dp.wait_for_timeout(3000); dp.click("#refreshBtn"); dp.wait_for_timeout(1000)
        dp.evaluate("showTab('today')")
        check(dp.evaluate("document.body.classList.contains('tint-invalid')") and "التغطية 40%" in dp.locator("#mChange").inner_text(), "غير صالح بسبب البيانات = رمادي مع السبب")
        dp.screenshot(path=os.path.join(shots, "desktop_invalid_gray.png"))
        contrast = dp.evaluate("""() => { const lum = c => { const m = c.match(/[\\d.]+/g).map(Number); const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(m[0]) + .7152 * f(m[1]) + .0722 * f(m[2]); };
          const bgOf = e => { while (e) { const c = getComputedStyle(e).backgroundColor; if (c && !/rgba\\(0, 0, 0, 0\\)|transparent/.test(c)) return c; e = e.parentElement; } return 'rgb(255,255,255)'; };
          return ['#mAdvice', '#mReason', '#mStamp', '.pcb .n', '.pcb .e'].map(s => { const e = document.querySelector(s); if (!e) return 99; const a = lum(getComputedStyle(e).color), b = lum(bgOf(e)); return (Math.max(a, b) + .05) / (Math.min(a, b) + .05); }); }""")
        check(min(contrast) >= 4.5, f"وضوح النص فوق الخلفية الملونة: أقل تباين {min(contrast):.1f}")
        mode["data"] = fx; dp.wait_for_timeout(3000); dp.click("#refreshBtn"); dp.wait_for_timeout(1000)
        # الجرس
        n0 = dp.evaluate("__bellLog.length")
        dp.evaluate("showTab('settings')"); dp.click("#bellToggle"); dp.wait_for_timeout(100)
        check("مفعّل" in dp.locator("#bellState").inner_text() and dp.evaluate("localStorage.getItem('mirsad-bell')") == "1", "الجرس: تشغيل وحفظ التفضيل")
        check(dp.evaluate("__bellLog.length") == n0, "الجرس: لا رنين لمجرد التفعيل أو تحميل الصفحة")
        dp.click("#bellTest"); dp.wait_for_timeout(100)
        check(dp.evaluate("!!(window.AudioContext||window.webkitAudioContext)"), "اختبار الصوت يعمل (WebAudio متاح)")
        mode["data"] = fresh_alert(copy.deepcopy(fx), aid="release|boot1"); mode["data"]["published_at"] = datetime.now(timezone.utc).isoformat()
        dp.reload(); dp.wait_for_timeout(1300); dp.evaluate("showTab('today')")
        check(dp.evaluate("__bellLog.length") == 0 and dp.locator("#updCard").is_visible(), f"أول تحميل: لا صوت لكن التحديث غير المقروء ظاهر (رنين={dp.evaluate('__bellLog.length')}، ظاهر={dp.locator('#updCard').is_visible()}، READ={dp.evaluate('localStorage.getItem(\"mirsad-read-v1\")')})")
        nw = copy.deepcopy(fx); fresh_alert(nw); mode["data"] = nw; nw["published_at"] = datetime.now(timezone.utc).isoformat()
        dp.click("#refreshBtn"); dp.wait_for_timeout(1000)
        check(dp.evaluate("__bellLog.length") == 1 and dp.evaluate("__bellLog[0].kind") == "alert", "حدث جديد: رنين واحد")
        dp.wait_for_timeout(3000); dp.click("#refreshBtn"); dp.wait_for_timeout(900); dp.wait_for_timeout(100)
        dp.evaluate("loadData(true)"); dp.wait_for_timeout(900)
        check(dp.evaluate("__bellLog.length") == 1, "تحديثات متكررة بلا جديد: لا تكرار للرنين")
        mode["m"] = "500"; dp.wait_for_timeout(3000); dp.click("#refreshBtn"); dp.wait_for_timeout(1000)
        check(dp.evaluate("__bellLog.length") == 2 and dp.evaluate("__bellLog[1].kind") == "outage", "تعطل البيانات: رنين تحذيري")
        dp.wait_for_timeout(3000); dp.click("#refreshBtn"); dp.wait_for_timeout(1000)
        check(dp.evaluate("__bellLog.length") == 2, "استمرار العطل لا يكرر الرنين")
        mode["m"] = "good"; dp.wait_for_timeout(3000); dp.click("#refreshBtn"); dp.wait_for_timeout(1000)
        mode["m"] = "500"; dp.wait_for_timeout(3000); dp.click("#refreshBtn"); dp.wait_for_timeout(1000)
        check(dp.evaluate("__bellLog.length") == 3, "عطل جديد بعد تعافٍ: يرنّ من جديد")
        mode["m"] = "good"
        dp.click("#bellBtn"); dp.wait_for_timeout(100)
        check("مكتوم" in dp.locator("#bellState").inner_text() and dp.evaluate("localStorage.getItem('mirsad-bell')") == "0", "كتم الجرس")
        # وضع المراقبة
        dp.click("#watchBtn2"); dp.wait_for_timeout(300)
        fs = dp.evaluate("parseFloat(getComputedStyle(document.getElementById('wBias')).fontSize)")
        check(dp.locator("#watchView").is_visible() and fs >= 80 and "مختلط" in dp.locator("#wBias").inner_text() and dp.locator("#wFull").is_visible(), f"وضع المراقبة: خط كبير ({fs:.0f}px) وزر ملء الشاشة")
        check("الثقة" in dp.locator("#watchView").inner_text() and "الحدة" in dp.locator("#watchView").inner_text() and dp.locator("#wPul .pc").count() == 4, "وضع المراقبة: الثقة والحدة منفصلتان + نبض")
        dp.screenshot(path=os.path.join(shots, "watch_mode_1366.png"))
        dp.click("#wExit"); dp.wait_for_timeout(100)
        check(not dp.locator("#watchView").is_visible(), "الخروج من وضع المراقبة")
        cd.close()

        # ===== 10) الأحجام والتكبير =====
        sums = {}
        for w, h in ((320, 700), (375, 800), (430, 900), (768, 1000), (1366, 800), (1920, 1000)):
            for zoom in (1, 2):
                c2, q = newpage(w // zoom, h // zoom, zoom); mode["m"] = "good"; mode["data"] = fx
                q.goto(url); q.wait_for_timeout(1000)
                for tab in ("today", "week", "macro", "details", "settings"):
                    q.evaluate(f"showTab('{tab}')"); q.evaluate("document.querySelectorAll('details').forEach(d=>d.open=true)"); q.wait_for_timeout(120)
                    sw = q.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
                    check(sw[0] <= sw[1] + 1, f"بلا تمرير أفقي {w}px×{zoom * 100}% تبويب {tab} ({sw[0]}/{sw[1]})")
                q.evaluate("showTab('today')")
                small = q.evaluate("""() => { const bad = []; document.querySelectorAll('#tab-today *').forEach(e => { if (!e.offsetParent || !e.childNodes.length) return;
                    const t = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 3); if (!t) return;
                    const fs = parseFloat(getComputedStyle(e).fontSize); if (fs < 12) bad.push(e.className + ':' + fs); }); return bad.slice(0, 5); }""")
                check(not small, f"الخط ≥ 12px في اليوم عند {w}px×{zoom * 100}% {small or ''}")
                fa = q.evaluate("parseFloat(getComputedStyle(document.getElementById('mAdvice')).fontSize)")
                check(fa >= 17, f"نص النصيحة مقروء ({fa}px) عند {w}px×{zoom * 100}%")
                if zoom == 1:
                    sums[w] = q.evaluate("({adv: document.getElementById('mAdvice').textContent, bias: document.getElementById('mBiasW').textContent, lean: document.getElementById('mLeanW').textContent, conf: document.getElementById('mConfW').textContent, pulse: [...document.querySelectorAll('#pcards .pc')].map(e => e.querySelector('.n').textContent + '|' + (e.querySelector('.p')||{}).textContent + '|' + (e.querySelector('.c')||{textContent:''}).textContent.replace(/\\s+/g,' ').trim()).join(';'), upd: (document.getElementById('updTitle')||{}).textContent})")
                    if w in (320, 375, 430, 768, 1366, 1920):
                        q.screenshot(path=os.path.join(shots, f"today_{w}.png"), full_page=False)
                    if w == 375:
                        q.screenshot(path=os.path.join(shots, "today_375_full.png"), full_page=True)
                c2.close()
        ref = sums[375]
        check(all(v == ref for v in sums.values()), "الأرقام والتقييم متطابقة بين الموبايل والكمبيوتر في كل الأحجام")
        check(not errs, f"لا أخطاء JavaScript {errs[:2]}")
        b.close()
    srv.shutdown()
    print("\n".join(log))
    print(f"\nالنتيجة: {len(log) - len(fails)}/{len(log)} نجح")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), "mirsad-shots"))
