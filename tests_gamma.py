"""اختبارات gamma.py بلا شبكة: تحليل السلسلة، الحساب، التحقق، الأرشفة، وعدم النظر للمستقبل."""
import json, os, shutil, tempfile
from datetime import datetime, timedelta, timezone
import gamma

N = 0
def ok(c, m):
    global N; N += 1
    assert c, m

def chain(spot=7000.0, ts="2026-10-19 13:30:00", zero=False, n=40):
    opts = []
    for i in range(n):
        k = 6800 + i * 10
        for kind in "CP":
            g = 0.0 if zero else max(0.0001, 0.01 - abs(k - spot) * 0.00003)
            opts.append({"option": "SPXW261020%s%08d" % (kind, int(k * 1000)), "gamma": g, "iv": 0.18,
                         "open_interest": 1000.0 + (i * 37) % 900 + (500 if kind == "C" and k > spot else 0), "volume": 5.0})
    opts.append({"option": "XYZ261020C00001000", "gamma": 1, "open_interest": 1})
    return {"timestamp": ts, "data": {"current_price": spot, "options": opts}}

t = tempfile.mkdtemp()
try:
    spot, ts, cs = gamma.parse_chain(chain())
    ok(spot == 7000.0 and len(cs) == 80, "تحليل 80 عقداً وتجاهل الرموز الغريبة")
    ok(ts.tzinfo is not None and ts.hour == 13 and ts.minute == 30, "09:30 EDT = 13:30 UTC")
    r = gamma.compute(spot, cs, ts)
    ok(r["regime"] in ("positive", "negative") and len(r["strikes"]) >= 20, "نتائج الحساب")
    ok(all("oi" not in s and "open_interest" not in s for s in r["strikes"]), "لا OI في المخرجات")
    c0 = next(x for x in r["strikes"] if x["k"] == 7000.0)
    ok(c0["call"] > 0 and c0["put"] < 0 and abs(c0["net"] - (c0["call"] + c0["put"])) < 1e-6, "Call موجب وPut سالب")
    ok(r["expiries"] == ["2026-10-20"], "الاستحقاقات")
    ok(gamma.validate(r, spot, cs) is None, "لقطة سليمة")
    zs, _, zc = gamma.parse_chain(chain(zero=True))
    ok("gamma" in (gamma.validate(gamma.compute(zs, zc, ts), zs, zc) or "") or gamma.validate(gamma.compute(zs, zc, ts), zs, zc), "gamma الصفرية تُرفض")
    ok(gamma.validate(r, None, cs), "بدون سعر تُرفض")
    for bad in ({}, {"data": {}}, {"data": {"options": []}, "timestamp": "2026-10-19 13:30:00"}):
        try:
            gamma.parse_chain(bad); ok(False, "يجب أن يفشل")
        except ValueError:
            ok(True, "")
    # الأرشفة وقاعدة «أول لقطة قبل 09:30 تفوز» وعدم النظر للمستقبل
    f1 = datetime(2026, 10, 19, 13, 10, tzinfo=timezone.utc)      # 09:10 ET
    s1 = gamma.build(chain(ts="2026-10-19 13:05:00"), fetched=f1, with_es=False)
    ok(s1["ok"] and s1["status"] in ("fresh", "late", "stale"), "بناء اللقطة")
    w = gamma.archive(s1, t); ok(any("preopen" in x for x in w), "حُفظت كأول لقطة قبل الافتتاح")
    f2 = datetime(2026, 10, 19, 13, 25, tzinfo=timezone.utc)
    s2 = gamma.build(chain(ts="2026-10-19 13:20:00"), fetched=f2, with_es=False)
    w = gamma.archive(s2, t); ok(not any("preopen" in x for x in w), "الثانية لا تستبدل الأولى")
    pre = json.load(open(os.path.join(t, "preopen", "2026-10-19.json")))
    ok(pre["snapshot_et"].endswith("09:05"), "preopen بقيت الأولى")
    f3 = datetime(2026, 10, 19, 13, 50, tzinfo=timezone.utc)      # جُمعت بعد الافتتاح
    s3 = gamma.build(chain(ts="2026-10-19 13:25:00"), fetched=f3, with_es=False)
    gamma.archive(s3, t)
    lb = gamma.last_before_open("2026-10-19", t)
    ok(lb and lb["snapshot_et"].endswith("09:20"), "آخر خريطة قبل الافتتاح تتجاهل ما جُمع بعد 09:30 (دون نظر للمستقبل)")
    ok(gamma.last_before_open("2026-10-18", t) is None, "يوم بلا بيانات")
    lat = json.load(open(os.path.join(t, "latest.json")))
    ok(lat["snapshot_et"].endswith("09:25"), "latest = الأحدث")
    s_old = gamma.build(chain(ts="2026-10-19 13:00:00"), fetched=f3, with_es=False)
    gamma.archive(s_old, t)
    ok(json.load(open(os.path.join(t, "latest.json")))["snapshot_et"].endswith("09:25"), "لقطة أقدم لا تستبدل latest")
    ok(gamma.status_of(datetime.now(timezone.utc) - timedelta(minutes=10)) == "fresh", "طازجة")
    ok(gamma.status_of(datetime.now(timezone.utc) - timedelta(minutes=90)) == "late", "متأخرة")
    ok(gamma.status_of(datetime.now(timezone.utc) - timedelta(hours=9)) == "stale", "قديمة")
    # قلب غاما حقيقي (BS) وجدران فوق/تحت السعر
    ref = datetime(2026, 10, 19, 13, 30, tzinfo=timezone.utc)
    rr = gamma.compute(spot, cs, ref)
    ok(rr["call_wall"] is None or rr["call_wall"] >= spot, "Call Wall فوق السعر")
    ok(rr["put_wall"] is None or rr["put_wall"] <= spot, "Put Wall تحت السعر")
    ok(rr["gamma_flip"] is None or 6500 < rr["gamma_flip"] < 7500, "قلب غاما ضمن نطاق منطقي")
    # خارج الجلسة: لا يظهر «طازجة»
    sc = gamma.build(chain(ts="2026-10-19 06:15:16"), fetched=datetime(2026, 10, 19, 6, 18, tzinfo=timezone.utc), with_es=False)
    ok(sc["status"] == "late" and "خارج ساعات الجلسة" in (sc["reason"] or ""), "خارج الجلسة ⇒ متأخرة وبسبب واضح")
    ok(sc["snapshot_utc"].startswith("2026-10-19T06:15"), "الختم يُقرأ UTC")
    sf = gamma.build(chain(ts="2026-10-19 20:00:00"), fetched=datetime(2026, 10, 19, 6, 18, tzinfo=timezone.utc), with_es=False)
    ok(not sf["ok"], "ختم مستقبلي يُرفض")
    # ===== سلال الاستحقاق المنفصلة (لا عدّ مزدوج) =====
    def multi(spot=7000.0, ts="2026-10-19 13:30:00", exps=("261019", "261022", "261030", "261130", "270115", "261016")):
        opts = []
        for ex in exps:
            for i in range(40):
                k = 6800 + i * 10
                for kind in "CP":
                    opts.append({"option": "SPXW%s%s%08d" % (ex, kind, int(k * 1000)), "gamma": max(0.0001, 0.01 - abs(k - spot) * 0.00003),
                                 "iv": 0.18, "open_interest": 800.0 + (i * 37) % 500 + (300 if kind == "C" else 0), "volume": 1.0})
        return {"timestamp": ts, "data": {"current_price": spot, "options": opts}}
    from datetime import date
    ok([gamma.bucket_of(date(2026,10,d), date(2026,10,19)) for d in (19,20,23,24,31)] == ["0","wk","wk","mo","mo"], "حدود السلال التقويمية")
    sp2, ts2, cs2 = gamma.parse_chain(multi())
    r2 = gamma.compute(sp2, cs2, datetime(2026, 10, 19, 13, 30, tzinfo=timezone.utc), date(2026, 10, 19))
    ok(r2["n_contracts"] == 5 * 80, "العقود المنتهية (261016) استُبعدت من «الكل»")
    ok([r2["buckets"][b]["n"] for b in gamma.BUCKETS] == [80, 80, 80, 160], "كل عقد في سلة واحدة فقط: 0/1-7/8-30/30+")
    ok(sum(b["n"] for b in r2["buckets"].values()) == r2["n_contracts"], "مجموع عدد العقود في السلال = الكل")
    ok(abs(sum(b["net_gex"] for b in r2["buckets"].values()) - r2["net_gex"]) < 1e-3 * abs(r2["net_gex"]), "مجموع صافي السلال = صافي الكل")
    for row in r2["strikes"]:
        tot = sum(next((x["net"] for x in b["strikes"] if x["k"] == row["k"]), 0.0) for b in r2["buckets"].values())
        ok(abs(tot - row["net"]) <= 1e-6 * max(1.0, abs(row["net"])), "مجموع السلال لكل Strike = «الكل» عند %s" % row["k"])
    # تتحرك السلال مع اليوم: غداً يصير 261019 منتهياً و261022 سلة 1-7 (يوم +2) ثم 261030 في 8-30
    r3 = gamma.compute(sp2, cs2, datetime(2026, 10, 20, 13, 30, tzinfo=timezone.utc), date(2026, 10, 20))
    ok(r3["n_contracts"] == 4 * 80 and r3["buckets"]["0"]["n"] == 0 and r3["buckets"]["wk"]["n"] == 80, "انتقال السلال وسقوط المنتهي مع تغيّر اليوم")
    # لقطة كاملة: Strikes مقرّبة والصافي = Call + Put، والأرشيف مختصر والـlatest كامل
    sb = gamma.build(multi(), fetched=datetime(2026, 10, 19, 13, 40, tzinfo=timezone.utc), with_es=False)
    ok(sb["ok"] and set(sb["buckets"]) == set(gamma.BUCKETS) and all(isinstance(x["call"], int) and x["net"] == x["call"] + x["put"] for x in sb["strikes"]), "اللقطة: سلال + أعداد صحيحة متسقة")
    w = gamma.archive(sb, t)
    arch = json.load(open([x for x in w if "archive" in x][0]))
    ok(all("strikes" not in v for v in arch["buckets"].values()) and arch["strikes"], "الأرشيف مختصر (بلا Strikes السلال) ويحفظ الكلية")
    ok(all("strikes" in v for v in json.load(open(os.path.join(t, "latest.json")))["buckets"].values()), "latest كامل بالسلال")
    # ===== SPY =====
    def spychain(spot=700.0, ts="2026-10-19 13:30:00"):
        opts = []
        for i in range(80):
            k = 660 + i
            for kind in "CP":
                opts.append({"option": "SPY261019%s%08d" % (kind, int(k * 1000)), "gamma": max(0.0001, 0.05 - abs(k - spot) * 0.0007),
                             "iv": 0.17, "open_interest": 2000.0 + (i * 53) % 700 + (800 if kind == "C" and k > spot else 0), "volume": 1.0})
        return {"timestamp": ts, "data": {"options": opts}}
    ref = {"ratio": 7000.0 / 700.0 * 1.0003, "spx_ref": 7000.0, "spy_ref": 700.0, "ref_time_utc": "2026-10-19T13:29:00+00:00", "ref_gap_min": 1.0, "mode": "live"}
    ft = datetime(2026, 10, 19, 13, 40, tzinfo=timezone.utc)
    sy = gamma.build_spy(ts2, ft, date(2026, 10, 19), ref=ref, raw=spychain())
    ok(sy["ok"] and sy["asset"] == "SPY" and sy["buckets"]["0"]["n"] > 0, "SPY: لقطة صالحة بسلال")
    ok(all(abs(x["kx"] - x["k"] * ref["ratio"]) < 0.06 for x in sy["strikes"]), "Strike السباي ← مكافئ SPX = Strike × (SPX/SPY)")
    ok(sy["call_wall_x"] is None or abs(sy["call_wall_x"] - sy["call_wall"] * ref["ratio"]) < 0.06, "جدار SPY محوَّل")
    ok(not gamma.build_spy(ts2, ft, date(2026, 10, 19), ref=ref, raw=spychain(ts="2026-10-19 11:00:00"))["ok"], "ختم SPY بعيد عن SPX ⇒ معطّل")
    ok(not gamma.build_spy(ts2, ft, date(2026, 10, 19), ref=ref, raw=spychain(ts="2026-10-19 15:00:00"))["ok"], "ختم SPY في المستقبل ⇒ معطّل")
    gamma.spy_ref = lambda: None
    nr = gamma.build_spy(ts2, ft, date(2026, 10, 19), raw=spychain())
    ok(not nr["ok"] and "متزامن" in nr["reason"], "بلا سعر متزامن ⇒ SPY معطّل بسبب واضح")
    ok(gamma.ref_mode(datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc), datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)) == "close", "قبل الافتتاح: مرجع إغلاق")
    ok(gamma.ref_mode(datetime(2026, 10, 19, 14, 20, tzinfo=timezone.utc), datetime(2026, 10, 19, 14, 25, tzinfo=timezone.utc)) == "live", "بعد الافتتاح: مرجع حي")
    ok(gamma.ref_mode(datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc), datetime(2026, 10, 19, 14, 25, tzinfo=timezone.utc)) == "close", "داخل الجلسة لكن المرجع قديم ⇒ إغلاق")
finally:
    shutil.rmtree(t, ignore_errors=True)
print("tests_gamma: %d فحصاً نجحت" % N)
