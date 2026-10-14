# -*- coding: utf-8 -*-
"""فحص النموذج A في متصفح حقيقي (Chromium عبر Playwright). يُشغَّل يدوياً: python tests_browser.py [مجلد_اللقطات]
يغطي: شاشات 320/375/430/768، تكبير 200%، عدم التمرير الأفقي، حجم الخط، حالات Actual (موثق/مفقود/مراجَع/غير موثق/غير مدعوم)،
وفشل التحديث (HTTP/شبكة/JSON/error) وبدء الصفحة دون بيانات ثم التعافي. لا يرسل تنبيهات ولا ينشر شيئاً (خادم محلي فقط)."""
import copy
import json
import os
import sys
import tempfile
import threading
from datetime import timedelta
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


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def main(shots):
    from playwright.sync_api import sync_playwright
    fx = build_fixture()
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

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 375, "height": 800}, device_scale_factor=2)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("**/data.json*", handler)
        banner = lambda: pg.locator("#banner").inner_text()
        btn = lambda: pg.locator("#refreshBtn").inner_text()

        # بدء الصفحة دون بيانات
        mode["m"] = "404"
        pg.goto(url); pg.wait_for_timeout(1200)
        t = banner()
        check("تعذّر تحميل البيانات الحية" in t and "مثال توضيحي" in t and "بيانات حقيقية —" not in t, "بدء بلا بيانات: تحذير ومثال توضيحي لا «بيانات حقيقية»")
        # نجاح
        mode["m"] = "good"
        pg.click("#refreshBtn"); pg.wait_for_timeout(1200)
        t = banner()
        check("بيانات حقيقية —" in t and "⚠" not in t, "التعافي بعد البدء الفاشل: يزول التحذير")
        good_time = pg.evaluate("loadedAt")
        shown_risk = pg.locator("#riskNum").inner_text()
        # حالات الفشل
        for m, kind in (("500", "الخادم رفض"), ("abort", "لا اتصال"), ("badjson", "تالف"), ("error", "المصدر أبلغ")):
            mode["m"] = m
            pg.wait_for_timeout(50)
            pg.click("#refreshBtn"); pg.wait_for_timeout(1300)
            t = banner()
            check("تعذّر التحديث — تُعرض آخر لقطة ناجحة" in t and kind in t and "بيانات حقيقية —" not in t, f"فشل {m}: تحذير + السبب + اللقطة السابقة")
            check("لا جديد" not in btn() and "تعذّر" in btn(), f"فشل {m}: الزر لا يقول «لا جديد»")
            check(pg.evaluate("loadedAt") == good_time, f"فشل {m}: وقت آخر جلب ناجح لم يتحدث")
            check(pg.locator("#riskNum").inner_text() == shown_risk, f"فشل {m}: اللقطة السابقة محفوظة")
            check("وقت بياناتها" in t and "آخر محاولة" in t and "آخر جلب ناجح" in t, f"فشل {m}: ثلاثة أزمنة منفصلة")
            pg.wait_for_timeout(3100)
        pg.screenshot(path=os.path.join(shots, "failed_banner.png"), clip={"x": 0, "y": 0, "width": 375, "height": 220})
        mode["m"] = "good"
        pg.wait_for_timeout(3100)
        pg.click("#refreshBtn"); pg.wait_for_timeout(1000)
        t = banner()
        check("⚠" not in t and "بيانات حقيقية —" in t and pg.evaluate("FAIL") is None, "التعافي بعد الفشل: يزول التحذير ويتحدث وقت الجلب")
        check(pg.evaluate("loadedAt") > good_time, "التعافي: وقت آخر جلب ناجح تقدّم")

        # حالات Actual في الواجهة
        pg.evaluate("goSec('today','relCard')"); pg.evaluate("document.querySelectorAll('details.fd, #relList details.rel').forEach(d=>d.open=true)"); pg.wait_for_timeout(400)
        txt = pg.locator("#relCard").inner_text()
        for needle, name in (("رسمي ومتحقق", "موثق رسمي"), ("مصدر ثانوي موثوق", "موثق ثانوي"), ("عُدّلت القيمة", "مراجَع"), ("يحتاج تحققاً", "غير موثق"),
                             ("Actual غير متوفر من المصدر الحالي", "غير مدعوم"), ("بانتظار", "مفقود/بانتظار")):
            check(needle in txt, f"حالة Actual ظاهرة: {name}")
        check("Powell" not in txt or "بانتظار الرقم" not in txt.split("Powell")[1][:200], "الخطبة لا تظهر «بانتظار الرقم»")
        pg.locator("#relCard").screenshot(path=os.path.join(shots, "actual_states.png"))

        # الشاشات والتكبير
        for w, h in ((320, 700), (375, 800), (430, 900), (768, 1000)):
            for zoom in (1, 2):
                # تكبير 200% في المتصفح = نصف عرض الإطار بالبكسل CSS (الخط والعناصر تكبر مرتين)، فنحاكيه بعرض w/2 لا بخاصية zoom
                c2 = b.new_context(viewport={"width": w // zoom, "height": h // zoom}, device_scale_factor=zoom)
                q = c2.new_page(); q.route("**/data.json*", handler); mode["m"] = "good"
                q.goto(url); q.wait_for_timeout(1000)
                for tab in ("today", "week", "macro", "details", "settings"):
                    q.evaluate(f"showTab('{tab}')"); q.evaluate("document.querySelectorAll('details').forEach(d=>d.open=true)"); q.wait_for_timeout(150)
                    sw = q.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
                    check(sw[0] <= sw[1] + 1, f"بلا تمرير أفقي {w}px×{zoom * 100}% تبويب {tab} ({sw[0]}/{sw[1]})")
                small = q.evaluate("""() => { const bad = []; document.querySelectorAll('#tab-today *, #tab-week *').forEach(e => { if (!e.offsetParent || !e.childNodes.length) return;
                    const t = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 3); if (!t) return;
                    const fs = parseFloat(getComputedStyle(e).fontSize); if (fs < 11) bad.push(e.className + ':' + fs); }); return bad.slice(0, 5); }""")
                check(not small, f"الخط ≥ 11px عند {w}px×{zoom * 100}% {small or ''}")
                if zoom == 1 and w in (320, 768):
                    q.evaluate("showTab('today')"); q.screenshot(path=os.path.join(shots, f"today_{w}.png"), full_page=False)
                c2.close()
        check(not errs, f"لا أخطاء JavaScript {errs[:2]}")
        b.close()
    srv.shutdown()
    print("\n".join(log))
    print(f"\nالنتيجة: {len(log) - len(fails)}/{len(log)} نجح")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), "mirsad-shots"))
