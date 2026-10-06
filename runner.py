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
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import calibrate
import auction
import dashboard
import events_ctx
import collector as c
import macro

STATE_FILE = "state.json"
HISTORY_FILE = "history.csv"
HISTORY_COLS = ["date", "score", "level", "es_close", "outcome_range_pct"]
BAGHDAD = timezone(timedelta(hours=3))

# عتبات رصد الصدمة خلال آخر ساعة
SHOCK = {"gold_up": 0.8, "oil_up": 1.5, "vix_up": 6.0, "es_down": -0.6}
SHOCK_COOLDOWN_H = 3
RELEASE_WINDOW_H = 3

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
INFO_ORDER = ["rates", "front", "dollar", "tech", "mag7", "banks", "corr", "cot", "earnings", "fed"]


# ───────────────────────── الحالة ─────────────────────────

def load_state(path=STATE_FILE):
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:  # noqa: BLE001
        s = {}
    s.setdefault("seen_events", [])
    s.setdefault("last_shock", None)
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
    a, f = parse_num(ev.get("actual")), parse_num(ev.get("forecast"))
    if a is None or f is None:
        return None
    if abs(a - f) < 1e-12:
        return "مطابق للمتوقع"
    return "أعلى من المتوقع" if a > f else "أدنى من المتوقع"


def due_releases(events, now, state, window_h=RELEASE_WINDOW_H):
    seen = set(state.get("seen_events", []))
    out = []
    for e in events:
        if e["impact"] != "High" or not e.get("actual"):
            continue
        if e["time"] > now or now - e["time"] > timedelta(hours=window_h):
            continue
        if event_id(e) in seen:
            continue
        out.append(e)
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
    import yfinance as yf
    out = {}
    for key in ("es", "vix", "oil", "gold"):
        h = yf.Ticker(c.SYMBOLS[key]).history(period="2d", interval="5m").dropna(subset=["Close"])
        out[key] = [(ts.to_pydatetime().astimezone(timezone.utc), float(v)) for ts, v in h["Close"].items()]
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
    "fred": c.fetch_fred,
    "cot": lambda now: c.fetch_cot(),
    "earnings": c.fetch_earnings,
    "news": lambda topic, now: fetch_headlines(now, *NEWS_TOPICS[topic]),
}


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


def format_preopen(report, events, now, prefix=""):
    lines = [prefix + "📊 مِرصاد — قبل افتتاح السوق", f"🕒 {hhmm(now)} بتوقيت بغداد", ""]
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
    upcoming = [e for e in events if e["impact"] in ("High", "Medium") and now <= e["time"] <= now + timedelta(hours=24)]
    if upcoming:
        lines += ["", "أحداث USD خلال 24 ساعة:"]
        for e in upcoming[:6]:
            mark = "🔴" if e["impact"] == "High" else "🟠"
            extra = f" (توقع {e['forecast']} | سابق {e['previous']})" if e["forecast"] or e["previous"] else ""
            d = events_ctx.describe(e, hhmm(e["time"]), ((report.get("macro") or {}).get("label", "")))
            lines.append(f"{mark} {hhmm(e['time'])} — {e['title']}{(' · ' + d['name']) if d['name'] != e['title'] else ''}{extra}")
            if d["expect"]:
                lines.append(f"   ↳ {d['expect']}")
            if d["short"] and e["impact"] == "High":
                lines.append(f"   ↳ {d['short']}")
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


def format_release(ev, es_reaction, report):
    lines = [f"📥 مِرصاد — صدرت بيانات: {ev['title']}",
             f"الفعلي: {ev['actual']} | المتوقع: {ev['forecast'] or '—'} | السابق: {ev['previous'] or '—'}"]
    s = surprise(ev)
    ml = ((report or {}).get("macro") or {}).get("label", "")
    ir = events_ctx.interpret_release(ev, ml)
    if ir["surprise"] or s:
        lines.append(f"النتيجة: {ir['surprise'] or s}")
    if ir["vs_prev"]:
        lines.append(f"مقارنة بالسابق: {ir['vs_prev']}")
    if ir["meaning"]:
        lines.append(f"المعنى المعتاد لـ ES: {ir['meaning']}")
    if ir["note"]:
        lines.append(f"ملاحظة: {ir['note']}")
    if es_reaction is not None:
        lines.append(f"حركة ES منذ الصدور: {es_reaction:+.2f}%")
    if report is not None:
        lines += [""] + risk_lines(report)
    lines += ["", "ملاحظة: اتجاه التأثير يعتمد على نوع البيانات، وقد يكون الخبر مسعَّراً مسبقاً."]
    return "\n".join(lines)


def format_shock(signals, changes, headlines, report):
    fmt = lambda k: "—" if changes.get(k) is None else f"{changes[k]:+.2f}%"
    lines = ["🚨 مِرصاد — حركة سوق غير معتادة (قد تدل على حدث مفاجئ)",
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

def send_telegram(text):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("—— (وضع تجريبي: لا إعدادات تيليجرام) ——")
        print(text)
        return False
    data = json.dumps({"chat_id": chat, "text": text[:4000]}).encode("utf-8")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        ok = json.loads(r.read().decode("utf-8")).get("ok", False)
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


def full_report(now, events, deps, want_prices=False):
    prices, problems = deps["prices"](now)
    extras, p2 = gather_extras(now, deps)
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


def run_preopen(now, state, send, deps, prefix=""):
    problems = []
    try:
        events = deps["calendar"](now)
    except Exception as e:  # noqa: BLE001
        events = []
        problems.append(f"تعذّر جلب التقويم الاقتصادي: {e}")
    report, prices = full_report(now, events, deps, want_prices=True)
    report.setdefault("problems", []).extend(problems)
    add_auction(report, prices, now, deps)
    try:
        update_history(report, prices, now, deps.get("history_path", HISTORY_FILE))
    except Exception as e:  # noqa: BLE001
        report["problems"].append(f"تعذّر تحديث سجل الأداء: {e}")
    try:
        dashboard.publish(report, events, now, NEWS_LABELS, docs_dir=deps.get("docs_dir"))
    except Exception as e:  # noqa: BLE001
        report["problems"].append(f"تعذّر تحديث صفحة الواجهة: {e}")
    msg = format_preopen(report, events, now, prefix)
    url = dashboard.page_url()
    if url:
        msg += f"\n\n🖥 الواجهة الكاملة: {url}"
    send(msg)


def run_auto(now, state, send, deps):
    sent = 0
    try:
        events = deps["calendar"](now)
    except Exception as e:  # noqa: BLE001
        print("تعذّر جلب التقويم:", e)
        events = []

    try:
        intr = deps["intraday"](now)
    except Exception as e:  # noqa: BLE001
        print("تعذّر جلب البيانات اللحظية:", e)
        intr = {}
    # بيانات قديمة (سوق مغلق) لا تُعامَل كصدمة
    fresh = {k: v for k, v in intr.items() if v and now - v[-1][0] <= timedelta(minutes=45)}

    # 1) صدور بيانات كبرى
    for ev in due_releases(events, now, state):
        minutes = max(5, int((now - ev["time"]).total_seconds() // 60))
        reaction = change_over(fresh.get("es", []), minutes) if "es" in fresh else None
        try:
            report = full_report(now, events, deps)
        except Exception:  # noqa: BLE001
            report = None
        send(format_release(ev, reaction, report))
        state["seen_events"].append(event_id(ev))
        sent += 1

    # 2) صدمة مفاجئة
    if fresh and not shock_in_cooldown(state, now):
        changes = {k: change_over(fresh[k], 60) for k in ("es", "vix", "oil", "gold") if k in fresh}
        hit, signals = detect_shock(changes)
        if hit:
            try:
                headlines = deps["headlines"](now)
            except Exception:  # noqa: BLE001
                headlines = []
            try:
                report = full_report(now, events, deps)
            except Exception:  # noqa: BLE001
                report = None
            send(format_shock(signals, changes, headlines, report))
            state["last_shock"] = now.isoformat()
            sent += 1
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
    ap.add_argument("--mode", choices=["preopen", "auto", "test", "calibrate", "backtest"], default="preopen")
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
    save_state(state, args.state)


if __name__ == "__main__":
    main()
