const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert');
const root=path.resolve('.test-output/fixtures');const logs=[];fs.mkdirSync('.test-output/screenshots',{recursive:true});
const server=http.createServer((req,res)=>{const name=decodeURIComponent(req.url.split('?')[0]).replace(/^\//,'')||'index.html';const file=path.resolve(root,name);if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404).end();return;}res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.json')?'application/json':'text/html');res.end(fs.readFileSync(file));});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));
const url=`http://127.0.0.1:${server.address().port}/index.html`;
const browser=await chromium.launch({...(process.env.MIRSAD_CHROME ? {executablePath:process.env.MIRSAD_CHROME} : {}),headless:true});
const errors=[];
const check=(cond,msg)=>{logs.push({pass:!!cond,message:msg});if(!cond)throw Error(msg);};
try{
for(const width of [320,375,430,768,1366,1920]){
 const page=await browser.newPage({viewport:{width,height:1000},colorScheme:'dark'});
 page.on('pageerror',e=>errors.push(e.message));
 await page.clock.install({time:new Date('2026-10-19T14:10:00Z')});
 await page.route('https://**/*',r=>r.abort());
 await page.goto(url);await page.waitForFunction(()=>document.querySelector('#output').hidden===false);
 await page.waitForFunction(()=>typeof GAMMA!=='undefined' && GAMMA && GAMMA.price_history);
 check(await page.locator('#mAdvice').isVisible(),`${width}: advice visible`);
 check(await page.locator('#sessionAside').isVisible(),`${width}: event and risk share aside`);
 check(await page.locator('#mainCard').evaluate(n=>n.getBoundingClientRect().top < document.getElementById('updCard').getBoundingClientRect().top),`${width}: advice before update details`);
 check(await page.locator('#gammaDiagnostics').evaluate(n=>n.open),`${width}: original strike diagnostics visible by default`);
 check(await page.locator('#nextCard').isVisible(),`${width}: next event visible`);
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${width}: no page horizontal overflow`);
 check(await page.locator('#pulseDetails').evaluate(d=>d.open)===(width>=900),`${width}: market disclosure responsive`);
 if(width<900){await page.locator('#pulseDetails summary').click();check(await page.locator('#pcards').isVisible(),`${width}: market details open`);}
 await page.locator('#gammaJump').click();
 check(await page.locator('#gPriceMap svg').count()===1,`${width}: time-price chart rendered`);
 check(await page.evaluate(()=>gESValue_(GAMMA,7000))===7020.25,`${width}: SPX to ES uses the actual supplied basis`);
 check(await page.evaluate(()=>gESValue_({es:{basis:-12.6}},7000))===6987.5,`${width}: ES rounds to quarter ticks with negative basis`);
 check(await page.evaluate(()=>gESValue_({es:{basis:null}},7000))===null,`${width}: absent basis is never zero`);
 check(await page.locator('#gLevels .lvb .price-stack .es-under').count()>=3,`${width}: ES directly under original SPX cards`);
 check(await page.locator('#gHeatmap .heat-table tbody tr').count()>0,`${width}: heatmap uses current original GEX`);
 check(await page.locator('#gHeatmap .heat-table td[data-gex]').count()>0,`${width}: heatmap cells have observed exposures`);
 check(await page.locator('#gCtl input[type=checkbox]').count()===4,`${width}: independent expiry checkboxes, no All button`);
 await page.locator('#gCtl input[data-b="0"]').uncheck();await page.locator('#gCtl input[data-b="later"]').uncheck();
 check(await page.evaluate(()=>JSON.stringify(gExpiryKeys_()))==='["wk","mo"]',`${width}: weekly and monthly selection excludes today`);
 check(await page.locator('#gHeatmap .heat-table thead th').count()===3,`${width}: heatmap follows two selected buckets`);
 await page.locator('#gCtl input[data-b="0"]').check();await page.locator('#gCtl input[data-b="mo"]').uncheck();
 check(await page.evaluate(()=>JSON.stringify(gExpiryKeys_()))==='["0","wk"]',`${width}: daily and weekly combination`);
 await page.locator('#gCtl input[data-b="0"]').uncheck();await page.locator('#gCtl input[data-b="wk"]').uncheck();
 check(await page.evaluate(()=>gExpiryKeys_().length===0),`${width}: empty selection never falls back to All`);
 for(const key of ['0','wk','mo','later'])await page.locator(`#gCtl input[data-b="${key}"]`).check();
 await page.locator('#gHeatmap select[aria-label="أصل الخارطة"]').selectOption('SPY');
 check(await page.locator('#gHeatmap .native-spy').count()>0 && await page.locator('#gHeatmap .es-under').count()>0,`${width}: SPY heatmap stacks SPY then SPX then ES`);
 if(width===430)await page.locator('#gHeatmap').screenshot({path:'.test-output/screenshots/mirsad-spy-heatmap-430.png'});
 await page.waitForFunction(()=>typeof GAMMA_HEATMAP!=='undefined' && GAMMA_HEATMAP && GAMMA_HEATMAP.snapshots.length>=2);
 await page.locator('#gHeatmap select[aria-label="عرض الخارطة"]').selectOption('time');
 check(await page.locator('#gHeatmap .heat-table thead th').count()===3,`${width}: temporal heatmap has two observed snapshots only`);
 await page.locator('#gHeatmap select[aria-label="عرض الخارطة"]').selectOption('buckets');
 await page.locator('#gHeatmap select[aria-label="أصل الخارطة"]').selectOption('SPX');
 await page.locator('#gCtl [data-a="SPY"]').click();
 check(await page.locator('#gLevels .native-spy').count()>=3,`${width}: native SPY retained above converted levels`);
 check(await page.evaluate(()=>{const c=document.querySelector('#gLevels .lv-cw .price-stack');return c.querySelector('.es-under').textContent===gESLabel_(GAMMA,GAMMA.spy.call_wall_x) && c.querySelector('.native-spy').textContent==='SPY '+GAMMA.spy.call_wall.toFixed(2);}),`${width}: SPY wall converts through its recorded SPX equivalent`);
 const bounds=await page.locator('#gLine svg').boundingBox();await page.locator('#gLine svg').dispatchEvent('pointermove',{clientX:bounds.x+bounds.width*.5,clientY:bounds.y+bounds.height*.4});
 check(await page.locator('#gLine .hv').textContent().then(t=>t.includes('SPY ') && t.includes('SPX ') && t.includes('ES ≈ ') && t.includes('الصافي')),`${width}: hover stacks SPY/SPX/ES and retains GEX`);
 if(width===430)await page.locator('#gLevels').screenshot({path:'.test-output/screenshots/mirsad-spy-es-430.png'});
 check(await page.locator('#gChart .gr .price-stack .es-under').count()===await page.locator('#gChart .gr').count(),`${width}: every strike has ES on the next line`);
 await page.locator('#gCtl [data-a="CMP"]').click();
 check(await page.locator('#gCmp .price-stack .es-under').count()>=4,`${width}: comparison table has ES under each asset level`);
 await page.locator('#gCtl [data-a="SPX"]').click();
 const esBefore=await page.evaluate(()=>GAMMA.es);await page.evaluate(()=>{GAMMA.es=null;renderGamma_();});
 check(await page.locator('#gLevels .price-stack .es-under').first().innerText()==='ES غير متاح',`${width}: missing ES reference does not hide SPX levels`);
 check(await page.locator('#gHeatmap .heat-table td[data-gex]').count()>0,`${width}: missing ES reference does not hide heatmap data`);
 await page.evaluate(e=>{GAMMA.es=e;renderGamma_();},esBefore);
 check(await page.locator('#gPriceMap').innerText().then(t=>t.includes('Gamma Regime معطلة')),`${width}: no unsupported regime`);
 const sel=page.locator('#gPriceMap select');await sel.selectOption('SPY');
 check(await page.locator('#gPriceMap svg').count()===1,`${width}: SPY chart`);
 await sel.selectOption('Combined');
 check(await page.locator('#gPriceMap svg').count()===1,`${width}: Combined chart`);
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${width}: gamma scroll confined`);
 if(width===430||width===1366){
  await page.evaluate(()=>{const m=document.createElement('div');m.textContent='اختبار الواجهة — بيانات توضيحية وليست قراءة سوق';m.style.cssText='background:#6c4c00;color:white;padding:10px;text-align:center;font-size:16px;margin-bottom:14px';document.querySelector('.wrap').prepend(m);});
  await sel.selectOption('SPX');
  await page.locator('#gHeatmap').screenshot({path:`.test-output/screenshots/mirsad-heatmap-${width}.png`});
  await page.locator('#gLevels').screenshot({path:`.test-output/screenshots/mirsad-es-levels-${width}.png`});
  await page.screenshot({path:`.test-output/screenshots/mirsad-final-gamma-${width}.png`,fullPage:true});
  await page.evaluate(()=>{showTab('today');window.scrollTo(0,0);});
  if(width<900) await page.locator('#pulseDetails').evaluate(n=>n.open=false);
  await page.screenshot({path:`.test-output/screenshots/mirsad-final-today-${width}.png`,fullPage:true});
  await page.screenshot({path:`.test-output/screenshots/mirsad-today-viewport-${width}.png`});
 }
 await page.evaluate(()=>showTab('gamma'));
 if(!await page.locator('#gammaDiagnostics').evaluate(n=>n.open))await page.locator('#gammaDiagnostics summary').click();
 check(await page.locator('#gChart').isVisible(),`${width}: retained strike chart expands`);
 const originalRows=await page.evaluate(()=>JSON.stringify(GAMMA.strikes));
 const independentHistory=await page.evaluate(()=>GAMMA.price_history);
 await page.evaluate(()=>{window.originalMapFunction=renderPriceMap_;renderPriceMap_=()=>{throw new Error('TEST optional map error');};renderGamma_();});
 check(await page.locator('#gLevels').isVisible(),`${width}: original levels survive optional map exception`);
 check(await page.evaluate(()=>JSON.stringify(GAMMA.strikes))===originalRows,`${width}: optional map never alters original strikes`);
 await page.evaluate(()=>{renderPriceMap_=window.originalMapFunction;});
 // Invalid/old SPY must never leave a previous chart overlay behind.
 await page.evaluate(()=>{GAMMA.spy.snapshot_utc='2026-10-18T14:00:00Z';gammaMapAsset='SPY';renderPriceMap_(GAMMA);});
 check(await page.locator('#gPriceMap').innerText().then(t=>t.includes('المستويات معطلة')),`${width}: stale SPY blocked`);
 check(await page.evaluate(()=>gData_(GAMMA,'SPY','all').rows.length>0),`${width}: original SPY remains available under original rules`);
 if(width===430){
  let releaseOptional;const held=new Promise(r=>releaseOptional=r);
  const hold=async route=>{await held;await route.fulfill({json:null});};
  await page.route('**/map.json*',hold);
  await page.evaluate(()=>loadGamma_());
  check(await page.evaluate(()=>GAMMA && GAMMA.ok && GAMMA.strikes.length>0),'Original Gamma resolves without waiting for optional map responses');
  releaseOptional();await page.unroute('**/map.json*',hold);
 }
 if(width===430){
  const history=independentHistory;
  await page.route('**/gamma.json*',r=>r.fulfill({json:{ok:false,reason:'TEST source unavailable'}}));
  await page.route('**/price.json*',r=>r.fulfill({json:history}));
  await page.evaluate(()=>loadGamma_());
  await page.waitForFunction(()=>GAMMA && !GAMMA.ok && GAMMA.price_history && GAMMA.price_history.ok);
  check(await page.evaluate(()=>!GAMMA.ok && GAMMA.price_history.ok),'Independent price response loads while gamma API fails');
  check(await page.locator('#gPriceMap svg').count()===1,'Independent price chart remains visible');
 }
 await page.evaluate(()=>{GAMMA.ok=false;gammaMapAsset='SPX';renderPriceMap_(GAMMA);});
 check(await page.locator('#gPriceMap svg').count()===1,`${width}: price survives unavailable gamma`);
 await page.evaluate(()=>{GAMMA.price_history.ok=false;renderPriceMap_(GAMMA);});
 check(await page.locator('#gPriceMap svg').count()===0,`${width}: missing history clears chart`);
 await page.evaluate(()=>{GAMMA=null;renderPriceMap_(GAMMA);});
 check(await page.locator('#gPriceMap').innerText().then(t=>t.includes('شارت السعر غير متاح')),`${width}: no data empty state`);
 await page.close();
}
check(errors.length===0,'No uncaught browser errors: '+errors.join('; '));
}finally{await browser.close();server.close();fs.writeFileSync('.test-output/ui-checks.json',JSON.stringify(logs,null,2));}
console.log(`${logs.filter(r=>r.pass).length} browser checks passed`);
})().catch(e=>{console.error(e);server.close();process.exitCode=1});
