"""
مِرصاد — تمركز المؤسسات الأسبوعي (تقرير CFTC، صيغة TFF للعقود الآجلة والخيارات معاً) لعقد E-mini S&P 500.

- المصدر: https://www.cftc.gov/dea/newcot/FinComWk.txt (يصدر الجمعة 3:30 م نيويورك ببيانات الثلاثاء السابق).
- ترتيب الأعمدة من وثيقة CFTC الرسمية (cotvariablestfm): الفائدة المفتوحة، ثم الوسطاء، مديرو الأصول، الصناديق ذات الرافعة...
- البطاقة في الواجهة: حكم واحد (صعودي/هبوطي/محايد) بسببين:
    1) الصناديق ذات الرافعة: التغيّر الأسبوعي في صافي مراكزها (طويل − قصير) من أعمدة التغيّر في الملف نفسه.
    2) مديرو الأصول: اتجاه صافي مراكزهم خلال 4 أسابيع، من تاريخ يتراكم في state.json (cot_hist؛ لا يوجد تاريخ كافٍ بعد = «يتجمّع»).
- الحدود (SIGNAL_PCT) تقديرية وغير معايَرة، كبقية أوزان مِرصاد؛ وبطاقة COT خلفية أسبوعية لا إشارة دخول.
"""
import csv
import io
import urllib.request
from datetime import datetime

COMBINED_URL = "https://www.cftc.gov/dea/newcot/FinComWk.txt"
ES_CODE = "13874A"                 # E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE (ليس الـ Micro ولا Consolidated)
UA = {"User-Agent": "Mozilla/5.0 (mirsad-collector)"}

# فهارس الأعمدة (من 0) حسب وثيقة CFTC
I_CODE, I_YYMMDD, I_DATE = 3, 1, 2
I_OI = 7
I_AM_L, I_AM_S = 11, 12
I_LEV_L, I_LEV_S = 14, 15
I_D_OI = 24
I_D_AM_L, I_D_AM_S = 28, 29
I_D_LEV_L, I_D_LEV_S = 31, 32
I_FLAG = 86                        # FutOnly_or_Combined (إن وُجد)
MIN_COLS = 33

SIGNAL_PCT = 0.2                   # تغيّر صافي الصناديق بأقل من 0.2% من الفائدة المفتوحة = «ثابت» (تقديري)
AM_TREND_PCT = 0.5                 # تغيّر صافي مديري الأصول خلال 4 أسابيع بأقل من 0.5% من الفائدة المفتوحة = «ثابت» (تقديري)
AM_WEEKS = 4                       # عدد الأسابيع للاتجاه الأكبر
HIST_KEEP = 12                     # أقصى عدد أسابيع محفوظة


def _int(x):
    return int(str(x).strip().replace(",", ""))


def _date(row):
    """تاريخ التقرير (الثلاثاء) بصيغة ISO من عمود التاريخ، ثم من YYMMDD إن تعذّر."""
    raw = row[I_DATE].strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return datetime.strptime(row[I_YYMMDD].strip(), "%y%m%d").date().isoformat()


def parse_row(row):
    """صف E-mini من ملف TFF الموحّد ← قاموس. يرفع ValueError عند أي أرقام غير منطقية أو صيغة غير موحّدة."""
    if len(row) < MIN_COLS:
        raise ValueError(f"صف COT قصير ({len(row)} عموداً): الصيغة تغيّرت على الأرجح")
    if len(row) > I_FLAG and row[I_FLAG].strip().lower().replace(" ", "").startswith(("futonly", "futuresonly")):
        raise ValueError("ملف COT بصيغة العقود الآجلة فقط وليس الموحّدة")
    oi = _int(row[I_OI])
    vals = {k: _int(row[i]) for k, i in (("am_long", I_AM_L), ("am_short", I_AM_S), ("lev_long", I_LEV_L), ("lev_short", I_LEV_S))}
    chg = {k: _int(row[i]) for k, i in (("am_dlong", I_D_AM_L), ("am_dshort", I_D_AM_S), ("lev_dlong", I_D_LEV_L), ("lev_dshort", I_D_LEV_S))}
    if oi <= 0 or any(v < 0 or v > oi for v in vals.values()):
        raise ValueError("أرقام COT غير منطقية: الصيغة تغيّرت على الأرجح")
    if any(abs(v) > oi for v in chg.values()):
        raise ValueError("تغيّرات COT غير منطقية: الصيغة تغيّرت على الأرجح")
    out = {"date": _date(row), "oi": oi, "combined": True, **vals, **chg}
    out["net_pct"] = (out["lev_long"] - out["lev_short"]) / oi * 100       # يبقى اسم الحقل القديم لتوافق build_info
    return out


def parse_text(text):
    """يجد صف الإي ميني بالرمز 13874A (لا بالاسم: اسم الـ Micro يحوي اسمه)."""
    for row in csv.reader(io.StringIO(text)):
        if len(row) > I_CODE and row[I_CODE].strip() == ES_CODE:
            return parse_row(row)
    raise ValueError("لم يُعثر على عقد E-mini S&P 500 (13874A) في ملف COT الموحّد")


def fetch(now=None):
    req = urllib.request.Request(COMBINED_URL, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        text = r.read().decode("utf-8", errors="replace")
    return parse_text(text)


# ───────────────────────── الحكم والبطاقة ─────────────────────────

def _net(cot, who):
    return cot[who + "_long"] - cot[who + "_short"]


def _dir(x, thr):
    return "up" if x > thr else "down" if x < -thr else "flat"


def update_history(hist, cot):
    """يضيف أسبوع التقرير إلى التاريخ (مرة واحدة لكل تاريخ) ويُبقي آخر HIST_KEEP أسبوعاً."""
    hist = [h for h in (hist or []) if isinstance(h, dict) and h.get("date")]
    if cot and not any(h["date"] == cot["date"] for h in hist):
        hist.append({"date": cot["date"], "oi": cot["oi"], "am_net": _net(cot, "am"), "lev_net": _net(cot, "lev")})
    hist.sort(key=lambda h: h["date"])
    return hist[-HIST_KEEP:]


def card(cot, prev_card=None):
    """بنية البطاقة للواجهة: لا أرقام للعرض، فقط الاتجاهات. None إن لم يصل التقرير."""
    hist = (cot or {}).get("hist") or (prev_card or {}).get("hist") or []
    need = ("date", "oi", "lev_long", "lev_short", "lev_dlong", "lev_dshort", "am_long", "am_short")
    if cot and not all(k in cot for k in need):
        cot = None                       # شكل قديم أو بيانات تجريبية بلا أعمدة التغيّر: لا بطاقة مخترَعة
    if not cot:
        # لا تقرير جديد: تبقى آخر بطاقة صالحة للعرض مع وسم القِدَم تتولاه الواجهة بتاريخ التقرير
        return prev_card if prev_card and prev_card.get("verdict") else None
    hist = update_history(hist, cot)
    oi = cot["oi"]
    lev_d = (cot["lev_dlong"] - cot["lev_dshort"]) / oi * 100
    lev_dir = _dir(lev_d, SIGNAL_PCT)
    am_dir, am_basis = None, f"يتجمّع التاريخ ({max(len(hist) - 1, 0)} من {AM_WEEKS} أسابيع)"
    if len(hist) > AM_WEEKS:
        base = hist[-1 - AM_WEEKS]
        am_d = (hist[-1]["am_net"] - base["am_net"]) / oi * 100
        am_dir, am_basis = _dir(am_d, AM_TREND_PCT), f"خلال {AM_WEEKS} أسابيع"
    if am_dir is None:
        verdict, agree = lev_dir, None
    elif lev_dir == am_dir:
        verdict, agree = lev_dir, True
    else:
        verdict, agree = "flat", False
    return {"date": cot["date"], "verdict": verdict, "agree": agree, "partial": am_dir is None,
            "lev": lev_dir, "am": am_dir, "am_basis": am_basis, "hist": hist,
            "source": "CFTC TFF (العقود الآجلة والخيارات موحّدة)"}
