# مقارنة الإصدار v0.22.1

## قاعدة التوافق

`gamma.py` ليس نسخة محرك جديدة: هو ملف المستخدم الأخير نفسه بايتاً ببايت. اختلافه عن ZIP v0.21.0 سببه تعديلات المستخدم التي قدمها لاحقاً، مثل السلال التقويمية والرجوع خمسة أيام. نسخة المرجع داخل reference للتدقيق.

مهمة جمع Gamma الأصلية محفوظة كما هي. الإضافة في gamma_map.py ومهمة مستقلة اختيارية، لا تكتب آخر لقطة الأصل ولا تغير قبول SPY أو حساب Flip.

## التغييرات مقارنة بـ ZIP v0.21.0

- `.github/workflows/gamma.yml`
- `.github/workflows/mirsad.yml`
- `README.md`
- `dashboard.py`
- `docs/index.html`
- `gamma.py`
- `index.html`
- `requirements.txt`
- `tests_gamma.py`
- `workflow-gamma.yml`
- `workflow-mirsad.yml`

## ملفات جديدة

- `.github/workflows/checks.yml`
- `.gitignore`
- `CHANGES_v0.22.1.md`
- `RELEASE_TESTS_v0.22.1.md`
- `UPGRADE_v0.22.1_AR.md`
- `docs/es-conversion.js`
- `docs/expiry-selection.js`
- `docs/gamma-heatmap.js`
- `docs/gamma-map.js`
- `docs/layout-v022.css`
- `docs/layout-v022.js`
- `es-conversion.js`
- `expiry-selection.js`
- `gamma-heatmap.js`
- `gamma-map.js`
- `gamma_map.py`
- `layout-v022.css`
- `layout-v022.js`
- `package.json`
- `reference/gamma_original.py`
- `reference/gamma_workflow_original.yml`
- `run_tests.py`
- `tests_expiry_selection.cjs`
- `tests_gamma_v022.py`
- `tests_ui_fixture.py`
- `tests_ui_v022.cjs`

## ملفات تشغيل الماكرو المطابقة للأصل

- `macro.py`
- `bias.py`
- `verdict.py`
- `runner.py`
- `collector.py`
- `actuals.py`
- `release_impact.py`
- `events_ctx.py`
- `safety.py`
- `quality.py`
- `health.py`
- `bls.py`
- `indicators.py`
- `auction.py`
- `backtest.py`

رقم الإصدار فقط تغيّر في dashboard.py. بيانات المستخدم الحالية ليست ضمن الحزمة ولا يُطلب حذفها عند الرفع. حُفظ backtest.json الأصلي. استُبعدت بيئة الاختبار والمكتبات وfixtures واللقطات الحية والأسرار من ملفات النشر.
