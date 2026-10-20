"""Compatibility contract: preserve the user's gamma.py and isolate optional enrichment."""
import copy,json,tempfile,unittest,types,importlib.util,hashlib
from pathlib import Path
from datetime import datetime,timedelta,timezone,date
from unittest.mock import patch
import gamma
import gamma_map

T = datetime(2026,10,19,14,0,tzinfo=timezone.utc)

def raw_chain(asset='SPX', timestamp=None):
    spot=700 if asset=='SPY' else 7000
    rows=[]
    for i in range(-24,25):
        k=spot+i*(1 if asset=='SPY' else 5)
        for kind in 'CP':
            rows.append({'option': ('SPY' if asset=='SPY' else 'SPXW')+'261020'+kind+f'{int(k*1000):08d}',
                         'gamma':.01,'iv':.2,'open_interest':1000+(300 if kind=='C' and i>0 else 0)})
    return {'timestamp':timestamp or T.isoformat(),'data':{'current_price':spot,'options':rows}}

def spy_ref(at=T):
    return {'ratio':10.,'spy_ref':700.,'spx_ref':7000.,'ref_time_utc':at.isoformat(),'ref_gap_min':10.,'mode':'live'}


REFERENCE=Path(__file__).resolve().parent/'reference/gamma_original.py'
spec=importlib.util.spec_from_file_location('gamma_original',REFERENCE)
original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)

class GammaCompatibility(unittest.TestCase):
    def build(self,raw=None,module=gamma):
        return module.build(raw or raw_chain(),fetched=T+timedelta(minutes=10),with_es=False,with_spy=False)

    def test_original_file_byte_identical(self):
        self.assertEqual(Path(gamma.__file__).read_bytes(),REFERENCE.read_bytes())

    def test_collection_inputs_unchanged(self):
        for name in ('URLS','SPY_URLS','UA','FRESH_MIN','LATE_MIN','SPY_MAX_GAP_MIN'):
            self.assertEqual(getattr(gamma,name),getattr(original,name))

    def test_full_original_snapshot_unchanged(self):
        self.assertEqual(self.build(),self.build(module=original))

    def test_old_missing_iv_not_rejected(self):
        raw=raw_chain()
        for o in raw['data']['options']:o.pop('iv')
        self.assertEqual(self.build(raw),self.build(raw,module=original))

    def test_preopen_rules_unchanged(self):
        raw=raw_chain(timestamp='2026-10-19T12:00:00+00:00')
        self.assertEqual(self.build(raw),self.build(raw,module=original))

    def test_original_spy_output_unchanged(self):
        args=(T,T+timedelta(minutes=10),T.date())
        kw=dict(ref=spy_ref(),raw=raw_chain('SPY'))
        self.assertEqual(gamma.build_spy(*args,**kw),original.build_spy(*args,**kw))

    def test_original_flip_is_preserved(self):
        result=self.build(); enriched=gamma_map.enrich(result)
        self.assertEqual(enriched['gamma_flip'],result['gamma_flip'])
        self.assertEqual(gamma.compute(*gamma.parse_chain(raw_chain())[::2],ref_utc=T)['gamma_flip'],original.compute(*original.parse_chain(raw_chain())[::2],ref_utc=T)['gamma_flip'])

    def test_enrichment_never_mutates_input_or_original_fields(self):
        snap=self.build();before=copy.deepcopy(snap);out=gamma_map.enrich(snap)
        self.assertEqual(snap,before)
        for key in before:self.assertEqual(out[key],before[key])

    def test_spy_original_fields_survive(self):
        snap=self.build();snap['spy']=gamma.build_spy(T,T,T.date(),ref=spy_ref(),raw=raw_chain('SPY'))
        before=copy.deepcopy(snap);out=gamma_map.enrich(snap)
        for key in before['spy']:self.assertEqual(out['spy'][key],before['spy'][key])

    def test_stale_spy_only_disables_combined(self):
        snap=self.build();snap['spy']=gamma.build_spy(T,T,T.date(),ref=spy_ref(),raw=raw_chain('SPY'))
        snap['spy']['ref_time_utc']='2026-10-18T14:00:00+00:00'
        out=gamma_map.enrich(snap)
        self.assertTrue(out['spy']['ok']);self.assertTrue(out['spy']['strikes']);self.assertFalse(out['combined']['ok'])

    def test_no_verified_regime_claim(self):
        self.assertFalse(gamma_map.enrich(self.build())['regime_model']['valid'])

    def test_zones_are_derived(self):
        rows=[{'k':k,'net':net} for k,net in [(1,1),(2,10),(3,11),(4,0),(5,-12),(6,-13),(7,1),(20,14)]]
        for z in gamma_map.zones(rows):
            self.assertIn(z['low'],[r['k'] for r in rows]);self.assertIn(z['high'],[r['k'] for r in rows])
            self.assertFalse(z['low']<20 and z['high']==20)
        self.assertEqual(gamma_map.zones([{'k':1,'net':0}]),[])

    def test_missing_spy_is_not_added(self):
        out=gamma_map.enrich(self.build())
        self.assertFalse(out['spy']['ok']);self.assertFalse(out['combined']['ok'])

    def test_disk_snapshot_unchanged_when_enrichment_fails(self):
        with tempfile.TemporaryDirectory() as root:
            file=Path(root)/'latest.json';file.write_text(json.dumps(self.build()),encoding='utf-8');before=file.read_bytes()
            with patch('gamma_map.enrich',side_effect=RuntimeError('optional error')),patch('gamma_map.price_history',return_value={'ok':False,'points':[]}):
                self.assertEqual(gamma_map.main(['--root',root]),0)
            self.assertEqual(file.read_bytes(),before)

    def test_disk_snapshot_unchanged_when_enrichment_succeeds(self):
        with tempfile.TemporaryDirectory() as root:
            file=Path(root)/'latest.json';file.write_text(json.dumps(self.build()),encoding='utf-8');before=file.read_bytes()
            with patch('gamma_map.price_history',return_value={'ok':True,'points':[1,2]}):
                gamma_map.main(['--root',root])
            self.assertEqual(file.read_bytes(),before);self.assertTrue((Path(root)/'map.json').exists())

    def test_independent_price_without_original_snapshot(self):
        with tempfile.TemporaryDirectory() as root,patch('gamma_map.price_history',return_value={'ok':True,'points':[1,2]}):
            self.assertEqual(gamma_map.main(['--root',root]),0)
            self.assertFalse((Path(root)/'latest.json').exists());self.assertTrue((Path(root)/'price.json').exists())

    def test_optional_workflow_cannot_fail_collection_step(self):
        workflow=(Path(__file__).parent/'.github/workflows/gamma.yml').read_text(encoding='utf-8')
        self.assertIn('continue-on-error: true\n        run: python gamma_map.py',workflow)
        self.assertIn('needs: gamma',workflow)
        self.assertIn('timeout-minutes: 3',workflow)
        core=workflow.split('  gamma_map_optional:')[0]
        import zipfile
        reference=(Path(__file__).parent/'reference/gamma_workflow_original.yml').read_text(encoding='utf-8')
        self.assertEqual(core.strip(),reference.strip())
        self.assertIn('python gamma.py --collect',workflow)

    def test_heatmap_history_reads_only_observed_archive(self):
        with tempfile.TemporaryDirectory() as root:
            archive=Path(root)/'archive/2026-10-19';archive.mkdir(parents=True)
            before=self.build();before['snapshot_utc']=(T-timedelta(minutes=20)).isoformat();before['fetched_utc']=(T-timedelta(minutes=10)).isoformat()
            before['spy']={'ok':True,'spot':700,'ratio':10}
            file=archive/'0950.json';file.write_text(json.dumps(before),encoding='utf-8');original_bytes=file.read_bytes()
            current=self.build();current['spy']=gamma.build_spy(T,T,T.date(),ref=spy_ref(),raw=raw_chain('SPY'))
            out=gamma_map.heatmap_history(root,current,T+timedelta(hours=1))
            self.assertEqual(len(out['snapshots']),2)
            self.assertNotIn('spy',out['snapshots'][0])
            self.assertTrue(out['snapshots'][1]['spy']['strikes'])
            self.assertEqual(file.read_bytes(),original_bytes)

    def test_heatmap_does_not_backfill_future_snapshots(self):
        with tempfile.TemporaryDirectory() as root:
            snapshot=self.build();snapshot['fetched_utc']=(T+timedelta(days=1)).isoformat()
            self.assertEqual(gamma_map.heatmap_history(root,snapshot,T)['snapshots'],[])

    def test_heatmap_history_preserves_known_spy_rows(self):
        with tempfile.TemporaryDirectory() as root:
            snapshot=self.build();snapshot['spy']=gamma.build_spy(T,T,T.date(),ref=spy_ref(),raw=raw_chain('SPY'))
            first=gamma_map.heatmap_history(root,snapshot,T+timedelta(hours=1))
            (Path(root)/'heatmap.json').write_text(json.dumps(first),encoding='utf-8')
            legacy_archive=copy.deepcopy(snapshot);legacy_archive['spy'].pop('strikes')
            out=gamma_map.heatmap_history(root,legacy_archive,T+timedelta(hours=1))
            self.assertEqual(out['snapshots'][0]['spy']['strikes'],first['snapshots'][0]['spy']['strikes'])

if __name__=='__main__':unittest.main()
