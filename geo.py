#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مِرصاد — تصنيف الأخبار الجيوسياسية بالقواعد (دون ذكاء اصطناعي).

ما يفعله: يصنّف كل عنوان (النوع، المنطقة، الحدّة، تهدئة أم تصعيد)، يدمج العناوين المتكررة في «قصة» واحدة،
يزن القصة بعدد المصادر وحداثتها، ثم يتحقق من حركة السوق: العنوان الخطير الذي لا يصدّقه السوق تنخفض درجته.
ما لا يفعله: لا يفهم السياق ولا يحدد اتجاه الأثر (صعود/هبوط). الأوزان والقوائم تقديرية وتُضبط بعد التشغيل الفعلي.
"""
import math
import re
from datetime import datetime, timezone

# نوع الحدث: (الاسم العربي، الحدّة الأساسية 0-3، الكلمات)
CATEGORIES = {
    "military": ("عسكري", 2, ["missile", "airstrike", "air strike", "drone strike", "attack", "invasion", "invade",
                              "troops", "shelling", "bombing", "offensive", "war ", " war", "military strike",
                              "هجوم", "غارة", "صاروخ", "حرب", "قصف", "اجتياح"]),
    "nuclear": ("نووي", 3, ["nuclear", "uranium", "enrichment", "atomic", "نووي", "تخصيب"]),
    "energy": ("طاقة", 2, ["hormuz", "pipeline", "opec", "oil supply", "refinery", "oil facility", "tanker",
                           "red sea", "shipping lane", "blockade", "oil output", "gas supply",
                           "مضيق", "أوبك", "خط أنابيب", "ناقلة", "حصار"]),
    "sanctions": ("عقوبات", 1, ["sanction", "embargo", "export ban", "asset freeze", "عقوبات", "حظر"]),
    "trade": ("تجارة", 1, ["tariff", "trade war", "export control", "retaliatory dut", "rare earth",
                           "رسوم جمركية", "حرب تجارية"]),
    "unrest": ("اضطراب", 1, ["coup", "protest", "unrest", "assassinat", "martial law", "state of emergency",
                             "انقلاب", "احتجاجات", "اغتيال"]),
}
# كلمات ترفع الحدّة +1 / كلمات التهدئة تخفضها
INTENSIFIERS = ["escalat", "killed", "dead", "casualt", "retaliat", "emergency", "explosion", "closure", "closes",
                "shut", "seize", "warship", "تصعيد", "قتلى", "رد انتقامي", "طوارئ"]
DEESCALATORS = ["ceasefire", "cease-fire", "truce", "peace", "de-escalat", "talks", "agree", "eases", "ease ",
                "deal", "withdraw", "هدنة", "وقف إطلاق", "تهدئة", "محادثات", "اتفاق"]
REGIONS = {
    "الشرق الأوسط": ["iran", "israel", "gaza", "hezbollah", "lebanon", "yemen", "houthi", "syria", "iraq", "saudi",
                     "gulf", "hormuz", "red sea", "إيران", "إسرائيل", "غزة", "لبنان", "اليمن", "الخليج", "العراق"],
    "روسيا/أوكرانيا": ["russia", "ukraine", "kremlin", "putin", "nato", "روسيا", "أوكرانيا"],
    "الصين/تايوان": ["china", "chinese", "taiwan", "beijing", "south china sea", "الصين", "تايوان"],
    "كوريا": ["north korea", "pyongyang", "korea", "كوريا"],
    "الهند/باكستان": ["india", "pakistan", "kashmir"],
}
DECAY_HOURS = 6.0       # نصف عمر تقريبي لأثر العنوان
MARKET_CONFIRMS = 5.5   # درجة score_geopolitics التي تعني إشارتين فأكثر من السوق
STOP = set("the a an of in on to for and with as at by from after over amid says say new us is are was be".split())


def _has(text, words):
    return any(w in text for w in words)


def classify(title):
    """يُرجع dict(cats, regions, severity, deesc) أو None إن لم يكن العنوان جيوسياسياً."""
    t = " " + title.lower() + " "
    cats = [k for k, (_, _, words) in CATEGORIES.items() if _has(t, words)]
    if not cats:
        return None
    sev = max(CATEGORIES[k][1] for k in cats)
    if _has(t, INTENSIFIERS):
        sev += 1
    deesc = _has(t, DEESCALATORS)
    if deesc:
        sev -= 1
    regions = [r for r, words in REGIONS.items() if _has(t, words)]
    return {"cats": cats, "regions": regions, "severity": max(0, min(4, sev)), "deesc": deesc}


def split_source(title):
    """عناوين Google News تنتهي عادةً بـ « - المصدر »."""
    if " - " in title:
        head, src = title.rsplit(" - ", 1)
        return head.strip(), src.strip().lower()
    return title.strip(), ""


def _tokens(s):
    return {w for w in re.findall(r"[a-z؀-ۿ]{4,}", s.lower()) if w not in STOP}


def cluster(items, now):
    """items: [(وقت، عنوان)] ← قصص مدموجة، كل قصة: أعلى حدّة وعدد مصادر مستقلة وأحدث وقت."""
    stories = []
    for when, raw in sorted(items, reverse=True):
        title, src = split_source(raw)
        info = classify(title)
        if not info:
            continue
        tk = _tokens(title)
        for s in stories:
            inter = len(tk & s["tokens"])
            if tk and s["tokens"] and inter / len(tk | s["tokens"]) >= 0.4:
                s["sources"].add(src or title)
                s["severity"] = max(s["severity"], info["severity"])
                s["deesc"] = s["deesc"] and info["deesc"]
                s["cats"] |= set(info["cats"])
                s["regions"] |= set(info["regions"])
                break
        else:
            stories.append({"title": title, "when": when, "tokens": tk, "sources": {src or title},
                            "severity": info["severity"], "deesc": info["deesc"],
                            "cats": set(info["cats"]), "regions": set(info["regions"])})
    for s in stories:
        age = max(0.0, (now - s["when"]).total_seconds() / 3600)
        breadth = 1 + 0.25 * min(len(s["sources"]) - 1, 4)
        s["value"] = s["severity"] * breadth * math.exp(-age / DECAY_HOURS * math.log(2))
    stories.sort(key=lambda s: s["value"], reverse=True)
    return stories


def score_geo_news(items, market_geo_score, now):
    """يُرجع (درجة 0-10 أو None، ملاحظة، تفاصيل). items=None تعني فشل الجلب فيُستبعد المكوّن."""
    if items is None:
        return None, "عناوين الجيوسياسة غير متوفرة", {}
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    stories = cluster(items, now)
    live = [s for s in stories if s["severity"] >= 1]
    if not live:
        un = market_geo_score is not None and market_geo_score >= MARKET_CONFIRMS
        note = "لا قصص جيوسياسية بارزة في آخر 24 ساعة" + (" — حركة سوق جيوسياسية الطابع بلا عناوين مطابقة" if un else "")
        return 1.0, note, {"stories": 0, "confirmed": False, "unexplained_market_move": un}
    top = live[0]["value"] + 0.3 * sum(s["value"] for s in live[1:3])
    text_score = max(0.0, min(10.0, top * 1.6))
    confirmed = market_geo_score is not None and market_geo_score >= MARKET_CONFIRMS
    score, verdict = text_score, ""
    if market_geo_score is None:
        verdict = "تعذّر التحقق من السوق"
    elif confirmed:
        verdict = "السوق يؤكد (حركة ذهب/نفط/VIX)"
        score = min(10.0, text_score * 1.1)
    elif text_score >= 4:
        score = text_score * 0.7
        verdict = "السوق لم يؤكد بعد"
    if live[0]["deesc"]:
        verdict = (verdict + "؛ " if verdict else "") + "أبرز خبر يميل للتهدئة"
    first = live[0]
    cats = "، ".join(CATEGORIES[k][0] for k in sorted(first["cats"]))
    reg = "، ".join(sorted(first["regions"])) or "منطقة غير محددة"
    note = f"{cats} — {reg} — {len(first['sources'])} مصدر؛ {verdict}"
    unexplained = (market_geo_score is not None and market_geo_score >= MARKET_CONFIRMS and text_score < 3)
    if unexplained:
        note += " — حركة سوق جيوسياسية الطابع بلا عناوين مطابقة"
    detail = {"stories": len(live), "text_score": round(text_score, 1), "confirmed": confirmed,
              "unexplained_market_move": unexplained,
              "top": [{"title": s["title"][:110], "severity": s["severity"], "sources": len(s["sources"]),
                       "regions": sorted(s["regions"]), "cats": sorted(s["cats"]), "deesc": s["deesc"]}
                      for s in live[:3]]}
    return round(max(0.0, min(10.0, score)), 1), note, detail
