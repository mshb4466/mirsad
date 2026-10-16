#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — المشغّل (v0.2)

ثلاثة أوضاع:
  preopen : تقرير كامل قبل افتتاح السوق
  auto    : مراقبة (تُشغَّل كل 15 دقيقة): تنبّه عند صدور بيانات كبرى، أو عند حركة سوق مفاجئة
  test    : رسالة اختبار + تقرير قبل الافتتاح (لتجربة الاتصال والبيانات فعلياً)

الإرسال إلى تيليجرام يحتاج المتغيرين TELEGRAM_TOKEN وTELEGRAM_CHAT_ID،
وبدونهما يطبع الرسالة فقط (وضع تجريبي).
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import calibrate
import auction
import actuals
import quality
import values
import bls
import dashboard
import events_ctx
import extras
import health
import verdict
import impact
import indicators
import safety
import collector as c
import macro

STATE_FILE = "state.json"
HISTORY_FILE = "history.csv"
HISTORY_COLS = ["date", "score", "level", "es_close", "outcome_range_pct"]
BAGHDAD = timezone(timedelta(hours=3))

# عتبات رصد الصدمة خلال آخر ساعة
SHOCK = {"gold_up": 0.8, "oil_up": 1.5, "vix_up": 6.0, "es_down": -0.6}
SHOCK_COOLDOWN_H = 3
# العوامل المراقَبة: المفتاح -> (الاسم، الوحدة، حدّ 15 دقيقة، حدّ 60 دقيقة، حدّ 180 دقيقة).
# الوحدة pct نسبة مئوية، bp نقاط أساس للعوائد. الحدود مخفَّضة لرصد الحركات السريعة، والتصفية بالزخم والحجم تمنع الضجيج.
MOVE = {
    "es": ("ES", "pct", 0.30, 0.45, 0.80), "nq": ("ناسداك", "pct", 0.40, 0.60, 1.00),
    "vix": ("VIX", "pct", 6.0, 8.0, 14.0), "oil": ("النفط", "pct", 0.9, 1.3, 2.4), "gold": ("الذهب", "pct", 0.45, 0.65, 1.2),
    "dxy": ("الدولار DXY", "pct", 0.18, 0.28, 0.5), "jpy": ("الدولار/الين", "pct", 0.25, 0.4, 0.7),
    "y10": ("عائد 10 سنوات", "bp", 3.0, 4.5, 7.5), "y5": ("عائد 5 سنوات", "bp", 3.0, 4.5, 7.5),
    "y30": ("عائد 30 سنة", "bp", 3.0, 4.5, 7.5),
    "hyg": ("سندات عالية العائد HYG", "pct", 0.15, 0.25, 0.45), "kre": ("البنوك الإقليمية KRE", "pct", 0.7, 1.1, 1.9),
}
WINDOWS = (15, 60, 180)             # دقائق؛ فهارس الحدود في MOVE هي 2 و3 و4
MARKET_KEYS = ("es", "nq")          # حركة هذه (بعد تأكيد الزخم والحجم) تكفي لتنبيه
VOLUME_KEYS = ("es", "nq", "oil", "gold", "hyg", "kre")   # أصول لها حجم تداول موثوق في Yahoo؛ بقية العوامل (VIX، الدولار، الين، العوائد) بلا حجم
MOVE_ES_CONFIRM = 0.3               # بقية العوامل يلزم أن يتحرك ES معها (مؤكَّداً) بهذا القدر
MOVE_ALONE_MULT = 1.5               # عامل مؤثر يتحرك وحده (ذو حجم): حدّه أعلى بهذا المضاعف
MIN_Z = 1.8                         # أقل دلالة إحصائية للحركة مقارنةً بتقلب الأصل المعتاد (إن توفرت بيانات كافية)
MIN_EFFICIENCY = 0.35               # كفاءة الاتجاه: صافي الحركة ÷ مجموع حركات الشموع (يستبعد التذبذب)
MIN_VOL_RATIO = 1.3                 # حجم آخر 30 دقيقة ÷ متوسط الحجم قبلها (6 ساعات)
STRICT_Z, STRICT_EFF = 3.0, 0.5     # عند غياب بيانات الحجم: شروط أشد للزخم بدلاً من الحجم
MOVE_COOLDOWN_H = 2
MOVE_ESCALATE = 1.5                 # يسمح بتنبيه جديد في فترة التهدئة إذا كبرت الحركة بهذا المضاعف
RELEASE_WINDOW_H = 3

FED_QUERY = '(Fed OR Powell OR FOMC OR "Federal Reserve") (says OR said OR minutes OR remarks OR speech OR signals) when:12h'
MARKET_QUERY = '(oil OR crude OR Brent OR OPEC OR stocks OR "Wall Street" OR Fed OR Treasury OR tariff) when:3h'
NEWS_QUERY = ('(strike OR attack OR escalation OR sanctions OR missile OR invasion) '
              '(Iran OR Israel OR Russia OR Ukraine OR China OR Taiwan OR Hormuz OR "North Korea" OR Gulf) when:3h')
# محاور الأخبار: (الاستعلام، نافذة الساعات، الحد الأقصى). عناوين فقط بلا تفسير.
NEWS_TOPICS = {
    "banks": ('(Goldman OR "Morgan Stanley" OR JPMorgan OR "Bank of America" OR Citi) ("S&P 500" OR stocks) '
              '(target OR forecast OR outlook OR upgrade OR downgrade) when:2d', 48, 3),
    "companies": ('(Apple OR Microsoft OR Nvidia OR Amazon OR Alphabet OR Meta OR Tesla) '
                  '(earnings OR guidance OR lawsuit OR probe OR ban OR recall OR antitrust) when:1d', 24, 3),
    "policy": ('(tariffs OR "government shutdown" OR "debt ceiling" OR "Fed chair" OR "Treasury auction") when:1d', 24, 2),
}
NEWS_LABELS = {"banks": "عناوين عن توقعات البنوك", "companies": "عناوين الشركات الكبرى",
               "policy": "عناوين السياسة المالية والتجارية"}
INFO_ORDER = ["rates", "long_end", "front", "dollar", "tech", "mag7", "banks", "corr", "cot", "earnings", "fed"]


# ───────────────────────── الحالة ─────────────────────────

def load_state(path=STATE_FILE):
    try:
        import migrate
        s, rep = migrate.load_and_migrate(path)      # ترحيل آمن + نسخة احتياطية قبل أول تغيير (انظر migrate.py)
        if rep and not rep["skipped"]:
            print(f"ترحيل الحالة v{rep['from']}→v{rep['to']}: أُعيدت تسمية {rep['renamed']}، حُجر {rep['quarantined']}، بقي موثّقاً {rep['kept']}")
    except Exception as e:  # noqa: BLE001
        print("تعذّر ترحيل الحالة، تُستعمل كما هي:", type(e).__name__)
        try:
            with open(path, encoding="utf-8") as f:
                s = json.load(f)
        except Exception:  # noqa: BLE001
            s = {}
    if not s.get("actuals"):
        s.setdefault("schema_version", 2)           # حالة جديدة بلا أرقام قديمة: لا ترحيل مطلوب
    s.setdefault("seen_events", [])
    s.setdefault("last_shock", None)
    s.setdefault("last_move", {})
    s.setdefault("last_move_mag", {})
    s.setdefault("alerts", [])
    for a in s["alerts"]:                       # سجلات v0.18 بلا معرّف: نعطيها معرّفاً ثابتاً كي تُفتح وتُحفظ قراءتها
        if isinstance(a, dict):
            a.setdefault("id", f"{a.get('kind', 'x')}|{str(a.get('t', ''))[:16].replace('-', '').replace(':', '').replace('T', '')}")
            a.setdefault("important", True)
            a.setdefault("rev", 0)
    return s


def save_state(state, path=STATE_FILE):
    state["seen_events"] = state["seen_events"][-200:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ───────────────────────── صدور البيانات ─────────────────────────

def event_id(e):
    return f"{e['title']}|{e['time'].isoformat()}"


def parse_num(s):
    if not s:
        return None
    t = str(s).replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    if not m:
        return None
    v = float(m.group())
    sfx = re.search(r"\d([KMBT])\b", t)
    if sfx:
        v *= {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[sfx.group(1)]
    return v


def surprise(ev):
    sg = values.sign(ev.get("actual"), ev.get("forecast"))
    if sg is None:
        return None
    if sg == 0:
        return "مطابق للمتوقع"
    return "أعلى من المتوقع" if sg > 0 else "أدنى من المتوقع"


def due_releases(events, now, state, window_h=RELEASE_WINDOW_H):
    seen = set(state.get("seen_events", []))
    out = []
    for e in events:
        if e["impact"] != "High" or not e.get("actual") or not actuals.is_verified(e):   # الشرط الموحّد: رقم الخبر لا ينبّه
            continue
        if e["time"] > now or now - e["time"] > timedelta(hours=window_h):
            continue
        if event_id(e) in seen:
            continue
        out.append(e)
    return out


def _alerted(state):
    return state.setdefault("alerted", {})


def mark_alerted(state, ev, kind):
    """يسجّل أن تنبيهاً أُرسل لهذا الحدث بهذه القيمة (لمنع التكرار وتمييز المراجعة عن أول وصول). محدود بآخر 200 حدث."""
    al = _alerted(state)
    al[actuals.event_id(ev)] = {"value": ev.get("actual", ""), "kind": kind, "title": ev.get("title", ""), "at": ev["time"].isoformat()}
    for k in sorted(al, key=lambda k: al[k].get("at", ""))[:-200]:
        al.pop(k, None)


def late_releases(events, now, state, window_h=RELEASE_WINDOW_H):
    """رقم موثَّق وصل بعد انتهاء نافذة تنبيه الصدور ولم يُنبَّه عنه (وصول متأخر)، خلال مدة الجلب المسموحة. لا تكرار بعد التنبيه."""
    seen, al = set(state.get("seen_events", [])), _alerted(state)
    out = []
    for e in events:
        if e.get("impact") != "High" or not actuals.is_verified(e) or e["time"] > now:
            continue
        age = now - e["time"]
        if age <= timedelta(hours=window_h) or age > timedelta(days=actuals.GIVE_UP_DAYS) or e.get("status") == "revised":
            continue
        if event_id(e) in seen or actuals.event_id(e) in al:
            continue
        out.append(e)
    return out


def revisions(events, now, state):
    """حدث نُبِّه عنه بقيمة ثم وُثِّقت له قيمة مختلفة (مراجعة): تنبيه واحد لكل قيمة جديدة، ويُميَّز عن أول وصول."""
    al = _alerted(state)
    out = []
    for e in events:
        rec = al.get(actuals.event_id(e))
        if rec and actuals.is_verified(e) and e.get("actual") != rec.get("value") and rec.get("value"):
            out.append((e, rec["value"]))
    return out


# ───────────────────────── رصد الصدمات ─────────────────────────

def change_over(series, minutes):
    """التغير % للسعر الأخير مقارنة بما قبل minutes دقيقة. series: [(datetime_utc, price)]"""
    if not series:
        return None
    t_last, last = series[-1]
    past = [x for x in series if x[0] <= t_last - timedelta(minutes=minutes)]
    if not past or past[-1][1] == 0:
        return None
    return (last / past[-1][1] - 1) * 100


def detect_shock(changes):
    """changes: {'es','vix','oil','gold'} -> % خلال ساعة. يعيد (هل صدمة، قائمة الإشارات)."""
    sig = []
    if changes.get("gold") is not None and changes["gold"] >= SHOCK["gold_up"]:
        sig.append("الذهب")
    if changes.get("oil") is not None and changes["oil"] >= SHOCK["oil_up"]:
        sig.append("النفط")
    if changes.get("vix") is not None and changes["vix"] >= SHOCK["vix_up"]:
        sig.append("VIX")
    if changes.get("es") is not None and changes["es"] <= SHOCK["es_down"]:
        sig.append("ES")
    es_hard = changes.get("es") is not None and changes["es"] <= -1.0
    return (len(sig) >= 3 or (len(sig) >= 2 and es_hard)), sig


def _chg(series, minutes, unit):
    if unit == "bp":
        if not series:
            return None
        t_last, last = series[-1]
        past = [x for x in series if x[0] <= t_last - timedelta(minutes=minutes)]
        return None if not past else (last - past[-1][1]) * 100
    return change_over(series, minutes)


def _sign(x):
    return 0 if x is None or x == 0 else (1 if x > 0 else -1)


def _std(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    return (sum((x - m) ** 2 for x in xs) / (n - 1)) ** 0.5


def _bar_moves(series, unit):
    """تغيّر كل شمعة (نسبة % أو bp) مع طابعها الزمني."""
    out = []
    for (t0, p0), (t1, p1) in zip(series, series[1:]):
        if p0:
            out.append((t1, (p1 - p0) * 100 if unit == "bp" else (p1 / p0 - 1) * 100))
    return out


def momentum_stats(series, vol, unit):
    """مؤشرات الزخم والتقلب والحجم لأصل واحد:
    roc: التغير خلال 15/60/180 دقيقة. aligned: اتساق الاتجاه عبر الأطر. eff: كفاءة الاتجاه (1 = خط مستقيم، 0 = تذبذب).
    z: حجم حركة الساعة مقابل تقلب الأصل المعتاد (انحراف معياري). volat: توسع التقلب اللحظي مقابل المعتاد.
    volx: حجم آخر 30 دقيقة ÷ المعتاد (None إن لم تتوفر بيانات حجم)."""
    st = {"roc": {w: _chg(series, w, unit) for w in WINDOWS}, "aligned": False, "eff": None, "z": None, "volat": None, "volx": None}
    if not series:
        return st
    t_last = series[-1][0]
    r15, r60, r180 = (st["roc"][w] for w in WINDOWS)
    s60 = _sign(r60)
    ok = s60 != 0 and (r15 is None or _sign(r15) == s60)
    if ok and r180 is not None and _sign(r180) not in (0, s60) and abs(r180) >= 0.5 * abs(r60):
        ok = False                                  # الإطار الطويل عكس القصير وبحجم معتبر: ارتداد وليس زخماً مستمراً
    st["aligned"] = ok
    moves = _bar_moves(series, unit)
    recent = [m for t, m in moves if t > t_last - timedelta(minutes=60)]
    base = [m for t, m in moves if t <= t_last - timedelta(minutes=60)]
    if len(recent) >= 6:
        tot = sum(abs(m) for m in recent)
        st["eff"] = abs(sum(recent)) / tot if tot else 0.0
    sb = _std(base) if len(base) >= 20 else None
    if sb and recent:
        if r60 is not None:
            st["z"] = r60 / (sb * (len(recent) ** 0.5))
        rms = lambda xs: (sum(x * x for x in xs) / len(xs)) ** 0.5
        rb = rms(base)
        if rb:
            st["volat"] = rms(recent) / rb          # توسع التقلب اللحظي (جذر متوسط المربعات يشمل الاتجاه)
    if vol:
        cut = t_last - timedelta(minutes=30)
        rec = [v for t, v in vol if t > cut]
        old = [v for t, v in vol if t_last - timedelta(hours=6) <= t <= cut]
        if len(old) >= 20 and rec and sum(old) > 0:
            st["volx"] = (sum(rec) / len(rec)) / (sum(old) / len(old))
    return st


def confirm_move(k, st, mult=1.0):
    """هل الحركة مؤكَّدة؟ يعيد (مؤكَّدة، سبب نصي). الشروط: تجاوز حدّ + زخم متسق + كفاءة + دلالة إحصائية + حجم مرتفع (للأصول ذات الحجم)."""
    name, unit = MOVE[k][0], MOVE[k][1]
    hit = [w for i, w in enumerate(WINDOWS) if st["roc"][w] is not None and abs(st["roc"][w]) >= MOVE[k][2 + i] * mult]
    if not hit:
        return False, "لم يتجاوز الحد"
    if not st["aligned"]:
        return False, "الزخم غير متسق عبر الأطر"
    if st["eff"] is not None and st["eff"] < MIN_EFFICIENCY:
        return False, "الحركة متذبذبة"
    if st["z"] is not None and abs(st["z"]) < MIN_Z:
        return False, "الحركة ضمن تقلب الأصل المعتاد"
    if k in VOLUME_KEYS:
        if st["volx"] is not None:
            if st["volx"] < MIN_VOL_RATIO:
                return False, "الحجم لا يؤكد الحركة"
        else:  # لا حجم متاح: شروط زخم أشد بدلاً من تجاهل الشرط
            if not (st["z"] is not None and abs(st["z"]) >= STRICT_Z and st["eff"] is not None and st["eff"] >= STRICT_EFF):
                return False, "الحجم غير متاح والزخم غير كافٍ"
    return True, "مؤكَّدة"


def detect_move(fresh, vols=None):
    """حركة قوية مستمرة بأي اتجاه، مؤكَّدة بالزخم والحجم. يعيد None أو {'keys','ch','alone','stats'}.
    - ES أو ناسداك: يلزم أن تتحقق شروط confirm_move على الأصل نفسه.
    - النفط والذهب وHYG وKRE (لها حجم): تلزمها شروطها كاملة، ومع ES المؤكَّد بالحدّ العادي، أو وحدها بحدّ ×MOVE_ALONE_MULT.
    - VIX والدولار والين والعوائد (بلا حجم): تُدرج فقط مع ES أو ناسداك المؤكَّد، ولا تنبّه وحدها."""
    vols = vols or {}
    st = {k: momentum_stats(fresh[k], vols.get(k), MOVE[k][1]) for k in MOVE if k in fresh}
    ch = {k: (st[k]["roc"][60], st[k]["roc"][180], st[k]["roc"][15]) for k in st}
    keys, alone, why = [], [], {}
    for k in MARKET_KEYS:
        if k in st:
            ok, w = confirm_move(k, st[k])
            why[k] = w
            if ok:
                keys.append(k)
    market_ok = bool(keys)
    for k in ("oil", "gold", "hyg", "kre"):
        if k not in st:
            continue
        ok, w = confirm_move(k, st[k]) if market_ok else (False, "")
        if ok:
            keys.append(k)
        elif not market_ok:
            ok2, w2 = confirm_move(k, st[k], MOVE_ALONE_MULT)
            if ok2:
                keys.append(k)
                alone.append(k)
    if market_ok:
        for k in ("vix", "dxy", "jpy", "y10", "y5", "y30"):
            if k not in st:
                continue
            hit = [w for i, w in enumerate(WINDOWS) if st[k]["roc"][w] is not None and abs(st[k]["roc"][w]) >= MOVE[k][2 + i]]
            if hit and st[k]["aligned"] and (st[k]["z"] is None or abs(st[k]["z"]) >= MIN_Z):
                keys.append(k)
    return {"keys": keys, "ch": ch, "alone": alone, "stats": st} if keys else None


def move_dir_key(k, ch):
    name, unit, t15, t60, t180 = MOVE[k]
    v = ch[k][0] if ch[k][0] is not None and abs(ch[k][0]) >= t60 * 0.7 else ch[k][1]
    return f"{k}_{'up' if v and v > 0 else 'down'}"


def move_magnitude(k, ch):
    return abs(ch[k][0] or 0) / MOVE[k][3]


def move_in_cooldown(state, key, now, mag=None):
    ts = (state.get("last_move") or {}).get(key)
    if not ts:
        return False
    try:
        if now - datetime.fromisoformat(ts) >= timedelta(hours=MOVE_COOLDOWN_H):
            return False
    except Exception:  # noqa: BLE001
        return False
    prev = (state.get("last_move_mag") or {}).get(key)
    return not (mag is not None and prev and mag >= prev * MOVE_ESCALATE)    # الحركة تضاعفت: يُسمح بتنبيه جديد


def _val(ch, k):
    v = ch.get(k)
    if not v:
        return None
    return v[0] if v[0] is not None else v[1]


def move_pattern(ch):
    """قراءة النمط من اتجاه الأصول معاً. هذا ترابط في الحركة وليس تأكيداً للسبب."""
    es, oil, gold, vix = _val(ch, "es"), _val(ch, "oil"), _val(ch, "gold"), _val(ch, "vix")
    y10, dxy, jpy, hyg, kre = _val(ch, "y10"), _val(ch, "dxy"), _val(ch, "jpy"), _val(ch, "hyg"), _val(ch, "kre")
    out = []
    if oil is not None and abs(oil) >= 1.0 and es is not None and abs(es) >= 0.3:
        up = es > 0
        out.append("النفط يهبط والأسهم تصعد: نمط يرتبط عادة بتراجع تكلفة الطاقة أو تهدئة التوتر الجيوسياسي" if (up and oil < 0)
                   else "النفط يرتفع والأسهم تهبط: نمط يرتبط عادة بمخاوف التضخم أو توتر جيوسياسي" if (not up and oil > 0)
                   else "النفط والأسهم يصعدان معاً: نمط يرتبط عادة بتحسن توقعات النمو والطلب" if up
                   else "النفط والأسهم يهبطان معاً: نمط يرتبط عادة بمخاوف تباطؤ الطلب")
    elif oil is not None and abs(oil) >= 2.0:
        out.append("النفط يتحرك بقوة قبل استجابة واضحة من الأسهم: راقب ES والطاقة")
    if y10 is not None and abs(y10) >= 4.0:
        if es is not None and abs(es) >= 0.3 and ((y10 > 0) != (es > 0)):
            out.append("العوائد " + ("ترتفع" if y10 > 0 else "تنخفض") + " عكس الأسهم: السوق يعيد تسعير الفائدة، وهذا ما يحرّك التقنية خاصة")
        else:
            out.append("العوائد " + ("ترتفع" if y10 > 0 else "تنخفض") + " بحدّة: عامل مؤثر على تسعير الفائدة والأسهم")
    y30 = _val(ch, "y30")
    if y30 is not None and abs(y30) >= 4.0 and (y10 is None or abs(y30) >= abs(y10) + 1.0):
        out.append("الطرف الطويل (30 سنة) " + ("يرتفع أسرع من 10 سنوات" if y30 > 0 else "ينخفض أسرع") +
                   ": يرتبط عادة بالتضخم والدين وعلاوة الأجل، لا بتوقعات الفائدة وحدها")
    if dxy is not None and abs(dxy) >= 0.3:
        out.append("الدولار " + ("يقوى: ضغط على الأسهم والسلع عادةً" if dxy > 0 else "يضعف: دعم للأسهم والسلع عادةً"))
    if jpy is not None and jpy <= -0.6:
        out.append("الين يقوى بسرعة: قد يدل على تفكيك صفقات الفائدة (carry)، وهو ضاغط على الأسهم أحياناً")
    if hyg is not None and hyg <= -0.3:
        out.append("الائتمان عالي العائد يضعف: إشارة حذر")
    if kre is not None and kre <= -1.5:
        out.append("البنوك الإقليمية تضعف: راقب الائتمان")
    if vix is not None and abs(vix) >= 5.0:
        out.append("VIX " + ("يرتفع: زيادة الطلب على الحماية" if vix > 0 else "ينخفض: ارتياح وتراجع الطلب على الحماية"))
    if gold is not None and abs(gold) >= 0.8 and es is not None and es < 0 and gold > 0:
        out.append("الذهب يرتفع مع هبوط الأسهم: توجّه للملاذ الآمن")
    return out


def shock_in_cooldown(state, now):
    ls = state.get("last_shock")
    if not ls:
        return False
    try:
        return now - datetime.fromisoformat(ls) < timedelta(hours=SHOCK_COOLDOWN_H)
    except Exception:  # noqa: BLE001
        return False


# ───────────────────────── جلب (حقيقي) ─────────────────────────

def fetch_intraday(now):
    """يعيد {مفتاح: [(وقت, سعر)]} مع مفتاح خاص "_vol": {مفتاح: [(وقت, حجم)]} للأصول ذات الحجم."""
    import yfinance as yf
    out, vols = {}, {}
    for key in MOVE:
        try:
            h = yf.Ticker(c.SYMBOLS[key]).history(period="2d", interval="5m").dropna(subset=["Close"])
            sc = 0.1 if key in ("y10", "y5", "y30") and len(h) and float(h["Close"].iloc[-1]) > 20 else 1.0   # بعض الإصدارات تعرض العائد ×10 (كما في الجلب اليومي)
            out[key] = [(ts.to_pydatetime().astimezone(timezone.utc), float(v) * sc) for ts, v in h["Close"].items()]
            if key in VOLUME_KEYS and "Volume" in h:
                vv = [(ts.to_pydatetime().astimezone(timezone.utc), float(v)) for ts, v in h["Volume"].items()]
                if sum(v for _, v in vv) > 0:
                    vols[key] = vv
        except Exception as e:  # noqa: BLE001
            print(f"تعذّر جلب {key}: {e}")
    out["_vol"] = vols
    return out


def fetch_headlines(now, query=NEWS_QUERY, hours=3, limit=4):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (mirsad)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        root = ET.fromstring(r.read())
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        try:
            when = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
        except Exception:  # noqa: BLE001
            continue
        if title and now - when <= timedelta(hours=hours):
            items.append((when, title))
    items.sort(reverse=True)
    return [t for _, t in items[:limit]]


GEO_QUERIES = [
    '(missile OR airstrike OR attack OR invasion OR ceasefire OR escalation) (Iran OR Israel OR Gaza OR Russia OR Ukraine OR China OR Taiwan OR "North Korea" OR Yemen) when:1d',
    '(Hormuz OR "Red Sea" OR OPEC OR pipeline OR tanker OR sanctions OR tariffs OR "export controls" OR nuclear) when:1d',
]


def fetch_geo(now):
    """كل العناوين الجيوسياسية خلال 24 ساعة كما هي (وقت، عنوان) ليصنّفها geo.py. يفشل فقط إن فشلت كل الاستعلامات."""
    seen, out, ok = set(), [], 0
    for q in GEO_QUERIES:
        try:
            url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
                {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (mirsad)"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                root = ET.fromstring(resp.read())
            ok += 1
        except Exception:  # noqa: BLE001
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            try:
                when = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
            except Exception:  # noqa: BLE001
                continue
            if title and title not in seen and timedelta(0) <= now - when <= timedelta(hours=24):
                seen.add(title)
                out.append((when, title))
    if not ok:
        raise RuntimeError("تعذّر جلب أخبار الجيوسياسة")
    return out


def fetch_es5m(now):
    """شموع ES كل 5 دقائق لآخر ~7 أيام (Yahoo) لحساب سياق المزاد."""
    import yfinance as yf
    h = yf.Ticker(c.SYMBOLS["es"]).history(period="7d", interval="5m").dropna(subset=["Close"])
    return [{"t": ts.to_pydatetime().astimezone(timezone.utc), "o": float(r["Open"]), "h": float(r["High"]),
             "l": float(r["Low"]), "c": float(r["Close"]), "v": float(r["Volume"])} for ts, r in h.iterrows()]


DEPS = {
    "es5m": fetch_es5m,
    "geo": fetch_geo,
    "macro": lambda now: c.fetch_fred(now, 800, macro.SERIES),
    "calendar": lambda now: c.parse_events(c.fetch_calendar()),
    "prices": c.fetch_prices,
    "intraday": fetch_intraday,
    "headlines": fetch_headlines,
    "headlines_market": lambda now: fetch_headlines(now, query=MARKET_QUERY, hours=3, limit=4),
    "headlines_fed": lambda now: fetch_headlines(now, query=FED_QUERY, hours=12, limit=6),
    "fred": c.fetch_fred,
    "cot": lambda now: c.fetch_cot(),
    "earnings": c.fetch_earnings,
    "news": lambda topic, now: fetch_headlines(now, *NEWS_TOPICS[topic]),
    "week_news": lambda now, asset="es": fetch_week_news(now, asset),
}


# ───────── أخبار الأصل المختار (الآن ES) خلال الأسبوع ─────────
# كل أصل له قائمة محاور خاصة به (انظر ROADMAP.md: ملف تعريف لكل أصل). العناوين فقط، مرتبة بالأحدث، بلا تقييم أهمية.
ASSET_NEWS = {
    "es": [
        ("fed", "الفدرالي والفائدة", '(Fed OR Powell OR FOMC OR "Federal Reserve" OR "rate cut" OR "rate hike") when:7d', 5),
        ("stocks", "الأسهم الأمريكية و S&P 500", '("S&P 500" OR "Wall Street" OR "stock futures" OR "E-mini") when:7d', 5),
        ("companies", "الشركات الكبرى والأرباح", '(Apple OR Microsoft OR Nvidia OR Amazon OR Alphabet OR Meta OR Tesla) (earnings OR guidance OR antitrust OR probe) when:7d', 5),
        ("macro", "الاقتصاد والبيانات", '(inflation OR CPI OR "jobs report" OR payrolls OR GDP OR "consumer sentiment") when:7d', 5),
        ("policy", "السياسة التجارية والمالية", '(tariffs OR "government shutdown" OR "debt ceiling" OR "Treasury yields") when:7d', 4),
        ("geo", "الجيوسياسة والنفط", '(Iran OR Israel OR Russia OR Ukraine OR China OR Taiwan OR Hormuz OR OPEC) (oil OR strike OR attack OR sanctions OR ceasefire) when:7d', 4),
    ],
}
WEEK_NEWS_TTL_MIN = 60


def fetch_rss_items(now, query, days=7):
    """[(وقت UTC، عنوان نظيف، مصدر)] من أخبار Google RSS."""
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (mirsad)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        root = ET.fromstring(r.read())
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        try:
            when = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
        except Exception:  # noqa: BLE001
            continue
        if title and timedelta(0) <= now - when <= timedelta(days=days):
            out.append((when, title, src))
    return out


def fetch_week_news(now, asset="es", fetch=None):
    """{محور: {label, items:[{t, title, src}]}} لأخبار الأسبوع. يفشل ناعماً محوراً محوراً؛ يعيد (النتيجة، أسماء المحاور الفاشلة)."""
    fetch = fetch or fetch_rss_items
    res, failed, seen = {}, [], set()
    for key, label, query, limit in ASSET_NEWS.get(asset, []):
        try:
            rows = fetch(now, query)
        except Exception:  # noqa: BLE001
            failed.append(label)
            continue
        items = []
        for when, title, src in sorted(rows, key=lambda r: r[0], reverse=True):
            norm = re.sub(r"[^a-z0-9]+", "", title.lower())[:60]
            if not norm or norm in seen:
                continue
            seen.add(norm)
            items.append({"t": when.isoformat(), "title": title, "src": src})
            if len(items) >= limit:
                break
        if items:
            res[key] = {"label": label, "items": items}
    return res, failed


def get_week_news(now, deps, state, asset="es"):
    """يعيد أخبار الأسبوع من الذاكرة إن كانت أحدث من ساعة (لا نطلب RSS كل 15 دقيقة)، وإلا يجلبها. فشل ناعم."""
    try:
        cache = (state or {}).get("week_news") or {}
        if cache.get("at") and cache.get("asset") == asset and now - datetime.fromisoformat(cache["at"]) < timedelta(minutes=WEEK_NEWS_TTL_MIN):
            return {"data": cache["data"], "at": cache["at"], "failed": cache.get("failed", [])}
        fn = deps.get("week_news") if isinstance(deps, dict) else None
        if not fn:
            return None        # بلا مزوّد (مثلاً في الاختبارات) لا طلب شبكة
        data, failed = fn(now, asset)
        if data or failed:
            if state is not None and data:
                state["week_news"] = {"at": now.isoformat(), "asset": asset, "data": data, "failed": failed}
            return {"data": data, "at": now.isoformat(), "failed": failed}
    except Exception as e:  # noqa: BLE001
        return {"data": {}, "at": None, "failed": [], "error": type(e).__name__}
    return None


# ───────────────────────── صياغة الرسائل ─────────────────────────

def hhmm(t):
    return t.astimezone(BAGHDAD).strftime("%H:%M")


def bar(score, n=10):
    """شريط ملوّن من مربعات: اللون بحسب المستوى والعدد بحسب الدرجة."""
    k = int(round(max(0, min(10, score)) * n / 10))
    sq = "🟩" if score <= 3 else "🟨" if score <= 6 else "🟧" if score <= 8 else "🟥"
    return sq * k + "⬜" * (n - k)


def dot(score):
    return "🟢" if score <= 3 else "🟡" if score <= 6 else "🟠" if score <= 8 else "🔴"


def risk_lines(report):
    if "error" in report:
        return ["⚠ " + report["error"]]
    r = report["risk"]
    lines = [f"المخاطرة: {r['score']}/10 {r['emoji']} ({r['level']})", bar(r["score"]),
             f"{r.get('reason_label', 'السبب')}: {r['main_reason']}", r["advice"]]
    comps = sorted(r["components"], key=lambda x: x["score"] * x["weight"], reverse=True)[:4]
    lines += ["", "أبرز المكوّنات:"] + [f"{dot(x['score'])} {x['name']} {x['score']:g}/10" for x in comps]
    return lines


def geo_lines(report):
    g = report.get("geo") or {}
    top = g.get("top")
    if not top:
        return []
    mark = "🟢" if g.get("confirmed") else "🟡"
    lines = [f"🌍 الجيوسياسة (تصنيف بالقواعد): {g['stories']} قصة بارزة — "
             + ("السوق يؤكد " + "🔴" if g.get("confirmed") else "السوق لم يؤكد بعد " + mark)]
    for t in top[:2]:
        arrow = "▼ تهدئة" if t["deesc"] else "▲ تصعيد" if t["severity"] >= 2 else "◆ متابعة"
        reg = "، ".join(t["regions"]) or "—"
        lines.append(f"• {arrow} | {reg} | حدّة {t['severity']}/4 | {t['sources']} مصدر: {t['title']}")
    if g.get("unexplained_market_move"):
        lines.append("⚠ حركة سوق جيوسياسية الطابع دون عناوين مطابقة")
    return lines


def macro_lines(report):
    m = report.get("macro")
    if not m:
        return []
    lines = [f"{m['emoji']} المنظومة الكلية — ميل الفدرالي: {m['arrow']} {m['label']} (ثقة {m['confidence']})"]
    for p in m["pillars"][:5]:
        lines.append(f"{p['arrow']} {p['name']}: {p['note']}")
    lines += [f"• {x}" for x in m["summary"][1:]]
    if m.get("net_liquidity"):
        nl = m["net_liquidity"]
        lines.append(f"• السيولة الصافية ≈{nl['net_bn']:.0f} مليار$ ({nl['chg_pct']:+.1f}% خلال 4 أسابيع)")
    lines.append(m["assumptions"])
    return lines


def format_preopen(report, events, now, prefix="", url=""):
    lines = [prefix + "📊 مِرصاد — قبل افتتاح السوق", f"🕒 {hhmm(now)} بتوقيت بغداد"]
    if url:      # الرابط في الأعلى حتى لا يضيعه طول التقرير
        lines += ["🖥 الواجهة الكاملة:", url + "index.html"]
    lines += [""]
    lines += risk_lines(report)
    info = report.get("info", {})
    ctx = [info[k] for k in INFO_ORDER if k in info]
    if ctx:
        lines += ["", "السياق:"] + [f"• {x}" for x in ctx]
    al = auction.lines(report.get("auction"), (report["tilt"]["score"], report["tilt"]["parts"]) if report.get("tilt") else (None, {}))
    if al:
        lines += [""] + al
    ml = macro_lines(report)
    if ml:
        lines += [""] + ml
    gl = geo_lines(report)
    if gl:
        lines += [""] + gl
    upcoming = sorted([e for e in events if events_ctx.relevant(e) and now <= e["time"] <= now + timedelta(hours=24)], key=lambda e: e["time"])
    if upcoming:
        lines += ["", "أحداث USD خلال 24 ساعة:"]
        shown_kind = set()
        for e in upcoming[:10]:
            mark = "🔴" if e["impact"] == "High" else "🟠" if e["impact"] == "Medium" else "⚪"
            extra = f" (توقع {e['forecast']} | سابق {e['previous']})" if e["forecast"] or e["previous"] else ""
            d = events_ctx.describe(e, hhmm(e["time"]), ((report.get("macro") or {}).get("label", "")), events_ctx.build_ctx(report))
            lines.append(f"{mark} {hhmm(e['time'])} — {e['title']}{(' · ' + d['name']) if d['name'] != e['title'] else ''}{extra}")
            if d["expect"]:
                lines.append(f"   ↳ {d['expect']}")
            first = d["kind"] not in shown_kind
            shown_kind.add(d["kind"])
            if d["short"] and first and (e["impact"] == "High" or d["kind"] in events_ctx.ALWAYS):
                lines.append(f"   ↳ {d['short']}")
                if d["system"] and e["impact"] == "High":
                    lines.append(f"   ↳ المنظومة: {d['system'][0]} | {d['system'][-2] if len(d['system']) > 2 else d['system'][-1]}")
    for topic, label in NEWS_LABELS.items():
        items = (report.get("news") or {}).get(topic)
        if items:
            lines += ["", label + ":"] + [f"• {h[:110]}" for h in items]
    if info.get("data_age"):
        lines += ["", "🕓 " + info["data_age"]]
    for p in report.get("problems", []):
        lines.append("⚠ " + p)
    lines += ["", "إشارات إحصائية لأغراض التجربة، لا توصية استثمارية. العناوين للاطلاع فقط دون تفسير."]
    return "\n".join(lines)


def _link_lines(link):
    return ["🔗 افتح الحدث في التطبيق:", link] if link else []


def _assess_lines(assess):
    """ما تغيّر في التقييم الرئيسي بسبب الإصدار (من سجل الحدث الموحّد)."""
    if not assess:
        return []
    out = []
    if assess.get("changed"):
        out.append(f"⚠ التقييم السابق لم يعد صالحاً — تغيّر الانحياز من {assess.get('before')} إلى {assess.get('after')}")
    elif assess.get("after"):
        out.append(f"الانحياز الماكروي بعد الإصدار: {assess['after']}" + (f" (قبله: {assess['before']})" if assess.get("before") else ""))
    if assess.get("text"):
        out.append(assess["text"])
    if assess.get("market"):
        out.append(assess["market"])
    return out


def format_release(ev, es_reaction, report, late=False, now=None, revised_from=None, link="", assess=None):
    if revised_from is not None:
        return "\n".join([f"↻ مِرصاد — مراجعة بيانات: {ev['title']}", *_link_lines(link),
                          f"القيمة الموثّقة تغيّرت من {revised_from} إلى {ev['actual']} "
                          f"(المتوقع: {ev['forecast'] or '—'} | السابق: {ev['previous'] or '—'}).",
                          "هذه مراجعة لإصدار سبق التنبيه عنه وليست إصداراً جديداً.", *_assess_lines(assess)])
    head = f"📥 مِرصاد — وصلت البيانات متأخرة: {ev['title']}" if late else f"📥 مِرصاد — صدرت بيانات: {ev['title']}"
    lines = [head, *_link_lines(link)]
    if late:
        lines.append(f"صدر الحدث {(ev['time'] + timedelta(hours=3)).strftime('%d-%m %H:%M')} بغداد، ووُثّقت قيمته بعد انتهاء نافذة تنبيه الصدور"
                     + (f" (المصدر: {ev.get('actual_source') or 'غير محدد'})." if ev.get("actual_source") else "."))
        lines.append("حركة ES منذ الصدور غير محسوبة: مضى زمن طويل ولا يصحّ نسبتها للخبر.")
    lines.append(f"الفعلي: {ev['actual']} | المتوقع: {ev['forecast'] or '—'} | السابق: {ev['previous'] or '—'}")
    s = surprise(ev)
    ml = ((report or {}).get("macro") or {}).get("label", "")
    ir = events_ctx.interpret_release(ev, ml, events_ctx.build_ctx(report))
    if ir["surprise"] or s:
        lines.append(f"النتيجة: {ir['surprise'] or s}")
    if ir["vs_prev"]:
        lines.append(f"مقارنة بالسابق: {ir['vs_prev']}")
    if ir["combined"]:
        lines.append(f"القراءة المشتركة: {ir['combined']}")
    if ir["system_effect"]:
        lines.append(f"في منظور المنظومة: {ir['system_effect']}")
    if ir["meaning"]:
        lines.append(f"المعنى المعتاد لـ ES: {ir['meaning']}")
    if ir["note"]:
        lines.append(f"ملاحظة: {ir['note']}")
    if es_reaction is not None:
        lines.append(f"حركة ES منذ الصدور: {es_reaction:+.2f}%")
    al_ = _assess_lines(assess)
    if al_:
        lines += ["", "ما تغيّر في التقييم:"] + al_
    if report is not None:
        lines += [""] + risk_lines(report)
    lines += ["", "ملاحظة: اتجاه التأثير يعتمد على نوع البيانات، وقد يكون الخبر مسعَّراً مسبقاً."]
    return "\n".join(lines)


def _conf_lines(mv):
    sts = mv.get("stats") or {}
    conf = []
    for k in mv["keys"]:
        s = sts.get(k)
        if not s or k not in VOLUME_KEYS + ("vix",) and s.get("eff") is None:
            continue
        parts = []
        if s.get("eff") is not None:
            parts.append(f"كفاءة الاتجاه {s['eff']:.2f}")
        if s.get("z") is not None:
            parts.append(f"دلالة الحركة {abs(s['z']):.1f}σ")
        if s.get("volat") is not None:
            parts.append(f"التقلب اللحظي ×{s['volat']:.1f}")
        if k in VOLUME_KEYS:
            parts.append(f"الحجم ×{s['volx']:.1f}" if s.get("volx") is not None else "الحجم غير متاح (شروط زخم أشد)")
        if parts:
            conf.append(f"• {MOVE[k][0]}: " + " | ".join(parts))
    return conf


def _fmt_ch(k, v):
    return "—" if v is None else (f"{v:+.0f}bp" if MOVE[k][1] == "bp" else f"{v:+.2f}%")


ALERT_KEEP_H = 72                     # سجل الأحداث الموحّد: كل ما أُرسل يبقى ظاهراً في التطبيق ثلاثة أيام (لا 24 ساعة)
ALERT_MAX = 40
KIND_AR = {"release": "صدور بيانات", "late": "وصول متأخر", "revision": "مراجعة", "shock": "حركة غير معتادة", "move": "حركة كبيرة"}


def alert_link(aid, url=None):
    """رابط يفتح الحدث نفسه في التطبيق بمعرّفه الثابت (#e=). فارغ إن لم يُعرف عنوان الصفحة."""
    base = dashboard.page_url() if url is None else url
    return f"{base}index.html#e={urllib.parse.quote(aid, safe='')}" if base else ""


def alert_from_move(mv, headlines, now):
    ch = mv["ch"]
    rows = [{"name": MOVE[k][0], "c60": _fmt_ch(k, ch[k][0]), "c180": _fmt_ch(k, ch[k][1]), "lead": k in mv["keys"]}
            for k in MOVE if k in ch and (k in mv["keys"] or k in ("es", "oil", "y10", "y30", "dxy", "vix"))]
    only = set(mv["keys"]) == set(mv.get("alone", [])) and bool(mv.get("alone"))
    es = _val(ch, "es")
    title = ("عامل مؤثر يتحرك بقوة" if only else "حركة كبيرة في السوق") + " (" + "، ".join(MOVE[k][0] for k in mv["keys"]) + ")"
    pat = move_pattern(ch)
    return {"id": f"move|{now:%Y%m%d%H%M}|{'-'.join(sorted(mv['keys']))}", "t": now.isoformat(), "kind": "move", "important": True,
            "icon": "📈" if (es or 0) > 0 else "📉", "title": title, "what": title, "why": "؛ ".join(pat[:2]) if pat else "",
            "rows": rows, "confirm": [x.lstrip("• ") for x in _conf_lines(mv)], "pattern": pat, "headlines": list(headlines or [])[:4]}


def alert_from_shock(signals, changes, headlines, now):
    f = lambda k: "—" if changes.get(k) is None else f"{changes[k]:+.2f}%"
    rows = [{"name": n, "c60": f(k), "c180": "—", "lead": False} for k, n in (("es", "ES"), ("vix", "VIX"), ("gold", "الذهب"), ("oil", "النفط")) if k in changes]
    t = "حركة سوق غير معتادة (قد تدل على حدث مفاجئ)"
    return {"id": f"shock|{now:%Y%m%d%H%M}", "t": now.isoformat(), "kind": "shock", "important": True, "icon": "🚨", "title": t, "what": t,
            "why": "؛ ".join(signals or []), "rows": rows, "confirm": list(signals or []), "pattern": [], "headlines": list(headlines or [])[:4]}


def alert_from_release(ev, es_reaction, report, state, now, kind="release", revised_from=None):
    """سجل موحّد لإصدار/وصول متأخر/مراجعة: ماذا حدث، لماذا يهم ES، ما تغيّر في التقييم، الأرقام والمصدر وحالة التحقق.
    «قبل» من آخر تقييم منشور (state.verdict_sig) و«بعد» من التقرير الحالي الذي يشمل الإصدار."""
    ml = ((report or {}).get("macro") or {}).get("label", "")
    ir = events_ctx.interpret_release(ev, ml, events_ctx.build_ctx(report))
    name = events_ctx.classify(ev.get("title", ""))[1] or ev.get("title", "")
    prev = (state or {}).get("verdict_sig") or {}
    b = (report or {}).get("bias") or {}
    after = b.get("label") if b.get("available") else None
    before = prev.get("bias_label")
    vd = None
    try:
        vd = verdict.build(report, now, prev) if report else None
    except Exception:  # noqa: BLE001
        vd = None
    mk = ((report or {}).get("releases") or {}).get("market") or {}
    a_txt = (vd or {}).get("news_relation") or ""
    if not a_txt and report is not None and not (report.get("releases") or {}).get("items"):
        a_txt = "لم يُدمج الإصدار في التقييم بعد"
    if revised_from is not None:
        what = f"مراجعة {name}: الفعلي من {revised_from} إلى {ev.get('actual', '')}"
    else:
        what = f"صدر {name}: الفعلي {ev.get('actual', '—')} مقابل المتوقع {ev.get('forecast') or '—'}"
    return {"id": actuals.event_id(ev), "t": now.isoformat(), "kind": kind, "important": True,
            "icon": "↻" if kind == "revision" else "📥", "title": name, "ev_title": ev.get("title", ""), "event_time": ev["time"].isoformat(),
            "what": what, "surprise": ir.get("surprise") or surprise(ev) or "", "why": ir.get("meaning") or ir.get("system_effect") or "",
            "numbers": {"actual": ev.get("actual", ""), "forecast": ev.get("forecast", ""), "previous": ev.get("previous", ""),
                        "revised_from": revised_from or ev.get("revised_from", ""), "prev_revised": ev.get("prev_revised", "")},
            "source": ev.get("actual_source", ""), "trust": ev.get("actual_src", ""), "period": ev.get("actual_period", ""),
            "status": ev.get("status", ""), "verification": actuals.STATUS_AR.get(ev.get("status", ""), ""),
            "reaction": es_reaction,
            "assessment": {"before": before, "after": after, "changed": bool(before and after and before != after),
                           "text": a_txt, "market": mk.get("label", ""), "market_key": mk.get("key", "")},
            "rows": [], "headlines": [],
            "update_text": (f"مراجعة: الفعلي من {revised_from} إلى {ev.get('actual', '')}" if revised_from is not None else "")}


def _ts(a):
    try:
        return datetime.fromisoformat(a.get("updated_at") or a["t"])
    except Exception:  # noqa: BLE001
        return None


def push_alert(state, rec, now):
    """السجل الوحيد لما يُرسل للمستخدم (يغذّي الإشعار والواجهة). رقم الحدث الواحد = سجل واحد: التصحيح أو التحديث اللاحق
    يُضاف إلى updates ويرفع rev (فيظهر غير مقروء من جديد) ولا يكرر البطاقة."""
    rec = dict(rec)
    rec.setdefault("id", f"{rec.get('kind', 'x')}|{now:%Y%m%d%H%M%S}")
    cur = list(state.get("alerts") or [])
    old = next((a for a in cur if a.get("id") == rec["id"]), None)
    upd_txt = rec.pop("update_text", "")
    if old:
        upd = list(old.get("updates") or [])
        upd.append({"t": now.isoformat(), "text": upd_txt or "تحديث", "kind": rec.get("kind", "")})
        keep = {k: v for k, v in rec.items() if k not in ("t", "id", "updates", "kind")}
        if rec.get("kind") == "revision":
            keep["revised"] = True
        merged = dict(old, **keep)
        merged["updates"], merged["updated_at"], merged["rev"] = upd[-8:], now.isoformat(), int(old.get("rev", 0)) + 1
        cur = [merged if a.get("id") == rec["id"] else a for a in cur]
    else:
        rec.setdefault("rev", 0)
        cur.append(rec)
    keep_l = []
    for a in cur:
        t = _ts(a)
        if t is not None and now - t <= timedelta(hours=ALERT_KEEP_H):
            keep_l.append(a)
    state["alerts"] = keep_l[-ALERT_MAX:]


SHORT_NAME = {"es": "ES", "nq": "NQ", "vix": "VIX", "oil": "نفط", "gold": "ذهب", "dxy": "دولار", "jpy": "ين",
              "y10": "10Y", "y5": "5Y", "y30": "30Y", "hyg": "HYG", "kre": "KRE"}


def market_pulse(fresh, vols):
    """نبض السوق الحالي لكل العوامل المراقَبة: التغير عبر 15/60/180 دقيقة وهل الحركة مؤكَّدة بالزخم والحجم."""
    out = []
    for k in MOVE:
        if k not in fresh:
            continue
        try:
            st = momentum_stats(fresh[k], vols.get(k), MOVE[k][1])
            ok, why = confirm_move(k, st)
        except Exception:  # noqa: BLE001
            continue
        best = None
        for i, w in enumerate(WINDOWS):
            v = st["roc"][w]
            if v is None:
                continue
            r = abs(v) / MOVE[k][2 + i]
            if best is None or r > best[0]:
                best = (r, w, v, MOVE[k][2 + i])
        r, w, v, th = best if best else (0.0, 60, 0.0, MOVE[k][3])
        sfx = "bp" if MOVE[k][1] == "bp" else "%"
        out.append({"key": k, "name": MOVE[k][0], "short": SHORT_NAME.get(k, MOVE[k][0]), "w": w, "v": round(v, 2), "th": th,
                    "ratio": round(r, 2), "val": _fmt_ch(k, v), "thr": (f"±{th:g}{sfx}"),
                    "c15": _fmt_ch(k, st["roc"][15]), "c60": _fmt_ch(k, st["roc"][60]),
                    "c180": _fmt_ch(k, st["roc"][180]), "confirmed": bool(ok), "why": why, "tone": impact.tone(k, v),
                    "eff": None if st["eff"] is None else round(st["eff"], 2),
                    "z": None if st["z"] is None else round(abs(st["z"]), 1),
                    "volx": None if st["volx"] is None else round(st["volx"], 1)})
    return out


def format_move(mv, headlines, report, link=""):
    ch = mv["ch"]
    unit = lambda k: "bp" if MOVE[k][1] == "bp" else "%"
    fmt = lambda k, v: "—" if v is None else (f"{v:+.0f}bp" if MOVE[k][1] == "bp" else f"{v:+.2f}%")
    lead = max(mv["keys"], key=lambda k: abs(_val(ch, k) or 0) / MOVE[k][3])
    v0 = _val(ch, "es") if _val(ch, "es") is not None and abs(_val(ch, "es")) >= MOVE_ES_CONFIRM else _val(ch, lead)
    icon = "📈" if v0 and v0 > 0 else "📉"
    only = set(mv["keys"]) == set(mv.get("alone", [])) and bool(mv.get("alone"))
    head = "عامل مؤثر يتحرك بقوة" if only else "حركة كبيرة في السوق"
    lines = [f"{icon} مِرصاد — {head} ({'، '.join(MOVE[k][0] for k in mv['keys'])})", *_link_lines(link), "التغير: ساعة | 3 ساعات"]
    shown = [k for k in MOVE if k in ch and (k in mv["keys"] or k in ("es", "oil", "y10", "y30", "dxy", "vix"))]
    for k in shown:
        mark = " ◀" if k in mv["keys"] else ""
        lines.append(f"• {MOVE[k][0]}: {fmt(k, ch[k][0])} | {fmt(k, ch[k][1])}{mark}")
    conf = _conf_lines(mv)
    if conf:
        lines += ["", "تأكيد الزخم والحجم:"] + conf
    pat = move_pattern(ch)
    if pat:
        lines += ["", "القراءة (من ترابط الحركة، وليست تأكيداً للسبب):"] + [f"• {p}" for p in pat]
    if headlines:
        lines += ["", "عناوين حديثة قد تكون ذات صلة:"] + [f"• {h}" for h in headlines]
    if report is not None:
        lines += [""] + risk_lines(report)
        al = auction.lines(report.get("auction"), (report["tilt"]["score"], report["tilt"]["parts"]) if report.get("tilt") else (None, {}))
        if al:
            lines += [""] + al[:3]
    lines += ["", "تنبيه: بيانات Yahoo المجانية متأخرة عن السوق، فقد تكون الحركة بدأت قبل التنبيه. هذا رصد لا توصية."]
    return "\n".join(lines)


def format_shock(signals, changes, headlines, report, link=""):
    fmt = lambda k: "—" if changes.get(k) is None else f"{changes[k]:+.2f}%"
    lines = ["🚨 مِرصاد — حركة سوق غير معتادة (قد تدل على حدث مفاجئ)", *_link_lines(link),
             f"خلال آخر ساعة: ES {fmt('es')} | VIX {fmt('vix')} | الذهب {fmt('gold')} | النفط {fmt('oil')}",
             "إشارات: " + "، ".join(signals)]
    if headlines:
        lines += ["", "عناوين أخبار حديثة ذات صلة (آخر 3 ساعات):"] + [f"• {h}" for h in headlines]
    if report is not None:
        lines += [""] + risk_lines(report)
        gl = geo_lines(report)
        if gl:
            lines += [""] + gl
    lines += ["", "تنبيه: هذا رصد لحركة السوق وعناوين أخبار، وليس تحليلاً مؤكداً لسبب الحركة."]
    return "\n".join(lines)


# ───────────────────────── الإرسال ─────────────────────────

def split_message(text, limit=3800):
    """يقسّم النص الطويل عند حدود الفقرات (وعند الأسطر إن لزم) دون قصّ أي جزء."""
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for block in text.split("\n\n"):
        cand = block if not cur else cur + "\n\n" + block
        if len(cand) <= limit:
            cur = cand
            continue
        if cur:
            parts.append(cur)
            cur = ""
        while len(block) > limit:                  # فقرة أطول من الحد: نقسّمها عند آخر سطر
            cut = block.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            parts.append(block[:cut])
            block = block[cut:].lstrip("\n")
        cur = block
    if cur:
        parts.append(cur)
    return parts


def send_telegram(text):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("—— (وضع تجريبي: لا إعدادات تيليجرام) ——")
        print(text)
        return False
    ok = True
    for part in split_message(text):          # حد تيليجرام 4096 حرفاً: نقسّم بدل القصّ حتى لا يضيع الجزء الأخير
        data = json.dumps({"chat_id": chat, "text": part, "disable_web_page_preview": True}).encode("utf-8")
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            ok = ok and json.loads(resp.read().decode("utf-8")).get("ok", False)
    if not ok:
        raise RuntimeError("رفض تيليجرام الرسالة")
    return True


# ───────────────────────── الأوضاع ─────────────────────────

def gather_extras(now, deps):
    """مصادر إضافية بفشل ناعم: FRED وCOT والأرباح والعناوين."""
    extras, problems = {}, []
    if deps.get("fred"):
        try:
            extras["fred"], p = deps["fred"](now)
            problems += p
        except Exception as e:  # noqa: BLE001
            problems.append(f"تعذّر FRED: {e}")
    if deps.get("macro"):
        try:
            extras["macro"], p = deps["macro"](now)
            problems += [x.replace("FRED", "FRED (المنظومة الكلية)") for x in p]
        except Exception as e:  # noqa: BLE001
            problems.append(f"تعذّر جلب بيانات المنظومة الكلية: {e}")
    for name in ("cot", "earnings", "geo"):
        if deps.get(name):
            try:
                extras[name] = deps[name](now)
            except Exception as e:  # noqa: BLE001
                problems.append(f"تعذّر جلب {name}: {e}")
    # مزوّدو المكوّنات المدفوعة (فارغ الآن): {"gamma": دالة(now) -> (درجة 0-10، ملاحظة)} — انظر ROADMAP.md
    for key, fn in (deps.get("premium") or {}).items():
        try:
            extras.setdefault("premium", {})[key] = fn(now)
        except Exception as e:  # noqa: BLE001
            problems.append(f"تعذّر مزوّد {key}: {e}")
    if deps.get("news"):
        news = {}
        for topic in NEWS_TOPICS:
            try:
                items = deps["news"](topic, now)
                if items:
                    news[topic] = items
            except Exception:  # noqa: BLE001
                continue
        if news:
            extras["news"] = news
    return extras, problems


def full_report(now, events, deps, want_prices=False, series=None):
    """series: {es,y10,dxy,oil: [(وقت, سعر)]} لقياس تأكيد السوق للإصدارات (إن غابت: «تأكيد السوق غير متاح بعد»)."""
    prices, problems = deps["prices"](now)
    extras, p2 = gather_extras(now, deps)
    if series:
        extras["series"] = series
    report = c.build_report(prices, events, now, problems + p2, extras)
    return (report, prices) if want_prices else report


# ───────────────────────── سجل الأداء (للمعايرة) ─────────────────────────

def read_history(path):
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def update_history(report, prices, now, path=HISTORY_FILE):
    """يسجّل درجة اليوم، ويملأ مدى حركة ES الفعلي للأيام السابقة عند توفره."""
    if "error" in report:
        return
    today = c.et_date(now).isoformat()
    rows = read_history(path)
    bars = {b[0]: b for b in ((prices.get("es") or {}).get("bars") or [])}
    for r in rows:
        if not r.get("outcome_range_pct") and r["date"] < today and r["date"] in bars:
            _, hi, lo, cl = bars[r["date"]]
            r["outcome_range_pct"] = f"{(hi - lo) / cl * 100:.3f}"
    if not any(r["date"] == today for r in rows):
        es = prices.get("es") or {}
        rows.append({"date": today, "score": str(report["risk"]["score"]), "level": report["risk"]["level"],
                     "es_close": f"{es.get('last', 0):.2f}", "outcome_range_pct": ""})
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLS)
        w.writeheader()
        w.writerows(rows[-400:])


def add_auction(report, prices, now, deps):
    """سياق المزاد والميل اليومي (فشل ناعم)."""
    ctx = None
    if deps.get("es5m"):
        try:
            vix = (prices.get("vix") or {}).get("last")
            ctx = auction.context(deps["es5m"](now), now, vix)
            if ctx is None:
                report.setdefault("problems", []).append("بيانات ES الدقيقة غير كافية لسياق المزاد")
        except Exception as e:  # noqa: BLE001
            report.setdefault("problems", []).append(f"تعذّر سياق المزاد: {e}")
    t = auction.tilt(auction.tilt_features(prices, ctx))
    report["auction"] = ctx
    report["tilt"] = ({"score": round(t[0], 2), "parts": t[1]} if t[0] is not None else None)


def calendar_events(now, state, deps, problems=None):
    """التقويم الاقتصادي مع نسخة احتياطية: إن فشل الجلب (حدّ الطلبات أو انقطاع) نستعمل آخر نسخة ناجحة (حتى 3 أيام)
    بدل فقدان كل الأحداث وما يتبعها من أرقام. تُذكر النسخة القديمة صراحة في المشاكل."""
    try:
        ev = deps["calendar"](now)
        if ev:
            state["cal_cache"] = {"at": now.isoformat(), "events": [
                {"title": e["title"], "impact": e["impact"], "time": e["time"].isoformat(), "forecast": e.get("forecast", ""),
                 "previous": e.get("previous", ""), "type": e.get("type", "OTHER")} for e in ev]}
        return ev
    except Exception as e:  # noqa: BLE001
        cc = state.get("cal_cache") or {}
        try:
            at = datetime.fromisoformat(cc["at"])
            if now - at <= timedelta(days=3) and cc.get("events"):
                if problems is not None:
                    problems.append(f"التقويم الاقتصادي من نسخة محفوظة قبل {int((now - at).total_seconds() // 60)} دقيقة (تعذّر الجلب: {type(e).__name__})")
                return [dict(x, time=datetime.fromisoformat(x["time"]), actual="") for x in cc["events"]]
        except Exception:  # noqa: BLE001
            pass
        raise


def resolve_actuals(events, now, state, deps):
    """يملأ الأرقام الفعلية قبل أي استعمال لها (تنبيه الصدور، التحليل، الواجهة): استرجاع المحفوظ، ثم جلب ما يستحق من
    BLS ثم FRED ثم العناوين، ثم التسجيل الدائم والحالات. يُنفَّذ مرة واحدة لكل تشغيل. لا يرفع استثناءً."""
    marker = now.isoformat()
    if events and all(e.get("_res") == marker for e in events):
        return
    for e in events:
        e["_res"] = marker
    try:
        actuals.quarantine(events)       # أي رقم قادم من التقويم نفسه بلا مصدر موثّق = غير موثّق: يُحجر ثم يُجلب رقم موثّق
        events.extend(actuals.ghost_events(events, state, now))      # أحداث الأسبوع الماضي المعلّقة: تُكمل محاولاتها رغم غيابها عن thisweek
        for e in events:
            e["_res"] = marker
        actuals.restore(events, state)
        todo, checks = actuals.pending(events, state, now)
        live = "fetch_oil" not in deps
        diag = {}
        if todo or checks:
            key = os.environ.get("BLS_API_KEY", "").strip() or None
            fb = deps.get("fetch_bls") or ((lambda ids: bls.fetch(ids, now, key, state=state)) if live else None)
            extras.apply_actuals(todo + checks, now, c, deps.get("fetch_oil"), deps.get("fetch_auctions"),
                                 (lambda: fetch_headlines(now, query="EIA crude oil inventories", hours=36, limit=6)) if live else None,
                                 fetch_series_fn=deps.get("fetch_series"),
                                 fetch_heads_q_fn=deps.get("fetch_heads_q") or ((lambda q: fetch_headlines(now, query=q, hours=48, limit=10)) if live else None),
                                 fetch_bls_fn=fb, window_h=24 * 7 + 1, diag=diag,
                                 fetch_vintage_fn=deps.get("fetch_vintage") or ((lambda sid, ref, rel: extras.fetch_gdp_vintage(now, c, sid, ref, rel)) if live else None))
            for k, v in diag.items():            # حالة المصدر من آخر محاولة فعلية (للتقرير والصحة)
                state.setdefault("source_status", {})[k] = dict(v, at=marker)
        actuals.record(events, checks, todo + [x["_clone_of"] for x in checks], state, now)
        actuals.quarantine(events)                       # رقم الخبر لا يصل إلى أي تحليل أو تنبيه كأنه Actual
    except Exception as e:  # noqa: BLE001
        print("تعذّر ملء الأرقام الفعلية:", e)


def enrich_for_ui(events, now, deps, intr=None, state=None):
    """أرقام فعلية ناقصة (تُحلّ مرة واحدة لكل تشغيل)، عناوين الفدرالي إن صدر كلام خلال 24 ساعة، وسلاسل الأسعار لقياس رد الفعل."""
    resolve_actuals(events, now, state if state is not None else {}, deps)
    heads = []
    try:
        has_speech = any(events_ctx.classify(e.get("title", ""))[0] == "speech" and now - timedelta(hours=24) <= e["time"] < now for e in events)
        if has_speech and deps.get("headlines_fed"):
            heads = deps["headlines_fed"](now)
    except Exception:  # noqa: BLE001
        heads = []
    series = {k: intr[k] for k in ("es", "y10", "dxy", "oil") if isinstance(intr, dict) and intr.get(k)} if intr else {}
    return heads, series


WATCH_MAX_S = 330        # أقصى انتظار داخل التشغيل الواحد (بالزمن الحقيقي المنقضي، شاملاً زمن الطلبات)
WATCH_STEP_S = 30


def _series(intr):
    return {k: intr[k] for k in ("es", "y10", "dxy", "oil") if isinstance(intr, dict) and intr.get(k)}


def fast_waiting(events, now):
    """أحداث تستحق الانتظار السريع: عالية التأثير، صدرت للتو (أو خلال دقيقتين)، لها مصدر آلي فعلي (BLS/FRED)، ولم يصل رقمها الموثّق.
    الأحداث غير المدعومة (ISM/ADP/Conference Board…) والخطب والمزادات لا تُنتظر: لا فائدة من ثوانٍ تُحجب بلا مصدر."""
    return [e for e in events if e.get("impact") == "High" and actuals.wants_number(e) and not actuals.is_verified(e)
            and indicators.match(e.get("title", "")) and not indicators.no_source_reason(e.get("title", ""))
            and -120 <= (now - e["time"]).total_seconds() <= 600]


def poll_budget(waiting, state, now, limit):
    """أقصى عدد جولات جلب في الانتظار: بلا مفتاح BLS تُحسب حصة اليوم (25 استعلاماً) وتُترك للأحداث التالية نصفها على الأقل،
    فلا يستنزف انتظارٌ واحد الحصة. الأحداث التي مصدرها FRED فقط لا تستهلك حصة BLS."""
    n = max(0, int(limit // WATCH_STEP_S))
    if os.environ.get("BLS_API_KEY", "").strip():
        return n
    uses_bls = any(indicators.match(e.get("title", ""))["key"] in indicators.BLS_IDS for e in waiting)
    if not uses_bls:
        return n
    used = (state.get("bls_calls") or {}).get(now.date().isoformat(), 0)
    left = max(0, bls.DAILY_LIMIT_V1 - bls.SAFETY_MARGIN - used)
    return min(n, left // 2)


def watch_releases(events, now, state, deps):
    """يُستدعى بعد إرسال ونشر ما تحقق فعلاً (لا يحجب التحديث الأول). ينتظر فقط الأحداث المدعومة التي صدرت للتو، يُعيد الجلب كل 30 ثانية
    حتى WATCH_MAX_S من الزمن الحقيقي المنقضي، وبميزانية جولات تراعي حصة BLS. يعيد (الوقت الحالي، هل وصل رقم جديد).
    لا يضمن تنبيهاً لحظياً: التأخر الأكبر هو بدء مشغّل GitHub المجدول، ثم زمن نشر المصدر نفسه. معطّل في الاختبارات ما لم يُمرَّر deps['watch_s']."""
    limit = deps.get("watch_s", WATCH_MAX_S if "fetch_oil" not in deps else 0)
    waiting = fast_waiting(events, now)
    info = {"at": now.isoformat(), "limit_s": limit, "polls": 0, "budget": 0, "waited_s": 0.0, "reason": ""}
    state["last_watch"] = info
    if limit <= 0 or not waiting:
        info["reason"] = "لا انتظار" if limit <= 0 else "لا حدث مدعوم ينتظر رقمه"
        return now, False
    budget = poll_budget(waiting, state, now, limit)
    info["budget"] = budget
    if budget <= 0:
        info["reason"] = "حصة BLS اليومية لا تسمح بانتظار سريع"
        return now, False
    sleep = deps.get("sleep", time.sleep)
    mono = deps.get("monotonic") or (None if "sleep" in deps else time.monotonic)      # بدون ساعة مُمرَّرة وبنوم مزيّف: زمن اسمي
    t0 = mono() if mono else 0.0
    start, got = now, False
    elapsed = lambda polls: (mono() - t0) if mono else polls * WATCH_STEP_S
    polls = 0
    while polls < budget and fast_waiting(events, now) and elapsed(polls) < limit:
        sleep(min(WATCH_STEP_S, max(0.0, limit - elapsed(polls))))
        polls += 1
        now = start + timedelta(seconds=elapsed(polls))
        resolve_actuals(events, now, state, deps)
    got = any(actuals.is_verified(e) for e in waiting)           # «وصل» فقط إن تحقق رقم فعلاً، لا لمجرد خروج الحدث من نافذة الانتظار
    still = bool(fast_waiting(events, now))
    info.update(polls=polls, waited_s=round(elapsed(polls), 1),
                reason="وصل الرقم" if got and not still else ("خرج الحدث من نافذة الانتظار دون رقم" if not still else "انتهت الميزانية أو المدة"))
    return now, got


def _send_releases(events, now, state, send, deps, fresh, series):
    """يرسل ويسجّل كل ما تحقق ولم يُرسل: صدور، وصول متأخر، مراجعة. كلها تدخل السجل الموحّد (state.alerts) بمعرّف الحدث الثابت
    والرابط المباشر في الرسالة، فلا يُرسل شيء للمستخدم ثم يغيب عن التطبيق."""
    sent = 0
    cache = {}

    def rep():
        if "r" not in cache:
            try:
                cache["r"] = full_report(now, events, deps, series=series)
            except Exception:  # noqa: BLE001
                cache["r"] = None
        return cache["r"]

    for ev in due_releases(events, now, state):
        minutes = max(5, int((now - ev["time"]).total_seconds() // 60))
        reaction = change_over(fresh.get("es", []), minutes) if "es" in fresh else None
        report = rep()
        rec = alert_from_release(ev, reaction, report, state, now, "release")
        send(format_release(ev, reaction, report, link=alert_link(rec["id"]), assess=rec["assessment"]))
        push_alert(state, rec, now)
        state["seen_events"].append(event_id(ev))
        mark_alerted(state, ev, "release")
        health.bump(state, "sent", now)
        sent += 1
    for ev in late_releases(events, now, state):          # وصل الرقم الموثّق بعد نافذة الصدور: تنبيه مستقل مرة واحدة
        report = rep()
        rec = alert_from_release(ev, None, report, state, now, "late")
        send(format_release(ev, None, report, late=True, now=now, link=alert_link(rec["id"]), assess=rec["assessment"]))
        push_alert(state, rec, now)
        state["seen_events"].append(event_id(ev))
        mark_alerted(state, ev, "late")
        health.bump(state, "sent", now)
        sent += 1
    for ev, old in revisions(events, now, state):         # مراجعة لاحقة لقيمة سبق التنبيه عنها: تُضاف إلى سجل الحدث نفسه
        report = rep()
        rec = alert_from_release(ev, None, report, state, now, "revision", revised_from=old)
        send(format_release(ev, None, None, revised_from=old, link=alert_link(rec["id"]), assess=rec["assessment"]))
        push_alert(state, rec, now)
        mark_alerted(state, ev, "revision")
        health.bump(state, "sent", now)
        sent += 1
    return sent


def _publish(report, events, now, state, deps, **kw):
    """نشر data.json ثم تسجيل نجاح النشر وآخر تقييم صالح (verdict_sig). يرفع استثناءً إن كانت اللقطة معيبة: لا يُعدّ نجاحاً
    وتبقى آخر لقطة صالحة منشورة كما هي (dashboard.publish يتحقق قبل الكتابة)."""
    view = dashboard.publish(report, events, now, NEWS_LABELS, docs_dir=deps.get("docs_dir"),
                             alerts=list(reversed(state.get("alerts") or [])), verdict_prev=state.get("verdict_sig"), **kw)
    if not view.get("error"):                  # حالة «تقييم غير مكتمل» كُتبت للعرض لكنها ليست نجاح نشر
        state["last_publish_ok"] = now.isoformat()
    vd = view.get("verdict") or {}
    if vd.get("available") and vd.get("signature"):
        state["verdict_sig"] = vd["signature"]
    return view


def run_preopen(now, state, send, deps, prefix=""):
    problems = []
    try:
        events = calendar_events(now, state, deps, problems)
    except Exception as e:  # noqa: BLE001
        events = []
        problems.append(f"تعذّر جلب التقويم الاقتصادي: {e}")
    resolve_actuals(events, now, state, deps)
    ser = {}
    if deps.get("intraday"):
        try:
            ser = _series(deps["intraday"](now))
        except Exception:  # noqa: BLE001
            ser = {}
    report, prices = full_report(now, events, deps, want_prices=True, series={k: v for k, v in ser.items() if v and now - v[-1][0] <= timedelta(minutes=45)})
    report.setdefault("problems", []).extend(problems)
    add_auction(report, prices, now, deps)
    try:
        update_history(report, prices, now, deps.get("history_path", HISTORY_FILE))
    except Exception as e:  # noqa: BLE001
        report["problems"].append(f"تعذّر تحديث سجل الأداء: {e}")
    pulse = state.get("pulse") or []
    heads, series = enrich_for_ui(events, now, deps, state=state)
    hv = None
    try:
        hv = health.build(report, events, now, state)
        _publish(report, events, now, state, deps, pulse=pulse, series=series, fed_heads=heads, health=hv,
                 week_news=get_week_news(now, deps, state), quality=quality.build(events, state, now))
    except Exception as e:  # noqa: BLE001
        report["problems"].append(f"تعذّر تحديث صفحة الواجهة: {e}")
    msg = format_preopen(report, events, now, prefix, dashboard.page_url())
    if hv and (health.daily_enabled() or health.should_notify(hv, state, now)):
        msg += "\n\n" + health.format_message(hv)      # لا تقرير يومي للصحة إلا إن فُعّل أو ظهر خلل مؤثر
    send(msg)


def _snapshot(now, events, deps, state, send, fresh, vols, intr):
    """لقطة الواجهة: تقرير كامل، نبض، صحة، نشر. يرفع استثناءً عند الفشل (لا يُحسب نجاحاً)."""
    snap = full_report(now, events, deps, series=_series(intr))
    try:
        pulse = market_pulse(fresh, vols) if fresh else []
    except Exception:  # noqa: BLE001
        pulse = []
    if pulse:
        state["pulse"] = pulse
    heads, series = enrich_for_ui(events, now, deps, intr, state)
    hv = health.build(snap, events, now, state)
    _publish(snap, events, now, state, deps, pulse=pulse or state.get("pulse") or [], series=series, fed_heads=heads, health=hv,
             week_news=get_week_news(now, deps, state), quality=quality.build(events, state, now))
    if health.should_notify(hv, state, now):
        send(health.format_message(hv))


def run_auto(now, state, send, deps):
    """الترتيب (v0.19): 1) ملء ما تحقق 2) إرسال الصدور والحركات فوراً 3) نشر اللقطة الأولى 4) بعدها فقط انتظار قصير
    للأحداث المدعومة التي لم يصل رقمها، فإن وصل شيء أُرسل ونُشر تحديث ثانٍ. لا شيء مُتحقَّق يتأخر بسبب انتظار غيره."""
    sent = 0
    try:
        events = calendar_events(now, state, deps)
    except Exception as e:  # noqa: BLE001
        print("تعذّر جلب التقويم:", e)
        events = []
    resolve_actuals(events, now, state, deps)      # قبل due_releases: التقويم لا يحمل الرقم الفعلي أصلاً

    try:
        intr = deps["intraday"](now)
    except Exception as e:  # noqa: BLE001
        print("تعذّر جلب البيانات اللحظية:", e)
        intr = {}
    # بيانات قديمة (سوق مغلق) لا تُعامَل كصدمة
    vols = intr.pop("_vol", {}) if isinstance(intr, dict) else {}
    fresh = {k: v for k, v in intr.items() if v and now - v[-1][0] <= timedelta(minutes=45)}
    bad = [k for k, v in fresh.items() if not safety.valid_quote(k, v[-1][1])]
    for k in bad:                       # قيمة بوحدة/نطاق غير منطقي: لا تنبيه مبني عليها
        fresh.pop(k, None)
        health.bump(state, "suppressed", now)
        print(f"استُبعد {k} من المراقبة اللحظية: قيمة خارج النطاق المنطقي")

    # 1) صدور بيانات كبرى (يشمل الوصول المتأخر والمراجعات): فوراً، بما تحقق الآن
    sent += _send_releases(events, now, state, send, deps, fresh, _series(intr))

    # 2) صدمة مفاجئة
    if fresh and shock_in_cooldown(state, now):
        _chg0 = {k: change_over(fresh[k], 60) for k in ("es", "vix", "oil", "gold") if k in fresh}
        if detect_shock(_chg0)[0]:
            health.bump(state, "suppressed", now)      # صدمة مكررة منعتها فترة التهدئة
    if fresh and not shock_in_cooldown(state, now):
        changes = {k: change_over(fresh[k], 60) for k in ("es", "vix", "oil", "gold") if k in fresh}
        hit, signals = detect_shock(changes)
        if hit:
            try:
                headlines = deps["headlines"](now)
            except Exception:  # noqa: BLE001
                headlines = []
            try:
                report = full_report(now, events, deps, series=_series(intr))
            except Exception:  # noqa: BLE001
                report = None
            rec = alert_from_shock(signals, changes, headlines, now)
            send(format_shock(signals, changes, headlines, report, link=alert_link(rec["id"])))
            push_alert(state, rec, now)
            state["last_shock"] = now.isoformat()
            health.bump(state, "sent", now)
            sent += 1
            _m = detect_move(fresh, vols)      # الصدمة تغطي الحركة نفسها: لا تنبيه مكرر
            for k in (_m["keys"] if _m else []):
                state.setdefault("last_move", {})[move_dir_key(k, _m["ch"])] = now.isoformat()
    # 3) حركة كبيرة بأي اتجاه (مثل صعود الأسهم مع هبوط النفط)
    if fresh:
        mv = detect_move(fresh, vols)
        shock_sent = state.get("last_shock") == now.isoformat()
        if mv and not shock_sent:
            dkeys = [move_dir_key(k, mv["ch"]) for k in mv["keys"]]
            mags = {move_dir_key(k, mv["ch"]): move_magnitude(k, mv["ch"]) for k in mv["keys"]}
            if all(move_in_cooldown(state, dk, now, mags[dk]) for dk in dkeys):
                health.bump(state, "suppressed", now)   # تنبيه مكرر منعته فترة التهدئة
            if not all(move_in_cooldown(state, dk, now, mags[dk]) for dk in dkeys):
                try:
                    headlines = (deps.get("headlines_market") or deps["headlines"])(now)
                except Exception:  # noqa: BLE001
                    headlines = []
                try:
                    report = full_report(now, events, deps, series=_series(intr))
                except Exception:  # noqa: BLE001
                    report = None
                rec = alert_from_move(mv, headlines, now)
                send(format_move(mv, headlines, report, link=alert_link(rec["id"])))
                health.bump(state, "sent", now)
                push_alert(state, rec, now)
                lm = state.setdefault("last_move", {})
                lmm = state.setdefault("last_move_mag", {})
                for dk in dkeys:
                    lm[dk] = now.isoformat()
                    lmm[dk] = mags[dk]
                sent += 1

    # 4) تحديث الواجهة الأول (كل ~15 دقيقة): ما تحقق ينشر الآن دون انتظار غيره
    def publish_snapshot(n):
        try:
            _snapshot(n, events, deps, state, send, fresh, vols, intr)
        except Exception as e:  # noqa: BLE001
            print("تعذّر تحديث لقطة الواجهة:", e)
            try:       # لا نُبقي حالة «سليمة» قديمة: نكتب أن الفحص تعذّر
                dashboard.patch_health(health.build(None, events, n, state, error=f"تعذّر بناء اللقطة: {e}"), deps.get("docs_dir"))
            except Exception:  # noqa: BLE001
                pass
    publish_snapshot(now)

    # 5) متابعة ما لم يصل رقمه (مدعوم فقط، بميزانية زمن حقيقي وحصة): لا يحجب شيئاً مما سبق
    now2, arrived = watch_releases(events, now, state, deps)
    if arrived:
        sent += _send_releases(events, now2, state, send, deps, fresh, _series(intr))
        publish_snapshot(now2)
    print(f"انتهت المراقبة: أُرسل {sent} تنبيه")
    return sent


def run_backtest(send, deps=None):
    """اختبار بأثر رجعي على 5 سنوات؛ يرسل الملخص ويحفظ backtest.json."""
    import backtest
    deps = deps or {"history": lambda: backtest.fetch_history(5),
                    "fred": lambda now: c.fetch_fred(datetime.now(timezone.utc), 2000)}
    hist, problems = deps["history"]()
    fred = {}
    try:
        fred, p2 = deps["fred"](None)
        problems += p2
    except Exception as e:  # noqa: BLE001
        problems.append(f"تعذّر FRED في الاختبار التاريخي: {e}")
    res = backtest.run_backtest(hist, fred)
    try:
        with open("backtest.json", "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    except OSError:
        pass
    msg = backtest.format_result(res)
    if problems:
        msg += "\n" + "\n".join("⚠ " + p for p in problems[:6])
    send(msg)
    return res


def run_calibrate(send, path=HISTORY_FILE):
    try:
        data = calibrate.load(path)
    except FileNotFoundError:
        send("📈 مِرصاد — معايرة\nلا يوجد سجل بعد: يُنشأ بعد أول تقرير قبل الافتتاح.")
        return
    body = calibrate.summarize(data) if data else "لا أيام مكتملة بعد: تُملأ النتيجة الفعلية في اليوم التالي."
    send("📈 مِرصاد — معايرة أسبوعية\n" + body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["preopen", "auto", "test", "calibrate", "backtest", "actuals-check"], default="preopen")
    ap.add_argument("--state", default=STATE_FILE)
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    state = load_state(args.state)
    try:
        if args.mode == "test":
            send_telegram("🧪 مِرصاد: اختبار الاتصال ناجح. سيصلك الآن تقرير تجريبي ببيانات حقيقية.")
            run_preopen(now, state, send_telegram, DEPS, prefix="🧪 [اختبار] ")
        elif args.mode == "preopen":
            run_preopen(now, state, send_telegram, DEPS)
        elif args.mode == "calibrate":
            run_calibrate(send_telegram)
        elif args.mode == "backtest":
            run_backtest(send_telegram)
        elif args.mode == "actuals-check":
            import verify
            verify.run_check(now, state, send=send_telegram)
        else:
            run_auto(now, state, send_telegram, DEPS)
    except Exception as e:  # noqa: BLE001
        try:
            send_telegram(f"⚠ مِرصاد: تعذّر التشغيل ({args.mode}): {e}")
        except Exception:  # noqa: BLE001
            pass
        save_state(state, args.state)
        print("خطأ:", e)
        sys.exit(1)
    if args.mode in ("preopen", "auto", "test"):
        state["last_run_ok"] = {"mode": args.mode, "at": datetime.now(timezone.utc).isoformat()}   # اكتمل التشغيل دون استثناء
    save_state(state, args.state)


if __name__ == "__main__":
    main()
