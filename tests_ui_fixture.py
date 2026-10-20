from pathlib import Path
import os,sys,json,shutil
root=Path(__file__).resolve().parent
source=root
os.environ['TEMP']=os.environ['TMP']=str(root/'.test-output/tmp')
(root/'.test-output/tmp').mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(root))
os.chdir(root)
import tests_browser as tb
from tests_gamma_v022 import raw_chain,T,spy_ref
import gamma
import gamma_map
from datetime import timedelta,datetime,timezone
fx=tb.rich(tb.build_fixture());fx['version']='0.22.1'
fixture=root/'.test-output/fixtures';fixture.mkdir(parents=True,exist_ok=True)
for f in ('index.html','expiry-selection.js','es-conversion.js','gamma-map.js','gamma-heatmap.js','layout-v022.css','layout-v022.js','manifest.webmanifest'):
    shutil.copy2(root/f,fixture/f)
shutil.copytree(root/'icons',fixture/'icons',dirs_exist_ok=True)
(fixture/'data.json').write_text(json.dumps(fx,ensure_ascii=False),encoding='utf-8')
def two_sided_fixture(asset='SPX'):
    raw=raw_chain(asset);spot=700 if asset=='SPY' else 7000
    for option in raw['data']['options']:
        if 'P' in option['option'][-9:-8] and int(option['option'][-8:])/1000<spot:option['open_interest']+=200
    return raw
snap=gamma.build(two_sided_fixture(),fetched=T+timedelta(minutes=10),with_es=False)
snap['spy']=gamma.build_spy(T,T+timedelta(minutes=10),T.date(),ref=spy_ref(),raw=two_sided_fixture('SPY'))
enriched=gamma_map.enrich(snap)
(fixture/'map.json').write_text(json.dumps(enriched,ensure_ascii=False),encoding='utf-8')
pts=[{'time':(T-timedelta(minutes=70-i*5)).isoformat(),'close':6998+i*.35+(i%3-1)*1.2} for i in range(17)]
history={'ok':True,'asset':'SPX','interval':'5m','source':'TEST FIXTURE — بيانات اختبار توضيحية','fetched_utc':snap['fetched_utc'],'points':pts}
(fixture/'price.json').write_text(json.dumps(history,ensure_ascii=False),encoding='utf-8')
snap['es']={'basis':20.25,'es_ref':7020.25,'spx_ref':7000.,'ref_time_utc':(T+timedelta(minutes=9)).isoformat(),'ref_gap_min':1.,'mode':'live'}
(fixture/'gamma.json').write_text(json.dumps(snap,ensure_ascii=False),encoding='utf-8')
print('fixture ready')

import copy
earlier=copy.deepcopy(snap)
earlier['snapshot_utc']=(T-timedelta(minutes=20)).isoformat()
earlier['fetched_utc']=(T-timedelta(minutes=10)).isoformat()
earlier['spy']['snapshot_utc']=(T-timedelta(minutes=20)).isoformat()
heat={'ok':True,'fetched_utc':(T+timedelta(minutes=10)).isoformat(),'snapshots':[earlier,snap]}
(fixture/'heatmap.json').write_text(json.dumps(heat,ensure_ascii=False),encoding='utf-8')
