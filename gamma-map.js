/* Gamma Price Map v0.22: real timestamps, observed zones, fail closed. */
let gammaMapAsset = 'SPX';
function gMapZones_(rows) {
  const rs=(rows||[]).filter(r=>r && Number.isFinite(r.k) && Number.isFinite(r.net)).slice().sort((a,b)=>a.k-b.k);
  const values=rs.filter(r=>r.net).map(r=>Math.abs(r.net)).sort((a,b)=>a-b);
  if(!values.length)return [];
  const threshold=values[Math.floor((values.length-1)*.75)], gaps=rs.slice(1).map((r,i)=>r.k-rs[i].k).filter(v=>v>0).sort((a,b)=>a-b), grid=gaps[Math.floor((gaps.length-1)/2)]||0;
  const out=[];let active=null,prev=null;
  for(const r of rs){
    if(prev!==null && r.k-prev>grid*1.5)active=null;prev=r.k;
    if(!r.net || Math.abs(r.net)<threshold){active=null;continue;}
    const sign=r.net>0?'positive':'negative';
    if(!active || active.sign!==sign){active={low:r.k,high:r.k,sign,strikes:[],net_gex:0};out.push(active);}
    active.high=r.k;active.strikes.push(r.k);active.net_gex+=r.net;
  }return out;
}
function gMapView_(original) {
  if(!original)return original;
  const g=Object.assign({},original,{zones:original.zones||gMapZones_(original.strikes)});
  if(g.spy && g.spy.ok){
    const spy=Object.assign({},g.spy), ratio=spy.ratio;
    spy.zones=spy.zones || (Number.isFinite(ratio) && ratio>0 ? gMapZones_(spy.strikes).map(z=>Object.assign({},z,{low_x:z.low*ratio,high_x:z.high*ratio})) : []);
    g.spy=spy;
    if(!g.combined){
      const gap=Math.abs(Date.parse(g.snapshot_utc)-Date.parse(spy.snapshot_utc))/60000, refGap=Math.abs(Date.parse(spy.snapshot_utc)-Date.parse(spy.ref_time_utc))/60000;
      const ok=Number.isFinite(gap) && gap<=30 && Number.isFinite(refGap) && refGap<=30;
      const zones=[];
      if(ok)for(const a of g.zones)for(const b of spy.zones){const low=Math.max(a.low,b.low_x),high=Math.min(a.high,b.high_x);if(low<=high && a.sign===b.sign)zones.push({low,high,sign:a.sign});}
      g.combined={ok,zones,reason:ok?null:'Combined فقط غير متاح: توقيت مرجع التحويل غير متزامن'};
    }
  }return g;
}
function renderPriceMap_(g) {
  if(typeof gSelectedSnapshot_==='function')g=gSelectedSnapshot_(g);
  g=gMapView_(g); // a copy: original data and its acceptance rules are never mutated.
  const box = document.getElementById('gPriceMap');
  if (!box) return;
  box.replaceChildren();
  const add = (tag, text) => { const n = document.createElement(tag); n.textContent = text; box.append(n); return n; };
  add('h2', 'Gamma Price Map — سعر SPX / 5 دقائق');
  add('p', 'Macro → Weekly Context → Daily Rhythm → Order Flow. المستويات سياق تقديري، مو إشارة تنفيذ.');
  const select = add('select', ''); select.setAttribute('aria-label', 'مصدر مستويات Price Map');
  for (const a of ['SPX', 'SPY', 'Combined']) {
    const o = document.createElement('option'); o.value = a; o.textContent = a === 'SPY' ? 'SPY → SPX' : a;
    select.append(o);
  }
  select.value = gammaMapAsset;
  select.onchange = () => { gammaMapAsset = select.value; renderPriceMap_(g); };
  add('p', 'المحور العمودي SPX دائماً. Combined = تداخل مناطق SPX وSPY بنفس الإشارة، وليس جمع GEX. السلال: '+(typeof gExpiryLabel_==='function'?gExpiryLabel_():'بيانات المصدر الأصلية')).className = 'src';
  const history = g && g.price_history;
  let points = history && history.ok ? (history.points || []).filter(p => Number.isFinite(p.close) && p.close > 0 && Number.isFinite(Date.parse(p.time)) && Date.parse(p.time) <= Date.now()) : [];
  points.sort((a,b) => Date.parse(a.time)-Date.parse(b.time));
  // Display only the last observed NY date; avoid connecting overnight gaps.
  const day = t => Number.isFinite(Date.parse(t)) ? new Date(t).toLocaleDateString('en-CA', {timeZone:'America/New_York'}) : null;
  if (points.length) { const lastDay = day(points[points.length-1].time); points = points.filter(p => day(p.time) === lastDay); }
  if (points.length < 2) { add('p', 'شارت السعر غير متاح: ماكو سلسلة SPX زمنية صالحة. ما نرسم أسعار افتراضية.'); return; }
  const last = Date.parse(points[points.length-1].time), age = (Date.now()-last)/60000;
  add('p', 'مصدر السعر: ' + history.source + ' · آخر شمعة مكتملة: ' + new Date(last).toLocaleString('ar-IQ', {timeZone:'Asia/Baghdad'}) + ' بغداد · العمر ' + Math.round(age) + ' دقيقة' + (age > 30 ? ' — سعر متأخر' : '')).className = 'src';
  const fresh = g && g.ok && Date.now()-Date.parse(g.snapshot_utc) >= 0 && Date.now()-Date.parse(g.snapshot_utc) < 30*60000;
  let source = gammaMapAsset === 'SPY' ? g.spy : gammaMapAsset === 'Combined' ? g.combined : g;
  const sourceAge = source ? (Date.now()-Date.parse(source.snapshot_utc))/60000 : NaN;
  const sourceFresh = gammaMapAsset !== 'SPY' || (source && source.ok && sourceAge >= 0 && sourceAge < 30);
  const alignedPrice = age <= 30 && g && day(last) === day(g.snapshot_utc);
  const available = fresh && source && source.ok && sourceFresh && alignedPrice;
  const levels = [], zones = [];
  if (available) {
    for (const z of source.zones || []) {
      const lo = gammaMapAsset === 'SPY' ? z.low_x : z.low, hi = gammaMapAsset === 'SPY' ? z.high_x : z.high;
      if (Number.isFinite(lo) && Number.isFinite(hi) && lo <= hi) zones.push({lo, hi, sign:z.sign,nativeLow:gammaMapAsset==='SPY'?z.low:null,nativeHigh:gammaMapAsset==='SPY'?z.high:null});
    }
    if (gammaMapAsset !== 'Combined') for (const [label,key] of [['Call Wall','call_wall'],['Put Wall','put_wall'],['Gamma Flip','gamma_flip']]) {
      if (key === 'gamma_flip') continue; // the original Flip remains in legacy details, not a verified map overlay.
      const v = source[key + (gammaMapAsset === 'SPY' ? '_x' : '')];
      if (Number.isFinite(v) && v > 0) levels.push({label,v,native:gammaMapAsset==='SPY'?source[key]:null});
    }
    add('p', 'وقت بيانات المستويات: ' + g.snapshot_utc + ' · متاحة منذ الجمع: ' + g.fetched_utc + ' · المناطق من Strikes فعلية، بإشارة Net GEX المقدّرة.').className='src';
    if (gammaMapAsset === 'Combined' && !zones.length) add('p','ماكو تداخل مناطق موثّق بهاللقطة.');
  } else add('p', 'المستويات معطلة: ' + (!fresh ? 'لقطة Gamma قديمة أو غير صالحة أو تحتاج إعادة جمع بالإصدار الجديد.' : !alignedPrice ? 'السعر متأخر أو من جلسة مختلفة عن Gamma.' : (source && source.reason) || 'المصدر غير متاح أو متأخر.'));
  // No uniform or historical regime coloring based merely on net sign.
  add('p', 'خلفية Gamma Regime معطلة: ما متوفر نموذج repricing مُعاير ومتحقق منه.').className='review-badge';
  const W=1100,H=480,L=135,R=220,T=24,B=65;
  const start=Date.parse(points[0].time), fetched = Date.parse(g.fetched_utc);
  const onset=Number.isFinite(fetched) ? Math.max(start,fetched) : last;
  const end=Math.max(last+5*60000,available ? onset+45*60000 : last+5*60000);
  const all=points.map(p=>p.close).concat(levels.map(p=>p.v),zones.flatMap(z=>[z.lo,z.hi]));
  let low=Math.min(...all),high=Math.max(...all),pad=Math.max(3,(high-low)*.08); low-=pad; high+=pad;
  const x=t=>L+(t-start)/(end-start)*(W-L-R), y=v=>T+(high-v)/(high-low)*(H-T-B);
  const ns='http://www.w3.org/2000/svg', svg=document.createElementNS(ns,'svg');
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`); svg.setAttribute('role','img'); svg.setAttribute('aria-label','سعر SPX عبر الزمن ومستويات Gamma الحالية، لا تاريخ افتراضي');
  svg.style.cssText='width:100%;min-width:680px;display:block;direction:ltr;background:var(--bg,#111827)';
  const draw=(tag,attrs,text)=>{ const n=document.createElementNS(ns,tag); for(const [k,v] of Object.entries(attrs)) n.setAttribute(k,v); if(text)n.textContent=text; svg.append(n);return n; };
  for(let i=0;i<=5;i++){const v=low+(high-low)*i/5;draw('line',{x1:L,x2:W-R,y1:y(v),y2:y(v),stroke:'#7b8796','stroke-opacity':'.25'});draw('text',{x:L-8,y:y(v),fill:'#94a3b8','text-anchor':'end','font-size':16},'SPX '+v.toFixed(1));if(typeof gESLabel_==='function')draw('text',{x:L-8,y:y(v)+17,fill:'#60a5fa','text-anchor':'end','font-size':14},gESLabel_(g,v));}
  for(let i=0;i<=4;i++){const t=start+(end-start)*i/4;draw('text',{x:x(t),y:H-30,fill:'#94a3b8','font-size':15,'text-anchor':'middle'},new Date(t).toLocaleTimeString('en-GB',{timeZone:'Asia/Baghdad',hour:'2-digit',minute:'2-digit'}));}
  const sx=x(onset), ex=W-R;
  for(const z of zones){const color=z.sign==='positive'?'#2fbf71':'#e5484d';draw('rect',{x:sx,y:y(z.hi),width:Math.max(0,ex-sx),height:Math.max(2,y(z.lo)-y(z.hi)),fill:color,'fill-opacity':'.2'});}
  for(const l of levels){const color=l.label==='Call Wall'?'#2fbf71':l.label==='Put Wall'?'#e5484d':'#60a5fa';draw('line',{x1:sx,x2:ex,y1:y(l.v),y2:y(l.v),stroke:color,'stroke-width':2,'stroke-dasharray':'6 4'});draw('text',{x:ex+6,y:y(l.v)-6,fill:color,'font-size':14},l.label+' · SPX '+l.v.toFixed(1));if(typeof gESLabel_==='function')draw('text',{x:ex+6,y:y(l.v)+11,fill:color,'font-size':14},gESLabel_(g,l.v));if(Number.isFinite(l.native))draw('text',{x:ex+6,y:y(l.v)-23,fill:color,'font-size':13},'SPY '+l.native.toFixed(2));}
  let path='',prev=null;
  for(const p of points){const t=Date.parse(p.time);path+=(prev===null || t-prev>6*60000?'M':'L')+x(t).toFixed(2)+','+y(p.close).toFixed(2)+' ';prev=t;}
  draw('path',{d:path,fill:'none',stroke:'#60a5fa','stroke-width':2.5});
  if(available) {draw('line',{x1:sx,x2:sx,y1:T,y2:H-B,stroke:'#d4a84b','stroke-dasharray':'3 4'});draw('text',{x:sx+5,y:T+16,fill:'#d4a84b','font-size':13},'Snapshot available →');}
  const wrap=add('div','');wrap.className='gmap-scroll';wrap.style.overflowX='auto';wrap.append(svg);
  if(typeof gPriceStack_==='function'){
    const lastPrice=add('div','');lastPrice.className='map-levels';const current=document.createElement('div');current.textContent='آخر سعر على الشارت';current.append(gPriceStack_(g,points[points.length-1].close));lastPrice.append(current);
    for(const l of levels){const row=document.createElement('div');row.textContent=l.label;row.append(gPriceStack_(g,l.v,l.native));lastPrice.append(row);}
    for(const z of zones){const row=document.createElement('div');row.textContent='منطقة '+(z.sign==='positive'?'موجبة':'سالبة');row.append(gPriceStack_(g,z.lo,z.nativeLow),document.createTextNode(' ↔ '),gPriceStack_(g,z.hi,z.nativeHigh));lastPrice.append(row);}
  }
  add('p','على الموبايل: اسحب الشارت أفقياً لقراءة الأسعار والتوقيت.').className='src';
  add('p','الزمن بتوقيت بغداد. المستويات تبدأ من وقت إتاحة اللقطة؛ المساحة بعدها عرض للمستويات الحالية، مو توقع لسعر مستقبلي.').className='src';
  const metadata=document.createElement('details');metadata.className='gmap-meta';
  const metaTitle=document.createElement('summary');metaTitle.textContent='المصادر والتوقيت وحدود الحساب';metadata.append(metaTitle);
  for(const n of [...box.querySelectorAll('p.src')])metadata.append(n);
  box.append(metadata);
}
