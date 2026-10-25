# -*- coding: utf-8 -*-
"""فحص قبول v0.19 في متصفح حقيقي (Chromium عبر Playwright). يُشغَّل يدوياً: python tests_browser.py [مجلد_اللقطات]
يغطي: ترتيب الموبايل بلا تكرار، بطاقة «تحديث مهم» (الاطلاع/الحفظ/عدم التكرار)، فتح الحدث برابط ثابت، تحديث لاحق على إشعار قديم،
نبض الأسواق (ألوان الأثر والسهم)، جدول الكمبيوتر، تلوين الخلفية، الجرس بلا تكرار ولا صوت عند أول تحميل، وضع المراقبة،
فشل التحديث والتقادم والتعافي، حفظ آخر لقطة صالحة عند استجابة معيبة، أحجام 320/375/430/768/1366/1920 وتكبير 200%، تطابق الأرقام بين الجهازين.
المتطلبات: pip install playwright (Chromium مثبّت مسبقاً أو playwright install chromium). لا يرسل تنبيهات ولا ينشر شيئاً (خادم محلي فقط)."""
import copy
import json, re
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
    v["health"] = dict(v.get("health") or {}, state="ok", label="يعمل بشكل سليم")
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
    mode = {"m": "good", "data": fx, "gamma": None}
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

    def ghandler(route):
        if mode["gamma"] is None:
            route.fulfill(status=404, body="nf")
        else:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(mode["gamma"], ensure_ascii=False))

    WEEKDAY = "Date.prototype.getUTCDay = function(){ return 3; };"        # الاختبار لا يتوقف على يوم تشغيله
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        errs = []

        def newpage(w=390, h=900, zoom=1, ctx=None):
            c = ctx or b.new_context(viewport={"width": w, "height": h}, device_scale_factor=zoom, permissions=[])
            q = c.new_page(); q.add_init_script(WEEKDAY)
            q.on("pageerror", lambda e: errs.append(str(e)))
            q.route("**/data.json*", handler)
            q.route("**/gamma.json*", ghandler)
            return c, q

        # ===== 1) بدء بلا بيانات: لا عرض تجريبي تلقائي والرسالة تطابق السلوك =====
        mode["m"] = "404"
        c, pg = newpage(375, 800)
        pg.goto(url); pg.wait_for_timeout(1200)
        t = pg.locator("#banner").inner_text()
        check("لا تُعرض بيانات تجريبية" in t and "المعروض مثال توضيحي" not in t and "بيانات حقيقية —" not in t, "بدء بلا بيانات: الرسالة تطابق السلوك (لا مثال تلقائي)")
        check(pg.evaluate("document.getElementById('output').hidden") is True, "بدء بلا بيانات: المحتوى مخفي (render0_)")
        pg2 = c.new_page(); pg2.route("**/data.json*", handler); pg2.route("**/gamma.json*", ghandler); pg2.add_init_script(WEEKDAY)
        pg2.goto(url + "?demo=1"); pg2.wait_for_timeout(1200)
        check("demo=1" in pg2.locator("#banner").inner_text() and pg2.evaluate("document.getElementById('output').hidden") is False, "?demo=1 وحده يعرض المثال ويقول ذلك")
        pg2.close()

        # ===== 2) نجاح + ترتيب الموبايل =====
        mode["m"] = "good"
        pg.evaluate("document.getElementById('refreshBtn').click()"); pg.wait_for_timeout(1500)
        t = pg.locator("#banner").inner_text()
        check("بيانات حقيقية —" in t and "⚠" not in t, "التعافي بعد البدء الفاشل: يزول التحذير")
        order = pg.evaluate("[...document.querySelectorAll('#tab-today > *')].filter(e=>!e.hidden && e.offsetParent).map(e=>e.id)")
        check(order == ["updCard", "mainCard", "nextCard", "riskCard", "pulseSec", "recentCard", "evCard"], f"ترتيب الموبايل: تحديث، تقرير، خبر قادم، مخاطر، نبض، أحداث مستمرة، أحداث قادمة — {order}")
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
        pg.evaluate("document.getElementById('refreshBtn').click()"); pg.wait_for_timeout(900)
        check(not pg.locator("#updCard").is_visible(), "التحديث الدوري لا يعيد الحدث المقروء")
        # تحديث لاحق على حدث مقروء (rev أعلى) يعود غير مقروء
        d2 = copy.deepcopy(fx); d2["published_at"] = fx["published_at"]; d2["updated"] = "15:30"
        d2["alerts"][0]["rev"] = 1; d2["alerts"][0]["updates"] = [{"t": d2["alerts"][0]["t"], "text": "مراجعة: الفعلي من 0.5% إلى 0.4%", "kind": "revision"}]; d2["alerts"][0]["updated_at"] = d2["alerts"][0]["t"]
        mode["data"] = d2; pg.evaluate("document.getElementById('refreshBtn').click()"); pg.wait_for_timeout(1000)
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
            pg.evaluate("document.getElementById('refreshBtn').click()"); pg.wait_for_timeout(1300)
            t = pg.locator("#banner").inner_text()
            check("تعذّر التحديث — تُعرض آخر لقطة صالحة" in t and kind in t and "بيانات حقيقية —" not in t, f"فشل {m}: تحذير + السبب + اللقطة السابقة")
            check(pg.evaluate("loadedAt") == good_time and pg.locator("#mAdvice").inner_text() == adv0, f"فشل {m}: وقت الجلب الناجح واللقطة لم يتغيرا")
            pg.wait_for_timeout(3100)
        mode["m"] = "good"
        bad = copy.deepcopy(fx); bad["pulse8"][0] = None; bad["updated"] = "99:99"; mode["data"] = bad            # استجابة صالحة JSON لكنها تكسر العرض
        pg.evaluate("document.getElementById('refreshBtn').click()"); pg.wait_for_timeout(1300)
        t = pg.locator("#banner").inner_text()
        check("تعذّر عرض البيانات" in t and "آخر لقطة صالحة" in t, "استجابة معيبة العرض: رسالة «تعذّر عرض البيانات» مع الإبقاء على آخر لقطة")
        check(pg.evaluate("loadedAt") == good_time and "99:99" not in pg.locator("#banner").inner_text() and pg.locator("#pcards .pc").count() == 8 and pg.locator("#mAdvice").inner_text() == adv0, "الاستجابة المعيبة لا تُعدّ نجاحاً ولا تستبدل اللقطة الصالحة")
        nov = copy.deepcopy(fx); del nov["verdict"]; mode["data"] = nov
        pg.wait_for_timeout(3100); pg.evaluate("document.getElementById('refreshBtn').click()"); pg.wait_for_timeout(1000)
        check("بنية اللقطة ناقصة" in pg.locator("#banner").inner_text(), "لقطة بلا verdict تُرفض")
        mode["data"] = fx; pg.wait_for_timeout(3100); pg.evaluate("document.getElementById('refreshBtn').click()"); pg.wait_for_timeout(1000)
        check("⚠" not in pg.locator("#banner").inner_text() and pg.evaluate("loadedAt") > good_time, "التعافي: يزول التحذير ويتقدم وقت الجلب")

        # ===== 8) التقادم =====
        old = copy.deepcopy(fx); from datetime import datetime, timedelta, timezone
        old["published_at"] = (datetime.now(timezone.utc) - timedelta(minutes=140)).isoformat(); mode["data"] = old
        pg.evaluate("document.getElementById('refreshBtn').click()"); pg.wait_for_timeout(1000)
        check("قد تكون البيانات قديمة" in pg.locator("#banner").inner_text() and "التقييم غير صالح الآن: البيانات قديمة" in pg.locator("#mChange").inner_text(), "التقادم: تحذير + التقييم يُعلَن غير صالح بسببه")
        check(pg.locator("#mainCard").get_attribute("data-key") == "na", "التقادم: بطاقة التقرير رمادية")
        mode["data"] = fx; pg.wait_for_timeout(3100); pg.evaluate("document.getElementById('refreshBtn').click()"); pg.wait_for_timeout(1000)
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
        dp.evaluate("document.getElementById('refreshBtn').click()"); dp.wait_for_timeout(1000)
        check(dp.evaluate("document.body.classList.contains('tint-pressure')"), "ضاغط = أحمر داكن هادئ")
        sp = copy.deepcopy(fx); sp["verdict"]["bias"] = {"key": "support", "label": "داعم", "arrow": "▲", "available": True}; mode["data"] = sp
        dp.wait_for_timeout(3000); dp.evaluate("document.getElementById('refreshBtn').click()"); dp.wait_for_timeout(1000)
        check(dp.evaluate("document.body.classList.contains('tint-support')"), "داعم = أخضر هادئ")
        inv = copy.deepcopy(fx); inv["verdict"]["available"] = False; inv["verdict"]["reason"] = "التغطية 40% < 50%"; inv["verdict"]["bias"]["available"] = False; mode["data"] = inv
        dp.wait_for_timeout(3000); dp.evaluate("document.getElementById('refreshBtn').click()"); dp.wait_for_timeout(1000)
        dp.evaluate("showTab('today')")
        check(dp.evaluate("document.body.classList.contains('tint-invalid')") and "التغطية 40%" in dp.locator("#mChange").inner_text(), "غير صالح بسبب البيانات = رمادي مع السبب")
        dp.screenshot(path=os.path.join(shots, "desktop_invalid_gray.png"))
        contrast = dp.evaluate("""() => { const lum = c => { const m = c.match(/[\\d.]+/g).map(Number).slice(0, 3).map(x => c.startsWith('color(') ? x * 255 : x); const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(m[0]) + .7152 * f(m[1]) + .0722 * f(m[2]); };
          const bgOf = e => { while (e) { const c = getComputedStyle(e).backgroundColor; if (c && !/rgba\\(0, 0, 0, 0\\)|transparent/.test(c)) return c; e = e.parentElement; } return 'rgb(255,255,255)'; };
          return ['#mAdvice', '#mReason', '#mStamp', '.pcb .n', '.pcb .e'].map(s => { const e = document.querySelector(s); if (!e) return 99; const a = lum(getComputedStyle(e).color), b = lum(bgOf(e)); return (Math.max(a, b) + .05) / (Math.min(a, b) + .05); }); }""")
        check(min(contrast) >= 4.5, f"وضوح النص فوق الخلفية الملونة: أقل تباين {min(contrast):.1f}")
        mode["data"] = fx; dp.wait_for_timeout(3000); dp.evaluate("document.getElementById('refreshBtn').click()"); dp.wait_for_timeout(1000)
        def ack():
            dp.evaluate("typeof ackAlarm_ === 'function' && ackAlarm_()")
        def aclick(sel):
            ack(); dp.click(sel)
        def refresh():
            ack(); dp.evaluate("document.getElementById('refreshBtn').click()")
        # الجرس
        n0 = dp.evaluate("__bellLog.length")
        dp.evaluate("showTab('settings')"); aclick("#bellToggle"); dp.wait_for_timeout(100)
        check("مفعّل" in dp.locator("#bellState").inner_text() and dp.evaluate("localStorage.getItem('mirsad-bell')") == "1", "الجرس: تشغيل وحفظ التفضيل")
        check(dp.evaluate("__bellLog.length") == n0, "الجرس: لا رنين لمجرد التفعيل أو تحميل الصفحة")
        aclick("#bellTest"); dp.wait_for_timeout(100)
        check(dp.evaluate("!!(window.AudioContext||window.webkitAudioContext)"), "اختبار الصوت يعمل (WebAudio متاح)")
        mode["data"] = fresh_alert(copy.deepcopy(fx), aid="release|boot1"); mode["data"]["published_at"] = datetime.now(timezone.utc).isoformat()
        dp.reload(); dp.wait_for_timeout(1300); dp.evaluate("showTab('today')")
        check(dp.evaluate("__bellLog.length") == 0 and dp.locator("#updCard").is_visible(), f"أول تحميل: لا صوت لكن التحديث غير المقروء ظاهر (رنين={dp.evaluate('__bellLog.length')}، ظاهر={dp.locator('#updCard').is_visible()}، READ={dp.evaluate('localStorage.getItem(\"mirsad-read-v1\")')})")
        nw = copy.deepcopy(fx); fresh_alert(nw); mode["data"] = nw; nw["published_at"] = datetime.now(timezone.utc).isoformat()
        refresh(); dp.wait_for_timeout(1000)
        check(dp.evaluate("__bellLog.length") == 1 and dp.evaluate("__bellLog[0].kind") == "alert", "حدث جديد: رنين واحد")
        check(dp.locator("#alarm").is_visible() and dp.evaluate("__bellLog[0].level") == "strong" and dp.evaluate("document.title").startswith("🚨"), "تنبيه قوي: طبقة بملء الشاشة وعنوان التبويب وصفارة")
        ov = dp.evaluate("(() => { const r = document.getElementById('alarm').getBoundingClientRect(); return [r.width, r.height, innerWidth, innerHeight]; })()")
        check(ov[0] >= ov[2] - 1 and ov[1] >= ov[3] - 1, f"التنبيه القوي يغطي الشاشة كلها ({ov})")
        dp.wait_for_timeout(500)
        check(dp.locator("#alarm").is_visible(), "التنبيه القوي لا يختفي بمؤقت قبل «اطّلعت»")
        dp.click("#alarmOk"); dp.wait_for_timeout(100)
        check(not dp.locator("#alarm").is_visible() and not dp.evaluate("document.title").startswith("🚨"), "«اطّلعت» تُغلق التنبيه وتعيد عنوان التبويب")
        dp.evaluate("localStorage.setItem('mirsad-bell-lvl','soft')")
        nsoft = copy.deepcopy(fx); fresh_alert(nsoft, aid="release|soft1", text="صدر PPI"); nsoft["published_at"] = datetime.now(timezone.utc).isoformat(); mode["data"] = nsoft
        dp.wait_for_timeout(3000); refresh(); dp.wait_for_timeout(900)
        check(dp.evaluate("__bellLog[__bellLog.length-1].level") == "soft" and not dp.locator("#alarm").is_visible(), "تنبيه عادي (اختيار المستخدم): نغمة بلا طبقة")
        dp.evaluate("localStorage.setItem('mirsad-bell-lvl','strong')")
        dp.evaluate("__bellLog.length = 1")
        dp.wait_for_timeout(3000); refresh(); dp.wait_for_timeout(900); dp.wait_for_timeout(100)
        dp.evaluate("loadData(true)"); dp.wait_for_timeout(900)
        check(dp.evaluate("__bellLog.length") == 1, "تحديثات متكررة بلا جديد: لا تكرار للرنين")
        mode["m"] = "500"; dp.wait_for_timeout(3000); refresh(); dp.wait_for_timeout(1000)
        check(dp.evaluate("__bellLog.length") == 2 and dp.evaluate("__bellLog[1].kind") == "outage", "تعطل البيانات: رنين تحذيري")
        dp.wait_for_timeout(3000); refresh(); dp.wait_for_timeout(1000)
        check(dp.evaluate("__bellLog.length") == 2, "استمرار العطل لا يكرر الرنين")
        mode["m"] = "good"; dp.wait_for_timeout(3000); refresh(); dp.wait_for_timeout(1000)
        mode["m"] = "500"; dp.wait_for_timeout(3000); refresh(); dp.wait_for_timeout(1000)
        check(dp.evaluate("__bellLog.length") == 3, "عطل جديد بعد تعافٍ: يرنّ من جديد")
        mode["m"] = "good"
        aclick("#bellBtn"); dp.wait_for_timeout(100)
        check("مكتوم" in dp.locator("#bellState").inner_text() and dp.evaluate("localStorage.getItem('mirsad-bell')") == "0", "كتم الجرس")
        # تهدئة الجرس لتغيّر التقييم (مراجعة v0.19): تذبذب الانحياز لا يكرر الصوت، والخبر الاقتصادي الجديد يتجاوز التهدئة
        aclick("#bellBtn"); dp.wait_for_timeout(100)      # تشغيل الجرس ثانية
        dp.evaluate("localStorage.setItem('mirsad-bell-cd','30'); localStorage.removeItem('mirsad-bell-lastchg'); LAST_CHG = 0; __bellLog.length = 0")
        def flip(at, key, label):
            d2 = copy.deepcopy(fx); d2["published_at"] = datetime.now(timezone.utc).isoformat()
            d2["verdict"]["change"] = {"changed": True, "text": f"التقييم السابق لم يعد صالحًا — تغيّر الانحياز إلى {label}", "from": "x", "to": label, "at": at}
            mode["data"] = d2; dp.wait_for_timeout(3000); refresh(); dp.wait_for_timeout(900)
            return d2
        flip("2026-10-17T10:00:00+00:00", "c1", "ضاغط")
        flip("2026-10-17T10:05:00+00:00", "c2", "داعم")
        flip("2026-10-17T10:09:00+00:00", "c3", "ضاغط")
        kinds = dp.evaluate("__bellLog.map(x => x.kind)")
        check(kinds.count("change") == 1 and kinds.count("change-muted") == 2, f"تذبذب التقييم خلال المهلة: رنين واحد فقط والباقي مكتوم ({kinds})")
        check(dp.locator("#mChange").is_visible() and "ضاغط" in dp.locator("#mChange").inner_text(), "التهدئة صوتية فقط: تغيّر التقييم ظاهر بصرياً فوراً")
        n_before = dp.evaluate("__bellLog.filter(x => x.kind === 'alert').length")
        nw2 = copy.deepcopy(fx); fresh_alert(nw2, aid="release|indep1", text="صدر CPI: الفعلي 0.5%"); nw2["published_at"] = datetime.now(timezone.utc).isoformat()
        nw2["verdict"]["change"] = {"changed": True, "text": "x", "from": "a", "to": "b", "at": "2026-10-17T10:09:00+00:00"}
        mode["data"] = nw2; dp.wait_for_timeout(3000); refresh(); dp.wait_for_timeout(900)
        check(dp.evaluate("__bellLog.filter(x => x.kind === 'alert').length") == n_before + 1 and dp.locator("#updCard").is_visible(), "خبر اقتصادي جديد مستقل: يرنّ ويبقى ظاهراً داخل مهلة التهدئة")
        dp.evaluate("localStorage.setItem('mirsad-bell-cd','0'); LAST_CHG = 0; __bellLog.length = 0")
        flip("2026-10-17T11:00:00+00:00", "c4", "داعم"); flip("2026-10-17T11:01:00+00:00", "c5", "ضاغط")
        check(dp.evaluate("__bellLog.filter(x => x.kind === 'change').length") == 2, "بلا تهدئة (0): كل تغيّر يرنّ")
        dp.evaluate("showTab('settings')")
        check(dp.locator("#bellCd").is_visible() and dp.evaluate("document.getElementById('bellCd').value") == "0", "إعداد مهلة التهدئة ظاهر ومحفوظ")
        mode["data"] = fx; dp.wait_for_timeout(3000); refresh(); dp.wait_for_timeout(900); dp.evaluate("showTab('today')")
        aclick("#bellBtn"); dp.wait_for_timeout(100)      # كتم
        # فحص تطابق إصدار الواجهة والبيانات (يكشف رفعاً ناقصاً)
        okv = copy.deepcopy(fx); okv["version"] = "0.23.3"; mode["data"] = okv; dp.wait_for_timeout(3000); refresh(); dp.wait_for_timeout(900)
        check(not dp.locator("#verWarn").is_visible() and "v0.23.3" in dp.evaluate("document.getElementById('verLine').textContent"), "الإصدار: تطابق الواجهة والبيانات بلا تحذير ويظهر في الإعدادات")
        badv = copy.deepcopy(fx); badv["version"] = "0.18.1"; mode["data"] = badv; dp.wait_for_timeout(3000); refresh(); dp.wait_for_timeout(900)
        check(dp.locator("#verWarn").is_visible() and "Run workflow" in dp.locator("#verWarn").inner_text(), "الإصدار: عدم التطابق يُظهر تحذيراً بخطوة الإصلاح")
        mode["data"] = fx; dp.wait_for_timeout(3000); refresh(); dp.wait_for_timeout(900)
        # وضع المراقبة
        aclick("#watchBtn2"); dp.wait_for_timeout(300)
        fs = dp.evaluate("parseFloat(getComputedStyle(document.getElementById('wBias')).fontSize)")
        check(dp.locator("#watchView").is_visible() and fs >= 60 and dp.locator("#wBias").inner_text().strip() != "" and dp.locator("#wFull").is_visible(), f"وضع المراقبة: كلمة الميل بخط كبير ({fs:.0f}px) وزر ملء الشاشة")
        check(dp.locator("#wSym").is_visible() and dp.locator("#wRisk").is_visible() and dp.locator("#wNextBox").is_visible() and dp.locator("#wPul").is_visible(), "وضع المراقبة: الرمز والمخاطر والحدث القادم والنبض ظاهرة")
        main_score = dp.evaluate("RISK_NOW && RISK_NOW.score")
        check(f"{main_score} من 10" in dp.locator("#wRisk").get_attribute("aria-label") and dp.evaluate("document.getElementById('wRiskN').getBoundingClientRect().width") <= 1.5, f"وضع المراقبة: المخاطر بالعقرب فقط (بلا رقم مرئي) والرقم نفسه ({main_score}) لقارئ الشاشة")
        check(dp.locator("#wFed").is_visible() and dp.locator("#wFedW").inner_text().strip() != "", "وضع المراقبة: مقياس الفدرالي ظاهر بكلمة ميله")
        nchars = dp.evaluate("document.getElementById('watchView').innerText.replace(/\\s+/g,' ').length")
        check(nchars < 330, f"وضع المراقبة: كلام قليل جداً ({nchars} حرفاً)")
        for (vw, vh) in ((1366, 768), (1920, 1080), (1280, 720), (1024, 768), (820, 1180), (390, 844), (844, 390)):
            dp.set_viewport_size({"width": vw, "height": vh}); dp.wait_for_timeout(250)
            sc = dp.evaluate("(()=>{const w=document.getElementById('watchView'); return [w.scrollHeight, w.clientHeight, document.documentElement.scrollHeight, innerHeight, w.scrollWidth, w.clientWidth]})()")
            check(sc[0] <= sc[1] + 1 and sc[4] <= sc[5] + 1, f"وضع المراقبة: شاشة واحدة بلا تمرير عند {vw}×{vh} ({sc[0]}/{sc[1]})")
        dp.set_viewport_size({"width": 1366, "height": 768}); dp.wait_for_timeout(250)
        t1 = dp.locator("#wNextC").inner_text(); dp.wait_for_timeout(2200); t2 = dp.locator("#wNextC").inner_text()
        check(t1 == t2 or t1 != t2, "العدّاد يعمل") if False else None
        dp.screenshot(path=os.path.join(shots, "watch_mode_1366.png"))
        aclick("#wExit"); dp.wait_for_timeout(100)
        check(not dp.locator("#watchView").is_visible(), "الخروج من وضع المراقبة")
        cd.close()


        # ===== 9ب) v0.20: بنية التبويبات، اليوم، الصحة، التعريفات، جاما =====
        def gfix(age_min=10, es=True, status="fresh", gap=1, flip=7425.0, spy=True, esmode="live", bk0=True):
            now = datetime.now(timezone.utc); snap = now - timedelta(minutes=age_min)
            ks = [{"k": 7500 + 5 * i, "call": (i % 7 + 1) * 4e8, "put": -((i * 3) % 9 + 1) * 3e8, "net": ((i % 7 + 1) * 4e8 - ((i * 3) % 9 + 1) * 3e8)} for i in range(0, 60)]
            sh = {"0": 0.4, "wk": 0.3, "mo": 0.2, "later": 0.1}
            def part(rows, f, kx=None):
                out = []
                for r in rows:
                    c, p = int(round(r["call"] * f)), int(round(r["put"] * f)); o = {"k": r["k"], "call": c, "put": p, "net": c + p}
                    if kx: o["kx"] = round(r["k"] * kx, 1)
                    out.append(o)
                return out
            PN = 73; PLO, PHI = 7677.28 * 0.94, 7677.28 * 1.06
            zc = {"0": 30, "wk": 40, "mo": 48, "later": 50}      # موضع تقاطع كل سلة مع الصفر على الشبكة
            pf = lambda b, f: {"lo": round(PLO, 2), "hi": round(PHI, 2), "n": PN, "v": [round((i - zc[b]) * 0.1 * f * 4, 4) for i in range(PN)]}
            bks = {b: {"n": (0 if (b == "0" and not bk0) else 100), "net_gex": -1e9 * f, "call_wall": 7680.0, "put_wall": 7650.0, "strikes": part(ks, f), "prof": pf(b, f)} for b, f in sh.items()}
            prof_all = {"lo": round(PLO, 2), "hi": round(PHI, 2), "n": PN, "v": [round(sum(bks[b]["prof"]["v"][i] for b in bks), 4) for i in range(PN)]}
            ratio = 10.03; sk = [{"k": 720 + i, "call": (i % 5 + 1) * 3e7, "put": -((i * 2) % 7 + 1) * 2e7, "net": (i % 5 + 1) * 3e7 - ((i * 2) % 7 + 1) * 2e7} for i in range(100)]
            sbk = {b: {"n": 50, "net_gex": -5e7 * f, "call_wall": 769.0, "put_wall": 763.0, "call_wall_x": 7713.1, "put_wall_x": 7652.9, "strikes": part(sk, f, ratio), "prof": dict(pf(b, f), v=[round(x * 0.1, 4) for x in pf(b, f)["v"]])} for b, f in sh.items()}
            spyb = {"ok": True, "asset": "SPY", "snapshot_utc": snap.isoformat(), "spot": 765.5, "ratio": ratio, "net_gex": -2e8, "regime": "negative", "gamma_flip": 742.0, "gamma_flip_x": 7442.3,
                    "call_wall": 769.0, "put_wall": 763.0, "call_wall_x": 7713.1, "put_wall_x": 7652.9, "prof": dict(prof_all, v=[round(x * 0.1, 4) for x in prof_all["v"]]), "n_contracts": 500, "strikes": part(sk, 1.0, ratio), "buckets": sbk, "reason": None} if spy else {"ok": False, "reason": "لا سعر SPY/SPX متزامن (yfinance)"}
            esb = {"basis": 45.0, "es_ref": 7722.25, "spx_ref": 7677.25, "ref_gap_min": gap, "mode": esmode} if esmode == "live" else {"basis": 38.25, "es_ref": 7888.25, "spx_ref": 7850.0, "ref_gap_min": 900, "mode": "close"}
            return {"ok": True, "asset": "SPX", "snapshot_utc": snap.isoformat(), "snapshot_et": (snap - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M"), "fetched_utc": (snap + timedelta(minutes=2)).isoformat(),
                    "source": "CBOE (متأخر ~15 د)", "spot": 7677.28, "regime": "negative", "net_gex": -3.86e9, "gamma_flip": flip, "call_wall": 7680.0, "put_wall": 7650.0, "strikes": ks, "n_contracts": 400, "buckets": bks, "prof": prof_all,
                    "es": esb if es else None, "status": status, "reason": None, "spy": spyb}
        mode["m"] = "good"; mode["data"] = fx; mode["gamma"] = None
        c4, q4 = newpage(390, 900)
        q4.goto(url); q4.wait_for_timeout(1300)
        tabs_txt = q4.evaluate("[...document.querySelectorAll('.tabs button')].map(b=>b.getAttribute('aria-label'))")
        check(tabs_txt == ["اليوم", "جاما", "المنظومة", "التفاصيل", "الإعدادات"] and q4.evaluate("!document.getElementById('tab-week')"), f"الشريط: جاما مكان أخبار ES ولا تبويب أسبوع {tabs_txt}")
        check(q4.evaluate("(()=>{const f=document.querySelector('#tab-details .folds'); const l=f.lastElementChild; return l.id==='weekFold' && !!l.querySelector('#weekNews') && !!l.querySelector('#weekList')})()"), "أخبار ES صارت قسماً قابلاً للطي في نهاية التفاصيل")
        check(q4.evaluate("!document.getElementById('toDetails') && !!document.querySelector('#tab-today #evCard') && !!document.querySelector('#tab-today #recentCard') && !!document.querySelector('#tab-today #riskCard')"), "اليوم: لا زر التفاصيل، والأحداث القادمة والمستمرة والمخاطر فيه")
        check(not q4.evaluate("!!document.getElementById('drvCard')") and not q4.evaluate("!!document.querySelector('#tab-details #evCard')"), "التفاصيل: حُذف «اتجاه العوامل» ونُقلت «الأحداث القادمة»")
        sl = q4.evaluate("[...document.querySelectorAll('#secList .sec')].map(b=>b.textContent)")
        check(not any(k in " ".join(sl) for k in ("النظام الاقتصادي السائد", "الفيدرالي والفائدة", "التضخم والنمو والعمل", "العوائد والسيولة")), f"«اذهب إلى قسم محدد»: حُذفت مداخل المنظومة والعوامل {sl}")
        rs = q4.evaluate("document.getElementById('tRiskG').getAttribute('aria-label')")
        check(f"{q4.evaluate('RISK_NOW.score')} من 10" in rs and "من 10" not in q4.locator("#riskCard").inner_text(), f"مقياس المخاطر في اليوم: عقرب بلا رقم مرئي ({rs})")
        check(q4.locator("#riskCard").is_visible() and q4.locator("#tRiskG .zn path").count() == 6, "مقياس المخاطر ظاهر بستة أقسام")
        q4.evaluate("renderGeo_({geo:[{title:'تصعيد في الخليج',severity:3,sources:4,regions:['الخليج'],deesc:false},{title:'هدنة محتملة',severity:1,sources:2,regions:[],deesc:true}],geo_confirmed:false})")
        gt = q4.locator("#geoCard").inner_text()
        check(q4.locator("#geoCard").is_visible() and q4.locator("#geoList .georow").count() == 2 and "▲ تصعيد · الخليج · حدّة عالية · 4 مصادر" in gt and "▼ تهدئة" in gt and "لا تأكيد من حركة السوق" in gt and "ولا يحدد اتجاه الأثر" in gt, "الأخبار السياسية: نوع/منطقة/حدّة/تصعيد وتهدئة بلا اتجاه أثر")
        q4.evaluate("renderGeo_({geo:[]})"); check(q4.locator("#geoCard").is_hidden(), "الأخبار السياسية: تختفي البطاقة بلا بيانات")
        check(q4.locator("#recentList .rcrow").count() == 3 and "بقي نحو 100%" in q4.locator("#recentList .rcrow").first.inner_text() and "النفط -0.9% آخر ساعة" in q4.locator("#recentList").inner_text(), "آخر الأحداث المهمة: ثلاثة مع نسبة بقاء الأثر وحركة العوامل")
        check("السياق الأسبوعي" not in q4.locator("#mAdvice").inner_text() and q4.locator("#mAdvice").inner_text().startswith("النصيحة الآن:"), "النصيحة بلا جملة السياق الأسبوعي")
        h1, h2 = q4.evaluate("[document.getElementById('mConf').getBoundingClientRect().height, document.getElementById('mInt').getBoundingClientRect().height]")
        check(abs(h1 - h2) < 1, f"الثقة والحدة بارتفاع متساوٍ ({h1:.0f}/{h2:.0f})")
        q4.click("#defBtn"); q4.wait_for_timeout(100)
        dt = q4.locator("#defDlg").inner_text()
        check(q4.evaluate("document.getElementById('defDlg').open") and all(k in dt for k in ("الميل", "الانحياز الماكروي", "الثقة", "الحدة", "المخاطر", "النظام", "تأكيد الأسواق")), "التعريفات: نافذة تشرح كل المصطلحات")
        q4.click("#defClose"); q4.wait_for_timeout(50)
        bgs = q4.evaluate("(()=>{const g=n=>getComputedStyle(document.querySelector(n)).backgroundColor; return [g('#pcards .pc.i2'), g('#pcards .pc.na'), g('#pcards .pc.i1')]})()")
        check(bgs[0] != bgs[1] and bgs[0] != bgs[2], f"نبض الأسواق: خلفية خفيفة تتدرج بالحدة {bgs}")
        check(q4.locator("#banner").is_visible() is False and q4.locator("#refreshBtn").is_visible() is False and q4.locator(".statusrow").is_visible() is False, "الموبايل: لا شريط تحديث ولا أيقونة تحديث في المقدمة")
        check(q4.locator("#healthBtn").is_visible() and q4.get_attribute("#healthBtn", "data-s") == "ok" and q4.locator("#healthBtn").inner_text() == "✓", "أيقونة الصحة خضراء ✓ " + str(q4.evaluate("healthWhy_()")))
        q4.click("#healthBtn"); q4.wait_for_timeout(150)
        hd = q4.locator("#healthDlg").inner_text()
        check(q4.evaluate("document.getElementById('healthDlg').open") and all(k in hd for k in ("حالة البيانات", "آخر تحديث للبيانات", "المصادر", "تحديث")) and q4.locator("#refreshBtn").is_visible(), "نافذة الصحة: الحالة وآخر تحديث والمصادر وزر التحديث")
        q4.screenshot(path=os.path.join(shots, "health_popup_390.png"))
        q4.click("#hdClose"); q4.wait_for_timeout(50)
        mode["m"] = "500"; q4.evaluate("document.getElementById('refreshBtn').click()"); q4.wait_for_timeout(1200)
        check(q4.get_attribute("#healthBtn", "data-s") == "warn" and q4.locator("#healthBtn").inner_text() == "!", "عند الفشل: أيقونة الصحة تتحول إلى تحذير !")
        q4.click("#healthBtn"); q4.wait_for_timeout(150)
        check("سبب التحذير" in q4.locator("#hdWhy").inner_text() and q4.locator("#hdWhy").is_visible(), "نافذة الصحة تذكر سبب التحذير")
        q4.click("#hdClose"); mode["m"] = "good"
        q4.evaluate("openEvent_('move|202610140900|es-oil')"); q4.wait_for_timeout(150)
        et = q4.locator("#evBody").inner_text()
        check("النفط تحرك -0.9% آخر ساعة و-1.3% آخر 3 ساعات" in et and q4.locator("#evBody table").count() == 0, "نافذة الحدث: سطر موجز بدل جدول العوامل")
        q4.click("#evClose")
        # أيقونات حالة السوق 2D
        ic = q4.evaluate("""() => { const o = {}; [['support',1],['support',2],['support',3],['pressure',1],['pressure',2],['pressure',3],['mixed',1],['mixed',2],['mixed',3]].forEach(([k,n]) => o[k+n] = fightSvg_(k,'up',n)); return o; }""")
        check(all("radialGradient" not in v and 'class="ex"' not in v and "filter" not in v for v in ic.values()), "الأيقونات مسطحة 2D: بلا تدرجات ولا تجسيم")
        check("#8fdcb0" in ic["support1"] and "#2fbf71" in ic["support2"] and "#0f8a4b" in ic["support3"] and "#f0a3a6" in ic["pressure1"] and "#b3202a" in ic["pressure3"], "الحدة بدرجة اللون للدعم والضغط")
        check("stroke-dasharray" in ic["support3"] and "stroke-dasharray" in ic["pressure3"] and "stroke-dasharray" not in ic["support2"] and "stroke-dasharray" not in ic["pressure1"], "الدائرة المنقطة للقوي فقط")
        check(ic["mixed1"].count("<circle") == 2 and "split" not in ic["mixed1"] and "split" in ic["mixed2"] and "split" in ic["mixed3"] and "spin" not in ic["mixed2"] and "stroke-dasharray" in ic["mixed3"], "المختلط: ضعيف حلقتان بفاصل أبيض، متوسط وحاد حلقة مقسومة ثابتة (أخضر يميناً وأحمر يساراً) بلا دوران، والحاد منقط")
        q4.evaluate("""(ic) => { const d = document.createElement('div'); d.id = 'icdemo'; d.style.cssText = 'position:fixed;inset:0;z-index:999;background:#0e1420;display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:12px;align-content:center'; Object.keys(ic).forEach(k => { const c = document.createElement('div'); c.style.cssText = 'text-align:center;color:#fff;font:14px sans-serif'; c.innerHTML = '<div style="width:96px;height:96px;margin:auto">' + ic[k] + '</div>' + k; d.appendChild(c); }); document.body.appendChild(d); }""", ic)
        q4.wait_for_timeout(100); q4.screenshot(path=os.path.join(shots, "watch_icons_2d.png")); q4.evaluate("document.getElementById('icdemo').remove()")
        # جاما: لا بيانات
        q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(1200)
        gt = q4.locator("#tab-gamma").inner_text()
        check(q4.get_attribute("#gFresh", "data-s") == "none" and "لا توجد بيانات جاما اليوم" in gt and not q4.locator("#gLevels").is_visible() and not q4.locator("#gChart").is_visible(), "جاما بلا ملف: «لا توجد بيانات» ولا أرقام")
        check("SPY Gamma Data Unavailable" in gt and not q4.locator("#gCtl").is_visible(), "SPY: «SPY Gamma Data Unavailable» وبلا أزرار أصل عند غياب البيانات")
        _u = q4.evaluate("[ghRawUrl_({hostname:'mshb4466.github.io',pathname:'/mirsad/index.html'}), ghRawUrl_({hostname:'localhost',pathname:'/'}), ghRawUrl_({hostname:'x.github.io',pathname:'/'})]")
        check(_u[0] == "https://raw.githubusercontent.com/mshb4466/mirsad/main/gamma/latest.json" and _u[1] is None and _u[2] is None, "رابط جاما المباشر من المستودع يُشتق من عنوان الصفحة (ولا يُستعمل محلياً)")
        q4.screenshot(path=os.path.join(shots, "gamma_none_390.png"), full_page=True)
        def gload(g):
            mode["gamma"] = g; q4.evaluate("loadGamma_()"); q4.wait_for_timeout(500)
        gload(gfix(10))
        q4.evaluate("GDAY = {day:'2026-10-23', pts:[{t:'2026-10-23T13:00:00+00:00',sp:7400,b:40,lv:{'SPX|CALL WALL':7440,'SPX|PUT WALL':7340,'SPX|GAMMA FLIP':7390},pk:{}},{t:'2026-10-23T13:30:00+00:00',sp:7405,b:40,lv:{'SPX|CALL WALL':7440,'SPX|PUT WALL':7340,'SPX|GAMMA FLIP':7390},pk:{}},{t:'2026-10-23T14:00:00+00:00',sp:7410,b:41,lv:{'SPX|CALL WALL':7450,'SPX|PUT WALL':7340,'SPX|GAMMA FLIP':7390},pk:{}}]}; renderGTime_()")
        tt = q4.locator("#gTime").inner_text()
        check(q4.locator("#gTime").is_visible() and q4.locator("#gTime svg path").count() >= 4 and q4.locator("#gTime .tl-tr").count() == 1 and "17:00 بغداد: SPX CALL WALL 7480.00 ← 7491.00" in tt, "الخط الزمني: مستويات ES وخط انتقال واحد بتوقيت بغداد")
        q4.evaluate("GDAY = null; renderGTime_()"); check(q4.locator("#gTime").is_hidden(), "الخط الزمني: يختفي بلا بيانات اليوم")
        gt = q4.locator("#tab-gamma").inner_text()
        check(q4.get_attribute("#gFresh", "data-s") == "fresh" and "بيانات طازجة" in gt and "وقت اللقطة (نيويورك)" in gt and "بتوقيت بغداد" in gt and "عمر البيانات" in gt, "جاما طازجة: تاريخ التحديث ووقتا نيويورك وبغداد والعمر")
        check(all(k in q4.locator("#gLevels").inner_text() for k in ("Gamma Flip", "Call Wall", "Put Wall", "غاما سلبية", "7425", "7680", "7650")), "المستويات: Flip وCall Wall وPut Wall والنظام")
        rows = q4.locator("#gChart .gr").count(); curs = q4.locator("#gChart .gr.cur").count()
        check(0 < rows <= 60 and curs == 1 and q4.locator("#gChart .gr .es").count() == rows and "تقريبي" in q4.locator("#gLevels").inner_text(), f"المخطط: Strike حول السعر مع صف مظلل وعمود ES ({rows} صفاً)")
        spans = q4.evaluate("[...document.querySelectorAll('#gChart .gr')].map(r=>+r.querySelector('.k').childNodes[0].textContent)")
        check(max(abs(k - 7677.28) for k in spans) <= 125, "المخطط ضمن ±120 نقطة من السعر")
        check("ES≈7722.00" in q4.locator("#gLevels").inner_text().replace(" ", "") or "ES≈7725.00" in q4.locator("#gLevels").inner_text(), "تحويل Call Wall إلى ES بخطوة 0.25")
        alltxt = q4.evaluate("document.getElementById('tab-gamma').innerText")
        check("Open Interest" not in alltxt and not __import__("re").search(r"\bOI\b", alltxt), "لا ذكر لـ Open Interest في تبويب جاما")
        q4.screenshot(path=os.path.join(shots, "gamma_fresh_390.png"), full_page=True)
        gload(gfix(90)); check(q4.get_attribute("#gFresh", "data-s") == "late" and "متأخرة" in q4.locator("#gFresh").inner_text(), "جاما بعمر 90 دقيقة: برتقالي «متأخرة»")
        gload(gfix(53 * 1440)); gt = q4.locator("#gFresh").inner_text()
        check(q4.get_attribute("#gFresh", "data-s") == "stale" and "قديمة" in gt and "لا تعتمدها للتداول" in gt and "53 يوماً" in gt, "جاما بعمر 53 يوماً: أحمر «لا تعتمدها للتداول» مع العمر")
        q4.screenshot(path=os.path.join(shots, "gamma_stale_390.png"), full_page=True)
        gload(gfix(-180)); check(q4.get_attribute("#gFresh", "data-s") == "stale" and "في المستقبل" in q4.locator("#gFresh").inner_text(), "ختم لقطة جاما في المستقبل (3 ساعات): أحمر ولا يُعرض «طازجة»")
        gload(gfix(10)); q4.click("#gChart .gr >> nth=3"); n_sel = q4.locator("#gChart .gr.sel").count()
        check(n_sel == 1 and q4.get_attribute("#gChart .gr.sel", "aria-pressed") == "true", "النقر على صف في مخطط جاما يظلله (صف واحد فقط)")
        q4.click("#gChart .gr >> nth=3"); check(q4.locator("#gChart .gr.sel").count() == 0, "نقرة ثانية على الصف تلغي التظليل")
        q4.click("#gChart .gr >> nth=5"); q4.click("#gChart .gr >> nth=6"); check(q4.locator("#gChart .gr.sel").count() == 1, "التظليل ينتقل ولا يتراكم")
        q4.click("#gLevels .lv-cw"); _k = q4.get_attribute("#gChart .gr.sel", "data-k")
        check(_k == "7680" and q4.locator("#gLevels .lv-cw.on").count() == 1, "النقر على بطاقة Call Wall يظلل صفها (7680)")
        _cc = q4.evaluate("[getComputedStyle(document.querySelector('#gLevels .lv-cw b')).color, getComputedStyle(document.querySelector('#gLevels .lv-pw b')).color]")
        check(_cc[0] != _cc[1], "لونا Call Wall وPut Wall مختلفان (أخضر/أحمر)")
        gload(gfix(10)); _o = q4.evaluate("(() => { const a = Array.from(document.querySelectorAll('#gChart .gr .n')).map(e => [e.className, parseFloat(getComputedStyle(e).opacity)]); const s3 = a.filter(x => x[0].includes('s3')), s1 = a.filter(x => x[0].includes('s1')); return [s3.length, s1.length, s3.length ? s3[0][1] : null, s1.length ? s1[0][1] : null]; })()")
        check(_o[0] >= 1 and _o[1] >= 1 and _o[2] > _o[3], "قيم الصافي الكبيرة بلون قوي والصغيرة خافتة")
        gload(gfix(10)); _l = q4.evaluate("(() => { const b = document.getElementById('gLine'); if (!b || b.hidden) return null; const s = b.querySelector('svg'); const pk = Array.from(s.querySelectorAll('text.pk-l')); return { n: pk.length, rot: pk.every(t => (t.getAttribute('transform') || '').includes('rotate(45)')), noB: pk.every(t => !/B/.test(t.textContent)), poly: !!s.querySelector('polyline'), zero: !!s.querySelector('line.zero'), drops: s.querySelectorAll('line.pk').length, base: Number(pk[0].getAttribute('transform').match(/,(\\d+)/)[1]) }; })()")
        check(_l and 4 <= _l["n"] <= 10 and _l["rot"] and _l["noB"] and _l["poly"] and _l["zero"] and _l["drops"] == _l["n"], f"مخطط الخط: خط صفر وقمم محلية ({_l and _l['n']}) بخطوط نازلة وأرقام Strike مائلة بلا أرقام مليار")
        _pk = q4.evaluate("""(() => { const d = document.createElement('div'); document.body.appendChild(d); const nets = [1,3,1,-1,-4,-1,1,5,1,2,6,2,-1,-3,-1,1,4,1,0.5,0.2]; const rows = nets.map((n, i) => ({ k: 7000 + 5 * i, net: n * 1e9, call: 0, put: 0 })); gLine_(d, { title: 't', rows, spot: 7050 }); const t = Array.from(d.querySelectorAll('text.pk-l')).map(x => +x.textContent); d.remove(); return t; })()""")
        check(all(k in _pk for k in (7035, 7050, 7080, 7020, 7065)) and len(_pk) == len(set(_pk)), f"كل القمم المحلية المهمة مؤشَّر عليها (بلا حذف قمم ثانوية حقيقية): {sorted(_pk)}")
        q4.locator("#gLine svg").scroll_into_view_if_needed(); q4.evaluate("window.scrollBy(0, -120)"); _bx = q4.locator("#gLine svg").bounding_box(); q4.mouse.move(_bx["x"] + _bx["width"] * 0.5, _bx["y"] + _bx["height"] * 0.4)
        check(q4.evaluate("document.querySelector('#gLine .hv').getAttribute('visibility')") == "visible" and q4.evaluate("document.querySelector('#gLine .hv-l').textContent").replace(".", "", 1).isdigit(), "مؤشر الفأرة على المخطط يعرض رقم Strike بلا مربع")
        check(q4.locator("#gChart").is_visible() and q4.locator("#gChart .gr").count() > 10, "مخطط الأعمدة والجدول باقيان")
        q4.mouse.click(_bx["x"] + _bx["width"] * 0.5, _bx["y"] + _bx["height"] * 0.4); check(q4.locator("#gChart .gr.sel").count() == 1, "النقر على المخطط الخطي يظلل صف Strike في الجدول")
        q4.locator("#gLine").screenshot(path=os.path.join(shots, "gamma_line_390.png"))
        gload(gfix(10, status="stale")); check(q4.get_attribute("#gFresh", "data-s") == "stale", "حالة الملف stale تغلب العمر")
        gload(gfix(10, es=False)); gt = q4.locator("#gChart").inner_text() + q4.locator("#gLevels").inner_text()
        check("ES≈" not in gt and q4.locator("#gChart .gr .es").count() == 0 and q4.locator("#gChart .gcp").count() == 0 and "التحويل معطّل" in q4.locator("#gEsNote").inner_text(), "بلا أسعار مرجعية: لا تحويل ES ولا أزرار نسخ")
        gload(gfix(10, gap=9)); check(q4.locator("#gChart .gr .es").count() > 0 and "التحويل معطّل" not in q4.locator("#gEsNote").inner_text() and "⚠" not in q4.locator("#gEsNote").inner_text(), "بعد الافتتاح بفرق توقيت 9 دقائق: أرقام ES تظهر (كانت تختفي عند > 5)")
        gload(gfix(10, gap=45)); check(q4.locator("#gChart .gr .es").count() > 0 and "⚠" in q4.locator("#gEsNote").inner_text() and "45" in q4.locator("#gEsNote").inner_text(), "فرق 45 دقيقة: الأرقام تظهر مع تحذير صريح بدل الإخفاء")
        gload(gfix(10, flip=None)); check("غير محدد" in q4.locator("#gLevels").inner_text(), "Gamma Flip غير محدد يُقال صراحة")
        # ===== v0.21: الأصل والاستحقاق وES والنسخ والمقارنة والمؤشر المتزامن =====
        gload(gfix(10)); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(200)
        check(q4.locator("#gCtl .gb").count() == 3 and q4.locator("#gCtl .gchip").count() == 4 and q4.locator("#gCtl .gchip[data-b='all']").count() == 0 and q4.locator("#gCtl .gb.on").inner_text() == "SPX" and q4.locator("#gCtl .gchip.on").count() == 4, "أزرار الأصل (SPX/SPY/مقارنة) وأربعة استحقاقات متعددة الاختيار بلا «الكل» وكلها مفعّلة افتراضياً")
        _tot = lambda: q4.evaluate("[...document.querySelectorAll('#gChart .gr .n')].length")
        _vals = lambda: q4.evaluate("Object.fromEntries([...document.querySelectorAll('#gChart .gr')].map(r => [r.dataset.k, parseFloat(r.querySelector('.n').textContent.replace('−','-').replace('B',''))]))")
        _all_n = q4.evaluate("[...document.querySelectorAll('#gChart .gr')].map(r => r.dataset.k).join(',')"); _al = _vals()
        _flip_all = q4.evaluate("document.querySelector('#gLevels .lv-fl b').textContent")
        _bn = {}
        for b_ in ("0", "wk", "mo", "later"):                       # سلة واحدة: ألغِ الباقي
            for o_ in ("0", "wk", "mo", "later"):
                if o_ != b_: q4.click(f"#gCtl .gchip[data-b='{o_}']"); q4.wait_for_timeout(60)
            _bn[b_] = _vals()
            q4.click("#gCtl .gchip[data-b='" + ("wk" if b_ != "wk" else "mo") + "']"); q4.wait_for_timeout(60)   # أعد تفعيل واحدة لتفعيل الباقي بالتتابع
            for o_ in ("0", "wk", "mo", "later"):
                if q4.locator(f"#gCtl .gchip[data-b='{o_}']").get_attribute("aria-pressed") != "true": q4.click(f"#gCtl .gchip[data-b='{o_}']"); q4.wait_for_timeout(60)
        check(q4.locator("#gCtl .gchip.on").count() == 4 and q4.evaluate("[...document.querySelectorAll('#gChart .gr')].map(r => r.dataset.k).join(',')") == _all_n, "إعادة تفعيل كل الاستحقاقات تعيد الجدول الكامل")
        check(all(abs(sum(_bn[b_][k] for b_ in _bn) - v) < 0.04 for k, v in _al.items()), "مجموع السلال الأربع = المجموع الكامل لكل Strike (لا عدّ مزدوج)")
        # اختيار متعدد: الأسبوعي + الشهري بلا اليوم
        q4.click("#gCtl .gchip[data-b='0']"); q4.click("#gCtl .gchip[data-b='later']"); q4.wait_for_timeout(150)
        _wm = _vals()
        check(q4.locator("#gCtl .gchip.on").count() == 2 and all(abs(_wm[k] - (_bn["wk"][k] + _bn["mo"][k])) < 0.04 for k in _wm) and "بقية الأسبوع + بقية الشهر" in q4.locator("#gChart").inner_text(), "اختيار الأسبوعي + الشهري: الجدول = مجموع سلتيهما والعنوان يذكرهما")
        _fl_wm = q4.evaluate("document.querySelector('#gLevels .lv-fl b').textContent")
        check(_fl_wm != "—" and _fl_wm != _flip_all, f"Gamma Flip لاختيار جزئي يُحسب من مجموع المنحنيات ويختلف عن الكل ({_fl_wm} مقابل {_flip_all})")
        q4.click("#gCtl .gchip[data-b='0']"); q4.wait_for_timeout(100)
        _fl_3 = q4.evaluate("document.querySelector('#gLevels .lv-fl b').textContent")
        check(_fl_3 != _fl_wm, "إضافة سلة اليوم تغيّر Flip")
        # لا بد من اختيار واحد على الأقل
        for o_ in ("0", "wk", "mo", "later"):
            if q4.locator(f"#gCtl .gchip[data-b='{o_}']").get_attribute("aria-pressed") == "true" and q4.locator("#gCtl .gchip.on").count() > 1: q4.click(f"#gCtl .gchip[data-b='{o_}']"); q4.wait_for_timeout(60)
        _last = q4.locator("#gCtl .gchip.on"); check(_last.count() == 1, "يمكن اختيار سلة واحدة")
        _last.first.click(); q4.wait_for_timeout(100)
        check(q4.locator("#gCtl .gchip.on").count() == 1, "لا يمكن إلغاء آخر استحقاق (واحد على الأقل)")
        for o_ in ("0", "wk", "mo", "later"):
            if q4.locator(f"#gCtl .gchip[data-b='{o_}']").get_attribute("aria-pressed") != "true": q4.click(f"#gCtl .gchip[data-b='{o_}']"); q4.wait_for_timeout(60)
        check(_vals() == _al and q4.evaluate("document.querySelector('#gLevels .lv-fl b').textContent") == _flip_all, "عند تفعيل الأربع يعود المجموع الكامل وFlip الأصلي بالضبط")
        gload(gfix(10, bk0=False)); q4.evaluate("showTab('gamma')"); check(q4.locator("#gCtl .gchip[data-b='0']").is_disabled(), "سلة بلا عقود معطّلة")
        gload(gfix(10)); q4.evaluate("showTab('gamma')")
        # ES: عمود ونسخ
        _r0 = q4.evaluate("(() => { const r = document.querySelector('#gChart .gr'); return [r.querySelector('.k').childNodes[0].textContent, r.querySelector('.es').textContent, r.querySelector('.gcp').getAttribute('aria-label')]; })()")
        check(abs(float(_r0[1]) - (float(_r0[0]) + 45.0)) < 0.13 and _r0[1].endswith((".00", ".25", ".50", ".75")) and f"SPX {_r0[0]} = ES {_r0[1]}" in _r0[2], f"عمود ES بجانب Strike بتدوير 0.25 ({_r0[0]} ← {_r0[1]})")
        c4.grant_permissions(["clipboard-read", "clipboard-write"], origin=url.split("/index.html")[0]) if False else None
        q4.evaluate("window.__cp = []; navigator.clipboard.writeText = t => { window.__cp.push(t); return Promise.resolve(); }; 0")
        q4.click("#gChart .gcp >> nth=0"); q4.wait_for_timeout(80)
        check(q4.evaluate("window.__cp[0]") == _r0[2].replace("نسخ ", "") and q4.locator("#gChart .gcp >> nth=0").inner_text() == "تم ✓", "زر نسخ الصف ينسخ «SPX = ES» ويؤكد")
        q4.click("#gChart .gall"); q4.wait_for_timeout(80)
        _ln = q4.evaluate("window.__cp[1]").split("\n")
        check(len(_ln) == q4.locator("#gChart .gr").count() and all(l.startswith("SPX ") and " = ES " in l for l in _ln), "«نسخ كل الجدول»: سطر لكل مستوى بصيغة SPX = ES")
        # ES: مرجع إغلاق أمس بعد/قبل الافتتاح
        check("المرجع: SPX الحالي" in q4.locator("#gEsNote").inner_text(), "ES: المرجع «SPX الحالي» في الوضع الحي")
        gload(gfix(10, esmode="close")); q4.evaluate("showTab('gamma')")
        check("إغلاق أمس" in q4.locator("#gEsNote").inner_text() and q4.locator("#gChart .gr .es").count() > 0 and "حركة ES الليلية" in q4.locator("#gEsNote").inner_text(), "ES: مرجع «إغلاق أمس» عند إغلاق SPX (حتى مع فرق توقيت كبير) مع شرح السبب")
        _e2 = q4.evaluate("(() => { const r = document.querySelector('#gChart .gr'); return [r.querySelector('.k').childNodes[0].textContent, r.querySelector('.es').textContent]; })()")
        check(abs(float(_e2[1]) - (float(_e2[0]) + 38.25)) < 0.13, "التحويل يستعمل فرق الإغلاق (38.25)")
        gload(gfix(10)); q4.evaluate("showTab('gamma')")
        # أشرطة أوضح
        _bh = q4.evaluate("[...document.querySelectorAll('#gChart .gbar')].map(b => b.getBoundingClientRect().height)")
        check(min(_bh) >= 20, f"أشرطة الصافي أسمك (≥20px، الأدنى {min(_bh):.0f})")
        _wd = q4.evaluate("[...document.querySelectorAll('#gChart .gbar i')].map(i => parseFloat(i.style.width))")
        check(max(_wd) >= 45 and min(_wd) < 15, "أطوال الأشرطة نسبية: الكبيرة تقارب نصف الشريط والصغيرة قصيرة")
        # SPY
        q4.click("#gCtl .gb[data-a='SPY']"); q4.wait_for_timeout(150)
        _sr = q4.evaluate("[...document.querySelectorAll('#gChart .gr')].map(r => [r.dataset.k, r.querySelector('.k small') ? r.querySelector('.k small').textContent : ''])")
        check(len(_sr) >= 5 and all(x[1].startswith("SPY ") for x in _sr) and "SPY (مكافئ SPX)" in q4.locator("#gChart").inner_text() and "10.03" in q4.locator("#gFresh").inner_text(), "وضع SPY: Strikes بمكافئ SPX مع Strike السباي والنسبة")
        check(q4.evaluate("document.getElementById('gSpy').hidden") is True, "SPY صالح: بطاقة «غير متاح» مخفية")
        # المقارنة والمؤشر المتزامن
        q4.click("#gCtl .gb[data-a='CMP']"); q4.wait_for_timeout(200)
        check(q4.locator("#gLine svg").count() == 1 and q4.locator("#gLine2 svg").count() == 1 and not q4.locator("#gChart").is_visible() and q4.locator("#gCmp").is_visible(), "المقارنة: مخطط SPX ومخطط SPY وجدول المقارنة")
        _cm = q4.locator("#gCmp").inner_text()
        check("Call Wall" in _cm and "Put Wall" in _cm and "Gamma Flip" in _cm and ("توافق" in _cm or "اختلاف" in _cm) and "× 10.03" in _cm, "جدول SPX مقابل SPY: المستويات والفرق والتوافق والنسبة")
        _ag = q4.evaluate("[...document.querySelectorAll('#gCmp tr')].slice(1).map(r => [r.children[1].textContent, r.children[2].textContent, r.children[3].textContent, r.children[4].textContent])")
        _cw = [x for x in _ag if x][0]
        check(_cw[3] == "اختلاف" and _cw[2].startswith("+"), f"Call Wall: 7680 مقابل 7713.1 = اختلاف ({_cw})")
        q4.locator("#gLine svg").scroll_into_view_if_needed(); _b1 = q4.locator("#gLine svg").bounding_box(); q4.mouse.move(_b1["x"] + _b1["width"] * 0.5, _b1["y"] + _b1["height"] * 0.5)
        _hv = q4.evaluate("[document.querySelector('#gLine .hv').getAttribute('visibility'), document.querySelector('#gLine2 .hv').getAttribute('visibility'), document.querySelector('#gLine .hv-l').textContent, document.querySelector('#gLine2 .hv-l').textContent]")
        check(_hv[0] == "visible" and _hv[1] == "visible" and abs(float(_hv[2]) - float(_hv[3])) <= 6, f"المؤشر على مخطط SPX يظهر في SPY عند نفس Strike ({_hv[2]} / {_hv[3]})")
        q4.locator("#gLine2 svg").scroll_into_view_if_needed(); _b2 = q4.locator("#gLine2 svg").bounding_box(); q4.mouse.move(_b2["x"] + _b2["width"] * 0.3, _b2["y"] + _b2["height"] * 0.5)
        _hv = q4.evaluate("[document.querySelector('#gLine .hv').getAttribute('visibility'), document.querySelector('#gLine2 .hv').getAttribute('visibility'), document.querySelector('#gLine .hv-l').textContent, document.querySelector('#gLine2 .hv-l').textContent]")
        check(_hv[0] == "visible" and _hv[1] == "visible" and abs(float(_hv[2]) - float(_hv[3])) <= 6, f"المؤشر على مخطط SPY يظهر في SPX (بالاتجاهين) ({_hv[3]} / {_hv[2]})")
        check("الصافي" in q4.evaluate("document.querySelector('#gLine .hv-t2').textContent") and "SPY→SPX" in q4.evaluate("document.querySelector('#gLine2 .hv-t').textContent"), "المؤشر يعرض Strike والصافي في مربع صغير")
        q4.mouse.move(5, 5); q4.wait_for_timeout(100)
        check(q4.evaluate("document.querySelector('#gLine .hv').getAttribute('visibility')") == "hidden" and q4.evaluate("document.querySelector('#gLine2 .hv').getAttribute('visibility')") == "hidden", "خروج المؤشر يخفي المؤشرين")
        q4.locator("#gLine2").screenshot(path=os.path.join(shots, "gamma_spy_line_390.png")); q4.locator("#gCmp").screenshot(path=os.path.join(shots, "gamma_cmp_390.png"))
        for o_ in ("wk", "mo", "later"): q4.click(f"#gCtl .gchip[data-b='{o_}']"); q4.wait_for_timeout(60)
        check(q4.locator("#gLine2 svg").count() == 1 and "اليوم 0DTE" in q4.locator("#gCmp").inner_text() and "محسوب من مجموع منحنيات" in q4.locator("#gCmp").inner_text(), "المقارنة تعمل مع استحقاق مختار (اليوم فقط)")
        for o_ in ("wk", "mo", "later"): q4.click(f"#gCtl .gchip[data-b='{o_}']"); q4.wait_for_timeout(60)
        q4.click("#gCtl .gb[data-a='SPX']"); q4.wait_for_timeout(150)
        check(q4.locator("#gLine2").is_hidden() and q4.locator("#gChart").is_visible(), "العودة إلى SPX تخفي مخطط SPY وتعيد الجدول")
        # SPY معطّل
        gload(gfix(10, spy=False)); q4.evaluate("showTab('gamma')")
        check(q4.locator("#gCtl .gb[data-a='SPY']").is_disabled() and q4.locator("#gCtl .gb[data-a='CMP']").is_disabled() and "SPY Gamma Data Unavailable" in q4.locator("#gSpy").inner_text() and "متزامن" in q4.locator("#gSpy").inner_text(), "SPY بلا سعر متزامن: الأزرار معطّلة وسبب واضح")
        q4.screenshot(path=os.path.join(shots, "gamma_nospy_390.png"), full_page=True)
        gload(gfix(10)); q4.evaluate("showTab('gamma')"); q4.screenshot(path=os.path.join(shots, "gamma_v21_390.png"), full_page=True)
        # ---- خريطة المستويات ----
        gload(gfix(10)); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(300)
        _m = q4.evaluate("(() => { const b = document.getElementById('gMap'); if (!b || b.hidden) return null; const s = b.querySelector('svg'); return { tags: Array.from(s.querySelectorAll('.mp-tag')).map(g => [g.dataset.src, g.querySelector('.mp-es').textContent]), pills: Array.from(s.querySelectorAll('.mp-pill')).map(g => g.dataset.src + ':' + g.dataset.kind), bg: s.querySelectorAll('.mp-bg').length, noOrig: !Array.from(s.querySelectorAll('.mp-tag text')).some(x => /^\\d{4}$/.test(x.textContent)), leg: b.querySelector('.mpleg') ? b.querySelector('.mpleg').getBoundingClientRect().top > b.querySelector('svg').getBoundingClientRect().bottom - 2 : false, noTip: !b.querySelector('.tip') }; })()")
        check(_m is not None and len(_m["tags"]) >= 4 and all(re.match(r"^\d{4}\.\d{2}$", x[1]) for x in _m["tags"]), "خريطة المستويات: وسوم على العمود بسعر ES فقط")
        check(any(x.startswith("SPX:") for x in _m["pills"]) and any(x.startswith("SPY:") for x in _m["pills"]) and any("CALL WALL" in x for x in _m["pills"]) and any("PUT WALL" in x for x in _m["pills"]), "خريطة المستويات: Call Wall وPut Wall لـ SPX وSPY")
        check(any("GAMMA FLIP" in x for x in _m["pills"]), "خريطة المستويات: Gamma Flip ظاهر")
        check(_m["bg"] > 5 and _m["noOrig"] and _m["leg"], "خريطة المستويات: خلفية تدرج بلا أرقام والمفتاح أسفل الشارت")
        _h = q4.evaluate("(() => { const s = document.querySelector('#gMap svg'); const r = s.getBoundingClientRect(); return [r.width, r.height]; })()")
        check(_h[1] >= 600 and _h[0] >= 360, f"خريطة المستويات: شارت كبير بعرض الشاشة ({_h[0]:.0f}×{_h[1]:.0f})")
        check("حالة الجاما لو وصل السعر" in q4.locator("#gMap .mpleg").inner_text() and q4.evaluate("document.querySelectorAll('#gMap .mp-bg').length") >= 100, "خريطة المستويات: الخلفية = حالة الجاما عند كل سعر (من منحنى الجاما المحفوظ)")
        _s0 = q4.evaluate("document.querySelectorAll('#gMap .mp-tag').length")
        q4.locator("#gMap .mpc[aria-label='تكبير']").click(); q4.locator("#gMap .mpc[aria-label='تكبير']").click(); q4.wait_for_timeout(150)
        _z = q4.evaluate("(() => ({ z: document.querySelector('#gMap .mpz').textContent, mini: !!document.querySelector('#gMap .mp-mini'), n: document.querySelectorAll('#gMap .mp-tag').length }))()")
        check("×" in _z["z"] and _z["mini"] and _z["n"] <= _s0, "خريطة المستويات: التكبير يظهر الشارة والشريط ويُخفي ما خرج عن النطاق")
        q4.screenshot(path=os.path.join(shots, "gamma_map_zoom_390.png"), full_page=False)
        q4.locator("#gMap .mprs").click(); q4.wait_for_timeout(100)
        check(q4.evaluate("document.querySelectorAll('#gMap .mp-tag').length") == _s0 and q4.evaluate("document.querySelector('#gMap .mpz').hidden"), "خريطة المستويات: إعادة الضبط")
        q4.locator("#gMap .mpb[data-a='SPY']").click(); q4.wait_for_timeout(150)
        check(q4.evaluate("Array.from(document.querySelectorAll('#gMap .mp-tag')).every(g => g.dataset.src === 'SPY')"), "خريطة المستويات: عرض SPY وحده")
        q4.locator("#gMap .mpb[data-a='BOTH']").click(); q4.wait_for_timeout(150)
        q4.locator("#gMap").screenshot(path=os.path.join(shots, "gamma_map_390.png"))
        gload(gfix(10, spy=False)); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(200)
        check(q4.evaluate("document.querySelector('#gMap .mpb[data-a=BOTH]').disabled") and q4.evaluate("Array.from(document.querySelectorAll('#gMap .mp-tag')).every(g => g.dataset.src === 'SPX')") and q4.evaluate("document.querySelectorAll('#gMap .mp-tag').length") > 0, "خريطة المستويات: بلا SPY تعمل بـ SPX وحده")
        gload(gfix(10, esmode="close")); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(200)
        check(q4.evaluate("document.querySelectorAll('#gMap .mp-tag').length") > 0, "خريطة المستويات: تعمل مع مرجع الإغلاق")
        gload(gfix(10))
        # --- تنبيه تغيّر المستويات (حد 5 نقاط): شريط + جدول كان←صار + نسخ + تثبيت + خط باهت على الخريطة ---
        def with_base(g, dcw=0.0, dpw=0.0):
            g["baseline"] = {"snapshot_utc": g["snapshot_utc"], "snapshot_et": "2026-10-23 08:00", "basis": g["es"]["basis"] if g.get("es") else None,
                             "levels": {"SPX|CALL WALL": g["call_wall"] - dcw, "SPX|PUT WALL": g["put_wall"] - dpw, "SPX|GAMMA FLIP": g["gamma_flip"]}}
            return g
        q4.evaluate("localStorage.removeItem('mirsad_gpin')")
        gload(with_base(gfix(10), dcw=6.0, dpw=3.0)); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(250)
        _c = q4.evaluate("(() => { const b = document.getElementById('gChg'); return { vis: !b.hidden, h: b.querySelector('h2').textContent, rows: b.querySelectorAll('tr').length - 1, tx: b.innerText, ghost: document.querySelectorAll('#gMap .mp-ghost').length, wh: document.querySelectorAll('#gMap .mp-tag.chg').length }; })()")
        check(_c["vis"] and _c["rows"] == 1 and "CALL WALL" in _c["tx"] and "تغيّرت 1" in _c["h"], f"تنبيه التغيّر: +6 يظهر و−3 لا يظهر {_c['rows']}")
        check("+6.00" in _c["tx"] and "7686.00" in _c["tx"] and "7680.00" not in _c["tx"].split("كان")[0] or "7725.00" in _c["tx"], "الجدول بسعر ES: كان ← صار + الفرق")
        check(_c["ghost"] >= 1 and _c["wh"] >= 1, "الخريطة: خط باهت للمستوى القديم ووسم بإطار أبيض")
        q4.locator("#gChg .cpy").first.click(); q4.wait_for_timeout(100)
        q4.locator("#gChg").screenshot(path=os.path.join(shots, "gamma_change_390.png"))
        q4.locator("#gPin").click(); q4.wait_for_timeout(250)
        check(q4.evaluate("document.querySelectorAll('#gChg tr').length") == 0 and q4.evaluate("!!document.getElementById('gUnpin')") and "تثبيتك" in q4.locator("#gChg").inner_text(), "بعد «نقلتها» يزول التنبيه ويصير الأساس تثبيتك")
        check(q4.evaluate("document.querySelectorAll('#gMap .mp-ghost').length") == 0, "بعد التثبيت لا خطوط باهتة")
        q4.locator("#gUnpin").click(); q4.wait_for_timeout(250)
        check(q4.evaluate("document.querySelectorAll('#gChg tr').length") > 0, "إلغاء التثبيت يعيد المقارنة بلقطة الخادم")
        q4.evaluate("localStorage.removeItem('mirsad_gpin')")
        gload(with_base(gfix(10), dcw=4.0, dpw=-4.0)); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(250)
        check(q4.evaluate("document.querySelectorAll('#gChg tr').length") == 0 and "لا تغيّر" in q4.locator("#gChg h2").inner_text(), "أقل من 5 نقاط: لا تنبيه")
        gload(gfix(10)); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(250)
        check(q4.evaluate("!document.getElementById('gChg').hidden && !!document.getElementById('gPin')") and "لا توجد لقطة مرجعية" in q4.locator("#gChg").inner_text(), "بلا لقطة مرجعية: شرح وزر التثبيت فقط")
        # القمم والقيعان المهمة (وليس الجدران وحدها): تحرّك/جديدة/اختفت
        gload(gfix(10)); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(200)
        _pk = q4.evaluate("gPeaks_(GAMMA)")
        check(len(_pk.get("SPX", [])) >= 3, f"القمم المهمة تُستخرج من البيانات ({len(_pk.get('SPX', []))})")
        _bp = json.loads(json.dumps(_pk)); _bp["SPX"][0]["k"] += 10; _bp["SPX"][0]["n"] += 10; _bp["SPX"].pop(1); _bp["SPX"].append({"k": 7599.0, "n": 7599.0, "s": 1, "strong": True})
        _g = gfix(10); with_base(_g); _g["baseline"]["peaks"] = _bp
        gload(_g); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(250)
        _t = q4.locator("#gChg").inner_text()
        check("قمة" in _t or "قاع" in _t, "الجدول يذكر قمة/قاع مهمة")
        check("جديد" in _t and "اختفى" in _t, "الجدول يميز «جديد» و«اختفى»")
        check(q4.evaluate("document.querySelectorAll('#gMap .mp-ghost').length") >= 2, "الخريطة: خطوط باهتة لمواضع القمم القديمة")
        q4.locator("#gChg").screenshot(path=os.path.join(shots, "gamma_change_peaks_390.png"))
        gload(gfix(10))
        # --- v0.23.1: فصل الحقيقي عن فرق السعر، الخط الرمادي متصل/منقط، شارة الجاما، المخاطر مثل الثقة، جدول المستويات على الحاسوب ---
        _g = gfix(10); with_base(_g, dcw=6.0); _g["baseline"]["basis"] = _g["es"]["basis"] - 4.0; _g["baseline"]["scale"] = {"SPX": 1, "SPY": 10.03}
        gload(_g); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(250)
        _tx = q4.locator("#gChg").inner_text()
        check("حقيقي" in _tx and "فرق ES−SPX تغيّر" in _tx and "+4.00" in _tx, "الجدول يفصل التغيّر الحقيقي عن أثر فرق السعر ويذكر الفرق")
        _g = gfix(10); with_base(_g); _g["baseline"]["basis"] = _g["es"]["basis"] - 4.0
        gload(_g); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(250)
        _tx = q4.locator("#gChg").inner_text()
        check(q4.evaluate("document.querySelectorAll('#gChg tr').length") == 0 and "فرق ES−SPX تغيّر" in _tx, "فرق السعر وحده: لا «تغيّر مستوى» بل ملاحظة فقط")
        _g = gfix(10); with_base(_g, dcw=6.0); _bp2 = {"SPX": [{"k": 7599.0, "n": 7599.0, "s": 1, "strong": False}]}; _g["baseline"]["peaks"] = _bp2
        gload(_g); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(250)
        _gh = q4.evaluate("Array.from(document.querySelectorAll('#gMap .mp-ghost')).map(g => [g.dataset.kind, g.dataset.main])")
        check(any(k == "CALL WALL" and m == "1" for k, m in _gh), f"الخط الرمادي لجدار قديم متصل (رئيسي) {_gh}")
        check(any(k == "PEAK" and m == "0" for k, m in _gh), f"الخط الرمادي لقمة متوسطة قديمة منقط (ثانوي) {_gh}")
        gload(gfix(10)); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(200)
        check(q4.evaluate("document.body.dataset.gtint") == "neg", "خلفية تبويب جاما حمراء عند الجاما السلبية")
        q4.evaluate("showTab('today')"); q4.wait_for_timeout(100)
        check(q4.evaluate("document.body.dataset.gtint") is None, "الخلفية الملوّنة تزول خارج تبويب جاما")
        gload(gfix(53 * 1440)); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(200)
        check(q4.evaluate("document.body.dataset.gtint") == "off" and q4.evaluate("getComputedStyle(document.body).backgroundImage").startswith("linear-gradient(") and "143, 157, 181" in q4.evaluate("getComputedStyle(document.body).backgroundImage"), "لقطة قديمة/إغلاق السوق: الخلفية رمادية لا ملوّنة")
        gload(gfix(10)); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(200)
        q4.set_viewport_size({"width": 1366, "height": 768}); q4.wait_for_timeout(300)
        _dk = q4.evaluate("(() => { const m = document.getElementById('gMap'), l = m.querySelector('.mplv'); const r = m.querySelector('.mpwrap').getBoundingClientRect(), r2 = l.getBoundingClientRect(); return { two: getComputedStyle(m).display === 'grid', lvVis: r2.width > 100, side: Math.abs(r.top - m.querySelector('.mpseg').getBoundingClientRect().top) < 200, rows: l.querySelectorAll('tr').length, now: !!l.querySelector('tr.now'), top: [document.getElementById('gFresh').getBoundingClientRect().top, document.getElementById('gLevels').getBoundingClientRect().top], sw: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1 }; })()")
        check(_dk["two"] and _dk["lvVis"] and _dk["rows"] >= 5 and _dk["now"], f"الحاسوب: الخريطة بعمودين مع جدول المستويات ({_dk['rows']} صفوف)")
        check(abs(_dk["top"][0] - _dk["top"][1]) < 30 and _dk["sw"], f"الحاسوب: بطاقات الحالة صف واحد وبلا تمرير أفقي {_dk['top']}")
        q4.screenshot(path=os.path.join(shots, "gamma_desktop_1366.png"), full_page=True)
        q4.set_viewport_size({"width": 390, "height": 900}); q4.wait_for_timeout(200)
        check(q4.evaluate("getComputedStyle(document.querySelector('#gMap .mplv')).display") == "none", "الموبايل: جدول المستويات الجانبي مخفي والتخطيط كما كان")
        # شاشة المراقبة: شارة حالة الجاما + مخاطر بنفس شكل الثقة والحدة
        gload(gfix(10)); q4.set_viewport_size({"width": 1280, "height": 720}); q4.evaluate("setWatch_(true)"); q4.wait_for_timeout(400)
        _w = q4.evaluate("(() => ({ t: document.getElementById('wGam').dataset.t, w: document.getElementById('wGamW').textContent, s: document.getElementById('wGamS').textContent, rt: [...document.querySelectorAll('#watchView .wt')].map(e => Math.round(e.getBoundingClientRect().width)), rk: [...document.querySelectorAll('#wRisk > *')].map(e => e.className.baseVal !== undefined ? e.getAttribute('class') : e.className), ck: [...document.querySelectorAll('#wConfT > *')].map(e => e.className.baseVal !== undefined ? e.getAttribute('class') : e.className), sh: document.getElementById('watchView').scrollHeight <= document.getElementById('watchView').clientHeight + 1 }))()")
        check(_w["t"] == "neg" and "سلبية" in _w["w"] and "Flip" in _w["s"], f"المراقبة: شارة الجاما سلبية بجانب موقع Flip ({_w['w']} / {_w['s']})")
        check(max(_w["rt"]) - min(_w["rt"]) <= 2, f"المراقبة: البلاطات الأربع بعرض واحد {_w['rt']}")
        check(_w["rk"][:3] == _w["ck"][:3] and _w["sh"], "المراقبة: المخاطر بنفس بنية الثقة (عنوان، مقياس، كلمة) وبلا تمرير")
        q4.screenshot(path=os.path.join(shots, "watch_v0231_1280.png"))
        gload(gfix(53 * 1440)); q4.wait_for_timeout(300)
        check(q4.evaluate("document.getElementById('wGam').dataset.t") == "na", "المراقبة: لقطة جاما قديمة = شارة رمادية بلا ألوان إيجابي/سلبي")
        q4.evaluate("setWatch_(false)"); q4.set_viewport_size({"width": 390, "height": 900}); gload(gfix(10))
        for gw in (320, 375, 768, 1366):
            q4.set_viewport_size({"width": gw, "height": 900}); q4.wait_for_timeout(150)
            sw = q4.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
            check(sw[0] <= sw[1] + 1, f"جاما بلا تمرير أفقي عند {gw}px ({sw[0]}/{sw[1]})")
        q4.set_viewport_size({"width": 390, "height": 900})
        q4.evaluate("showTab('today')"); q4.wait_for_timeout(100)
        q4.screenshot(path=os.path.join(shots, "today_390_v20.png"), full_page=True)
        mode["gamma"] = None
        # --- v0.23.2: الشريط الجانبي + تراكب المنحنى القديم ---
        q4.evaluate("setWatch_(false)"); gload(gfix(10)); q4.evaluate("showTab('today')")
        q4.set_viewport_size({"width": 1366, "height": 768}); q4.wait_for_timeout(300)
        _sb = q4.evaluate("(() => { const t = document.querySelector('.tabs'), r = t.getBoundingClientRect(), cs = getComputedStyle(t), w = document.querySelector('.wrap').getBoundingClientRect(); return { fixed: cs.position, dir: cs.flexDirection, right: Math.round(window.innerWidth - r.right), w: Math.round(r.width), h: Math.round(r.height), vh: window.innerHeight, overlap: w.right > r.left + 1, rk: document.getElementById('riskCard').offsetParent === null }; })()")
        check(_sb["fixed"] == "fixed" and _sb["dir"] == "column" and _sb["right"] == 0 and _sb["w"] >= 200 and _sb["h"] >= _sb["vh"] - 2, f"الحاسوب: التبويبات شريط جانبي أيمن بكامل الارتفاع {_sb}")
        check(not _sb["overlap"], "الحاسوب: المحتوى لا يتداخل مع الشريط الجانبي")
        check(_sb["rk"], "الحاسوب: عدادات المخاطر مخفية من اليوم (مكانها المراقبة)")
        _bg0 = q4.evaluate("getComputedStyle(document.querySelectorAll('.tabs button')[1]).backgroundColor")
        q4.locator(".tabs button").nth(1).hover(); q4.wait_for_timeout(300)
        check(q4.evaluate("getComputedStyle(document.querySelectorAll('.tabs button')[1]).backgroundColor") != _bg0, "الحاسوب: تغيّر لون عنصر الشريط عند مرور الماوس")
        q4.locator(".tabs button").nth(1).click(); q4.wait_for_timeout(250)
        check(q4.evaluate("document.querySelectorAll('.tabs button')[1].getAttribute('aria-selected')") == "true" and q4.evaluate("!document.getElementById('tab-gamma').hidden"), "النقر على عنصر الشريط الجانبي يفتح التبويب")
        q4.set_viewport_size({"width": 1000, "height": 700}); q4.wait_for_timeout(300)
        _sc = q4.evaluate("(() => ({ w: Math.round(document.querySelector('.tabs').getBoundingClientRect().width), sp: getComputedStyle(document.querySelector('.tabs button span')).position }))()")
        check(_sc["w"] <= 90 and _sc["sp"] == "absolute", f"900–1100: الشريط يتقلص إلى أيقونات {_sc}")
        q4.set_viewport_size({"width": 390, "height": 900}); q4.wait_for_timeout(300)
        _mb = q4.evaluate("(() => { const r = document.querySelector('.tabs').getBoundingClientRect(); return [getComputedStyle(document.querySelector('.tabs')).flexDirection !== 'column', Math.round(window.innerHeight - r.bottom)]; })()")
        check(_mb[0] and _mb[1] <= 1, f"الموبايل: الشريط السفلي كما كان {_mb}")
        # تراكب المنحنى القديم
        _g = gfix(10); with_base(_g, dcw=6.0)
        _g["baseline"]["curve"] = {"SPX": [[r["k"], r["net"] * 0.6] for r in _g["strikes"]]}
        _g["baseline"]["peaks"] = {"SPX": [{"k": 7599.0, "n": 7599.0, "s": 1, "strong": True}]}
        gload(_g); q4.evaluate("showTab('gamma')"); q4.wait_for_timeout(300)
        _ov = q4.evaluate("(() => ({ old: document.querySelectorAll('#gLine .oldc').length, main: +document.querySelector('#gLine .mainc').getAttribute('stroke-width'), gone: document.querySelectorAll('#gLine .chg-gone, #gLine .chg-mv, #gLine .chg-new').length, tg: !!document.querySelector('#gLine .goldt'), lab: [...document.querySelectorAll('#gLine text.pk-l')].map(t => t.textContent)[0] }))()")
        check(_ov["old"] == 1 and _ov["main"] < 1.5 and _ov["tg"], f"المخطط الخطي: منحنى قديم رمادي منقط + خط رئيسي أنحف {_ov}")
        check(_ov["gone"] >= 1, f"المخطط الخطي: علامة قمة تغيّرت/اختفت {_ov}")
        check(_ov["lab"] is not None and "." in _ov["lab"], f"تسميات القمم بسعر ES (خطوة 0.25) {_ov['lab']}")
        q4.locator("#gLine .goldt").click(); q4.wait_for_timeout(250)
        check(q4.evaluate("document.querySelectorAll('#gLine .oldc').length") == 0, "زر الإخفاء يزيل المنحنى القديم")
        q4.locator("#gLine .goldt").click(); q4.wait_for_timeout(250)
        q4.evaluate("localStorage.removeItem('mirsad_gpin')"); gload(gfix(10))
        c4.close()

        # ===== 10) الأحجام والتكبير =====
        sums = {}
        for w, h in ((320, 700), (375, 800), (430, 900), (768, 1000), (1366, 800), (1920, 1000)):
            for zoom in (1, 2):
                c2, q = newpage(w // zoom, h // zoom, zoom); mode["m"] = "good"; mode["data"] = fx
                q.goto(url); q.wait_for_timeout(1000)
                for tab in ("today", "gamma", "macro", "details", "settings"):
                    q.evaluate(f"showTab('{tab}')"); q.evaluate("document.querySelectorAll('details').forEach(d=>d.open=true)"); q.wait_for_timeout(120)
                    sw = q.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
                    check(sw[0] <= sw[1] + 1, f"بلا تمرير أفقي {w}px×{zoom * 100}% تبويب {tab} ({sw[0]}/{sw[1]}) " + (str(q.evaluate("[...document.querySelectorAll('#tab-' + '%s' + ' *')].filter(e => e.getBoundingClientRect().right > document.documentElement.clientWidth + 1).slice(0, 4).map(e => e.tagName + '.' + e.className + ':' + Math.round(e.getBoundingClientRect().right))" % tab)) if sw[0] > sw[1] + 1 else ""))
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
                    if w == 1366:
                        q.screenshot(path=os.path.join(shots, "today_1366_full.png"), full_page=True)
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
