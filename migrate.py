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
- آمن عند التكرار: بعد الترحيل schema_version=2 فيُتخطى.
- النسخة الاحتياطية (v0.19): تُكتب قبل أول ترحيل في مجلد backups/ (backups/state.json.bak-v<القديم>) ويُتحقق من قراءتها ومطابقتها للأصل،
  ويحفظها workflow في المستودع نفسه (git add backups/) فتبقى بعد انتهاء GitHub Actions ويمكن استعادتها من أي جهاز.
  الاستعادة: python migrate.py rollback [مسار النسخة] (تحفظ الحالة الحالية أولاً في backups/ ولا تحذف شيئاً).
"""
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone

import actuals
import indicators
from verification import ACCEPTED_TIERS

SCHEMA_VERSION = 2
BACKUP_DIR = "backups"
BACKUP_KEEP = 5
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
    if backup_path and state.get("actuals"):
        write_backup(state, backup_path)               # يرفع استثناءً إن لم تتطابق النسخة: لا ترحيل بلا نسخة موثوقة
        rep["backup"] = backup_path
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


def backup_path_for(path, ver):
    """مسار نسخة الترحيل الدائمة: backups/ بجانب ملف الحالة (يُضاف إلى git في workflow)."""
    d = os.path.join(os.path.dirname(os.path.abspath(path)), BACKUP_DIR)
    return os.path.join(d, f"{os.path.basename(path)}.bak-v{ver}")


def write_backup(state, backup_path):
    """يكتب النسخة ثم يقرأها ويقارنها بالأصل؛ يرفع RuntimeError إن لم تتطابق (لا ترحيل بنسخة لم نتأكد منها). لا يستبدل نسخة أقدم موجودة."""
    if os.path.exists(backup_path):
        return False
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    tmp = backup_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    with open(tmp, encoding="utf-8") as f:
        if json.load(f) != json.loads(json.dumps(state, ensure_ascii=False)):
            os.remove(tmp)
            raise RuntimeError("النسخة الاحتياطية لا تطابق الأصل")
    os.replace(tmp, backup_path)
    files = sorted(x for x in os.listdir(os.path.dirname(backup_path)) if ".bak-v" in x)
    for old in files[:-BACKUP_KEEP]:
        os.remove(os.path.join(os.path.dirname(backup_path), old))
    return True


def load_and_migrate(path, now=None):
    """يقرأ state.json ويرحّله بعد نسخة احتياطية دائمة في backups/ (بجانب الملف)؛ لا يكتب الملف الأصلي (الكتابة عند حفظ التشغيل).
    فشل النسخة الاحتياطية = لا ترحيل (تبقى الحالة كما هي ويُرفع الاستثناء ليُعرض في السجل)."""
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:  # noqa: BLE001
        return {}, None
    ver = s.get("schema_version", 1)
    bp = backup_path_for(path, ver)
    rep = migrate(s, now, backup_path=bp)
    if rep and rep.get("backup"):
        s.setdefault("migration", {})["backup"] = os.path.join(BACKUP_DIR, os.path.basename(bp))
    return s, rep


def latest_backup(path):
    d = os.path.join(os.path.dirname(os.path.abspath(path)), BACKUP_DIR)
    files = sorted(x for x in (os.listdir(d) if os.path.isdir(d) else []) if ".bak-v" in x and not x.endswith(".tmp"))
    return os.path.join(d, files[0]) if files else None        # الأقدم رقماً (v1) = الحالة قبل أول ترحيل


def rollback(path, backup_path=None):
    """يستعيد state.json من نسخة الترحيل: يتحقق أنها JSON سليم، يحفظ الحالة الحالية أولاً في backups/ (state.json.pre-rollback-<وقت>)
    ثم يكتب النسخة مكان الملف ذرّياً. يعيد {restored_from, saved_current, schema_version}."""
    bp = backup_path or latest_backup(path)
    if not bp or not os.path.exists(bp):
        raise FileNotFoundError("لا توجد نسخة احتياطية للاستعادة")
    with open(bp, encoding="utf-8") as f:
        data = json.load(f)
    saved = None
    if os.path.exists(path):
        d = os.path.join(os.path.dirname(os.path.abspath(path)), BACKUP_DIR)
        os.makedirs(d, exist_ok=True)
        saved = os.path.join(d, f"{os.path.basename(path)}.pre-rollback-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
        shutil.copyfile(path, saved)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return {"restored_from": bp, "saved_current": saved, "schema_version": data.get("schema_version", 1)}


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "rollback":
        r_ = rollback("state.json", sys.argv[2] if len(sys.argv) > 2 else None)
        print(f"استُعيدت الحالة من {r_['restored_from']} (الإصدار v{r_['schema_version']}). الحالة السابقة محفوظة في {r_['saved_current']}")
    else:
        print("الاستعمال: python migrate.py rollback [backups/state.json.bak-v1]")
