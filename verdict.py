# -*- coding: utf-8 -*-
"""
مِرصاد — التقرير الرئيسي الواحد (v0.19): «النصيحة الآن» وما يسندها، بلا بطاقات متنافسة.

يجمع في خلاصة واحدة متماسكة:
- الميل (صعودي/هبوطي/مختلط): قراءة موقع السعر من قيمة الأمس (نظرية المزاد، تجريبي) — أي «أين السعر الآن».
- الانحياز الماكروي (داعم/ضاغط/مختلط): قراءة البيانات والفدرالي والأسواق والإصدارات الموثّقة — أي «ما الخلفية».
  ويشرح العلاقة بينهما صراحة (اتفاق أو تعارض) بدل بطاقتين متجاورتين.
- الثقة والحدة، السبب الرئيسي وأهم عاملين أو ثلاثة، ما يؤكد السيناريو وما يبطله.
- وقت التقييم، وهل أُخذ آخر خبر مهم بالحسبان («لم يُدمج الإصدار بعد» إن لم يصل رقمه الموثّق).
- علاقة الخبر بالتقييم العام: «الخبر ضاغط، لكن التقييم العام ما زال مختلطاً لأن …»، وتغيّر الصورة: «التقييم السابق لم يعد صالحاً …».
الماكرو وحده لا يعطي أمر شراء أو بيع: الترتيب المعتمد ماكرو ← السياق الأسبوعي ← الإيقاع اليومي ← تدفق الأوامر.
قواعد نصية شفافة، بلا ذكاء اصطناعي. فشل ناعم: عند نقص البيانات يقول «غير مكتمل» بدل تقييم مختلق.
"""
from datetime import datetime, timedelta

import events_ctx

UPCOMING_WINDOW_MIN = 90      # نافذة «اقتراب خبر مهم» بالدقائق (قابلة للضبط: build(..., window_min=...))
IMMINENT_MIN = 15             # أقل من هذا: «وشيك» — نص أشدّ
RANK = {"منخفضة": 1, "متوسطة": 2, "مرتفعة": 3}
LABEL = {1: "منخفضة", 2: "متوسطة", 3: "مرتفعة"}

LEAN_AR = {"up": "صعودي", "down": "هبوطي", "mixed": "مختلط", "na": "غير متاح"}
BIAS_ARROW = {"support": "▲", "pressure": "▼", "neutral": "◆"}


def _baghdad(iso):
    try:
        return (datetime.fromisoformat(iso) + timedelta(hours=3)).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return ""


def lean_of(report):
    """الميل من موقع السعر (المزاد): (key, basis). غير متاح إن لم تتوفر البيانات."""
    t = (report or {}).get("tilt")
    if not t or t.get("score") is None:
        return "na", "بيانات موقع السعر غير متاحة"
    s = t["score"]
    key = "up" if s >= 0.25 else "down" if s <= -0.25 else "mixed"
    loc = {"above_value": "ES فوق قيمة الأمس", "below_value": "ES تحت قيمة الأمس", "inside_value": "ES داخل قيمة الأمس"}.get(((report or {}).get("auction") or {}).get("location"), "")
    return key, (loc + " (قراءة تجريبية)" if loc else "قراءة موقع السعر (تجريبية)")


def _relation(lean, b):
    """كيف يتصل الميل بالانحياز: اتفاق أو تعارض أو أحدهما غير متاح."""
    if lean == "na" or not b or not b.get("available"):
        return ""
    bk = b["key"]
    if (lean == "up" and bk == "support") or (lean == "down" and bk == "pressure"):
        return "الميل والانحياز الماكروي في الاتجاه نفسه، فالصورة متسقة."
    if lean == "mixed" or bk == "neutral":
        return "أحدهما محايد، فلا تعارض لكن لا قناعة كاملة باتجاه واحد."
    return ("الميل يعكس موضع السعر الآن بينما الانحياز يعكس الخلفية الماكروية، وهما متعارضان: "
            "أي حركة مع الميل تبقى هشّة حتى يؤيدها الماكرو أو يتغير موضع السعر.")


def _remain_ar(mins):
    m = int(mins) if mins == int(mins) else int(mins) + 1          # تقريب للأعلى: «بعد دقيقة» لا «بعد 0»
    if m < 1:
        return "أقل من دقيقة"
    if m < 60:
        return f"{m} دقيقة" if m > 2 else ("دقيقة" if m == 1 else "دقيقتين")
    h, r = divmod(m, 60)
    return f"{h} ساعة" + (f" و{r} دقيقة" if r else "")


def upcoming(events, now, window_min=UPCOMING_WINDOW_MIN):
    """أحداث عالية الأهمية خلال النافذة، الأقرب أولاً. الوقت بتوقيت بغداد (UTC+3 ثابت) من توقيت الحدث الفعلي لا من موعد مفترض."""
    out = []
    for e in events or []:
        t = e.get("time")
        if e.get("impact") != "High" or t is None or t <= now:
            continue
        mins = (t - now).total_seconds() / 60.0
        if mins > window_min:
            continue
        kind, name, _ = events_ctx.classify(e.get("title", ""))
        if kind == "holiday":
            continue
        out.append({"title": e.get("title", ""), "name": name or e.get("title", ""), "kind": kind, "minutes": round(mins, 1),
                    "remaining_ar": _remain_ar(mins), "at_ar": (t + timedelta(hours=3)).strftime("%H:%M"), "imminent": mins <= IMMINENT_MIN})
    return sorted(out, key=lambda x: x["minutes"])


def reliability(rep, b, pend):
    """موثوقية التقييم من جودة البيانات (منفصلة عن «اتفاق العوامل»): {valid, label, rank, reasons, state, coverage}.
    valid=False ⇒ التقييم غير صالح (سلامة حرجة/غير مكتملة أو تغطية <60% أو خطأ حساب). تسقف الثقة المعروضة ولا ترفعها كثرة العوامل المتفقة."""
    sf, rc = rep.get("safety") or {}, rep.get("confidence") or {}
    state, cov = sf.get("state"), sf.get("coverage")
    reasons, valid, cap = [], True, 3
    if "error" in rep:
        valid = False
        reasons.append("خطأ في حساب التقرير")
    if (rep.get("risk") or {}).get("incomplete") is True:
        valid = False
    if state in ("incomplete", "critical"):
        valid = False
        reasons.append(sf.get("label") or "فحوص السلامة: التقييم غير مكتمل")
    if cov is not None and cov < 0.6:
        valid = False
        reasons.append(f"تغطية البيانات {cov:.0%} فقط")
    if rc.get("label") in RANK:
        cap = min(cap, RANK[rc["label"]])
        if cap < 3:
            reasons += [w for w in (rc.get("why") or [])[:2]]
    elif not sf:
        cap = min(cap, 2)
        reasons.append("جودة البيانات غير معلومة في هذه اللقطة")
    if state == "major":
        cap = min(cap, 1)
        reasons.append("يوجد خلل مؤثر في البيانات")
    if cov is not None and 0.6 <= cov < 0.85:
        cap = min(cap, 2)
        reasons.append(f"تغطية البيانات {cov:.0%}")
    if pend:
        cap = min(cap, 2)
        reasons.append("إصدار مهم لم يُدمج بعد")
    seen, uniq = set(), []
    for r in reasons:
        if r and r not in seen:
            seen.add(r)
            uniq.append(r)
    return {"valid": valid, "rank": cap, "label": LABEL[cap], "reasons": uniq[:3], "state": state, "coverage": cov}


def _advice(b, lean, conf, intensity, pending, available, ups=None, rel=None):
    if not available:
        base = "التقييم غير مكتمل — لا تبنِ قراراً على السياق الماكروي الآن؛ اعتمد تحليلك الفني وانتظر عودة البيانات."
        if rel and rel.get("reasons"):
            base = base[:-1] + f" (السبب: {rel['reasons'][0]})."
        if ups:
            u = ups[0]
            base += f" وللعلم: {u['name']} بعد {u['remaining_ar']} ({u['at_ar']} بغداد)."
        return base
    bk, hi = b["key"], (intensity or {}).get("word") == "قوية"
    guard = ""
    if conf == "منخفضة":
        guard = " والثقة منخفضة" + (f" ({rel['reasons'][0]})" if rel and rel.get("rank", 3) < RANK.get(b.get("confidence"), 3) and rel.get("reasons") else "") + " فخفّض حجم القناعة."
    head = ""
    if pending:
        p = pending[0]
        extra = f" (+{len(pending) - 1} آخر)" if len(pending) > 1 else ""
        if p.get("unsupported"):
            head = f"صدر {p['name']}{extra} ولا مصدر آلي لرقمه فهو غير مدموج: لا تفترض أن التقييم يعكسه، "
        else:
            head = f"حان موعد {p['name']}{extra} ولم تتأكد القراءة بعد: لا تعتمد على هذا التقييم قبل وصول الرقم الموثّق، "
    elif ups:
        u = ups[0]
        extra = f" (ثم {ups[1]['name']} بعد {ups[1]['remaining_ar']})" if len(ups) > 1 else ""
        if u["imminent"]:
            head = (f"{u['name']} بعد {u['remaining_ar']} ({u['at_ar']} بغداد، أهمية عالية){extra}: التنفيذ قبل الإصدار أعلى مخاطرة "
                    "(اتساع السبريد وانزلاق وحركة ضعيفة الدلالة)، فانتظر الرقم ثم أعد التقييم. ")
        else:
            head = (f"{u['name']} بعد {u['remaining_ar']} ({u['at_ar']} بغداد، أهمية عالية){extra}: خفّض الاعتماد على التقييم الحالي "
                    "قبل الإصدار فقد يغيّره. ")
    if bk == "pressure":
        body = "الخلفية ضاغطة: ابحث عن التأكيد في سياقك الأسبوعي وإيقاعك اليومي قبل أي شراء، والصعود يحتاج دليلاً من تدفق الأوامر."
    elif bk == "support":
        body = "الخلفية داعمة: لا تعاكس الصعود بلا سبب فني، لكن لا تطارد الحركة؛ التنفيذ من تدفق الأوامر لا من الماكرو."
    else:
        body = "الخلفية مختلطة: لا ميزة ماكروية واضحة، فاعتمد على السياق الأسبوعي والإيقاع اليومي وتدفق الأوامر."
    if hi:
        body += " والحدة قوية: توقّع تقلباً أكبر حول الأخبار."
    return "النصيحة الآن: " + head + body + guard


def _short(avail, b, pend, ups, rel):
    """وسم قصير جداً (≤ 3 كلمات) لشاشة المراقبة؛ الأولوية: غير صالح ← بانتظار رقم ← خبر وشيك ← خبر قريب ← حال الخلفية."""
    if not avail:
        return "غير صالح"
    if pend:
        return "بانتظار الرقم"
    if ups and ups[0]["imminent"]:
        return "انتظر الإصدار"
    if ups:
        return "خبر قريب"
    base = {"pressure": "ضغط ماكروي", "support": "دعم ماكروي"}.get(b.get("key"), "بلا ميزة ماكروية")
    return base + (" · ثقة محدودة" if rel and rel["rank"] < 3 else "")


def _news_relation(releases, b):
    """علاقة أهم إصدار موثّق حديث بالتقييم العام (نص واحد)."""
    groups = (releases or {}).get("groups") or []
    if not groups or not b or not b.get("available"):
        return ""
    top = max(groups, key=lambda g: abs(g["value"]) * g["importance"])
    name = top["lead"]
    eff = top["effect"]
    word = {"bull": "داعم", "bear": "ضاغط", "neu": "محدود الأثر"}[eff]
    comps = b.get("components") or []
    label = b["label"]
    lab_acc = {"داعم": "داعمًا", "ضاغط": "ضاغطًا", "مختلط": "مختلطًا"}.get(label, label)
    bk = b["key"]
    if (eff == "bear" and bk == "pressure") or (eff == "bull" and bk == "support"):
        return f"الخبر ({name}) {word} ويتسق مع الانحياز الماكروي ({label}): الصورة العامة والخبر في الاتجاه نفسه."
    if eff == "neu":
        return f"الخبر ({name}) أثره محدود على التقييم العام ({label})."
    opp = [c for c in comps if c["key"] != "events" and c["tone"] == ("support" if eff == "bear" else "pressure")][:2]
    ev_c = next((c for c in comps if c["key"] == "events"), None)
    if bk == "neutral" or (eff == "bear" and bk == "support") or (eff == "bull" and bk == "pressure"):
        because = "؛ ".join(c["note"] for c in opp) or (
            f"مساهمة الخبر ({ev_c['contribution']:+.2f}) أصغر من أن تقلب الصورة" if ev_c else "عوامل أخرى توازنه")
        return f"الخبر ({name}) {word}، لكن التقييم العام ما زال {lab_acc} لأن {because}."
    return f"الخبر ({name}) {word}."


def _drivers(b, releases):
    out = []
    for c in (b.get("components") or [])[:6]:
        if c["tone"] == "flat":
            continue
        out.append({"name": c["name"], "arrow": c["arrow"], "tone": c["tone"], "note": c["note"], "contribution": c["contribution"]})
        if len(out) == 3:
            break
    return out


def _confirm_invalidate(b, releases, drivers_list):
    comps = (b or {}).get("components") or []
    bk = (b or {}).get("key")
    want = {"pressure": "pressure", "support": "support"}.get(bk)
    conf, inv = [], []
    if want:
        line = lambda c: c["note"] if c["key"] == "events" else f"{c['name']}: {c['note']}"
        conf = [line(c) for c in comps if c["tone"] == want][:2]
        inv = [line(c) + " — يضعف السيناريو إن زاد" for c in comps if c["tone"] not in ("flat", want)][:2]
        trig = {"pressure": "يبطله: تراجع العوائد والدولار مع استعادة ES قيمة الأمس وضيق فروق الائتمان.",
                "support": "يبطله: قفزة في العوائد أو الدولار أو اتساع فروق الائتمان مع كسر ES لقيمة الأمس."}[want]
        inv.append(trig)
    else:
        conf = ["لا سيناريو محدد بعد: التقييم مختلط"]
        inv = ["يتحدد الاتجاه بإصدار قادم أو بتأكيد واضح من العوائد والدولار وتدفق الأوامر."]
    mk = (releases or {}).get("market")
    if releases and releases.get("groups"):
        if mk and mk.get("key") == "na":
            conf.append("تأكيد السوق للإصدار الأخير غير متاح بعد — تقييم أولي")
        elif mk:
            (conf if mk.get("key") == "confirm" else inv).append("الإصدار الأخير: " + mk["label"])
    return conf[:3], inv[:3]


def _news_state(releases, events, now):
    pend = (releases or {}).get("pending") or []
    groups = (releases or {}).get("groups") or []
    if pend:
        p = pend[0]
        txt = f"لم يُدمج الإصدار بعد: {p['name']} ({p['status_ar'] or 'بانتظار الرقم'})"
        if p.get("unsupported"):
            txt = f"إصدار غير مدعوم آلياً: {p['name']} — لم يُدمج في التقييم"
        return {"state": "pending", "text": txt, "ids": [x["id"] for x in pend]}
    if groups:
        g = max(groups, key=lambda g: g["date"])
        return {"state": "integrated", "text": f"أُخذ آخر خبر مهم بالحسبان: {g['lead']}", "ids": g["ids"]}
    return {"state": "none", "text": "لا إصدار مهم خلال آخر 24 ساعة", "ids": []}


def build(report, now, prev=None, events=None, window_min=UPCOMING_WINDOW_MIN):
    """التقرير الرئيسي. prev: توقيع التقييم السابق من state (أو None). events: لاقتراب الخبر المهم. لا يرفع استثناءً."""
    try:
        return _build(report, now, prev, events, window_min)
    except Exception as ex:  # noqa: BLE001
        return {"available": False, "advice": "النصيحة الآن: التقييم غير مكتمل — تعذّر بناء الخلاصة (" + type(ex).__name__ + ").",
                "assessed_at": now.isoformat(), "assessed_at_ar": _baghdad(now.isoformat()), "signature": None, "error": True}


def _build(report, now, prev, events, window_min=UPCOMING_WINDOW_MIN):
    rep = report or {}
    b = rep.get("bias") or {}
    releases = rep.get("releases") or {}
    lean, lean_basis = lean_of(rep)
    pend = releases.get("pending") or []
    rel = reliability(rep, b, pend)
    avail = bool(b.get("available")) and rel["valid"]
    agreement = b.get("confidence") if b.get("available") else None            # اتفاق العوامل (ليس موثوقية البيانات)
    conf = LABEL[min(RANK.get(agreement, 1), rel["rank"])] if avail else None   # المعروضة = الأدنى: كثرة المتفقة لا ترفع ثقة بيانات ضعيفة
    ups = upcoming(events, now, window_min)
    from dashboard import _intensity_word
    inten = rep.get("intensity")
    intensity = {"score": inten, "word": _intensity_word(inten)} if inten is not None else None
    drivers = _drivers(b, releases) if avail else []
    confirms, invalid = _confirm_invalidate(b if avail else None, releases, drivers)
    sig = {"bias": b.get("key") if avail else None, "bias_label": b.get("label") if avail else None, "lean": lean, "at": now.isoformat(),
           "ok_at": now.isoformat() if avail else (prev or {}).get("ok_at")}
    change = None
    if prev and prev.get("bias") and sig["bias"] and prev["bias"] != sig["bias"]:
        change = {"changed": True, "text": f"التقييم السابق لم يعد صالحاً — تغيّر الانحياز من {prev.get('bias_label')} إلى {sig['bias_label']}",
                  "from": prev.get("bias_label"), "to": sig["bias_label"], "at": now.isoformat()}
    elif prev and prev.get("lean") and prev["lean"] != lean and lean != "na" and prev["lean"] != "na":
        change = {"changed": True, "text": f"تغيّر الميل من {LEAN_AR[prev['lean']]} إلى {LEAN_AR[lean]} (موضع السعر)", "from": LEAN_AR[prev["lean"]], "to": LEAN_AR[lean], "at": now.isoformat()}
    elif prev and (prev.get("change") or {}).get("at"):          # التغيّر يبقى ظاهراً 6 ساعات (لا يختفي بعد دورة واحدة)
        try:
            if now - datetime.fromisoformat(prev["change"]["at"]) <= timedelta(hours=6):
                change = prev["change"]
        except Exception:  # noqa: BLE001
            change = None
    sig["change"] = change
    why_parts = []
    if avail:
        top = [d for d in drivers][:3]
        why_parts = [f"{d['name']} {d['arrow']}" for d in top]
    reason = (b.get("why") if avail and not why_parts else "؛ ".join(why_parts)) if avail else ("؛ ".join(rel["reasons"]) or b.get("why") or "البيانات غير كافية لتقييم موثوق")
    return {
        "available": avail,
        "short": _short(avail, b, pend, ups, rel),
        "advice": _advice(b, lean, conf, intensity, pend, avail, ups, {**rel, "rank": rel["rank"]}),
        "lean": {"key": lean, "label": LEAN_AR[lean], "basis": lean_basis},
        "bias": {"key": b.get("key"), "label": b.get("label", "غير متاح"), "arrow": b.get("arrow") or BIAS_ARROW.get(b.get("key"), ""), "available": avail},
        "relation": _relation(lean, b) if avail else "",
        "news_relation": _news_relation(releases, b) if avail else "",
        "confidence": conf or "غير متاح", "agreement": agreement or "غير متاح",
        "reliability": {"label": rel["label"], "reasons": rel["reasons"], "valid": rel["valid"], "state": rel["state"], "coverage": rel["coverage"]},
        "degraded": bool(avail and rel["rank"] < RANK.get(agreement, 3)), "upcoming": ups, "intensity": intensity,
        "reason": reason, "drivers": drivers, "confirms": confirms, "invalidates": invalid,
        "news": _news_state(releases, events, now), "change": change,
        "market": releases.get("market"),
        "assessed_at": now.isoformat(), "assessed_at_ar": _baghdad(now.isoformat()),
        "last_ok_at": sig["ok_at"], "last_ok_at_ar": _baghdad(sig["ok_at"]) if sig["ok_at"] else "",
        "signature": sig, "method": "قواعد شفافة غير معايَرة؛ ليست توصية. الماكرو وحده لا يعطي أمر شراء أو بيع.",
        "workflow": "ماكرو ← سياق أسبوعي ← إيقاع يومي ← تدفق الأوامر",
    }
