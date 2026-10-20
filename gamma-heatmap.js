/* Observed GEX heatmaps only. Cell colors are not a verified Gamma Regime. */
let GAMMA_HEATMAP=window.MIRSAD_HEATMAP_PENDING||null, heatAsset='SPX', heatMode='buckets';
function renderGammaHeatmap_(g) {
  if(typeof gSelectedSnapshot_==='function')g=gSelectedSnapshot_(g);
  const box=document.getElementById('gHeatmap');if(!box)return;box.replaceChildren();
  const add=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;box.append(n);return n;};
  add('h2','الخارطة الحرارية — Gamma Heatmap');
  add('p','ألوان الخلايا = صافي GEX التقديري الموجود بالبيانات، وليست إثباتاً لـ Gamma Regime. لا تحتاج API جديداً.').className='src';
  if(!g || !g.ok){add('p',g?.reason||'بيانات Gamma الأصلية غير متاحة الآن؛ لا نضع ألواناً أو مستويات بديلة.');return;}
  const ctl=add('div','');ctl.className='heat-controls';
  const select=(label,options,value,fn)=>{const l=document.createElement('label');l.textContent=label+' ';const s=document.createElement('select');s.setAttribute('aria-label',label);for(const [v,text] of options){const o=document.createElement('option');o.value=v;o.textContent=text;s.append(o);}s.value=value;s.onchange=()=>{fn(s.value);renderGammaHeatmap_(g);};l.append(s);ctl.append(l);return s;};
  select('أصل الخارطة',[['SPX','SPX'],['SPY','SPY → SPX → ES'],['CMP','SPX وSPY جنباً إلى جنب']],heatAsset,v=>heatAsset=v);
  select('عرض الخارطة',[['buckets','اللقطة الحالية / سلال الاستحقاق'],['time','السجل الفعلي / الزمن']],heatMode,v=>heatMode=v);
  const spy=heatAsset==='SPY',comparison=heatAsset==='CMP',source=spy?g.spy:g;
  if(spy && (!source || !source.ok)){add('p','SPY غير متاح حسب المصدر الأصلي؛ بيانات SPX تبقى متاحة.');return;}
  if(comparison && (!g.spy || !g.spy.ok)){add('p','مقارنة الخارطة تحتاج SPY؛ لا يتم اختراع بياناته.');return;}
  let cols=[], keyed=new Map();
  const put=(key,cell,col,native=null)=>{if(!Number.isFinite(key)||!Number.isFinite(cell))return;const k=key.toFixed(4);if(!keyed.has(k))keyed.set(k,{key,values:new Map(),native});const r=keyed.get(k);if(native!==null)r.native=native;r.values.set(col,cell);};
  if(heatMode==='buckets'){
    if(comparison){
      cols=[{label:'SPX · الاختيار',id:'X'},{label:'SPY · الاختيار',id:'Y'}];
      for(const r of g.strikes||[])put(r.k,r.net,'X');
      for(const r of g.spy.strikes||[])put(r.kx,r.net,'Y',r.k);
      add('p','مقارنة الأصلين على الأسعار الفعلية: الفراغ يعني عدم وجود Strike مطابق. لا نجمع GEX للأصلين ولا نقرّب Strike إلى سعر مخترع.').className='src';
    }else{
      const keys=typeof gExpiryKeys_==='function'?gExpiryKeys_():['0','wk','mo','later'],labels={'0':'اليوم','wk':'بقية الأسبوع','mo':'بقية الشهر','later':'ما بعد الشهر'};
      cols=keys.filter(k=>source.buckets && source.buckets[k]).map(k=>({id:k,label:labels[k]}));
      if(!cols.length){add('p','لا يوجد تفصيل للسلال المختارة في هذه اللقطة؛ بيانات المصدر الأصلية محفوظة.');return;}
      for(const col of cols)for(const r of (col.id==='all'?source:source.buckets[col.id]).strikes||[])put(spy?r.kx:r.k,r.net,col.id,spy?r.k:null);
    }
    const stamp=source.snapshot_utc||g.snapshot_utc, formatted=Number.isFinite(Date.parse(stamp))?new Date(stamp).toLocaleString('ar-IQ',{timeZone:'Asia/Baghdad',hour12:false}):stamp;
    const timing=add('p','وقت بيانات اللقطة: '+formatted+' بغداد · البيانات الأصلية مع توقيتها، دون شروط قبول جديدة.');timing.className='src';timing.title=stamp;
  }else{
    if(comparison){add('p','السجل الزمني يُعرض لكل أصل منفرداً؛ اختر SPX أو SPY. المقارنة الحالية متاحة بالعرض الأول.');return;}
    const day=t=>Number.isFinite(Date.parse(t))?new Date(t).toLocaleDateString('en-CA',{timeZone:'America/New_York'}):null;
    const target=day(g.snapshot_utc);
    const history=(GAMMA_HEATMAP && Array.isArray(GAMMA_HEATMAP.snapshots)?GAMMA_HEATMAP.snapshots:[])
      .filter(s=>s && day(s.snapshot_utc)===target && Date.parse(s.fetched_utc)<=Date.now() && (typeof gCanFilterHistory_!=='function'||gCanFilterHistory_(s,spy)) && (!spy || (s.spy && s.spy.ok && Array.isArray(s.spy.strikes) && Date.parse(s.spy.snapshot_utc)<=Date.parse(s.fetched_utc))))
      .slice(-16);
    if(history.length<2){add('p','ماكو لقطات تاريخية كافية تحتوي تفصيل السلال المختارة لهذا الأصل. نحتاج لقطتين محفوظتين فعلياً؛ ما نلوّن الماضي اعتماداً على لقطة اليوم. استخدم عرض اللقطة الحالية.');return;}
    cols=history.map((s,i)=>({id:String(i),label:new Date(s.fetched_utc).toLocaleTimeString('en-GB',{timeZone:'Asia/Baghdad',hour:'2-digit',minute:'2-digit'}),snapshot:s.snapshot_utc}));
    history.forEach((s,i)=>{const source=spy?s.spy:s;const rows=typeof gSelectedRows_==='function'?gSelectedRows_(source,spy):source.strikes||[];for(const r of rows)put(spy?r.kx:r.k,r.net,String(i),spy?r.k:null);});
    add('p','الأفقي وقت حفظ اللقطة بتوقيت بغداد، وليس تاريخاً مفترضاً. الفراغات بيانات غير موجودة. أرقام ES تستخدم مرجع التحويل المعروض الآن، وليست سعراً تاريخياً فعلياً لـ ES.').className='src';
  }
  let rows=[...keyed.values()];if(!rows.length){add('p','لا توجد قيم GEX قابلة للرسم بهذه البيانات.');return;}
  const spot=Number(g.spot);rows.sort((a,b)=>Math.abs(a.key-spot)-Math.abs(b.key-spot));rows=rows.slice(0,24).sort((a,b)=>b.key-a.key);
  const scales=new Map();for(const c of cols)scales.set(c.id,Math.max(1,...rows.map(r=>Math.abs(r.values.get(c.id)||0))));
  const wrap=add('div','');wrap.className='heat-scroll';const table=document.createElement('table');table.className='heat-table';
  const head=document.createElement('thead'),tr=document.createElement('tr'),th=document.createElement('th');th.textContent=spy?'SPY → SPX / ES':'SPX / ES';tr.append(th);
  for(const c of cols){const h=document.createElement('th');h.textContent=c.label;if(c.snapshot)h.title='وقت بيانات المصدر '+c.snapshot;tr.append(h);}head.append(tr);table.append(head);
  const body=document.createElement('tbody');
  for(const r of rows){const row=document.createElement('tr'),price=document.createElement('th');price.scope='row';
    if(typeof gPriceStack_==='function')price.append(gPriceStack_(g,r.key,r.native));else price.textContent='SPX '+r.key;
    row.append(price);
    for(const c of cols){const cell=document.createElement('td'),value=r.values.get(c.id);
      if(value===undefined){cell.textContent='—';cell.className='heat-missing';cell.title='لا بيانات لهذا Strike في هذه السلة/اللقطة';}
      else{const strength=Math.sqrt(Math.abs(value)/scales.get(c.id));cell.style.backgroundColor=value>0?'rgba(32,165,103,'+(.12+.68*strength)+')':value<0?'rgba(205,55,73,'+(.12+.68*strength)+')':'var(--card-2)';cell.textContent=(value>0?'+':'')+(value/1e9).toFixed(3)+'B';cell.title='SPX '+r.key+' · '+(typeof gESLabel_==='function'?gESLabel_(g,r.key):'')+' · GEX '+value+' دولار لكل 1%';cell.dataset.gex=String(value);}
      row.append(cell);
    }body.append(row);
  }table.append(body);wrap.append(table);
  add('p','أخضر = صافي موجب، أحمر = صافي سالب، شدة اللون نسبية داخل كل عمود. تعرض أقرب 24 مستوى فعلياً للسعر؛ اسحب الجدول لقراءة البقية.').className='src';
  add('p','Regime التقديري من نموذجك الحالي: '+(g.regime==='positive'?'موجب':g.regime==='negative'?'سالب':g.regime==='neutral'?'متعادل':g.regime||'غير محدد')+' · لا توجد خلفية مؤكدة مضافة. Gamma Flip الأصلي يبقى ظاهراً كما هو.').className='review-badge';
}
