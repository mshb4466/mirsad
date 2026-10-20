/* Presentation-only price conversion. Never changes gamma.py or stored levels. */
function gESContext_(g) {
  const e=g && g.es;
  const ok=!!e && typeof e.basis==='number' && Number.isFinite(e.basis);
  const stamp=e && Date.parse(e.ref_time_utc), age=Number.isFinite(stamp)?(Date.now()-stamp)/60000:null;
  const live=ok && e.mode==='live' && age!==null && age>=0 && age<=5 && typeof e.ref_gap_min==='number' && e.ref_gap_min>=0 && e.ref_gap_min<=5;
  return {ok,basis:ok?e.basis:null,mode:live?'live':e && e.mode==='close'?'close':'dated',time:e && e.ref_time_utc,age};
}
function gESValue_(g,price) {
  const c=gESContext_(g);
  if(!c.ok || typeof price!=='number' || !Number.isFinite(price) || price<=0)return null;
  const value=Math.round((price+c.basis)*4)/4;return Number.isFinite(value) && value>0?value:null;
}
function gESLabel_(g,price) {const v=gESValue_(g,price);return v===null?'ES غير متاح':'ES ≈ '+v.toFixed(2);}
function gPriceStack_(g,spx,spy) {
  const box=document.createElement('span');box.className='price-stack';box.dir='ltr';
  if(typeof spy==='number' && Number.isFinite(spy)){const native=document.createElement('small');native.className='native-spy';native.textContent='SPY '+spy.toFixed(2);box.append(native);}
  const original=document.createElement('b');original.className='spx-price';original.textContent=typeof spx==='number' && Number.isFinite(spx)?'SPX '+spx.toFixed(2):'SPX غير متاح';box.append(original);
  const converted=document.createElement('small');converted.className='es-under';converted.textContent=gESLabel_(g,spx);box.append(converted);
  return box;
}
function gSVGPriceStack_(node,g,spx,spy) {
  const ns='http://www.w3.org/2000/svg';
  node.replaceChildren();
  const line=(text,dy,size)=>{const t=document.createElementNS(ns,'tspan');t.setAttribute('x','0');t.setAttribute('dy',dy);t.setAttribute('font-size',size);t.textContent=text;node.append(t);};
  if(typeof spy==='number' && Number.isFinite(spy))line('SPY '+spy.toFixed(2),'0','8');
  line('SPX '+Number(spx).toFixed(1),spy!=null?'10':'0','9');
  line(gESLabel_(g,spx),'11','8');
}
function decorateGammaES_(g) {
  if(typeof gSelectedSnapshot_==='function')g=gSelectedSnapshot_(g);
  if(!g || !g.ok)return;
  const ratio=g.spy && g.spy.ratio, isSpy=typeof GASSET!=='undefined' && GASSET==='SPY';
  // Native SPY, then its SPX equivalent, then ES on the next line.
  for(const card of document.querySelectorAll('#gLevels .lvb')){
    let v=Number(card.dataset.v);if(card.dataset.v==='' || !Number.isFinite(v))continue;
    let native=null;
    if(isSpy && g.spy && Number.isFinite(ratio) && ratio>0){
      if(card.classList.contains('lv-sp')){native=g.spy.spot;v=native*ratio;}
      else if(card.classList.contains('lv-cw'))native=g.spy.call_wall;
      else if(card.classList.contains('lv-pw'))native=g.spy.put_wall;
      else if(card.classList.contains('lv-fl'))native=g.spy.gamma_flip;
    }
    card.querySelector('.price-stack')?.remove();
    const value=card.querySelector('b'), existing=card.querySelector('.es');
    if(value)value.hidden=true;if(existing)existing.hidden=true;
    card.append(gPriceStack_(g,v,native));
  }
  for(const row of document.querySelectorAll('#gChart .gr')){
    const value=Number(row.dataset.k);if(!Number.isFinite(value))continue;
    const key=row.querySelector('.k'), actualSpy=isSpy && typeof gData_==='function'?gData_(g,'SPY',typeof GBKT==='undefined'?'all':GBKT)?.rows.find(r=>r.k===value)?.spyK:null;
    const native=typeof actualSpy==='number'?actualSpy:null;
    key.querySelector('.price-stack')?.remove();
    if(!key.querySelector('.original-key')){
      const original=document.createElement('span');original.className='original-key';while(key.firstChild)original.append(key.firstChild);key.append(original);
    }
    key.querySelector('.original-key').hidden=true;key.append(gPriceStack_(g,value,native));
  }
  for(const row of document.querySelectorAll('#gCmp .gcmpt tr')){
    const cells=row.querySelectorAll('td');if(cells.length<3)continue;
    for(const index of [1,2]){
      const text=cells[index].textContent.trim(), value=Number(text);if(!text || !Number.isFinite(value) || value<=0)continue;
      const label=cells[0].textContent, native=index===2 && g.spy ? label.includes('Call Wall')?g.spy.call_wall:label.includes('Put Wall')?g.spy.put_wall:label.includes('Gamma Flip')?g.spy.gamma_flip:null : null;
      cells[index].replaceChildren(gPriceStack_(g,value,native));
    }
    if(cells[3] && Number.isFinite(Number(cells[3].textContent.replace('−','-')))){
      const diff=Number(cells[3].textContent.replace('−','-')), line=document.createElement('small');line.className='es-under';line.textContent='Δ ES '+(diff>0?'+':'')+diff.toFixed(2);cells[3].append(line);
    }
  }
  const comparison=document.querySelector('#gCmp .gcmpt');
  if(comparison && !comparison.parentElement.classList.contains('cmp-scroll')){const wrap=document.createElement('div');wrap.className='cmp-scroll';comparison.before(wrap);wrap.append(comparison);}
  const note=document.getElementById('gESReference');
  if(note){
    const c=gESContext_(g);
    note.textContent=!c.ok?'تحويل ES غير متاح: بيانات Gamma الأصلية تبقى ظاهرة، ولا نفترض فرقاً صفرياً.':'ES ≈ SPX + '+c.basis.toFixed(2)+'، بخطوة 0.25 · '+(c.mode==='live'?'مرجع متزامن حديث':c.mode==='close'?'مرجع إغلاق، وليس سعر ES الحالي':'مرجع محفوظ غير حي')+' · وقت المرجع '+(c.time||'غير متاح');
  }
  const explanation=document.getElementById('gEsNote');
  if(explanation){
    explanation.replaceChildren();const title=document.createElement('h2');title.textContent='مرجع تحويل SPX / SPY إلى ES';explanation.append(title);
    const c=gESContext_(g),p=document.createElement('p');p.className='src';p.textContent=!c.ok?'لا يوجد فرق ES−SPX في البيانات. تظهر الأسعار الأصلية، ويكتب تحتها ES غير متاح.':'ES التقريبي = SPX + ('+c.basis.toFixed(2)+')، إلى أقرب 0.25. '+(c.mode==='live'?'المرجع متزامن حديث.':c.mode==='close'?'هذا مرجع إغلاق محفوظ؛ ليس سعر ES الحالي.':'هذا مرجع محفوظ غير حي، وليس سعر ES الحالي.')+' الوقت: '+(c.time||'غير متاح')+'. تحويل SPY يمر أولاً بنسبة SPX/SPY الموجودة ببياناتك.';explanation.append(p);
    if(c.ok && Number.isFinite(g.es.spx_ref))explanation.append(gPriceStack_(g,g.es.spx_ref));
  }
}
