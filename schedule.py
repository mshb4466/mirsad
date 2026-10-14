# -*- coding: utf-8 -*-
"""
مِرصاد — جدول الإصدارات الأمريكية بتوقيت نيويورك (يراعي التوقيت الصيفي) وتحويلها إلى UTC/بغداد.

حقيقة تقنية: cron في GitHub Actions بتوقيت UTC فقط ولا يعرف التوقيت الصيفي. بغداد ثابتة UTC+3.
إصدارات 8:30 صباحاً بتوقيت نيويورك = 12:30 UTC صيفاً (15:30 بغداد) و13:30 UTC شتاءً (16:30 بغداد).
لذلك نجدول فحصَي ما بعد الإصدار عند الدقيقة 31 في الساعتين 12 و13 UTC، ويتجاهل المشغّل الفحص غير المناسب لعدم وجود حدث.
التوقيت الفعلي لكل حدث يأتي من حقل وقته في التقويم (مطلق UTC)، لا من افتراض ثابت.
"""
from datetime import date, datetime, time as dtime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001
    ET = timezone(timedelta(hours=-5))

BAGHDAD = timezone(timedelta(hours=3))
# إصدارات معتادة (ساعة:دقيقة بتوقيت نيويورك). المرجع جدول الناشر؛ هذه قيم افتراضية للتحقق والتوثيق لا لقرار التشغيل.
TYPICAL_ET = {"8:30": "CPI, PPI, NFP, claims, GDP, retail, PCE", "10:00": "ISM, JOLTS, sentiment"}
PREOPEN_BAGHDAD = "14:30"
POST_RELEASE_BAGHDAD_TARGET = "15:31"       # لإصدارات 8:30 صيفاً فقط؛ تصبح 16:31 شتاءً


def et_to_utc(d, hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(d, dtime(h, m), tzinfo=ET).astimezone(timezone.utc)


def to_baghdad(dt_utc):
    return dt_utc.astimezone(BAGHDAD)


def post_release_target(d, hhmm="8:30", after_min=1):
    """موعد فحص ما بعد الإصدار المستهدف (UTC) ومقابله ببغداد ليوم d."""
    t = et_to_utc(d, hhmm) + timedelta(minutes=after_min)
    return t, to_baghdad(t)


def cron_minutes(cron):
    """يفكّ cron بسيطاً 'M H * * D' إلى (دقائق، ساعات) أو None لغير الصيغة الثابتة."""
    f = cron.split()
    if len(f) != 5 or not f[0].isdigit() or not f[1].isdigit():
        return None
    return int(f[0]), int(f[1])
