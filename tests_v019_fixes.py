# -*- coding: utf-8 -*-
"""اختبارات قبول v0.19 للإصلاحات: المراجعات، الرجوع من النسخة الاحتياطية، السجل الموحّد، الانتظار السريع، وأقل زمن للتنبيه."""
import json
import os
import tempfile
from datetime import timedelta

import actuals
import collector as c
import indicators
import migrate
import runner as r
from tests_actuals import NOW, raw, mk_deps, bls_rows, run
from tests_runner import Box
from tests_v0181 import DEAD, auto_deps, roundtrip, run_auto, stale_bls


# ───────── ب) المراجعة تُحدّث كل شيء معاً وتُسترجع ─────────
def test_revision_updates_value_raw_source_log_and_prev_revised_together_and_restores():
    evs = c.parse_events([raw("Unemployment Rate", 3, forecast="4.2%", previous="4.3%")])
    st = {}
    run(evs, st, mk_deps(bls_rows))
    eid = actuals.event_id(evs[0])
    first = dict(st["actuals"][eid])
    assert first["actual"] == "4.3%" and first["raw"] is not None
    rev = lambda: dict(bls_rows(), unrate=[(d, 4.4) for d, _ in bls_rows()["unrate"]])
    evs2 = c.parse_events([raw("Unemployment Rate", 3, forecast="4.2%", previous="4.3%")])
    r.resolve_actuals(evs2, NOW + timedelta(hours=5), roundtrip(st), mk_deps(rev))      # بعد إعادة تشغيل
    st2 = roundtrip(st)
    evs3 = c.parse_events([raw("Unemployment Rate", 3, forecast="4.2%", previous="4.3%")])
    r.resolve_actuals(evs3, NOW + timedelta(hours=5), st2, mk_deps(rev))
    rec = st2["actuals"][eid]
    assert rec["actual"] == "4.4%" and rec["status"] == "revised" and rec["revised_from"] == "4.3%"
    assert abs(rec["raw"] - 4.4) < 1e-9, "raw يجب أن يتبع القيمة الجديدة لا القديمة"
    e = evs3[0]
    assert e["actual"] == "4.4%" and abs(e["actual_raw"] - 4.4) < 1e-9 and e["revised_from"] == "4.3%"
    old = rec["history"][-1]                                       # القيمة القديمة محفوظة بخامها ومصدرها في التاريخ
    assert old["value"] == "4.3%" and abs(old["raw"] - 4.3) < 1e-9 and old.get("source") is not None
    log = [x for x in st2["actuals_log"] if x["value"]]
    assert log[-1]["value"] == "4.4%" and abs(log[-1]["raw"] - 4.4) < 1e-9          # سجل التدقيق يتبع القيمة الجديدة
    st3 = roundtrip(st2)                                           # استرجاع بعد الحفظ
    evs4 = c.parse_events([raw("Unemployment Rate", 3)])
    actuals.restore(evs4, st3)
    assert evs4[0]["actual"] == "4.4%" and evs4[0]["revised_from"] == "4.3%"


def test_revision_carries_new_prev_revised_and_clears_it_when_absent():
    st = {"actuals": {}}
    e = c.parse_events([raw("Core PCE Price Index m/m", 3)])[0]
    rec = {"actual": "0.2%", "note": "", "status": "verified_official", "trust": "official", "raw": 0.2, "history": []}
    new = {"actual": "0.4%", "actual_note": "n", "actual_raw": 0.4, "prev_revised": "0.3%"}
    actuals.apply_result(rec, e, new, "official", "revised")
    assert rec["actual"] == "0.4%" and rec["raw"] == 0.4 and rec["prev_revised"] == "0.3%" and e["prev_revised"] == "0.3%" and e["actual_raw"] == 0.4
    actuals.apply_result(rec, e, {"actual": "0.4%", "actual_raw": 0.4}, "official", "revised")
    assert rec["prev_revised"] == "" and e["prev_revised"] == ""      # لا يبقى حقل قديم


# ───────── ج) الرجوع من النسخة الاحتياطية ─────────
def test_rollback_restores_old_state_and_keeps_current_for_safety():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "state.json")
    old = {"seen_events": ["a"], "actuals": {"US|cpi|2026-09|2026-10-14": {"actual": "0.3%", "status": "verified", "title": "CPI m/m",
                                                                           "time": (NOW - timedelta(hours=3)).isoformat()}}}
    json.dump(old, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    s, rep = migrate.load_and_migrate(p, NOW)
    json.dump(s, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    assert json.load(open(p, encoding="utf-8")).get("schema_version") == migrate.SCHEMA_VERSION if hasattr(migrate, "SCHEMA_VERSION") else True
    res = r_ = migrate.rollback(p)
    back = json.load(open(p, encoding="utf-8"))
    assert back == old, "الاستعادة يجب أن تعيد الحالة القديمة حرفياً"
    assert res["saved_current"] and os.path.exists(res["saved_current"])
    assert json.load(open(res["saved_current"], encoding="utf-8")) == s        # الحالة المرحَّلة لم تضع
    s2, rep2 = migrate.load_and_migrate(p, NOW + timedelta(hours=1))             # الترحيل بعد الرجوع يعمل ثانية دون فقد
    assert rep2.get("skipped") is not True or s2.get("schema_version")


def test_workflow_commits_backups_dir_so_it_survives_actions_end():
    import yaml
    wf = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), ".github", "workflows", "mirsad.yml"), encoding="utf-8"))
    txt = json.dumps(wf, ensure_ascii=False)
    assert "git add backups" in txt, "مجلد backups يجب أن يُلتزم به في المستودع (دائم)"
    assert open("workflow-mirsad.yml", encoding="utf-8").read() == open(".github/workflows/mirsad.yml", encoding="utf-8").read()


# ───────── د) الانتظار لا يحجب ولا ينتظر غير المدعوم ─────────
def test_unsupported_events_are_never_fast_waited():
    evs = c.parse_events([raw("ISM Manufacturing PMI", 0.1), raw("ADP Non-Farm Employment Change", 0.1), raw("CB Consumer Confidence", 0.1),
                          raw("FOMC Member Speaks", 0.1)])
    assert r.fast_waiting(evs, NOW) == []
    sup = c.parse_events([raw("Unemployment Rate", 0.1)])
    assert len(r.fast_waiting(sup, NOW)) == 1


def test_watch_does_not_sleep_for_unsupported_event_and_uses_real_elapsed_time():
    evs = c.parse_events([raw("ISM Manufacturing PMI", 0.1)])
    slept = []
    now2, got = r.watch_releases(evs, NOW, {}, dict(DEAD, sleep=slept.append, watch_s=330))
    assert slept == [] and not got
    evs2 = c.parse_events([raw("Unemployment Rate", 0.1)])
    clock = iter([0.0, 40.0, 80.0, 400.0, 500.0, 600.0])
    slept2, st_w = [], {}
    n2, got2 = r.watch_releases(evs2, NOW, st_w, dict(DEAD, sleep=slept2.append, watch_s=330, monotonic=lambda: next(clock)))
    info = st_w["last_watch"]
    assert 1 <= len(slept2) <= 6 and info["polls"] == len(slept2)
    assert not got and info["reason"] != "وصل الرقم"                 # لم يصل رقم فلا يُدّعى وصوله
    assert info["waited_s"] >= 40 and info["waited_s"] <= 600      # الزمن مأخوذ من الساعة الحقيقية المُمرَّرة لا من عدد الجولات


def test_verified_release_is_sent_before_any_wait():
    """ما تحقق في الجولة الأولى يُرسَل قبل أي نوم؛ الانتظار لا يسبق الإرسال."""
    order, box = [], Box()
    cal = lambda now: c.parse_events([raw("Unemployment Rate", 0.5, forecast="4.2%", previous="4.3%"),
                                      raw("Non-Farm Employment Change", 0.5, forecast="150K", previous="140K")])
    d = auto_deps(cal, bls_rows)
    d["watch_s"] = 300
    d["sleep"] = lambda s: order.append(("sleep", len([m for m in box.msgs if "صدرت بيانات" in m])))
    st = {"seen_events": [], "last_shock": None}
    run_auto(NOW, st, box, d)
    assert [m for m in box.msgs if "صدرت بيانات" in m], "يجب إرسال ما تحقق"
    assert all(n >= 1 for _, n in order), "لا نوم قبل إرسال أول ما تحقق"


# ───────── السجل الموحّد: كل ما أُرسل يظهر في التطبيق بمعرّف ثابت ─────────
def test_every_sent_release_late_and_revision_alert_is_in_state_alerts_with_stable_id():
    os.environ["GITHUB_REPOSITORY"] = "user/mirsad"
    box, st = Box(), {"seen_events": [], "last_shock": None}
    cal = lambda now: c.parse_events([raw("Unemployment Rate", 4, forecast="4.2%", previous="4.3%")])
    run_auto(NOW, st, box, auto_deps(cal, stale_bls))
    run_auto(NOW + timedelta(hours=1), st, box, auto_deps(cal, bls_rows))                 # وصول متأخر
    rev = lambda: dict(bls_rows(), unrate=[(dd, 4.4) for dd, _ in bls_rows()["unrate"]])
    run_auto(NOW + timedelta(hours=5), roundtrip(st), box, auto_deps(cal, rev))
    st = roundtrip(st)
    run_auto(NOW + timedelta(hours=5), st, box, auto_deps(cal, rev))
    al = st.get("alerts") or []
    kinds = {a.get("kind") for a in al}
    assert "late" in kinds, kinds
    eid = actuals.event_id(c.parse_events([raw("Unemployment Rate", 4)])[0])
    mine = [a for a in al if a.get("id") == eid]
    assert len(mine) == 1, "حدث واحد = سجل واحد بمعرّف ثابت، تتراكم عليه التحديثات لا نسخ مكررة"
    assert any("مراجعة" in (u.get("text") or "") or u.get("kind") == "revision" for u in mine[0].get("updates", [])), mine[0]
    assert all(a.get("important") is not None for a in al)
    sent_with_link = [m for m in box.msgs if "#e=" in m]
    assert sent_with_link, "رسالة الإشعار تحمل رابطاً يفتح الحدث نفسه"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("✔", t.__name__)
    print(f"نجحت كل الاختبارات ({len(tests)})")
