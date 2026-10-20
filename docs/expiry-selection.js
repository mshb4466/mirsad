/* UI-only disjoint expiry selection. gamma.py and its snapshots stay untouched. */
const GEXPIRY_KEYS_=['0','wk','mo','later'];
let GEXPIRY_SELECTED_=new Set(GEXPIRY_KEYS_);
try{const saved=JSON.parse(localStorage.getItem('mirsad-expiry-selection-v1'));if(Array.isArray(saved))GEXPIRY_SELECTED_=new Set(saved.filter(k=>GEXPIRY_KEYS_.includes(k)));}catch(e){}
function gExpiryKeys_(){return GEXPIRY_KEYS_.filter(k=>GEXPIRY_SELECTED_.has(k));}
function gExpiryAll_(){return gExpiryKeys_().length===GEXPIRY_KEYS_.length;}
function gExpiryLabel_(){const labels={'0':'اليوم',wk:'بقية الأسبوع',mo:'بقية الشهر',later:'ما بعد الشهر'};return gExpiryKeys_().map(k=>labels[k]).join(' + ')||'لا سلال مختارة';}
function gToggleExpiry_(key,checked){
  if(!GEXPIRY_KEYS_.includes(key))return;
  if(checked)GEXPIRY_SELECTED_.add(key);else GEXPIRY_SELECTED_.delete(key);
  try{localStorage.setItem('mirsad-expiry-selection-v1',JSON.stringify(gExpiryKeys_()));}catch(e){}
  if(typeof GBKT!=='undefined')GBKT='selected';if(typeof GSEL!=='undefined')GSEL=null;
  if(typeof renderGamma_==='function')renderGamma_();
}
function gSelectedRows_(source,spy=false){
  if(!source)return [];
  if(gExpiryAll_())return (source.strikes||[]).map(r=>Object.assign({},r));
  const by=new Map();
  for(const key of gExpiryKeys_())for(const r of source.buckets?.[key]?.strikes||[]){
    if(!Number.isFinite(r.k)||!Number.isFinite(r.net))continue;
    if(!by.has(r.k))by.set(r.k,{k:r.k,call:0,put:0,net:0,...(spy&&Number.isFinite(r.kx)?{kx:r.kx}:{})});
    const sum=by.get(r.k);sum.call+=Number.isFinite(r.call)?r.call:0;sum.put+=Number.isFinite(r.put)?r.put:0;sum.net+=r.net;
  }return [...by.values()].sort((a,b)=>a.k-b.k);
}
function gSelectedSource_(source,spy=false){
  if(!source || !source.ok)return source;
  if(gExpiryAll_())return Object.assign({},source,{selected_expiries:gExpiryKeys_()});
  const out=Object.assign({},source), rows=gSelectedRows_(source,spy), selected=gExpiryKeys_().map(k=>source.buckets?.[k]).filter(Boolean);
  out.strikes=rows;out.n_contracts=selected.reduce((n,b)=>n+(Number(b.n)||0),0);out.net_gex=selected.reduce((n,b)=>n+(Number(b.net_gex)||0),0);
  const spot=source.spot, up=rows.filter(r=>r.call>0&&r.k>=spot&&r.k<=spot*1.04),dn=rows.filter(r=>r.put<0&&r.k<=spot&&r.k>=spot*.96);
  out.call_wall=up.length?up.reduce((a,b)=>b.call>a.call?b:a).k:null;
  out.put_wall=dn.length?dn.reduce((a,b)=>b.put<a.put?b:a).k:null;
  out.gamma_flip=null;out.gamma_flip_x=null;out.regime=out.net_gex>0?'positive':out.net_gex<0?'negative':'neutral';
  out.selected_expiries=gExpiryKeys_();delete out.zones;
  if(spy){const fx=k=>k!==null&&Number.isFinite(source.ratio)?Math.round(k*source.ratio*10)/10:null;out.call_wall_x=fx(out.call_wall);out.put_wall_x=fx(out.put_wall);}
  return out;
}
function gSelectedData_(g,asset){
  if(!g?.ok || !gExpiryKeys_().length)return null;
  const spy=asset==='SPY',s=gSelectedSource_(spy?g.spy:g,spy);if(!s?.ok)return null;
  if(!s.strikes?.length && !s.n_contracts)return null;
  const rows=spy?s.strikes.filter(r=>Number.isFinite(r.kx)).map(r=>Object.assign({},r,{spyK:r.k,k:r.kx})):s.strikes;
  return {asset,b:'selected',rows,net:s.net_gex,cw:spy?s.call_wall_x:s.call_wall,pw:spy?s.put_wall_x:s.put_wall,flip:spy?s.gamma_flip_x:s.gamma_flip,n:s.n_contracts,spyCw:s.call_wall,spyPw:s.put_wall};
}
function gSelectedSnapshot_(g){
  if(!g?.ok)return g;
  if(!gExpiryKeys_().length)return Object.assign({},g,{ok:false,reason:'اختر سلة واحدة أو أكثر؛ بيانات المصدر الأصلية لم تتغير.'});
  const out=gSelectedSource_(g);if(g.spy)out.spy=gSelectedSource_(g.spy,true);
  if(!gExpiryAll_()){delete out.zones;delete out.combined;}
  out.selected_label=gExpiryLabel_();return out;
}
function gCanFilterHistory_(snapshot,spy=false){
  const s=spy?snapshot.spy:snapshot;
  return !!s && gExpiryKeys_().length>0 && (gExpiryAll_() || gExpiryKeys_().every(k=>s.buckets?.[k] && Array.isArray(s.buckets[k].strikes)));
}
