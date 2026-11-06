"""Orthogonal purpose/engine contracts and DSH-only execution guards."""
import copy
import os
import tempfile
import unittest
from unittest.mock import patch

from gentactix import history_replay, missions, scenario_basis
from verify_dsh_resources import model_result


class ExecutionModeTests(unittest.TestCase):
    def test_six_purpose_engine_combinations_create_with_matching_contracts(self):
        from fastapi.testclient import TestClient
        from backend import main,scenario_builder as b,harness_engine as h
        seed=scenario_basis.exercise_seed('CA-AJ18-v1');battle=seed['basis']['battle']
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory+'/sessions'}), \
             patch('tools.afsim.launch.status',return_value={'available':True}),patch.object(h,'NATIVE_RUNTIME',True), \
             patch.object(b.afsim_world,'run_scene',return_value=({},{})),patch.object(b.afsim_world,'apply_observations'):
            client=TestClient(main.app)
            for purpose in ('analysis','historical','synthetic'):
                for engine in ('afsim','narrative'):
                    with self.subTest(purpose=purpose,engine=engine):
                        payload={'scenario':'用途/引擎矩阵','battle':battle,'execution_backend':engine,'product_mode':purpose,
                            'simulation_mode':'replay' if purpose=='analysis' else 'open'}
                        if purpose == 'historical':
                            from tools.qa.historical_operational_fixture import BATTLE, inputs
                            payload.update(battle=BATTLE, historical_parameters=inputs()[1])
                        if purpose == 'synthetic':
                            draft=b.stage('CA-AJ18-v1',seed['configuration'],construction={'source':'dsh_native_skill'},execution_backend=engine)
                            payload.update(mission_id='CA-AJ18-v1',scenario_draft_id=draft['id'],synthetic_configuration=draft['configuration'])
                        response=client.post('/api/sessions',json=payload)
                        self.assertEqual(response.status_code,200,response.text)
                        main._SESSIONS.pop(response.json()['session_id'])

    def test_dsh_source_frame_init_next_restore_and_failure_are_atomic(self):
        from fastapi.testclient import TestClient
        from backend import main,harness_engine as h,session_store
        battle='红军长征-湘江战役-1934.11.25至1934.12.01'
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory+'/sessions','GENTACTIX_TRACE_DIR':directory+'/traces'}), \
             patch.object(h,'ask_xuanji',return_value=('','根据给定来源说明该节点，不补充未知部署。')) as model, \
             patch.object(h,'enable_afsim_runtime',side_effect=AssertionError('No AFSIM runtime')), \
             patch('backend.afsim_world.run_scene',side_effect=AssertionError('No simulator')):
            client=TestClient(main.app)
            r=client.post('/api/sessions',json={'scenario':'DSH史料回溯','battle':battle,'product_mode':'analysis',
                'simulation_mode':'replay','execution_backend':'narrative','persist_roles':False})
            self.assertEqual(r.status_code,200,r.text);identity=r.json()['session_id'];path='/api/sessions/'+identity
            r=client.post(path+'/init');self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()['war_state'],history_replay.frame_for_session(main._SESSIONS[identity],0))
            r=client.post(path+'/next',json={'expected_turn':0});self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()['war_state'],history_replay.frame_for_session(main._SESSIONS[identity],1));self.assertEqual(model.call_count,2)
            session=main._SESSIONS[identity];saved=copy.deepcopy(session_store.serializable(session))
            model.return_value=('',{'explanation':'虚构节点','updated_state':{'red_units':[{'name':'假的'}]}})
            r=client.post(path+'/next',json={'expected_turn':1});self.assertEqual(r.status_code,409,r.text)
            self.assertEqual(session['war_state'],saved['war_state']);self.assertEqual(session['turn_count'],1)
            loaded,errors=session_store.load_all();self.assertFalse(errors);self.assertEqual(loaded[identity]['war_state'],saved['war_state'])
            main._SESSIONS.pop(identity)

    def test_switching_engine_rejects_old_draft_validation(self):
        from fastapi.testclient import TestClient
        from backend import main,scenario_builder as b
        seed=scenario_basis.exercise_seed('CA-AJ18-v1')
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory+'/sessions'}):
            draft=b.stage('CA-AJ18-v1',seed['configuration'],construction={'source':'dsh_native_skill'},execution_backend='narrative')
            r=TestClient(main.app).post('/api/sessions',json={'scenario':'引擎切换拒收旧验证','battle':seed['basis']['battle'],
                'execution_backend':'afsim','product_mode':'synthetic','mission_id':'CA-AJ18-v1','scenario_draft_id':draft['id']})
            self.assertEqual(r.status_code,422,r.text);self.assertIn('引擎',r.text)

    def test_source_analysis_can_use_dsh_without_starting_afsim(self):
        from fastapi.testclient import TestClient
        from backend import main
        battle='红军长征-湘江战役-1934.11.25至1934.12.01'
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory}), \
             patch('tools.afsim.launch.status',side_effect=AssertionError('AFSIM must not be inspected')):
            response=TestClient(main.app).post('/api/sessions',json={'scenario':'DSH来源重现','battle':battle,
                'product_mode':'analysis','simulation_mode':'replay','execution_backend':'narrative'})
            self.assertEqual(response.status_code,200,response.text)
            identity=response.json()['session_id']
            self.assertEqual(main._SESSIONS[identity]['product_mode'],'analysis')
            main._SESSIONS.pop(identity)

    def test_dsh_draft_validation_never_launches_simulator(self):
        from backend import scenario_builder as b
        config=scenario_basis.exercise_seed('CA-AJ18-v1')['configuration']
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory+'/sessions'}), \
             patch.object(b.afsim_world,'run_scene',side_effect=AssertionError('AFSIM must not run')):
            draft=b.stage('CA-AJ18-v1',config,construction={'source':'dsh_native_skill'},execution_backend='narrative')
            self.assertIsNone(draft['afsim'])
            self.assertEqual(draft['execution_backend'],'narrative')

    def test_dsh_mission_transition_uses_model_effects_and_conserves_accounts(self):
        from backend import dsh_simulation as d
        before=missions.initial('CA-AJ18-v1')
        result=model_result(before);rows=result['unit_updates']
        rows[0]['personnel']={**before['red_units'][0]['personnel'],'current':before['red_units'][0]['personnel']['current']-7,'casualties':7}
        attacker=before['blue_units'][0];target=before['red_units'][0]
        next(o for o in result['orders'] if o['unit']==attacker['name']).update(action='bombard',target=target['name'])
        account=next(r for r in result['resource_ledger']['units'] if r['unit']==attacker['name'])
        account.update(ammo_spent=1,spent={'shells':1})
        update=next(r for r in rows if r['unit']==attacker['name'])
        update['logistics']['ammo']-=1;update['formation'].update(shells=attacker['formation']['shells']-1)
        result['engagements']=[{'attacker':attacker['name'],'attacker_team':'blue','attacker_pos':[attacker['lat'],attacker['lng']],
            'target':target['name'],'lat':target['lat'],'lng':target['lng'],'weapon_action':'bombard'}]
        result['report']='模型估计本轮减员7人。'
        with patch.object(missions,'advance',side_effect=AssertionError('No Python combat')):
            after=d.apply(before,result,before['mission']['definition']['time_step'])
        self.assertEqual(after['red_units'][0]['personnel']['casualties'],7)
        self.assertEqual(before['red_units'][0]['personnel']['casualties'],0)
        self.assertEqual(after['dsh_execution']['effects_source'],'dsh_model_estimate')
        missions.validate(after)

    def test_dsh_mission_rejects_lost_roster_and_nonconserving_counts(self):
        from backend import dsh_simulation as d
        before=missions.initial('CA-AJ18-v1');rows=[{'unit':u['name']} for _,u in missions.units(before)]
        bad=copy.deepcopy(rows);bad.pop()
        with self.assertRaises(ValueError):d.apply(before,{'unit_updates':bad},'30分钟')
        bad=copy.deepcopy(rows);bad[0]['personnel']={'current':999999}
        with self.assertRaises(ValueError):d.apply(before,{'unit_updates':bad},'30分钟')

    def test_dsh_can_echo_unchanged_model_identity_and_valid_process_events(self):
        from backend import dsh_simulation as d
        before=missions.initial('CA-AJ18-v1');model=copy.deepcopy(before['combined_arms'])
        model['events']=[{'unit':before['red_units'][0]['name'],'action':'hold','seconds':60,'status_code':0}]
        result={**model_result(before),'combined_arms':model}
        after=d.apply(before,result,'30分钟');self.assertEqual(after['dsh_execution']['events'],model['events'])
        self.assertEqual(after['combined_arms']['events'],[])
        bad=copy.deepcopy(result);bad['combined_arms']['rules_hash']='forged'
        with self.assertRaises(ValueError):d.apply(before,bad,'30分钟')
        bad=copy.deepcopy(result);bad['combined_arms']['events'][0]['unit']='unknown'
        with self.assertRaises(ValueError):d.apply(before,bad,'30分钟')
        model['events']=[{'turn':1,'type':'移动','description':'模型估计的移动过程','model_estimate':True}]
        self.assertEqual(d.apply(before,result,'30分钟')['dsh_execution']['events'],model['events'])

    def test_dsh_equipment_updates_bind_known_categories_without_losing_others(self):
        from backend import dsh_simulation as d
        before=missions.initial('CA-AJ18-v1');result=model_result(before);rows=result['unit_updates']
        rows[0]['equipment']=[{'category':'transport','operational':before['red_units'][0]['equipment'][-1]['operational']}]
        after=d.apply(before,result,'30分钟')
        self.assertEqual(after['red_units'][0]['equipment'],before['red_units'][0]['equipment'])
        rows[0]['equipment']=[{'category':'unknown'}]
        with self.assertRaises(ValueError):d.apply(before,result,'30分钟')


if __name__=='__main__':unittest.main()
