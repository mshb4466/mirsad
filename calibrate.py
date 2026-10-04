#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
معايرة مِرصاد: هل المخاطرة العالية صحبتها حركة أكبر فعلاً في ES؟

يقرأ history.csv (يتراكم تلقائياً مع كل تقرير قبل الافتتاح) ويقارن درجة المخاطرة
بمدى حركة ES الفعلي في اليوم نفسه (الأعلى - الأدنى كنسبة من الإغلاق).

التشغيل: python calibrate.py
"""
import csv
import sys

import collector as c

BUCKETS = [("منخفضة 0-3", 0, 3), ("متوسطة 4-6", 4, 6), ("عالية 7-8", 7, 8), ("قصوى 9-10", 9, 10)]


def load(path="history.csv"):
    with open(path, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("outcome_range_pct")]
    return [(int(r["score"]), float(r["outcome_range_pct"])) for r in rows]


def summarize(data):
    lines = [f"عدد الأيام المكتملة: {len(data)}"]
    if len(data) < 20:
        lines.append("⚠ العينة صغيرة (أقل من 20 يوماً): لا تبنِ استنتاجاً عليها بعد.")
    for name, lo, hi in BUCKETS:
        g = [r for s, r in data if lo <= s <= hi]
        lines.append(f"{name}: " + (f"{len(g)} أيام، متوسط مدى ES {sum(g) / len(g):.2f}%" if g else "لا أيام"))
    if len(data) >= 5:
        r = c.pearson([float(s) for s, _ in data], [x for _, x in data])
        if r is not None:
            lines.append(f"الارتباط بين الدرجة والمدى الفعلي: {r:+.2f}  (الأقرب إلى +1 أفضل)")
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        d = load(sys.argv[1] if len(sys.argv) > 1 else "history.csv")
    except FileNotFoundError:
        print("لا يوجد history.csv بعد: يُنشأ بعد أول تقرير قبل الافتتاح.")
        sys.exit(0)
    print(summarize(d) if d else "لا أيام مكتملة بعد: تُملأ النتيجة الفعلية في اليوم التالي.")
