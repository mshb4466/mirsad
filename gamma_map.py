"""Optional, failure-isolated Gamma Price Map enrichment.

Reads gamma/latest.json; NEVER writes latest.json, archive or preopen.
The original gamma.py remains the only owner of collection and calculation.
"""
import argparse,copy,json,math,os
from pathlib import Path
from datetime import datetime,timedelta,timezone

def now_utc():return datetime.now(timezone.utc)

def zones(rows):
    """Observed contiguous strong-net strikes; no invented width or fixed price offsets.

    Strong = top quartile absolute nonzero net, separately signed connected
    components on the observed strike grid. A single strike has zero width.
    """
    rs = sorted((r for r in rows if math.isfinite(r["net"])), key=lambda r: r["k"])
    vals = sorted(abs(r["net"]) for r in rs if r["net"])
    if not vals:
        return []
    threshold = vals[int((len(vals)-1)*.75)]
    gaps = sorted(b["k"]-a["k"] for a,b in zip(rs,rs[1:]) if b["k"] > a["k"])
    grid = gaps[(len(gaps)-1)//2] if gaps else 0
    out = []
    active = None
    previous_k = None
    for row in rs:
        if previous_k is not None and row["k"]-previous_k > grid*1.5:
            active = None
        previous_k = row["k"]
        sign = "positive" if row["net"] > 0 else "negative"
        if not row["net"] or abs(row["net"]) < threshold:
            active = None
            continue
        if active is None or active["sign"] != sign:
            active = {"low": row["k"], "high": row["k"], "sign": sign, "net_gex": 0, "strikes": [], "method": "observed-top-quartile"}
            out.append(active)
        active["high"] = row["k"]
        active["net_gex"] += row["net"]
        active["strikes"].append(row["k"])
    return out

def price_history(now=None):
    """Actual SPX five-minute closes, separate source and timestamps; no synthetic bars."""
    now = now or now_utc()
    try:
        import yfinance as yf
        frame = yf.Ticker("^GSPC").history(period="5d", interval="5m", auto_adjust=False)
        points = []
        for t, row in frame.iterrows():
            dt = t.to_pydatetime().astimezone(timezone.utc)
            v = float(row["Close"])
            # Timestamp is bar start: expose close only after bar end.
            end = dt + timedelta(minutes=5)
            if end <= now and math.isfinite(v) and v > 0:
                points.append({"time": end.isoformat(), "close": v})
        return {"ok": len(points) > 1, "asset": "SPX", "interval": "5m", "source": "Yahoo Finance / yfinance (unofficial, may be delayed)", "fetched_utc": now.isoformat(), "points": points[-390:]}
    except Exception as exc:
        return {"ok": False, "asset": "SPX", "reason": type(exc).__name__, "points": []}

def enrich(snapshot):
    """Copy the existing output and add optional fields, never remove/alter originals."""
    out=copy.deepcopy(snapshot)
    out['map_version']='0.22.1'
    out['schema_version']=2
    out['zones']=zones(out.get('strikes') or []) if out.get('ok') else []
    out['regime_model']={'valid':False,'reason':'Estimated net GEX is not a verified dealer regime'}
    spy=out.get('spy')
    if isinstance(spy,dict) and spy.get('ok'):
        ratio=spy.get('ratio')
        if isinstance(ratio,(int,float)) and math.isfinite(ratio) and ratio>0:
            spy['zones']=[dict(z,low_x=z['low']*ratio,high_x=z['high']*ratio) for z in zones(spy.get('strikes') or [])]
    out['combined']=combined(out)
    return out

def _stamp(value):
    dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def combined(snapshot):
    """Only the NEW confluence feature checks synchronization; old SPY survives."""
    spy=snapshot.get('spy') or {}
    fail=lambda reason:{'ok':False,'zones':[],'reason':reason,'method':'confluence-only'}
    if not snapshot.get('ok') or not spy.get('ok'):
        return fail('Combined يحتاج SPX وSPY؛ بيانات كل أصل الأصلية تبقى متاحة')
    try:
        gap=abs((_stamp(snapshot['snapshot_utc'])-_stamp(spy['snapshot_utc'])).total_seconds())/60
        refgap=abs((_stamp(spy['ref_time_utc'])-_stamp(spy['snapshot_utc'])).total_seconds())/60
        if gap>30 or refgap>30:return fail('Combined فقط غير متاح: اللقطات/مرجع التحويل غير متزامنة')
    except (KeyError,ValueError,TypeError):return fail('Combined فقط غير متاح: توقيت مرجع التحويل غير مكتمل')
    out=[]
    for a in snapshot.get('zones',[]):
        for b in spy.get('zones',[]):
            lo,hi=max(a['low'],b['low_x']),min(a['high'],b['high_x'])
            if lo<=hi and a['sign']==b['sign']:
                out.append({'low':lo,'high':hi,'sign':a['sign'],'sources':['SPX','SPY'],'method':'observed-overlap'})
    return {'ok':True,'zones':out,'method':'confluence-only','reason':None}

def _write(path,value):
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with open(path+'.tmp','w',encoding='utf-8') as handle:
        json.dump(value,handle,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    os.replace(path+'.tmp',path)

def heatmap_history(root, latest=None, now=None):
    """Read-only archive access; preserve observed times and never fabricate SPY history."""
    now=now or now_utc()
    records=[]
    def record(snapshot):
        if not isinstance(snapshot,dict) or not snapshot.get('ok'):return None
        try:
            data_time=_stamp(snapshot['snapshot_utc']);known_time=_stamp(snapshot['fetched_utc'])
            if known_time>now or data_time>known_time+timedelta(minutes=5):return None
        except (KeyError,ValueError,TypeError):return None
        def rows(values,spy=False):
            out=[]
            for r in values or []:
                if not isinstance(r,dict):continue
                k,net=r.get('k'),r.get('net')
                if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (k,net)) or k<=0:continue
                item={'k':k,'net':net}
                for component in ('call','put'):
                    v=r.get(component)
                    if isinstance(v,(int,float)) and math.isfinite(v):item[component]=v
                if spy:
                    kx=r.get('kx')
                    if not isinstance(kx,(int,float)) or not math.isfinite(kx):continue
                    item['kx']=kx
                out.append(item)
            return out
        x=rows(snapshot.get('strikes'))
        if not x:return None
        out={'ok':True,'snapshot_utc':snapshot['snapshot_utc'],'fetched_utc':snapshot['fetched_utc'],'spot':snapshot.get('spot'),'strikes':x}
        def bucket_rows(source, is_spy=False):
            result={}
            for key,bucket in (source.get('buckets') or {}).items():
                if not isinstance(bucket,dict) or not isinstance(bucket.get('strikes'),list):continue
                result[key]={'n':bucket.get('n',0),'net_gex':bucket.get('net_gex',0),'strikes':rows(bucket['strikes'],is_spy)}
            return result
        buckets=bucket_rows(snapshot)
        if buckets:out['buckets']=buckets
        spy=snapshot.get('spy') or {}
        sy=rows(spy.get('strikes'),True) if spy.get('ok') else []
        try:
            if _stamp(spy.get('snapshot_utc'))>known_time:sy=[]
        except (ValueError,TypeError):sy=[]
        if sy:
            out['spy']={'ok':True,'snapshot_utc':spy.get('snapshot_utc'),'ratio':spy.get('ratio'),'strikes':sy}
            buckets=bucket_rows(spy,True)
            if buckets:out['spy']['buckets']=buckets
        return out
    old=Path(root)/'heatmap.json'
    if old.exists():
        try:records.extend(json.loads(old.read_text(encoding='utf-8')).get('snapshots',[]))
        except (OSError,ValueError,AttributeError):pass
    for path in sorted((Path(root)/'archive').glob('**/*.json'))[-96:]:
        try:records.append(json.loads(path.read_text(encoding='utf-8')))
        except (OSError,ValueError):pass
    if latest:records.append(latest)
    unique={}
    for source in records:
        r=record(source)
        if r:
            key=(r['snapshot_utc'],r['fetched_utc'])
            # A historical archive with no SPY strikes must not erase actually saved SPY observations.
            if key in unique and unique[key].get('spy') and not r.get('spy'):r['spy']=unique[key]['spy']
            unique[key]=r
    shots=sorted(unique.values(),key=lambda r:(_stamp(r['fetched_utc']),_stamp(r['snapshot_utc'])))[-48:]
    return {'ok':bool(shots),'fetched_utc':now.isoformat(),'snapshots':shots,'method':'observed-snapshots-only'}

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',default='gamma')
    args=parser.parse_args(argv)
    snapshot=None
    # No option-chain requests here. A failure cannot replace the user's snapshot.
    try:
        with open(os.path.join(args.root,'latest.json'),encoding='utf-8') as handle:
            snapshot=json.load(handle)
        out=enrich(snapshot)
        _write(os.path.join(args.root,'map.json'),out)
        print('Optional map enrichment saved; original latest.json unchanged')
    except Exception as error:
        print('Optional map unavailable:',type(error).__name__)
    try:
        _write(os.path.join(args.root,'heatmap.json'),heatmap_history(args.root,snapshot))
    except Exception as error:
        print('Optional heatmap history unavailable:',type(error).__name__)
    try:
        prices=price_history()
        _write(os.path.join(args.root,'price.json'),prices)
        print('Independent price:',bool(prices.get('ok')))
    except Exception as error:
        print('Optional price unavailable:',type(error).__name__)
    return 0

if __name__=='__main__':raise SystemExit(main())
