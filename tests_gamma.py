"""اختبارات gamma.py بلا شبكة: تحليل السلسلة، الحساب، التحقق، الأرشفة، وعدم النظر للمستقبل."""
import json, os, shutil, tempfile
from datetime import datetime, timedelta, timezone
import gamma

N = 0
def ok(c, m):
    global N; N += 1
    assert c, m

def chain(spot=7000.0, ts="2026-10-19 09:30:00", zero=False, n=40):
    opts = []
    for i in range(n):
        k = 6800 + i * 10
        for kind in "CP":
            g = 0.0 if zero else max(0.0001, 0.01 - abs(k - spot) * 0.00003)
            opts.append({"option": "SPXW261020%s%08d" % (kind, int(k * 1000)), "gamma": g,
                         "open_interest": 1000.0 + (i * 37) % 900 + (500 if kind == "C" and k > spot else 0), "volume": 5.0})
    opts.append({"option": "XYZ261020C00001000", "gamma": 1, "open_interest": 1})
    return {"timestamp": ts, "data": {"current_price": spot, "options": opts}}

t = tempfile.mkdtemp()
try:
    spot, ts, cs = gamma.parse_chain(chain())
    ok(spot == 7000.0 and len(cs) == 80, "تحليل 80 عقداً وتجاهل الرموز الغريبة")
    ok(ts.tzinfo is not None and ts.hour == 13 and ts.minute == 30, "09:30 EDT = 13:30 UTC")
    r = gamma.compute(spot, cs)
    ok(r["regime"] in ("positive", "negative") and len(r["strikes"]) >= 20, "نتائج الحساب")
    ok(all("oi" not in s and "open_interest" not in s for s in r["strikes"]), "لا OI في المخرجات")
    c0 = next(x for x in r["strikes"] if x["k"] == 7000.0)
    ok(c0["call"] > 0 and c0["put"] < 0 and abs(c0["net"] - (c0["call"] + c0["put"])) < 1e-6, "Call موجب وPut سالب")
    ok(r["expiries"] == ["2026-10-20"], "الاستحقاقات")
    ok(gamma.validate(r, spot, cs) is None, "لقطة سليمة")
    zs, _, zc = gamma.parse_chain(chain(zero=True))
    ok("gamma" in (gamma.validate(gamma.compute(zs, zc), zs, zc) or "") or gamma.validate(gamma.compute(zs, zc), zs, zc), "gamma الصفرية تُرفض")
    ok(gamma.validate(r, None, cs), "بدون سعر تُرفض")
    for bad in ({}, {"data": {}}, {"data": {"options": []}, "timestamp": "2026-10-19 09:30:00"}):
        try:
            gamma.parse_chain(bad); ok(False, "يجب أن يفشل")
        except ValueError:
            ok(True, "")
    # الأرشفة وقاعدة «أول لقطة قبل 09:30 تفوز» وعدم النظر للمستقبل
    f1 = datetime(2026, 10, 19, 13, 10, tzinfo=timezone.utc)      # 09:10 ET
    s1 = gamma.build(chain(ts="2026-10-19 09:05:00"), fetched=f1, with_es=False)
    ok(s1["ok"] and s1["status"] in ("fresh", "late", "stale"), "بناء اللقطة")
    w = gamma.archive(s1, t); ok(any("preopen" in x for x in w), "حُفظت كأول لقطة قبل الافتتاح")
    f2 = datetime(2026, 10, 19, 13, 25, tzinfo=timezone.utc)
    s2 = gamma.build(chain(ts="2026-10-19 09:20:00"), fetched=f2, with_es=False)
    w = gamma.archive(s2, t); ok(not any("preopen" in x for x in w), "الثانية لا تستبدل الأولى")
    pre = json.load(open(os.path.join(t, "preopen", "2026-10-19.json")))
    ok(pre["snapshot_et"].endswith("09:05"), "preopen بقيت الأولى")
    f3 = datetime(2026, 10, 19, 13, 50, tzinfo=timezone.utc)      # جُمعت بعد الافتتاح
    s3 = gamma.build(chain(ts="2026-10-19 09:25:00"), fetched=f3, with_es=False)
    gamma.archive(s3, t)
    lb = gamma.last_before_open("2026-10-19", t)
    ok(lb and lb["snapshot_et"].endswith("09:20"), "آخر خريطة قبل الافتتاح تتجاهل ما جُمع بعد 09:30 (دون نظر للمستقبل)")
    ok(gamma.last_before_open("2026-10-18", t) is None, "يوم بلا بيانات")
    lat = json.load(open(os.path.join(t, "latest.json")))
    ok(lat["snapshot_et"].endswith("09:25"), "latest = الأحدث")
    s_old = gamma.build(chain(ts="2026-10-19 09:00:00"), fetched=f3, with_es=False)
    gamma.archive(s_old, t)
    ok(json.load(open(os.path.join(t, "latest.json")))["snapshot_et"].endswith("09:25"), "لقطة أقدم لا تستبدل latest")
    ok(gamma.status_of(datetime.now(timezone.utc) - timedelta(minutes=10)) == "fresh", "طازجة")
    ok(gamma.status_of(datetime.now(timezone.utc) - timedelta(minutes=90)) == "late", "متأخرة")
    ok(gamma.status_of(datetime.now(timezone.utc) - timedelta(hours=9)) == "stale", "قديمة")
finally:
    shutil.rmtree(t, ignore_errors=True)
print("tests_gamma: %d فحصاً نجحت" % N)
