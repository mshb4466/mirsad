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
    D = date
    bo = lambda e, r: gamma.bucket_of(e, r)
    ok([bo(D(2026, 10, 19), D(2026, 10, 19)), bo(D(2026, 10, 20), D(2026, 10, 19)), bo(D(2026, 10, 23), D(2026, 10, 19)), bo(D(2026, 10, 26), D(2026, 10, 19)),
        bo(D(2026, 10, 30), D(2026, 10, 19)), bo(D(2026, 10, 31), D(2026, 10, 19)), bo(D(2026, 11, 2), D(2026, 10, 19))] == ["0", "wk", "wk", "mo", "mo", "mo", "later"], "سلال تقويمية: اليوم/بقية الأسبوع حتى الجمعة/بقية الشهر/ما بعد (الإثنين 19 أكتوبر)")
    ok([bo(D(2026, 10, 23), D(2026, 10, 23)), bo(D(2026, 10, 26), D(2026, 10, 23))] == ["0", "mo"], "الجمعة: لا «بقية الأسبوع»، والإثنين التالي من بقية الشهر")
    bb = gamma.bucket_bounds(D(2026, 10, 24))
    ok(bb["wk"] == (D(2026, 10, 25), D(2026, 10, 30)), "السبت: الأسبوع ينتهي الجمعة القادمة")
    bb = gamma.bucket_bounds(D(2026, 11, 30))
    ok(bb["wk"][1] == D(2026, 12, 4) and bb["mo"][0] > bb["mo"][1] and bb["later"][0] == D(2026, 12, 5), "أسبوع يعبر نهاية الشهر: «بقية الشهر» فارغة و«ما بعد» تبدأ بعد نهاية الأسبوع")
    bb = gamma.bucket_bounds(D(2026, 12, 15))
    ok(bb["mo"][1] == D(2026, 12, 31) and bb["later"][0] == D(2027, 1, 1), "ديسمبر: الشهر ينتهي 31 والتالي يناير بلا خطأ")
    for ref_ in (D(2026, 10, 19), D(2026, 10, 23), D(2026, 10, 24), D(2026, 11, 30), D(2026, 12, 31)):
        ok(all(sum(1 for _ in [0] if bo(ref_ + timedelta(days=i), ref_) == b) == 1 for i in range(0, 400) for b in [bo(ref_ + timedelta(days=i), ref_)]) and
           [bo(ref_ + timedelta(days=i), ref_) for i in range(0, 400)] == sorted([bo(ref_ + timedelta(days=i), ref_) for i in range(0, 400)], key=["0", "wk", "mo", "later"].index), "السلال متتابعة بلا تداخل ولا فجوة (%s)" % ref_)
    sp2, ts2, cs2 = gamma.parse_chain(multi())
    r2 = gamma.compute(sp2, cs2, datetime(2026, 10, 19, 13, 30, tzinfo=timezone.utc), date(2026, 10, 19))
    ok(r2["n_contracts"] == 5 * 80, "العقود المنتهية (261016) استُبعدت من «الكل»")
    ok([r2["buckets"][b]["n"] for b in gamma.BUCKETS] == [80, 80, 80, 160], "كل عقد في سلة واحدة فقط: اليوم/الأسبوع/الشهر/ما بعد")
    ok(sum(b["n"] for b in r2["buckets"].values()) == r2["n_contracts"], "مجموع عدد العقود في السلال = الكل")
    ok(abs(sum(b["net_gex"] for b in r2["buckets"].values()) - r2["net_gex"]) < 1e-3 * abs(r2["net_gex"]), "مجموع صافي السلال = صافي الكل")
    for row in r2["strikes"]:
        tot = sum(next((x["net"] for x in b["strikes"] if x["k"] == row["k"]), 0.0) for b in r2["buckets"].values())
        ok(abs(tot - row["net"]) <= 1e-6 * max(1.0, abs(row["net"])), "مجموع السلال لكل Strike = «الكل» عند %s" % row["k"])
    # تتحرك السلال مع اليوم: غداً يصير 261019 منتهياً و261022 «بقية الأسبوع» ثم 261030 «بقية الشهر»
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
    # --- انحدارات (20 أكتوبر): قائمة روابط SPY لا تُمرَّر كنص، وتقاطع ES/SPX ليلاً ---
    import sys, types, urllib.request, pandas as pd
    seen = []
    class _R:
        def __init__(s): pass
        def __enter__(s): return s
        def __exit__(s, *a): return False
        def read(s): return b"{}"
    _old = urllib.request.urlopen
    urllib.request.urlopen = lambda req, timeout=0: (seen.append(req.full_url), _R())[1]
    try:
        gamma.fetch(gamma.SPY_URLS)
    finally:
        urllib.request.urlopen = _old
    ok(seen == [gamma.SPY_URLS[0]], "fetch يقبل قائمة روابط SPY (ويجرب الأول)")
    idx_spx = pd.date_range("2026-10-19 19:55", periods=6, freq="1min", tz="UTC")                 # SPX توقف 20:00 UTC (إغلاق)
    idx_es = pd.date_range("2026-10-19 19:55", periods=6, freq="1min", tz="UTC").append(pd.date_range("2026-10-20 07:50", periods=3, freq="1min", tz="UTC"))
    class _T:
        def __init__(s, sym): s.sym = sym
        def history(s, period, interval, auto_adjust):
            if s.sym == "ES=F": return pd.DataFrame({"Close": [7050.0 + i for i in range(len(idx_es))]}, index=idx_es)
            if s.sym == "^GSPC": return pd.DataFrame({"Close": [7000.0 + i for i in range(len(idx_spx))]}, index=idx_spx)
            return pd.DataFrame({"Close": [700.0 + i / 10 for i in range(len(idx_spx))]}, index=idx_spx)
    fake = types.ModuleType("yfinance"); fake.Ticker = _T; _oy = sys.modules.get("yfinance"); sys.modules["yfinance"] = fake
    try:
        p = gamma._pair("ES=F", "^GSPC")
    finally:
        if _oy is not None: sys.modules["yfinance"] = _oy
        else: del sys.modules["yfinance"]
    ok(p is not None and p[0] == idx_spx[-1] and p[1] == 7055.0 and p[2] == 7005.0, "ES/SPX ليلاً: آخر دقيقة مشتركة = إغلاق أمس (لا None)")
    # --- خارج الجلسة: ملفا SPX وSPY من نفس إغلاق الجلسة يُقبلان ولو تباعد ختماهما ساعات (حالة 254 دقيقة) ---
    gamma.spy_ref = lambda: ref
    _ft = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
    _spx_ts = datetime(2026, 10, 20, 7, 52, tzinfo=timezone.utc)      # 03:52 نيويورك
    _spy_ts = _spx_ts - timedelta(minutes=254)                          # 23:38 نيويورك أمس
    _r = gamma.build_spy(_spx_ts, _ft, date(2026, 10, 19), ref=ref, raw=spychain(ts=_spy_ts.strftime("%Y-%m-%d %H:%M:%S")))
    ok(_r["ok"], "خارج الجلسة وفرق 254 دقيقة لكن نفس جلسة الإغلاق ⇒ SPY يُقبل: %s" % _r.get("reason"))
    _r2 = gamma.build_spy(_spx_ts, _ft, date(2026, 10, 19), ref=ref, raw=spychain(ts=(_spx_ts - timedelta(hours=20)).strftime("%Y-%m-%d %H:%M:%S")))
    ok(not _r2["ok"] and "جلسة" in _r2["reason"], "خارج الجلسة وملف SPY من جلسة سابقة أقدم ⇒ يُعطَّل")
    # --- حماية المصدر: تعطّل ES أو SPY (استثناء مفاجئ) لا يمنع بناء SPX ولا كتابته ---
    _oes, _osp = gamma.es_basis, gamma.build_spy
    def _boom(*a, **k): raise RuntimeError("انهيار تجريبي")
    gamma.es_basis = _boom; gamma.build_spy = _boom
    try:
        _s = gamma.build(chain(ts="2026-10-19 14:30:00"), fetched=datetime(2026, 10, 19, 18, 40, tzinfo=timezone.utc), with_es=True, with_spy=True)
    finally:
        gamma.es_basis, gamma.build_spy = _oes, _osp
    ok(_s["ok"] and _s["strikes"] and _s["es"] is None and _s["spy"]["ok"] is False and "SPY" in _s["spy"]["reason"], "انهيار ES وSPY معاً: SPX يبقى صالحاً ويُكتب مع تعطيل الطبقتين بسبب")
    # --- منحنى الجاما المحفوظ: مجموع منحنيات السلال = منحنى الكل (يُبنى عليه Flip والخلفية والاستحقاق المتعدد) ---
    _sp = gamma.build(chain(ts="2026-10-19 14:30:00"), fetched=datetime(2026, 10, 19, 18, 40, tzinfo=timezone.utc), with_es=False, with_spy=False)
    _pa = _sp.get("prof"); _bs = [b["prof"] for b in _sp["buckets"].values() if b.get("prof")]
    ok(_pa and _pa["n"] == len(_pa["v"]) == gamma.PROF_N and _bs, "الملف يحمل منحنى جاما للكل ولكل سلة غير فارغة")
    if _pa and _bs:
        ok(all(abs(sum(b["v"][i] for b in _bs) - _pa["v"][i]) < 0.002 for i in range(_pa["n"])), "مجموع منحنيات السلال = منحنى الكل (خطية)")
        ok(all(b["lo"] == _pa["lo"] and b["hi"] == _pa["hi"] for b in _bs), "كل المنحنيات على شبكة أسعار واحدة")
    _x2 = gamma._px(_pa, 10.0)
    ok(_x2["lo"] == round(_pa["lo"] * 10, 2) and _x2["v"] == _pa["v"], "منحنى SPY: الشبكة × النسبة والقيم كما هي")
    # --- تنبيه تغيّر المستويات: حدّ 5 نقاط، مقارنة بلقطة ما قبل الافتتاح، إشعار واحد لكل تغيّر جديد ---
    _b = {"ok": True, "snapshot_utc": "2026-10-23T12:00:00+00:00", "snapshot_et": "2026-10-23 08:00", "call_wall": 7740.0, "put_wall": 7640.0, "gamma_flip": 7770.0, "es": {"basis": 40.0},
          "spy": {"ok": True, "ratio": 10.0, "call_wall": 774.1, "put_wall": 764.1, "gamma_flip": 777.1, "call_wall_x": 7741.0, "put_wall_x": 7641.0, "gamma_flip_x": 7771.0}}
    _n = {"ok": True, "snapshot_utc": "2026-10-23T13:00:00+00:00", "snapshot_et": "2026-10-23 09:00", "status": "fresh", "call_wall": 7745.0, "put_wall": 7637.0, "gamma_flip": 7770.0, "es": {"basis": 41.0},
          "spy": {"ok": True, "ratio": 10.0, "call_wall": 774.1, "put_wall": 764.1, "gamma_flip": 777.1, "call_wall_x": 7741.0, "put_wall_x": 7641.0, "gamma_flip_x": 7771.0}}
    _ch = gamma.level_changes(gamma.level_map(_b), gamma.level_map(_n), sc_old=gamma.snap_scale(_b), sc_new=gamma.snap_scale(_n))
    ok([(c["key"], c["delta"]) for c in _ch] == [("SPX|CALL WALL", 5.0)], "حدّ التنبيه 5 نقاط: +5 يُحسب و−3 لا يُحسب")
    _root = tempfile.mkdtemp()
    try:
        gamma._wjson(os.path.join(_root, "preopen", "2026-10-23.json"), _b)
        gamma.attach_changes(_n, _root)
        ok(_n["baseline"]["snapshot_et"] == "2026-10-23 08:00" and _n["changes"]["n"] == 1, "اللقطة تحمل baseline وchanges")
        _cv = gamma.curve_of(dict(_b, spot=7700.0, strikes=[{"k": 7690.0, "net": 1e9}, {"k": 7900.0, "net": 2e9}]))
        ok(_cv and _cv["SPX"] == [[7690.0, 1e9]] and "curve" in _n["baseline"], "baseline يحمل منحنى الجاما القديم للتراكب (±150)")
        ok(gamma.curve_of({}) is None, "curve_of فشل ناعم")
        _sent = []
        ok(gamma.notify_changes(_n, _root, send=lambda m: _sent.append(m) or True) and len(_sent) == 1 and "SPX CALL WALL" in _sent[0] and "7780.00 ← 7786.00" in _sent[0], "إشعار تيليجرام بأسعار ES (7740+40 ← 7745+41)")
        ok(not gamma.notify_changes(_n, _root, send=lambda m: _sent.append(m) or True) and len(_sent) == 1, "لا تكرار لنفس التغيّر")
        _n2 = dict(_n, call_wall=7750.0); gamma.attach_changes(_n2, _root)
        ok(gamma.notify_changes(_n2, _root, send=lambda m: _sent.append(m) or True) and len(_sent) == 2, "تغيّر جديد = إشعار جديد")
        ok(not gamma.notify_changes(dict(_n2, status="stale"), _root, send=lambda m: _sent.append(m) or True), "لا إشعار على لقطة قديمة")
        _n3 = dict(_b, snapshot_utc="2026-10-23T11:00:00+00:00"); gamma.attach_changes(_n3, _root)
        ok(_n3["baseline"] is None and _n3["changes"]["n"] == 0, "لقطة أقدم من الأساس: لا مقارنة")
        _bad = dict(_n); _bad["spy"] = "x"; gamma.attach_changes(_bad, _root)
        ok(_bad["call_wall"] == 7745.0, "عطل في حساب التغيّر لا يمس بيانات SPX")
    finally:
        shutil.rmtree(_root, ignore_errors=True)
    # --- القمم والقيعان المهمة: تحرّك/جديدة/اختفت ---
    def _pk(peaks, spot=7700.0, base=1e8):
        rows = [{"k": 7550.0 + 5 * i, "net": base * 0.01} for i in range(60)]
        for k, v in peaks:
            for r in rows:
                if r["k"] == k: r["net"] = v
        return {"spot": spot, "strikes": rows, "call_wall": None, "put_wall": None}
    _o = gamma.peak_map(_pk([(7600.0, 1e9), (7650.0, -8e8), (7720.0, 5e8)]))
    ok([(x["k"], x["s"]) for x in _o["SPX"]] == [(7600.0, 1), (7650.0, -1), (7720.0, 1)], "القمم المحلية المهمة تُستخرج بالإشارة")
    _n1 = gamma.peak_map(_pk([(7600.0, 1e9), (7650.0, -8e8), (7720.0, 5e8)]))
    ok(gamma.peak_changes(_o, _n1) == [], "لا تغيّر عند تطابق القمم")
    _n2 = gamma.peak_map(_pk([(7610.0, 1e9), (7650.0, -8e8), (7720.0, 5e8)]))
    _c2 = gamma.peak_changes(_o, _n2)
    ok(len(_c2) == 1 and _c2[0]["change"] == "moved" and _c2[0]["old"] == 7600.0 and _c2[0]["new"] == 7610.0 and _c2[0]["delta"] == 10.0, "قمة تحرّكت 10 نقاط")
    _n3 = gamma.peak_map(_pk([(7600.0, 1e9), (7650.0, -8e8)]))
    _c3 = gamma.peak_changes(_o, _n3)
    ok(len(_c3) == 1 and _c3[0]["change"] == "gone" and _c3[0]["old"] == 7720.0, "قمة اختفت")
    _n4 = gamma.peak_map(_pk([(7600.0, 1e9), (7650.0, -8e8), (7720.0, 5e8), (7680.0, 6e8)]))
    _c4 = gamma.peak_changes(_o, _n4)
    ok(len(_c4) == 1 and _c4[0]["change"] == "new" and _c4[0]["new"] == 7680.0, "قمة جديدة")
    _n5 = gamma.peak_map(_pk([(7600.0, 1e9), (7650.0, -8e8), (7720.0, 5e8)], spot=7700.0)); _n5["SPX"][0]["k"] = 7603.0
    ok(gamma.peak_changes(_o, _n5) == [], "تحرّك أقل من 5 نقاط لا يُنبَّه")
    _w = gamma.peak_map(dict(_pk([(7720.0, 5e8)]), call_wall=7720.0))
    ok(all(abs(x["k"] - 7720.0) > 3 for x in _w["SPX"]), "القمة المطابقة لجدار تُتابَع كجدار لا كقمة")
    _bb = dict(_b, spot=7700.0, strikes=_pk([(7600.0, 1e9), (7650.0, -8e8)])["strikes"])
    _nn = dict(_n, spot=7700.0, strikes=_pk([(7610.0, 1e9), (7650.0, -8e8)])["strikes"])
    _r2 = tempfile.mkdtemp()
    try:
        gamma._wjson(os.path.join(_r2, "preopen", "2026-10-23.json"), _bb)
        gamma.attach_changes(_nn, _r2)
        _ks = [(i["kind"], i["change"]) for i in _nn["changes"]["items"]]
        ok(("PEAK", "moved") in _ks and ("CALL WALL", "moved") in _ks, "التغيّرات تشمل الجدران والقمم معاً")
        _s2 = []
        gamma.notify_changes(_nn, _r2, send=lambda m: _s2.append(m) or True)
        ok(_s2 and "قمة قوية" in _s2[0], "رسالة تيليجرام تذكر القمة")
    finally:
        shutil.rmtree(_r2, ignore_errors=True)
    # --- فصل التغيّر الحقيقي عن أثر فرق السعر ونسبة SPY ---
    _sp0 = {"ok": True, "ratio": 10.00, "call_wall": 774.0, "put_wall": 764.0, "gamma_flip": 777.0}
    _s_old = dict(_b, spy=_sp0); _s_new = dict(_b, spy=dict(_sp0, ratio=10.06))
    ok(gamma.level_changes(gamma.level_map(_s_old), gamma.level_map(_s_new), sc_old=gamma.snap_scale(_s_old), sc_new=gamma.snap_scale(_s_new)) == [], "تغيّر نسبة SPX/SPY وحده لا يُنتج تغيّر مستوى لـ SPY")
    _s_mv = dict(_b, spy=dict(_sp0, ratio=10.06, call_wall=775.0))
    _cm = gamma.level_changes(gamma.level_map(_s_old), gamma.level_map(_s_mv), sc_old=gamma.snap_scale(_s_old), sc_new=gamma.snap_scale(_s_mv))
    ok(len(_cm) == 1 and _cm[0]["key"] == "SPY|CALL WALL" and abs(_cm[0]["delta"] - 10.06) < 0.01, "تغيّر Strike فعلي في SPY (1 نقطة = ~10 نقاط SPX) يُرصد")
    _r3 = tempfile.mkdtemp()
    try:
        _bb2 = dict(_b, es={"basis": 38.0, "mode": "close"}); _nn2 = dict(_n, call_wall=7740.0, put_wall=7640.0, es={"basis": 42.5, "mode": "live"})
        gamma._wjson(os.path.join(_r3, "preopen", "2026-10-23.json"), _bb2)
        gamma.attach_changes(_nn2, _r3)
        _c3 = _nn2["changes"]
        ok(_c3["n"] == 0 and _c3["basis_note"] and _c3["basis_drift"] == 4.5, "فرق ES−SPX تغيّر 4.5 بلا تغيّر في الجاما: ملاحظة فقط لا تغيّر مستوى")
        _nn3 = dict(_nn2, call_wall=7746.0); gamma.attach_changes(_nn3, _r3)
        _m = []
        gamma.notify_changes(_nn3, _r3, send=lambda x: _m.append(x) or True)
        ok(_m and "منه حقيقي +6.00" in _m[0] and "فرق ES−SPX تغيّر من 38.00 إلى 42.50" in _m[0], "رسالة تيليجرام تفصل الحقيقي عن أثر فرق السعر")
    finally:
        shutil.rmtree(_r3, ignore_errors=True)
    # --- الخط الزمني لليوم ---
    _r4 = tempfile.mkdtemp()
    try:
        _d1 = dict(_n, snapshot_utc="2026-10-23T14:00:00+00:00", call_wall=7740.0)
        _d2 = dict(_n, snapshot_utc="2026-10-23T14:15:00+00:00", call_wall=7750.0)
        ok(gamma.append_day(_d1, _r4) and gamma.append_day(_d2, _r4), "الخط الزمني: إضافة نقطتين")
        ok(not gamma.append_day(_d2, _r4), "الخط الزمني: لا تكرار لنفس اللقطة")
        _dj = gamma._rjson(os.path.join(_r4, "day.json"))
        ok(len(_dj["pts"]) == 2 and _dj["pts"][1]["lv"]["SPX|CALL WALL"] == 7750.0 and _dj["day"] == "2026-10-23", "الخط الزمني: النقاط والمستويات بمكافئ SPX")
        _d3 = dict(_n, snapshot_utc="2026-10-26T14:00:00+00:00")
        gamma.append_day(_d3, _r4)
        ok(len(gamma._rjson(os.path.join(_r4, "day.json"))["pts"]) == 1, "الخط الزمني: يوم جديد يبدأ ملفاً جديداً")
    finally:
        shutil.rmtree(_r4, ignore_errors=True)
finally:
    shutil.rmtree(t, ignore_errors=True)
print("tests_gamma: %d فحصاً نجحت" % N)
