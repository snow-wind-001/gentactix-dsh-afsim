"""Complete, version-pinned change paging through the existing DSH tool."""
import copy
import json
from pathlib import Path
import subprocess
import unittest

from backend import afsim_state


class ChangePagingTests(unittest.TestCase):
    def session(self,count=19):
        return {'id':'a123456789ab','turn_count':2,'role_epoch':0,'war_state':{'current_time':'1938-03-31 01:00'},
                'trajectory':[{'id':'turn2','turn':2,'changes':[{'team':'red' if i%2==0 else 'blue','name':f'unit{i}',
                    'fields':{'logistics':{'before':{'ammo':80},'after':{'ammo':80-i}}},'moved_km':0} for i in range(count)]}]}

    def test_every_change_is_reachable_without_duplication(self):
        s=self.session();before=copy.deepcopy(s);page=afsim_state.changes(s,{'limit':16})
        self.assertEqual(page['total_changes'],19);self.assertEqual(page['next_offset'],16)
        last=afsim_state.changes(s,page['next_args'])
        self.assertEqual([x['change']['name'] for x in page['changes']+last['changes']],[f'unit{i}' for i in range(19)])
        self.assertEqual(len(last['changes']),3);self.assertIsNone(last['next_args']);self.assertFalse(last['limit_reached'])
        self.assertEqual(page['view_version'],last['view_version']);self.assertEqual(s,before)

    def test_exact_page_boundary_does_not_advertise_nonexistent_next_page(self):
        p=afsim_state.changes(self.session(16),{'limit':16})
        self.assertFalse(p['limit_reached']);self.assertIsNone(p['next_offset'])

    def test_paging_rejects_missing_or_stale_versions(self):
        s=self.session();p=afsim_state.changes(s,{'limit':8})
        with self.assertRaisesRegex(ValueError,'版本'):afsim_state.changes(s,{'offset':8,'limit':8})
        s['war_state']['current_time']='1938-03-31 01:30'
        with self.assertRaisesRegex(ValueError,'版本'):afsim_state.changes(s,p['next_args'])

    def test_changed_trajectory_is_detected_even_when_current_world_is_same(self):
        s=self.session();p=afsim_state.changes(s,{'limit':8});s['trajectory'][0]['changes'][17]['fields']['logistics']['after']['ammo']=0
        with self.assertRaisesRegex(ValueError,'版本'):afsim_state.changes(s,p['next_args'])

    def test_turn_window_and_invalid_queries_are_explicit(self):
        s=self.session();s['trajectory'].insert(0,{'id':'turn1','turn':1,'changes':[{'name':'old','team':'red','fields':{}}]})
        p=afsim_state.changes(s,{'since_turn':0,'through_turn':1});self.assertEqual(p['total_changes'],1)
        self.assertEqual(p['changes'][0]['change']['name'],'old')
        for args in ({'through_turn':3},{'offset':-1},{'offset':True},{'limit':17},{'since_turn':False},{'unexpected':0}):
            with self.subTest(args=args),self.assertRaises(ValueError):afsim_state.changes(s,args)

    def test_page_response_does_not_reintroduce_full_snapshots_or_long_sources(self):
        s=self.session();r=s['trajectory'][0];r['before']={'secret':'NO-SNAPSHOT'*10000}
        r['changes'][18]['fields']['formation']={'before':{'shells':120,'source':'NO-SOURCE'*2000},'after':{'shells':24}}
        page=afsim_state.changes(s,{'limit':16});tail=afsim_state.changes(s,page['next_args'])
        encoded=json.dumps(tail,ensure_ascii=False)
        self.assertNotIn('NO-SNAPSHOT',encoded);self.assertNotIn('NO-SOURCE',encoded)
        self.assertEqual(tail['changes'][-1]['change']['numeric_deltas']['formation.shells'],{'before':120,'after':24})

    def test_native_schema_advertises_paging_to_the_actual_runtime(self):
        script="import {definitions} from './plugins/dsh-afsim/protocol.mjs'; process.stdout.write(JSON.stringify(definitions.find(x=>x[0]==='get_afsim_changes')[2]));"
        p=subprocess.run(['node','--input-type=module','-e',script],cwd=Path(__file__).resolve().parent,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr);schema=json.loads(p.stdout)
        self.assertEqual(schema['offset']['minimum'],0);self.assertIn('view_version',schema);self.assertIn('through_turn',schema)

    def test_compressed_changes_keep_current_turn_execution_and_zero_delivery_evidence(self):
        s=self.session(1)
        receipt={'turn':2,'action':'fire','source':'combined-arms-teaching-1','fire_cycles':7,
                 'active_fire_s':814,'fire_stop_reason':0,'shots':7,'small_arms_rounds_estimate':3200,
                 'blocked':10,'command_done':1,'distance_milli':80438,'delay_s':138,
                 'received_shells':0,'received_aa_rounds':0,'received_fuel_liters':0,
                 'received_spares':0,'received_materials':0,'supply_receipt_revision':1,
                 'unrelated_verbose_text':'NO-UNBOUNDED-RECEIPT'*1000}
        s['trajectory'][0]['changes'][0]['fields']['formation']={'before':{},'after':{'last_execution':receipt}}
        before=copy.deepcopy(s)
        row=afsim_state.changes(s)['changes'][0]['change']
        self.assertTrue(row['summary_only'])
        expected={k:v for k,v in receipt.items() if k!='unrelated_verbose_text'}
        self.assertEqual(row['execution_receipt'],expected)
        self.assertNotIn('NO-UNBOUNDED-RECEIPT',json.dumps(row))
        self.assertEqual(s,before)

    def test_absent_or_stale_receipts_remain_unknown_in_compressed_changes(self):
        s=self.session(1)
        for receipt in (None,{}, {'turn':1,'action':'fire','active_fire_s':900}, {'turn':2,'action':'hold'}):
            s['trajectory'][0]['changes'][0]['fields']['formation']={'before':{},'after':{
                'source':'NO-SOURCE'*1000,'last_execution':receipt}}
            row=afsim_state.changes(s)['changes'][0]['change']
            if receipt and receipt.get('turn')==2:
                self.assertEqual(row['execution_receipt'],receipt)
                self.assertNotIn('received_shells',row['execution_receipt'])
                self.assertNotIn('active_fire_s',row['execution_receipt'])
            else:
                self.assertNotIn('execution_receipt',row)

    def test_compression_preserves_known_after_counts_without_inventing_unknown_before(self):
        s=self.session(1)
        s['trajectory'][0]['changes'][0]['fields']['personnel']={'before':{'source':'NO-SOURCE'*1000},
            'after':{'killed':11,'wounded':33,'captured':0}}
        row=afsim_state.changes(s)['changes'][0]['change']
        self.assertEqual(row['numeric_deltas']['personnel.killed'],{'before':None,'after':11})
        self.assertEqual(row['numeric_deltas']['personnel.wounded'],{'before':None,'after':33})
        self.assertEqual(row['numeric_deltas']['personnel.captured'],{'before':None,'after':0})


if __name__=='__main__':unittest.main()
