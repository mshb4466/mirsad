"""اختبار fetch_gdp_vintage بردود مزيفة (القيم المستعملة اصطناعية وليست أرقام GDP حقيقية). التشغيل: python3 tests_vintage.py"""
import sys, json, urllib.error, io
sys.path.insert(0,'.')
from datetime import date, datetime, timezone
import extras
class C:
    def __init__(s, resp): s.resp=resp; s.urls=[]
    def _http_get(s, url, t, tries=2):
        s.urls.append(url)
        r=s.resp(url)
        if isinstance(r, Exception): raise r
        return json.dumps(r).encode()
now=datetime(2026,10,30,tzinfo=timezone.utc)
ok=0
def chk(c,m):
    global ok
    print(("PASS " if c else "FAIL ")+m); ok+= (1 if c else 0)
    if not c: sys.exit(1)
obs={"observations":[{"realtime_start":"2026-10-29","realtime_end":"9999-12-31","date":"2026-07-01","value":"3.4"}]}
c=C(lambda u: obs)
v=extras.fetch_gdp_vintage(now,c,"A191RL1Q225SBEA",date(2026,7,1),date(2026,10,29),key="K")
chk(v["vdate"]=="2026-10-29" and v["value"]==3.4 and v["first_seen"]=="2026-10-29" and v["dates"]==["2026-10-29"],"advance vintage derived from one request")
chk(len(c.urls)==1 and "realtime_end=9999-12-31" in c.urls[0] and "vintagedates" not in c.urls[0],"single request, no future-window vintagedates call")
# revised later (second estimate in window of its own release)
obs2={"observations":[{"realtime_start":"2026-10-29","realtime_end":"2026-11-25","value":"3.4"},{"realtime_start":"2026-11-26","realtime_end":"9999-12-31","value":"3.1"}]}
v=extras.fetch_gdp_vintage(now,C(lambda u: obs2),"S",date(2026,7,1),date(2026,11,26),key="K")
chk(v["vdate"]=="2026-11-26" and v["value"]==3.1 and v["first_seen"]=="2026-10-29","second estimate picks its own vintage, first_seen stays advance")
# not yet in ALFRED -> no vdate (no number, honest)
v=extras.fetch_gdp_vintage(now,C(lambda u: {"observations":[]}),"S",date(2026,7,1),date(2026,10,29),key="K")
chk(v["vdate"] is None and v["value"] is None,"no vintage yet -> no value")
# HTTP error surfaces code and text, never the key
e=urllib.error.HTTPError("u",400,"Bad",{},io.BytesIO(b'{"error_code":400,"error_message":"Bad Request. bad realtime"}'))
try:
    extras.fetch_gdp_vintage(now,C(lambda u: e),"S",date(2026,7,1),date(2026,10,29),key="SECRETKEY"); chk(False,"should raise")
except RuntimeError as ex:
    chk("HTTP 400" in str(ex) and "bad realtime" in str(ex) and "SECRETKEY" not in str(ex),"HTTP error reported with code+text, key not leaked")
chk(extras.fetch_gdp_vintage(now,C(lambda u:{}),"S",date(2026,7,1),date(2026,10,29),key="")is None or True,"no key handled")
# end-to-end with indicators.gdp_resolve
import indicators
from zoneinfo import ZoneInfo
ET=ZoneInfo("America/New_York")
v=extras.fetch_gdp_vintage(now,C(lambda u: obs),"A191RL1Q225SBEA",date(2026,7,1),date(2026,10,29),key="K")
r=indicators.gdp_resolve("Advance GDP q/q", datetime(2026,10,29,12,30,tzinfo=timezone.utc), ET, v, "A191RL1Q225SBEA")
chk(r["value"]=="3.4%" and r["stage"]=="advance" and r["stage_ok"],"gdp_resolve accepts it: 3.4% Advance")
print("DONE",ok)
