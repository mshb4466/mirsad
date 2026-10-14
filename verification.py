# -*- coding: utf-8 -*-
"""
مِرصاد — شرط التحقق الموحّد (v0.18.1). كل حساب أو واجهة أو تنبيه أو درجة ثقة يسأل هذه الدالة وحدها: هل هذا رقم Actual موثَّق؟

لا تكفي كلمة «verified» ولا وجود قيمة. الشروط الثلاثة معاً:
1) قيمة صالحة يفهمها المحلّل الموحّد (values) — فارغة أو نصاً غير مفهوم ترفض.
2) مصدر مقبول: رسمي (BLS/TreasuryDirect) أو ثانوي موثوق (FRED). الخبر والمجهول لا يُقبلان.
3) حالة تحقق صحيحة: verified_official/verified_secondary، أو revised بمصدر مقبول.
وحدة بلا تبعيات على بقية المشروع كي تستوردها كل الوحدات بلا دورات استيراد.
"""
import values

TIER_RANK = {"news": 0, "secondary": 1, "official": 2}
ACCEPTED_TIERS = ("official", "secondary")
VERIFIED_STATUSES = ("verified_official", "verified_secondary")
TIER_STATUS = {"official": "verified_official", "secondary": "verified_secondary", "news": "needs_check"}


def tier_of(e):
    """درجة موثوقية مصدر الرقم؛ الغائب أو المجهول يُعامل كخبر (لا يُتحقق منه أبداً)."""
    t = e.get("actual_src") if e.get("actual_src") is not None else e.get("trust")
    return t if t in TIER_RANK else "news"


def valid_value(v):
    """قيمة قابلة للتحليل (مفردة أو مركّبة عائد|تغطية)."""
    return values.parse(v) is not None or values.parse_composite(v) is not None


def status_ok(e):
    st = e.get("status")
    return st in VERIFIED_STATUSES or (st == "revised" and tier_of(e) in ACCEPTED_TIERS)


def is_verified(e):
    """الشرط الموحّد: قيمة صالحة + مصدر مقبول + حالة تحقق صحيحة (e حدث أو سجل محفوظ)."""
    val = e.get("actual")
    return bool(val) and valid_value(val) and tier_of(e) in ACCEPTED_TIERS and status_ok(e)


def verified_status(tier):
    return TIER_STATUS.get(tier, "needs_check")
