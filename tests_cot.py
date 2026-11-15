"""اختبارات بطاقة ميل المؤسسات (cot.py). الأرقام مأخوذة من ملف CFTC الحقيقي FinComWk بتاريخ 2026-11-03 (E-mini، الرمز 13874A)."""
import copy
import json
from datetime import datetime, timezone

import cot
import runner

# فهارس الأعمدة الموثّقة: 7 فائدة مفتوحة، 11-13 مديرو الأصول، 14-16 الصناديق، 24 تغيّر الفائدة، 28-30 تغيّر مديري الأصول، 31-33 تغيّر الصناديق، 86 «Combined»
REAL = {7: 2942595, 8: 175327, 9: 871752, 10: 306661, 11: 1103739, 12: 188254, 13: 153407, 14: 141584, 15: 492283, 16: 658525,
        24: 98956, 28: -623, 29: -1261, 30: 3560, 31: 29420, 32: 6512, 33: 30637}


def real_row(flag="Combined"):
    r = [""] * 87
    r[0], r[1], r[2], r[3], r[86] = "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE", "261103", "2026-11-03", "13874A", flag
    for i, v in REAL.items():
        r[i] = str(v)
    return r


def real_text():
    r = real_row()
    return "MICRO,1,2026-11-03,99999X\n" + ",".join(['"%s"' % r[0]] + r[1:]) + "\n"


def with_hist(c, lev_dl, lev_ds, am_delta):
    x = copy.deepcopy(c)
    x["lev_dlong"], x["lev_dshort"] = lev_dl, lev_ds
    base = c["am_long"] - c["am_short"] - am_delta
    x["hist"] = [{"date": d, "oi": c["oi"], "am_net": base, "lev_net": 0} for d in ("2026-10-06", "2026-10-13", "2026-10-20", "2026-10-27", "2026-09-29")]
    x["hist"].sort(key=lambda h: h["date"])
    return x


def test_parse_real_row_matches_cftc_values():
    c = cot.parse_text(real_text())
    assert c["date"] == "2026-11-03" and c["oi"] == 2942595
    assert (c["lev_long"], c["lev_short"], c["am_long"], c["am_short"]) == (141584, 492283, 1103739, 188254)
    assert (c["lev_dlong"], c["lev_dshort"]) == (29420, 6512)


def test_futures_only_and_short_rows_are_rejected():
    for bad in (real_row("FutOnly"), real_row()[:20]):
        try:
            cot.parse_row(bad)
        except ValueError:
            continue
        raise AssertionError("صيغة غير صالحة قُبلت")


def test_micro_or_missing_contract_is_not_confused():
    try:
        cot.parse_text("MICRO E-MINI S&P 500,1,2026-11-03,99999X\n")
    except ValueError:
        return
    raise AssertionError("عقد آخر قُبل بدل 13874A")


def test_verdict_rules():
    c = cot.parse_text(real_text())
    assert cot.card(with_hist(c, 30000, 5000, 40000))["verdict"] == "up"
    assert cot.card(with_hist(c, 5000, 30000, -40000))["verdict"] == "down"
    k = cot.card(with_hist(c, 30000, 5000, -40000))
    assert k["verdict"] == "flat" and k["agree"] is False
    assert cot.card(with_hist(c, 1000, 500, 1000))["verdict"] == "flat"


def test_first_weeks_show_one_reason_only():
    k = cot.card(cot.parse_text(real_text()))
    assert k["partial"] is True and k["am"] is None and k["verdict"] == k["lev"]


def test_no_report_or_old_shape_gives_no_card():
    assert cot.card(None) is None
    assert cot.card({"date": "2026-10-06", "net_pct": 4.0, "oi": 2000000}) is None


def test_history_persists_in_state_and_failure_keeps_last_report():
    c = cot.parse_text(real_text())
    st = {"seen_events": []}
    now = datetime(2026, 11, 16, tzinfo=timezone.utc)
    runner.gather_extras(now, {"cot": lambda n: copy.deepcopy(c)}, st)
    runner.gather_extras(now, {"cot": lambda n: copy.deepcopy(c)}, st)
    assert len(st["cot_hist"]) == 1                     # نفس الأسبوع لا يتكرر

    def boom(n):
        raise ValueError("down")
    ex, problems = runner.gather_extras(now, {"cot": boom}, st)
    assert ex["cot"]["date"] == "2026-11-03" and problems
    json.dumps(st)


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
            print("✔", name)
    print(f"نجحت كل الاختبارات ({n})")
