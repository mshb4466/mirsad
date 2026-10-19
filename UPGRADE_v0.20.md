# ترقية مرصاد إلى v0.20.0

1. فُكّ الـ ZIP وارفع **محتوى** المجلد فوق المستودع (مع `.github` و`docs` و`icons` وملفات `gamma.py` و`tests_gamma.py`). لا تحذف `state.json` ولا `history.csv`.
2. ملفان في `.github/workflows`: `mirsad.yml` (محدَّث: ينسخ `gamma/latest.json` إلى `docs/gamma.json`) و**الجديد** `gamma.yml`. إن تعذّر رفع المجلد المخفي فالصق محتوى `workflow-mirsad.yml` و`workflow-gamma.yml` يدوياً.
3. **فحص CBOE أولاً:** Actions ← gamma ← Run workflow ← mode = `probe` (وlet telegram = true إن أردت الصورة على تيليجرام). تفتح نتيجة التشغيل ← Artifacts ← `gamma-probe` فيه `probe.json` و`probe.png`. أرسل لي `probe.json` (لا يحوي أسراراً).
4. بعد أي تشغيل لـ mirsad (كل 15 دقيقة في أيام التداول) يظهر ملف جاما في تبويب «جاما».
5. صحة الأسرار: يستعمل `TELEGRAM_TOKEN` و`TELEGRAM_CHAT_ID` الموجودين أصلاً. لا مفاتيح جديدة.

## ما لا يُضمن
- الوصول إلى CBOE وصيغة الملف لم يُتحقق منهما من هنا (الشبكة محجوبة)، والتحليل مبني على ما رأيته من الملف (`timestamp` و`data.options[].gamma/open_interest`). إن اختلف حقل السعر `current_price` سيفشل الجمع برسالة واضحة في `probe.json`.
- جدولة GitHub قد تتأخر ساعات؛ لذلك 8 مواعيد قبل وبعد الافتتاح وقاعدة «أول لقطة صالحة قبل 09:30 تفوز». لا ضمان لوجود لقطة قبل الافتتاح كل يوم.
- قبل الافتتاح قد تكون greeks قديمة؛ اللقطة تُرفض إن كانت كل قيم gamma صفرية، وإلا تُعرض بوقتها الفعلي وعمرها.
- ختم CBOE مفترض بتوقيت نيويورك؛ `probe.json` يعرض `timestamp_raw` للتأكد.
