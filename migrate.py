# -*- coding: utf-8 -*-
"""
مِرصاد — ترحيل حالة التشغيل (state.json) بين الإصدارات (v0.18.1، schema_version = 2).

لماذا: v0.17 كانت تكتب status=verified لرقم قد يكون مأخوذاً من عنوان خبر ولا تحفظ trust؛ واسترجاعه كما هو في الإصدارات
اللاحقة يتجاوز الحجر فيظهر الرقم موثّقاً. ومعرّفات الأحداث القديمة كانت تدمج مؤشرين يشتركان بسلسلة واحدة (Core PCE شهري/سنوي).

القواعد (لا تخمين أبداً):
- أي سجل فيه رقم بلا trust مقبول (رسمي/ثانوي) يُحجَر: trust=news وstatus=needs_check، فيُعاد التحقق منه من مصدر مقبول
  ولا يدخل Surprise ولا التحليل ولا تنبيه الصدور حتى ذلك. كلمة verified القديمة وحدها ليست دليلاً.
- معرّف قديم لمفتاح يشترك فيه أكثر من نوع قياس (pcelfe)، أو لـ GDP (فترة الربع القديمة خاطئة): الرقم لا يُنسب لأي مؤشر → يُحجَر.
- معرّف قديم غير ملتبس: يُعاد تسميته بالصيغة الجديدة ويحتفظ بقيمته وحالته الموثّقة.
- التاريخ لا يُمحى: القيمة القديمة تُضاف إلى history وlegacy مع السبب والوقت.
- آمن عند التكرار: بعد الترحيل schema_version=2 فيُتخطى. نسخة احتياطية تُكتب قبل أول ترحيل (state.json.bak-v<القديم>).
"""
import json
import os
import re
import shutil
from datetime import datetime, timezone

import actuals
import indicators
from verification import ACCEPTED_TIERS

SCHEMA_VERSION = 2
_OLD_ID = re.compile(r"^US\|([a-z_0-9]+)\|(\d{4}-\d{2}|w\d{4}-\d{2}-\d{2})\|(\d{4}-\d{2}-\d{2})$")


def _colliding_keys():
    tr = {}
    for _, key, _sid, t, _rule, _label in indicators.SPECS:
        tr.setdefault(key, set()).add(t)
    return {k for k, v in tr.items() if len(v) > 1}


def _parse(t):
    try:
        d = datetime.fromisoformat(t)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _quarantine(rec, reason, now_iso, from_ver):
    if rec.get("actual"):
        entry = {"value": rec["actual"], "trust": rec.get("trust") or "", "status": rec.get("status", ""), "until": now_iso, "reason": reason}
        rec.setdefault("history", []).append(dict(entry))
        rec.setdefault("legacy", []).append(entry)
        rec["trust"], rec["status"] = "news", "needs_check"
        rec["note"] = reason
        rec["source"] = rec.get("source") or "حالة قديمة بلا مصدر موثّق"
    rec["migrated"] = {"from": from_ver, "at": now_iso, "reason": reason}


def migrate(state, now=None, backup_path=None):
    """يرحّل state في مكانه. يعيد تقريراً {from, to, renamed, quarantined, kept, skipped}. backup_path: ملف يُكتب قبل أي تغيير."""
    now_iso = (now or datetime.now(timezone.utc)).isoformat()
    ver = state.get("schema_version", 1)
    rep = {"from": ver, "to": SCHEMA_VERSION, "renamed": 0, "quarantined": 0, "kept": 0, "skipped": ver >= SCHEMA_VERSION}
    if ver >= SCHEMA_VERSION:
        return rep
    if backup_path and state.get("actuals") and not os.path.exists(backup_path):
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    coll = _colliding_keys()
    store = state.get("actuals") or {}
    out = {}
    for eid, rec in list(store.items()):
        new_id, reason = eid, None
        m = _OLD_ID.match(eid)
        if m:
            key = m.group(1)
            t = _parse(rec.get("time", ""))
            if t and rec.get("title"):
                new_id = actuals.event_id({"title": rec["title"], "time": t})
            if key in coll:
                reason = "معرّف قديم دمج الشهري والسنوي لسلسلة واحدة: لا يمكن نسبة الرقم لأي منهما، يُعاد جلبه"
            elif key == "gdp":
                reason = "حُسبت فترة الربع بقاعدة قديمة خاطئة: يُعاد التحقق من الربع والمرحلة"
            if new_id != eid:
                rep["renamed"] += 1
        if reason is None and rec.get("actual") and (rec.get("trust") not in ACCEPTED_TIERS):
            reason = "رقم محفوظ من إصدار قديم بلا مصدر موثّق (قد يكون من عنوان خبر): يُعاد التحقق منه"
        elif reason is None and rec.get("actual") and rec.get("status") == "verified":
            rec["status"] = actuals.verified_status(rec["trust"])      # trust محفوظ = أُنتج بعد إضافة التتبّع؛ الحالة تُوحَّد فقط
        if reason:
            _quarantine(rec, reason, now_iso, ver)
            rep["quarantined"] += 1
        elif rec.get("actual"):
            rep["kept"] += 1
        if new_id in out:                                   # تصادم بعد إعادة التسمية: نحتفظ بالأوثق ونضم التاريخ
            a, b = out[new_id], rec
            keep, other = (a, b) if actuals.TIER_RANK.get(a.get("trust") or "news", 0) >= actuals.TIER_RANK.get(b.get("trust") or "news", 0) else (b, a)
            keep.setdefault("history", []).extend(other.get("history", []) + ([{"value": other["actual"], "trust": other.get("trust", ""), "until": now_iso,
                                                                                  "reason": "سجل مكرر عند الترحيل"}] if other.get("actual") else []))
            out[new_id] = keep
        else:
            out[new_id] = rec
    state["actuals"] = out
    for x in state.get("actuals_log", []):                  # سجل التدقيق القديم: لا نُبقي «مطابقة» لرقم لم يُتحقق منه
        ok = x.get("tier") in ACCEPTED_TIERS and x.get("value") and x.get("period")
        x["period_check"] = "مطابقة فترة التقرير" if ok else ("غير مُتحقَّق" if x.get("value") else "لا رقم")
        x["match"] = x["period_check"]
        x.setdefault("bulletin_check", "لم تُقارَن بنشرة الإصدار" if x.get("value") else "")
    state["schema_version"] = SCHEMA_VERSION
    state["migration"] = {"from": ver, "at": now_iso, "renamed": rep["renamed"], "quarantined": rep["quarantined"], "kept": rep["kept"]}
    return rep


def load_and_migrate(path, now=None):
    """يقرأ state.json ويرحّله مع نسخة احتياطية بجانبه؛ لا يكتب الملف الأصلي (الكتابة عند حفظ التشغيل)."""
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:  # noqa: BLE001
        return {}, None
    rep = migrate(s, now, backup_path=f"{path}.bak-v{s.get('schema_version', 1)}")
    return s, rep
