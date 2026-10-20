/* No network/browser: independent aggregation and persistence regression checks. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const storage=new Map();const context=vm.createContext({localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},Set,Map,console});
vm.runInContext(fs.readFileSync(require('path').join(__dirname,'expiry-selection.js'),'utf8'),context);
const keys=['0','wk','mo','later'];
const source={ok:true,spot:7000,net_gex:500,n_contracts:10,gamma_flip:6990,call_wall:7010,put_wall:6990,strikes:[{k:6990,call:500,put:-600,net:-100},{k:7010,call:1000,put:-400,net:600}],buckets:{}};
for(let i=0;i<4;i++)source.buckets[keys[i]]={n:i+1,net_gex:50*(i+1),strikes:[{k:6990,call:10*(i+1),put:-20*(i+1),net:-10*(i+1)},{k:7010,call:40*(i+1),put:-10*(i+1),net:30*(i+1)}]};
const spy={ok:true,spot:700,ratio:10,net_gex:500,n_contracts:10,gamma_flip:699,gamma_flip_x:6990,call_wall:701,put_wall:699,call_wall_x:7010,put_wall_x:6990,strikes:source.strikes.map(r=>({...r,k:r.k/10,kx:r.k})),buckets:{}};
for(const k of keys)spy.buckets[k]={...source.buckets[k],strikes:source.buckets[k].strikes.map(r=>({...r,k:r.k/10,kx:r.k}))};
context.fixture={...source,spy};const original=JSON.stringify(context.fixture);let checks=0;
const check=(fn)=>{fn();checks++;};
for(let mask=0;mask<16;mask++){
 const picked=keys.filter((_,i)=>mask&(1<<i));vm.runInContext('GEXPIRY_SELECTED_=new Set('+JSON.stringify(picked)+')',context);
 const view=JSON.parse(vm.runInContext('JSON.stringify(gSelectedData_(fixture,"SPX"))',context));
 if(mask===0){check(()=>assert.strictEqual(view,null));check(()=>assert.strictEqual(vm.runInContext('gSelectedSnapshot_(fixture).ok',context),false));continue;}
 if(mask===15){check(()=>assert.deepStrictEqual(view.rows,source.strikes));check(()=>assert.strictEqual(view.flip,6990));continue;}
 const expectedN=picked.reduce((n,k)=>n+source.buckets[k].n,0),expectedNet=picked.reduce((n,k)=>n+source.buckets[k].net_gex,0);
 check(()=>assert.strictEqual(view.n,expectedN));check(()=>assert.strictEqual(view.net,expectedNet));check(()=>assert.strictEqual(view.flip,null));
 for(const row of view.rows)check(()=>assert.strictEqual(row.net,picked.reduce((n,k)=>n+source.buckets[k].strikes.find(r=>r.k===row.k).net,0)));
 const y=JSON.parse(vm.runInContext('JSON.stringify(gSelectedData_(fixture,"SPY"))',context));
 check(()=>assert.strictEqual(y.cw,view.cw));check(()=>assert.strictEqual(y.spyCw,view.cw/10));
}
check(()=>assert.strictEqual(JSON.stringify(context.fixture),original));
vm.runInContext("GEXPIRY_SELECTED_=new Set(['wk','mo']);gToggleExpiry_('0',true);gToggleExpiry_('wk',false)",context);
check(()=>assert.deepStrictEqual(JSON.parse(storage.get('mirsad-expiry-selection-v1')),['0','mo']));
vm.runInContext("gToggleExpiry_('mo',false);gToggleExpiry_('0',false)",context);
check(()=>assert.strictEqual(vm.runInContext('gExpiryKeys_().length',context),0));
check(()=>assert.strictEqual(vm.runInContext("gCanFilterHistory_({strikes:[]})",context),false));
vm.runInContext("GEXPIRY_SELECTED_=new Set(['wk','mo'])",context);
check(()=>assert.strictEqual(vm.runInContext('gCanFilterHistory_(fixture)',context),true));
check(()=>assert.strictEqual(vm.runInContext("gCanFilterHistory_({buckets:{wk:{strikes:[]}}})",context),false));
console.log(`${checks} expiry-selection regression checks passed`);
