# -*- coding: utf-8 -*-
"""اختبارات قبول v0.19.1 — حالات مراجعة 17 أكتوبر: سقف الثقة بجودة البيانات، قرب الخبر المهم، توحيد الوحدات، تفسير السابق والمراجعات.
بيانات اصطناعية: تثبت المنطق لا صحة أرقام السوق الحقيقية ولا الجلب الحي."""
from datetime import datetime, timedelta, timezone

import bias
import release_impact as ri
import verdict
from tests_bias import full
from tests_v019_release import NOW, cpi, bias_with


def jolts(a, fc, prev="7.0M", minutes=20, title="JOLTS Job Openings"):
    return {"title": title, "time": NOW - timedelta(minutes=minutes), "impact": "High", "forecast": fc, "previous": prev, "actual": a,
            "actual_src": "official", "status": "verified_official", "actual_source": "BLS", "country": "USD"}


def good_bias():
    m, p, f, rg = full(lean=-0.6, gap=-0.4, y=(4.2, 3.9), dxy=(103, 100), liq=2.5, oas=2.8, rk="goldilocks")
    m["label"] = "تيسيري"
    return bias.compute(m, p, f, rg), (m, p, f, rg)


def rep(b, safety=None, conf=None, **kw):
    r = {"bias": b, "releases": {}, "risk": {}, "intensity": 5.0}
    if safety is not None:
        r["safety"] = safety
    if conf is not None:
        r["confidence"] = conf
    r.update(kw)
    return r


OK_SAFE = {"state": "ok", "coverage": 1.0, "issues": []}
HI = {"label": "مرتفعة", "points": 95, "why": []}


# ───────── 1) سقف الثقة ─────────
def test_weak_data_with_agreeing_factors_never_gives_high_confidence():
    b, _ = good_bias()
    assert b["confidence"] == "مرتفعة"                                                 # العوامل متفقة
    v = verdict.build(rep(b, {"state": "major", "coverage": 0.9, "issues": []}, {"label": "منخفضة", "points": 30, "why": ["مصدر معطوب"]}), NOW)
    assert v["available"] and v["confidence"] == "منخفضة" and v["agreement"] == "مرتفعة" and v["degraded"]
    assert v["reliability"]["label"] == "منخفضة" and v["reliability"]["reasons"]
    assert "الثقة منخفضة" in v["advice"] and "مصدر معطوب" in v["advice"] + " ".join(v["reliability"]["reasons"])


def test_major_safety_state_caps_even_if_report_confidence_label_is_high():
    b, _ = good_bias()
    v = verdict.build(rep(b, {"state": "major", "coverage": 0.95, "issues": []}, HI), NOW)
    assert v["confidence"] == "منخفضة" and v["available"]                              # خلل مؤثر: لا «مرتفعة» أبداً


def test_partial_coverage_caps_at_medium_and_healthy_data_keeps_high():
    b, _ = good_bias()
    assert verdict.build(rep(b, {"state": "warn", "coverage": 0.7, "issues": []}, HI), NOW)["confidence"] == "متوسطة"
    v = verdict.build(rep(b, OK_SAFE, HI), NOW)
    assert v["confidence"] == "مرتفعة" and not v["degraded"]


def test_unknown_data_quality_is_not_treated_as_good():
    b, _ = good_bias()
    v = verdict.build(rep(b), NOW)
    assert v["confidence"] == "متوسطة" and any("غير معلومة" in r for r in v["reliability"]["reasons"])


def test_invalid_data_is_explicit_and_keeps_last_valid_assessment_time():
    b, _ = good_bias()
    prev = {"bias": "support", "bias_label": "داعم", "lean": "mixed", "ok_at": (NOW - timedelta(hours=2)).isoformat()}
    for st, cov in (("critical", 0.95), ("incomplete", 0.5), ("ok", 0.55)):         # حرج حتى مع تغطية جيدة (كان يمرّ سابقاً)
        v = verdict.build(rep(b, {"state": st, "coverage": cov, "issues": [], "label": "التقييم غير مكتمل"}, HI), NOW, prev)
        assert not v["available"] and v["confidence"] == "غير متاح" and v["advice"].startswith("التقييم غير مكتمل"), st
        assert v["last_ok_at"] == prev["ok_at"] and v["last_ok_at_ar"] and v["reason"], st


def test_pending_release_still_caps_confidence():
    b, _ = good_bias()
    pend = {"pending": [{"id": "x", "name": "CPI", "status_ar": "بانتظار", "unsupported": False}], "groups": [], "items": []}
    v = verdict.build(rep(b, OK_SAFE, HI, releases=pend), NOW)
    assert v["confidence"] == "متوسطة" and "إصدار مهم لم يُدمج بعد" in v["reliability"]["reasons"]


# ───────── 2) قرب الخبر المهم ─────────
def ev(title, mins, impact="High", base=NOW, actual="", status="upcoming"):
    return {"title": title, "time": base + timedelta(minutes=mins), "impact": impact, "forecast": "0.3%", "previous": "0.3%", "actual": actual, "status": status}


def test_cpi_one_minute_away_changes_the_advice_and_shows_name_time_remaining():
    b, _ = good_bias()
    r = rep(b, OK_SAFE, HI)
    plain = verdict.build(r, NOW, None, [])["advice"]
    near = verdict.build(r, NOW, None, [ev("CPI m/m", 1)])
    assert near["advice"] != plain and ("CPI" in near["advice"] or "المستهلك" in near["advice"])
    assert "بعد دقيقة" in near["advice"] and "16:51" in near["advice"]                  # 13:51 UTC = 16:51 بغداد
    assert "مخاطرة" in near["advice"] and near["upcoming"][0]["imminent"]
    assert near["advice"].startswith("النصيحة الآن:")


def test_window_is_configurable_and_far_or_low_impact_events_are_ignored():
    b, _ = good_bias()
    r = rep(b, OK_SAFE, HI)
    far = [ev("CPI m/m", 200)]
    assert verdict.build(r, NOW, None, far)["upcoming"] == []
    assert verdict.build(r, NOW, None, far, window_min=300)["upcoming"][0]["remaining_ar"] == "3 ساعة و20 دقيقة"
    assert verdict.build(r, NOW, None, [ev("Some Low Data", 5, impact="Low")])["upcoming"] == []
    soon = verdict.build(r, NOW, None, [ev("CPI m/m", 40)])
    assert not soon["upcoming"][0]["imminent"] and "خفّض الاعتماد" in soon["advice"]


def test_baghdad_conversion_uses_the_events_real_utc_time_in_any_season():
    b, _ = good_bias()
    for base in (datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc), datetime(2026, 12, 10, 13, 0, tzinfo=timezone.utc)):
        e = {"title": "CPI m/m", "time": base + timedelta(minutes=30), "impact": "High", "forecast": "0.3%", "previous": "0.3%", "actual": "", "status": "upcoming"}
        u = verdict.build(rep(b, OK_SAFE, HI), base, None, [e])["upcoming"][0]
        assert u["at_ar"] == (base + timedelta(minutes=30, hours=3)).strftime("%H:%M")


def test_after_the_time_without_actual_says_confirmation_pending_not_old_text():
    b, _ = good_bias()
    e = cpi("", status="awaiting", trust="", minutes=3)
    e.update(actual="")
    m, p, f, rg = full(lean=-0.6, gap=-0.4, y=(4.2, 3.9), dxy=(103, 100), liq=2.5, oas=2.8, rk="goldilocks")
    rel = ri.build([e], NOW, m, None)
    bb = bias.compute(m, p, f, rg, None, rel)
    v = verdict.build({"bias": bb, "releases": rel, "risk": {}, "safety": OK_SAFE, "confidence": HI, "intensity": 5.0}, NOW, None, [e])
    assert "حان موعد" in v["advice"] and "ولم تتأكد القراءة بعد" in v["advice"] and v["confidence"] != "مرتفعة"
    ism = cpi("", title="ISM Manufacturing PMI", status="awaiting", trust="", minutes=3)
    rel2 = ri.build([ism], NOW, m, None)
    v2 = verdict.build({"bias": bb, "releases": rel2, "risk": {}, "safety": OK_SAFE, "confidence": HI}, NOW, None, [ism])
    assert "لا مصدر آلي" in v2["advice"]


# ───────── 3) توحيد الوحدات ─────────
def test_equivalent_units_give_identical_surprise_weight_and_bias():
    forms = [("7.5M", "7.2M"), ("7500K", "7200K"), ("7500000", "7200000"), ("7.5M", "7200K"), ("7500K", "7.2M"), ("7500000", "7.2M")]
    outs = []
    for a, fc in forms:
        it = ri.item_for(jolts(a, fc, prev="7.0M"), NOW, "محايد", 0.0, None)
        assert it, (a, fc)
        outs.append((it["z"], it["signal"], it["final"], it["effect"], it["importance"]))
    assert len(set(outs)) == 1, outs
    contrib = set()
    for a, fc in forms:
        b, _ = bias_with([jolts(a, fc)])
        contrib.add(next(x["contribution"] for x in b["components"] if x["key"] == "events"))
    assert len(contrib) == 1


def test_payroll_and_claims_equivalent_forms_and_revision_and_previous():
    for a, fc in (("250K", "150K"), ("250000", "150000"), ("0.25M", "150K")):
        e = {"title": "Non-Farm Employment Change", "time": NOW - timedelta(minutes=20), "impact": "High", "forecast": fc, "previous": "140K",
             "actual": a, "actual_src": "official", "status": "verified_official", "prev_revised": "160000"}
        it = ri.item_for(e, NOW, "محايد", 0.0, None)
        assert it and it["z"] == round((250 - 150) / 75.0, 2) and it["unit"] == "K" and "السابق عُدّل" in it["revision"], (a, fc, it and it["z"])
    c1 = ri.item_for({"title": "Unemployment Claims", "time": NOW - timedelta(minutes=20), "impact": "High", "forecast": "230K", "previous": "225K",
                      "actual": "260K", "actual_src": "official", "status": "verified_official"}, NOW, "محايد", 0.0, None)
    c2 = ri.item_for({"title": "Unemployment Claims", "time": NOW - timedelta(minutes=20), "impact": "High", "forecast": "230000", "previous": "225000",
                      "actual": "260000", "actual_src": "official", "status": "verified_official"}, NOW, "محايد", 0.0, None)
    assert c1["z"] == c2["z"] and c1["final"] == c2["final"]


def test_unit_mismatch_is_dropped_not_guessed():
    e = {"title": "Non-Farm Employment Change", "time": NOW - timedelta(minutes=20), "impact": "High", "forecast": "150K", "previous": "140K",
         "actual": "150", "actual_src": "official", "status": "verified_official"}
    assert ri.item_for(e, NOW, "محايد", 0.0, None) is None                           # 150 مقابل 150K = وحدتان مختلفتان
    e2 = dict(e, actual="0.3%", forecast="150K", previous="140K")
    assert ri.item_for(e2, NOW, "محايد", 0.0, None) is None                          # نسبة مقابل عدد
    assert ri.canon_value(None, "4.2%") == 4.2 and ri.canon_value(None, "4.2") is None


# ───────── 4) السابق والمراجعات والمكوّنات ─────────
def test_inline_but_accelerating_states_both_and_matches_contribution():
    it = ri.item_for(cpi("0.3%", fc="0.3%", prev="0.1%"), NOW, "محايد", 0.0, None)
    assert "مطابق للتوقع" in it["initial"] and "تسارع" in it["initial"] and "مُسعَّر" in it["initial"]
    assert it["signal"] == 0 and it["effect"] == "neu"                                   # التفسير يطابق المساهمة: لا إشارة
    assert "المكوّنات الداخلية" in it["explain"]["unavailable"] and "غير متاحة" in it["explain"]["unavailable"]
    assert "مُسعَّر" in it["explain"]["why_signal"]


def test_previous_does_not_double_count_when_forecast_exists():
    a = ri.item_for(cpi("0.4%", fc="0.3%", prev="0.1%"), NOW, "محايد", 0.0, None)
    b = ri.item_for(cpi("0.4%", fc="0.3%", prev="0.3%"), NOW, "محايد", 0.0, None)
    assert a["signal"] == b["signal"] and a["trend"] != b["trend"]                      # التفسير يختلف والإشارة لا تتضاعف


def test_trend_is_explained_in_both_directions_and_flags_miss_vs_expectation():
    dec = ri.item_for(cpi("0.1%", fc="0.3%", prev="0.4%"), NOW, "محايد", 0.0, None)
    assert "تباطؤ" in dec["trend"] and "أقل من المتوقع" in dec["initial"]
    surprise_accel = ri.item_for(cpi("0.4%", fc="0.1%", prev="0.1%"), NOW, "محايد", 0.0, None)
    assert "جزء من المفاجأة" in surprise_accel["trend"] and surprise_accel["signal"] != 0


def test_no_forecast_uses_previous_at_half_weight_and_says_so():
    nf = ri.item_for(cpi("0.5%", fc="", prev="0.3%"), NOW, "محايد", 0.0, None)
    wf = ri.item_for(cpi("0.5%", fc="0.3%", prev="0.1%"), NOW, "محايد", 0.0, None)
    assert nf and nf["basis"] == "previous" and "بلا توقع" in nf["initial"]
    same = ri.item_for(cpi("0.5%", fc="0.3%", prev="0.3%"), NOW, "محايد", 0.0, None)
    assert abs(nf["signal"]) == abs(same["signal"]) / 2 and abs(nf["signal"]) > 0
    assert ri.item_for(cpi("0.5%", fc="", prev=""), NOW, "محايد", 0.0, None) is None


def test_core_vs_headline_conflict_is_explained_and_weighted_not_a_tie():
    hot_headline = cpi("0.5%", fc="0.3%", prev="0.3%", title="CPI m/m")
    cool_core = cpi("0.1%", fc="0.3%", prev="0.3%", title="Core CPI m/m")
    rel = ri.build([hot_headline, cool_core], NOW, {}, None)
    g = rel["groups"][0]
    assert g["conflict"] and "Core CPI m/m" in g["conflict"] and "وليست تعادلاً آلياً" in g["conflict"]
    assert "مرجّح" in g["mode"] and g["value"] != 0 and g["value"] > 0                  # الأساسي أثقل فالمحصلة تتبعه (داعم)
    assert "اختلاف" in rel["note"]
    flip = ri.build([cpi("0.1%", title="CPI m/m"), cpi("0.5%", title="Core CPI m/m")], NOW, {}, None)["groups"][0]
    assert flip["value"] < 0 and flip["conflict"] != g["conflict"]


def test_revision_of_previous_enters_the_explanation_and_the_signal():
    e = cpi("0.3%", fc="0.3%", prev="0.1%", prev_revised="0.3%")
    it = ri.item_for(e, NOW, "محايد", 0.0, None)
    assert "السابق عُدّل من 0.1% إلى 0.3%" in it["revision"] and "السابق المعدَّل" in it["trend"]
    assert it["signal"] != 0                                                         # المراجعة أثّرت


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("✔", k)
    print(f"نجحت كل الاختبارات ({n})")
