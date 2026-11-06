"""Synthetic exercises derive from the exact frozen historical calculation."""
import copy
import os
import tempfile
import unittest
from unittest.mock import patch

from gentactix import historical_operations, missions
from tools.qa.historical_operational_fixture import inputs


class SyntheticHistoricalTests(unittest.TestCase):
    def setUp(self):
        from gentactix import synthetic_history
        self.module=synthetic_history
        self.snapshot,params=inputs()
        self.base=historical_operations.definition(self.snapshot,params)
        self.seed=self.module.seed(self.base['historical_calculation'])

    def definition(self,config=None):
        return self.module.definition(self.base['historical_calculation'],config or self.seed['configuration'])

    def test_fractional_historical_food_and_ammo_survive_derivation_unchanged(self):
        snapshot,parameters=inputs()
        parameters['actors']['ww2.cn.division31']['logistics'].update(food=.125,ammo=1.375)
        base=historical_operations.definition(snapshot,parameters);original=copy.deepcopy(base)
        seed=self.module.seed(base['historical_calculation'])
        world=missions.from_definition(self.module.definition(base['historical_calculation'],seed['configuration']))
        self.assertEqual(world['red_units'][0]['logistics'],{'food':.125,'ammo':1.375})
        self.assertEqual(base,original)

    def test_normal_api_preserves_fractional_stocks_from_history_to_saved_synthetic(self):
        from backend import main,scenario_builder as builder,session_store
        from fastapi.testclient import TestClient
        snapshot,parameters=inputs()
        parameters['actors']['ww2.cn.division31']['logistics'].update(food=.125,ammo=1.375)
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder+'/sessions'}), \
                patch.dict(main._SESSIONS,{},clear=True),TestClient(main.app) as client:
            parent=builder.stage_historical(snapshot,parameters,construction={'source':'dsh_native_skill','qa_fixed_input':True},execution_backend='narrative')
            response=client.post('/api/scenarios/from-historical',json={'base_draft_id':parent['id'],'execution_backend':'narrative'})
            self.assertEqual(response.status_code,200,response.text)
            draft=response.json()['draft'];configuration=draft['configuration']
            self.assertEqual(configuration['teams']['red'][0]['food'],.125)
            self.assertEqual(configuration['teams']['red'][0]['ammo'],1.375)
            response=client.post('/api/sessions',json={'scenario':'小数库存连续派生回归',
                'battle':self.base['battle'],'product_mode':'synthetic','scenario_draft_id':draft['id'],
                'synthetic_configuration':configuration,'execution_backend':'narrative','time_step':'30分钟'})
            self.assertEqual(response.status_code,200,response.text);sid=response.json()['session_id']
            response=client.post('/api/sessions/'+sid+'/init')
            self.assertEqual(response.status_code,200,response.text)
            restored,errors=session_store.load_all();self.assertEqual(errors,[])
            self.assertEqual(restored[sid]['war_state']['red_units'][0]['logistics'],{'food':.125,'ammo':1.375})

    def test_default_seed_keeps_all_historical_actors_and_numerical_initial_conditions(self):
        original=copy.deepcopy(self.base)
        with patch('gentactix.combined_arms.definition',side_effect=AssertionError('No CA teaching lookup')):
            derived=self.definition();world=missions.from_definition(derived)
        for side in ('red','blue'):
            for old,new in zip(self.base['initial_state'][side+'_units'],world[side+'_units']):
                for key in ('name','historical_unit_id','type','speed','lat','lng','attack_range','ground_control_radius_km','logistics'):
                    self.assertEqual(new[key],old[key],key)
                for key in ('committed','current','casualties','noncombat_losses'):
                    self.assertEqual(new['personnel'][key],old['personnel'][key])
                self.assertEqual([(e['category'],e['operational']) for e in new['equipment']],[(e['category'],e['operational']) for e in old['equipment']])
                self.assertEqual({k:v for k,v in new['formation'].items() if k!='source'},{k:v for k,v in old['formation'].items() if k!='source'})
        self.assertEqual(derived['time_step'],self.base['time_step'])
        self.assertEqual(derived['combined_rules'],self.base['combined_rules'])
        self.assertEqual(world['historical_initial'],self.snapshot)
        self.assertEqual(self.base,original)
        self.assertTrue(derived['id'].startswith('HS-'))

    def test_reference_is_the_selected_phase_not_campaign_wide_or_generic_forces(self):
        rows=self.seed['basis']['units']
        self.assertEqual({u['id'] for u in rows},set(inputs()[1]['actors']))
        self.assertEqual({u['basis_id'] for side in self.seed['configuration']['teams'].values() for u in side},{r['id'] for r in rows})
        self.assertTrue(all(u['actual_personnel'] is None for u in rows))
        self.assertEqual(self.seed['basis']['phase_id'],'taierzhuang')

    def test_added_formation_inherits_its_selected_origin_but_cannot_pose_as_an_extra_historical_unit(self):
        config=copy.deepcopy(self.seed['configuration'])
        row=copy.deepcopy(config['teams']['blue'][1]);row['name']='蓝方新增演习分队';row['personnel']=700
        row['equipment']['artillery']=12
        config['teams']['blue'].append(row)
        derived=self.definition(config);world=missions.from_definition(derived)
        added=world['blue_units'][-1]
        self.assertNotIn('historical_unit_id',added)
        self.assertEqual(added['source_historical_unit_id'],row['basis_id'])
        self.assertEqual(added['historical_reference']['id'],row['basis_id'])
        self.assertEqual(added['personnel']['committed'],700)
        self.assertEqual(added['formation'].get('motorized'),self.base['initial_state']['blue_units'][1]['formation'].get('motorized'))
        self.assertEqual(added['historical_evidence'],[])
        self.assertIsNone(added['parent_id'])
        self.assertEqual(world['historical_initial'],self.snapshot)
        self.assertEqual(self.module.from_binding(derived['historical_synthetic']),derived)

    def test_cross_team_or_unknown_origin_and_duplicate_names_are_rejected(self):
        for identity in ('invented',self.seed['configuration']['teams']['blue'][0]['basis_id']):
            config=copy.deepcopy(self.seed['configuration']);config['teams']['red'][0]['basis_id']=identity
            with self.assertRaises(ValueError):self.definition(config)
        config=copy.deepcopy(self.seed['configuration']);config['teams']['red'].append(copy.deepcopy(config['teams']['red'][0]))
        with self.assertRaises(ValueError):self.definition(config)

    def test_roster_count_changes_and_modified_personnel_do_not_mutate_facts(self):
        config=copy.deepcopy(self.seed['configuration']);config['teams']['blue'].pop();config['teams']['red'][0]['personnel']=9500
        world=missions.from_definition(self.definition(config))
        self.assertEqual(len(world['blue_units']),1)
        self.assertEqual(world['red_units'][0]['personnel']['committed'],9500)
        self.assertEqual(world['historical_initial'],self.snapshot)
        for side in ('red','blue'):
            bad=copy.deepcopy(config);bad['teams'][side]=[]
            with self.assertRaises(ValueError):self.definition(bad)

    def test_restore_is_self_contained_and_mutated_fact_or_binding_is_rejected(self):
        from gentactix import historical_initial
        derived=self.definition()
        with patch.object(historical_initial,'DATA_ROOT',historical_initial.DATA_ROOT/'absent'):
            restored=self.module.from_binding(derived['historical_synthetic'])
            world=missions.from_definition(restored)
        world['historical_initial']['phase_id']='invented'
        with self.assertRaises(ValueError):missions.validate(world)
        bad=copy.deepcopy(derived['historical_synthetic']);bad['configuration']['historical_basis']['basis_hash']='fake'
        with self.assertRaises(ValueError):self.module.from_binding(bad)

    def test_native_observation_identifies_the_derived_purpose_and_phase_without_full_base(self):
        from backend import afsim_state
        world=missions.from_definition(self.definition())
        view=afsim_state.observation({'id':'a123456789ab','war_state':world,'time_step':'30分钟','turn_count':0})
        summary=view['historical_synthetic']
        self.assertEqual(summary['phase_id'],'taierzhuang')
        self.assertEqual(summary['base_actor_count'],3)
        self.assertEqual(summary['configured_actor_count'],3)
        self.assertFalse(summary['historical_outcome_required'])
        self.assertNotIn('base',summary)

    def test_new_armored_formation_is_motorized_instead_of_inheriting_foot_mobility(self):
        config=copy.deepcopy(self.seed['configuration']);row=copy.deepcopy(config['teams']['red'][0])
        row.update(name='新增装甲演习分队',fuel_liters=0);row['equipment']['armor']=4
        config['teams']['red'].append(row)
        world=missions.from_definition(self.definition(config));unit=world['red_units'][-1]
        self.assertTrue(unit['formation']['motorized'])
        self.assertEqual(unit['formation']['role'],'armor')

    def test_observation_keeps_current_public_command_outcome_bounded_and_not_stale(self):
        from backend import afsim_state
        from gentactix import commands
        world=missions.from_definition(self.definition());world['mission']['turn']=1
        s={'id':'a123456789ab','war_state':world,'time_step':'30分钟','turn_count':1}
        cs=commands.state(s);entry=next(e for e in cs['registry'] if e['team']=='blue')
        cs['receipts']=[{'unit_id':entry['id'],'turn':1,'source':'human','action':'move','status':'completed',
            'reason':'燃油限制，已进入到达容差区。'*100,'rationale':'用户确认的机动命令',
            'goal':{'lat':34.561,'lng':117.73917},'unrelated':'NO-LONG-DECISION'*1000}]
        s['command_state']=cs;before=copy.deepcopy(s)
        row=afsim_state.observation(s,{'ids':[entry['id']]})['units'][0]
        self.assertEqual(row['last_decision']['status'],'completed')
        self.assertEqual(row['last_decision']['goal'],cs['receipts'][0]['goal'])
        self.assertLessEqual(len(row['last_decision']['reason']),400)
        self.assertNotIn('NO-LONG-DECISION',str(row))
        self.assertEqual(s,before)
        cs['receipts'][0]['turn']=0
        self.assertNotIn('last_decision',afsim_state.observation(s,{'ids':[entry['id']]})['units'][0])

    def test_normal_api_derives_from_verified_history_and_creates_a_self_contained_synthetic_session(self):
        from backend import main, scenario_builder as builder, session_store
        from fastapi.testclient import TestClient
        client=TestClient(main.app)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder+'/sessions'}):
            base=builder.stage_historical(self.snapshot,inputs()[1],construction={'source':'dsh_native_skill'},execution_backend='narrative')
            response=client.post('/api/scenarios/from-historical',json={'base_draft_id':base['id'],'execution_backend':'narrative'})
            self.assertEqual(response.status_code,200,response.text)
            result=response.json();draft=result['draft'];config=draft['configuration']
            self.assertEqual(draft['kind'],'historical_synthetic')
            self.assertEqual(draft['historical_base'],base['preview_world']['mission']['definition']['historical_calculation'])
            self.assertEqual(len(config['teams']['blue']),2)
            created=client.post('/api/sessions',json={'scenario':'共同初态派生回归','battle':self.base['battle'],
                'product_mode':'synthetic','scenario_draft_id':draft['id'],'synthetic_configuration':config,
                'execution_backend':'narrative','time_step':'30分钟'})
            self.assertEqual(created.status_code,200,created.text);sid=created.json()['session_id']
            try:
                initialized=client.post(f'/api/sessions/{sid}/init')
                self.assertEqual(initialized.status_code,200,initialized.text)
                world=initialized.json()['war_state'];self.assertEqual(world['historical_initial'],self.snapshot)
                self.assertEqual(world['mission']['id'],draft['mission_id'])
                session_store.validate(session_store.serializable(main._SESSIONS[sid]))
            finally:main._SESSIONS.pop(sid,None)

    def test_edited_configuration_is_revalidated_against_frozen_base_without_current_corpus(self):
        from backend import main, scenario_builder as builder
        from gentactix import historical_initial
        from fastapi.testclient import TestClient
        client=TestClient(main.app)
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder+'/sessions'}):
            base=builder.stage_historical(self.snapshot,inputs()[1],construction={'source':'dsh_native_skill'},execution_backend='narrative')
            draft=client.post('/api/scenarios/from-historical',json={'base_draft_id':base['id'],'execution_backend':'narrative'}).json()['draft']
            config=copy.deepcopy(draft['configuration']);config['teams']['red'][0]['personnel']=4500
            with patch.object(historical_initial,'DATA_ROOT',historical_initial.DATA_ROOT/'absent'):
                response=client.post('/api/scenarios/validate',json={'mission_id':'','parent_draft_id':draft['id'],
                    'configuration':config,'execution_backend':'narrative'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['preview_world']['red_units'][0]['personnel']['committed'],4500)
            self.assertEqual(response.json()['historical_base'],draft['historical_base'])
            self.assertNotEqual(response.json()['mission_id'],draft['mission_id'])


if __name__=='__main__':unittest.main(verbosity=2)
