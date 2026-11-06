"""Bounded, evidence-preserving aggregates through the existing native tool."""
import copy
import json
from pathlib import Path
import subprocess
import unittest

from backend import afsim_state, agent_tools


class ChangeSummaryTests(unittest.TestCase):
    def test_split_receipts_keep_food_ammo_and_transport_mass_distinct(self):
        records=[self.resource_record(1,0,4,food_received=8,ammo_received=0,
                     source='afsim-native-teaching-1',delivery_basis='native_mass_equivalent_split_stock'),
                 self.resource_record(2,2,1,food_received=2,ammo_received=0,
                     source='dsh_model_estimate',delivery_basis='declared_mass_equivalent_split_stock')]
        value=self.read(self.session(records))['units'][0]['logistics_workload']
        self.assertEqual(value['totals']['delivery']['known_sum'],5)
        self.assertEqual(value['totals']['food_received']['known_sum'],10)
        self.assertEqual(value['totals']['ammo_received']['known_sum'],0)
        self.assertEqual(value['totals']['food_received']['missing_receipts'],0)

    def test_legacy_package_does_not_fabricate_explicit_classified_receipts(self):
        record=self.resource_record(1,2,2,source='native',delivery_basis='native_gross_receipt')
        value=self.read(self.session([record]))['units'][0]['logistics_workload']
        self.assertIsNone(value['totals']['food_received']['known_sum'])
        self.assertEqual(value['totals']['food_received']['missing_receipts'],1)

    def test_stop_counts_have_canonical_meanings_without_guessing_unknown_codes(self):
        from gentactix import combat_effects
        receipts=[{'turn':1,'action':'bombard','fire_stop_reason':6},
                  {'turn':1,'action':'fire','fire_stop_reason':8},
                  {'turn':3,'action':'fire','fire_stop_reason':8},
                  {'turn':4,'action':'hold','fire_stop_reason':99}]
        s=self.session([self.record(i,[self.change(formation={'before':{},'after':{'last_execution':r}})])
                        for i,r in enumerate(receipts,1)])
        before=copy.deepcopy(s);value=self.read(s)
        self.assertEqual(value['units'][0]['execution']['fire_stop_counts'],{'6':1,'8':1,'99':1})
        self.assertEqual(value['fire_stop_reasons'],{str(k):v for k,v in combat_effects.FIRE_STOPS.items()})
        self.assertNotIn('99',value['fire_stop_reasons']);self.assertEqual(s,before)

    def resource_record(self,turn,food,delivery,**extra):
        record=self.record(turn,[self.change(logistics={'before':{'food':80,'ammo':80},'after':{'food':80,'ammo':80}})])
        record['after']={'mission':{'turn':turn,'ledger':[{'unit':'unit','food_spent':food,'ammo_spent':0,'delivery':delivery,**extra}]}}
        return record

    def test_gross_food_workload_is_not_inferred_from_net_stock_changes(self):
        records=[self.resource_record(1,4,2,source='native',delivery_basis='native_gross_receipt'),
                 self.resource_record(2,2,2,source='native',delivery_basis='native_gross_receipt')]
        value=self.read(self.session(records))['units'][0]['logistics_workload']
        self.assertEqual(value['totals']['food_spent']['known_sum'],6)
        self.assertEqual(value['totals']['delivery']['known_sum'],4)
        self.assertEqual(value['source_counts'],{'native':2})
        self.assertEqual(value['totals']['food_spent']['missing_receipts'],0)

    def test_old_net_estimate_is_not_counted_as_gross_arrival(self):
        record=self.resource_record(1,2,3,source='dsh_model_estimate')
        value=self.read(self.session([record]))['units'][0]['logistics_workload']
        self.assertIsNone(value['totals']['delivery']['known_sum'])
        self.assertEqual(value['basis_counts'],{'legacy_net_estimate':1})

    def test_model_estimates_missing_and_stale_workload_ledgers_remain_distinct(self):
        records=[self.resource_record(1,2,1,source='dsh_model_estimate',delivery_basis='declared_gross_estimate'),
                 self.record(2,[self.change()]),self.resource_record(3,9,9)]
        records[2]['after']['mission']['turn']=2
        value=self.read(self.session(records))['units'][0]['logistics_workload']
        self.assertEqual(value['totals']['food_spent'],{'known_sum':2,'known_receipts':1,'missing_receipts':2})
        self.assertEqual(value['source_counts'],{'dsh_model_estimate':1})
        self.assertEqual(value['missing_or_stale_ledgers'],2)

    def test_duplicate_unit_ledger_cannot_be_summed_twice(self):
        record=self.resource_record(1,2,1);record['after']['mission']['ledger']*=2
        with self.assertRaisesRegex(ValueError,'重复'):
            self.read(self.session([record]))

    def test_old_native_gross_ledger_needs_effects_provenance(self):
        record=self.resource_record(1,4,2)
        record['after']['afsim']={'effects_source':'afsim-native-teaching-1'}
        value=self.read(self.session([record]))['units'][0]['logistics_workload']
        self.assertEqual(value['totals']['delivery']['known_sum'],2)
        self.assertEqual(value['source_counts'],{'afsim-native-teaching-1':1})

    def test_afsim_label_alone_does_not_prove_gross_delivery_semantics(self):
        record=self.resource_record(1,4,2);record['after']['afsim']={'source':'motion-only'}
        value=self.read(self.session([record]))['units'][0]['logistics_workload']
        self.assertIsNone(value['totals']['delivery']['known_sum'])
        self.assertEqual(value['basis_counts'],{'unknown':1})

    def change(self,name='unit',team='red',**fields):
        return {'team':team,'name':name,'fields':fields,'moved_km':0,'status':'changed'}

    def session(self,records):
        return {'id':'a123456789ab','turn_count':max((r['turn'] for r in records),default=0),
                'role_epoch':0,'war_state':{'current_time':'1938-03-24 12:00'},'trajectory':records}

    def record(self,turn,changes):
        return {'id':'turn'+str(turn),'turn':turn,'epoch':0,'changes':changes,
                'clock':{'status':'verified','actual_minutes':15}}

    def read(self,s,**args):
        return afsim_state.changes(s,{'mode':'aggregate','since_turn':0,**args})

    def test_classified_endpoints_unknowns_and_chronological_direction(self):
        a=self.change(personnel={'before':{'current':100,'casualties':0,'killed':None},
            'after':{'current':90,'casualties':10,'killed':2,'wounded':8}})
        b=self.change(personnel={'before':{'current':90,'casualties':10,'killed':2,'wounded':8},
            'after':{'current':85,'casualties':15,'killed':3,'wounded':12}})
        s=self.session([self.record(2,[b]),self.record(1,[a])]);old=copy.deepcopy(s)
        p=self.read(s);row=p['units'][0]
        self.assertEqual(row['metrics']['personnel.current']['net_change'],-15)
        self.assertEqual(row['metrics']['personnel.casualties']['net_change'],15)
        self.assertIsNone(row['metrics']['personnel.killed']['before'])
        self.assertIsNone(row['metrics']['personnel.killed']['net_change'])
        self.assertEqual(row['metrics']['personnel.killed']['after'],3)
        self.assertEqual(row['metrics']['personnel.wounded']['after'],12)
        window=self.read(s,since_turn=1)['units'][0]['metrics']['personnel.killed']
        self.assertEqual((window['before'],window['after'],window['net_change']),(2,3,1))
        self.assertEqual(s,old)

    def test_default_aggregate_includes_first_turn_while_default_detail_stays_recent(self):
        records=[self.record(i,[self.change(formation={'before':{},'after':{'last_execution':{
            'turn':i,'action':'bombard','shots':i*10,'fire_cycles':i}}})]) for i in range(1,4)]
        session=self.session(records);before=copy.deepcopy(session)
        total=afsim_state.changes(session,{'mode':'aggregate'})
        self.assertEqual(total['query']['since_turn'],0)
        self.assertEqual(total['units'][0]['execution']['totals']['artillery_shells_fired']['known_sum'],60)
        self.assertEqual(afsim_state.changes(session)['query']['since_turn'],2)
        self.assertEqual(session,before)

    def test_partial_aggregate_discloses_exclusive_lower_bound_and_missing_first_turn(self):
        session=self.session([self.record(i,[self.change()]) for i in range(1,4)])
        full=self.read(session);partial=self.read(session,since_turn=1)
        self.assertEqual(full['window'],{'since_turn_exclusive':0,'through_turn_inclusive':3,
            'first_requested_turn':1,'includes_first_turn':True,'full_session':True})
        self.assertEqual(partial['window'],{'since_turn_exclusive':1,'through_turn_inclusive':3,
            'first_requested_turn':2,'includes_first_turn':False,'full_session':False})
        self.assertEqual(partial['coverage']['requested_turns'],2)

    def test_equipment_repair_is_not_destroyed_and_stocks_are_net_changes(self):
        equipment=lambda op,damage:[{'category':'armor','operational':op,'damaged':damage,'destroyed':0,'committed':6}]
        s=self.session([self.record(1,[self.change(equipment={'before':equipment(5,1),'after':equipment(6,0)},
            formation={'before':{'shells':20},'after':{'shells':20,'last_execution':{
                'turn':1,'action':'bombard','shots':10,'received_shells':10,'source':'native'}}})])])
        p=self.read(s)['units'][0]
        self.assertEqual(p['metrics']['equipment.armor.operational']['net_change'],1)
        self.assertEqual(p['metrics']['equipment.armor.damaged']['net_change'],-1)
        self.assertEqual(p['metrics']['equipment.armor.destroyed']['net_change'],0)
        self.assertEqual(p['metrics']['formation.shells']['net_change'],0)
        self.assertEqual(p['execution']['totals']['shots']['known_sum'],10)
        self.assertEqual(p['execution']['totals']['received_shells']['known_sum'],10)

    def test_artillery_projectiles_do_not_mix_with_direct_fire_cycle_counters(self):
        receipts=[{'action':'fire','shots':3,'fire_cycles':3,'small_arms_rounds_estimate':4000},
                  {'action':'bombard','shots':16,'fire_cycles':2,'small_arms_rounds_estimate':0},
                  {'action':'hold','shots':0,'fire_cycles':0,'small_arms_rounds_estimate':0}]
        s=self.session([self.record(i,[self.change(formation={'before':{},'after':{'last_execution':{'turn':i,**r}}})]) for i,r in enumerate(receipts,1)])
        p=self.read(s)['units'][0]['execution']['totals']
        self.assertEqual(p['shots']['known_sum'],19)
        self.assertEqual(p['artillery_shells_fired']['known_sum'],16)
        self.assertEqual(p['fire_cycles']['known_sum'],5)
        self.assertEqual(p['small_arms_rounds_estimate']['known_sum'],4000)

    def test_stale_and_missing_receipts_do_not_turn_into_zero_totals(self):
        rs=[{'turn':1,'action':'fire','active_fire_s':600,'received_shells':0},
            {'turn':1,'action':'fire','active_fire_s':600,'received_shells':99},
            {'turn':3,'action':'hold'}]
        s=self.session([self.record(i,[self.change(formation={'before':{},'after':{'last_execution':r}})]) for i,r in enumerate(rs,1)])
        p=self.read(s)['units'][0]['execution']
        self.assertEqual(p['valid_receipts'],2);self.assertEqual(p['missing_or_stale_receipts'],1)
        self.assertEqual(p['totals']['active_fire_s'],{'known_sum':600,'known_receipts':1,'missing_receipts':2})
        self.assertEqual(p['totals']['received_shells'],{'known_sum':0,'known_receipts':1,'missing_receipts':2})
        self.assertIsNone(p['totals']['shots']['known_sum'])
        self.assertEqual(p['action_counts'],{'fire':1,'hold':1})

    def test_complete_unit_paging_pins_mode_and_world(self):
        s=self.session([self.record(1,[self.change('u'+str(i)) for i in range(19)])])
        a=self.read(s,limit=16);b=afsim_state.changes(s,a['next_args'])
        self.assertEqual(a['total_units'],19);self.assertEqual(a['total_changes'],19)
        self.assertEqual(a['next_args']['mode'],'aggregate')
        self.assertEqual(len(a['units']+b['units']),19);self.assertIsNone(b['next_args'])
        self.assertEqual(len({r['name'] for r in a['units']+b['units']}),19)
        with self.assertRaisesRegex(ValueError,'版本'):
            afsim_state.changes(s,{**a['next_args'],'mode':'changes'})
        s['war_state']['current_time']='different'
        with self.assertRaisesRegex(ValueError,'版本'):afsim_state.changes(s,a['next_args'])

    def test_missing_turns_and_unknown_duration_are_visible(self):
        s=self.session([self.record(1,[self.change()]),self.record(3,[self.change()])]);s['trajectory'][1]['clock']={}
        p=self.read(s)
        self.assertEqual(p['coverage']['missing_turn_count'],1)
        self.assertFalse(p['coverage']['all_requested_turns_recorded'])
        self.assertEqual(p['coverage']['recorded_turns'],2)
        self.assertEqual(p['coverage']['known_duration_seconds'],900)
        self.assertEqual(p['coverage']['unknown_duration_turns'],1)
        self.assertEqual(self.read(s,through_turn=1)['coverage']['missing_turn_count'],0)

    def test_duplicate_turns_or_same_named_changes_are_not_double_counted(self):
        for records in ([self.record(1,[self.change()]),self.record(1,[self.change()])],
                        [self.record(1,[self.change(),self.change()])]):
            with self.subTest(records=records),self.assertRaisesRegex(ValueError,'重复'):
                self.read(self.session(records))

    def test_discontinuous_numeric_evidence_is_flagged(self):
        s=self.session([self.record(1,[self.change(logistics={'before':{'ammo':100},'after':{'ammo':80}})]),
            self.record(2,[self.change(logistics={'before':{'ammo':60},'after':{'ammo':50}})])])
        p=self.read(s)['units'][0]['metrics']['logistics.ammo']
        self.assertEqual(p['net_change'],-50);self.assertFalse(p['recorded_sequence_continuous'])

    def test_legacy_unnamed_category_is_preserved_without_inventing_a_weapon_class(self):
        old=[{'name':'教学支援装备','committed':4,'operational':4,'damaged':0,'destroyed':0}]
        new=[{**old[0],'operational':3,'destroyed':1}]
        s=self.session([self.record(1,[self.change(equipment={'before':old,'after':new})])])
        p=self.read(s)['units'][0]['metrics']
        self.assertEqual(p['equipment.unclassified:教学支援装备.destroyed']['net_change'],1)
        self.assertNotIn('equipment.artillery.destroyed',p)

    def test_duplicate_equipment_categories_cannot_silently_overwrite_counts(self):
        gear=[{'category':'armor','operational':4},{'category':'armor','operational':5}]
        s=self.session([self.record(1,[self.change(equipment={'before':gear,'after':gear})])])
        with self.assertRaisesRegex(ValueError,'重复分类'):self.read(s)

    def test_summary_size_does_not_grow_with_turn_count_or_verbose_sources(self):
        records=[]
        for i in range(1,101):
            c=self.change(personnel={'before':{'current':1000-i+1,'source':'SECRET-SOURCE'*1000},'after':{'current':1000-i}},
                formation={'before':{},'after':{'last_execution':{'turn':i,'action':'hold','active_fire_s':0,'source':'native'}}})
            r=self.record(i,[c]);r['before']={'secret':'NO-WORLD'*10000};records.append(r)
        s=self.session(records);p=self.read(s);raw=json.dumps(p,ensure_ascii=False)
        self.assertNotIn('SECRET-SOURCE',raw);self.assertNotIn('NO-WORLD',raw)
        self.assertLess(len(raw),6500);self.assertEqual(p['coverage']['recorded_turns'],100)
        self.assertEqual(p['units'][0]['execution']['totals']['active_fire_s']['known_sum'],0)

    def test_native_schema_and_existing_dispatch_support_the_same_query(self):
        script="import {definitions} from './plugins/dsh-afsim/protocol.mjs'; process.stdout.write(JSON.stringify(definitions.find(x=>x[0]==='get_afsim_changes')[2]));"
        p=subprocess.run(['node','--input-type=module','-e',script],cwd=Path(__file__).resolve().parent,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr);schema=json.loads(p.stdout)
        self.assertEqual(schema['mode']['enum'],['changes','aggregate'])
        s=self.session([self.record(1,[self.change()])])
        result=agent_tools.execute_tool_call(s,s['war_state'],{'tool':'get_afsim_changes','args':{'mode':'aggregate','since_turn':0}})
        self.assertTrue(result['ok']);self.assertEqual(result['mode'],'aggregate')

    def test_new_mode_validation_keeps_legacy_detail_contract(self):
        s=self.session([self.record(1,[self.change()])])
        self.assertIn('changes',afsim_state.changes(s))
        self.assertNotIn('units',afsim_state.changes(s))
        for args in ({'mode':'summary'},{'mode':True},{'mode':'aggregate','since_turn':2,'through_turn':1}):
            with self.subTest(args=args),self.assertRaises(ValueError):afsim_state.changes(s,args)


if __name__=='__main__':unittest.main()
