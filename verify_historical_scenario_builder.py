"""Normal historical launch must bind sourced IDs, never CA teaching seeds."""
import copy
import os
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from gentactix import historical_initial, historical_operations
from tools.qa.historical_operational_fixture import BATTLE, inputs


class HistoricalScenarioBuilderTests(unittest.TestCase):
    def test_old_scheduled_draft_requires_new_validation_before_new_session(self):
        from fastapi.testclient import TestClient
        from backend import main, scenario_builder
        from tools.qa.baozuo_fixture import inputs as baozuo_inputs, BATTLE as BAOZUO
        snapshot, params=baozuo_inputs()
        record={'kind':'historical_operation','construction':{'source':'dsh_native_skill'},
                'execution_backend':'narrative','initial':snapshot,'parameters':params}
        with patch.object(scenario_builder,'load',return_value=record):
            response=TestClient(main.app).post('/api/sessions',json={'scenario':'旧草稿验证',
                'battle':BAOZUO,'product_mode':'historical','simulation_mode':'open',
                'execution_backend':'narrative','scenario_draft_id':'a'*32,'historical_parameters':params})
        self.assertEqual(response.status_code,422)
        self.assertIn('重新装载验证',response.json()['detail'])

    def test_new_historical_draft_starts_all_units_and_keeps_source_schedule(self):
        from backend import scenario_builder as b
        from gentactix import campaign
        from tools.qa.baozuo_fixture import inputs as baozuo_inputs
        snapshot, params=baozuo_inputs(); original=copy.deepcopy(params)
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder+'/sessions'}):
            staged=b.stage_historical(snapshot,params,construction={'source':'dsh_native_skill'},execution_backend='narrative')
            self.assertEqual(staged['parameters']['campaign']['availability_mode'],'immediate')
            self.assertEqual(staged['parameters']['campaign']['arrivals'],original['campaign']['arrivals'])
            self.assertEqual(params,original)
            world=historical_operations.initial(snapshot,staged['parameters'])
            self.assertTrue(all(actor['active'] for actor in world['campaign']['actors'].values()))
            self.assertTrue(all(campaign.release_seconds(world,u)==0 for team in ('red','blue') for u in world[team+'_units']))

    def test_saved_legacy_window_drafts_remain_discoverable_after_transport_projection(self):
        from backend import scenario_builder as b
        from gentactix import campaign_windows as cw
        from tools.qa.wanjialing_estimate_fixture import inputs as campaign_inputs
        snapshot,parameters=campaign_inputs();window=parameters['campaign_scope']['window']
        raw=cw.load(window['id'],window['version'])
        raw['parameter_estimates']['area']['radius_km']=float(raw['parameter_estimates']['area']['radius_km'])
        parameters['campaign_scope']['window']=dict(format=cw.FORMAT,id=raw['id'],version=raw['version'],definition_hash=historical_initial.digest(raw),definition=raw)
        with tempfile.TemporaryDirectory()as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder+'/sessions'}),patch.object(cw,'load',return_value=raw):
            selected=cw.pin(raw['id'],raw['version'])
            self.assertNotEqual(selected['definition_hash'],parameters['campaign_scope']['window']['definition_hash'])
            world=historical_operations.initial(snapshot,parameters)
            for identity,kind in [('b'*32,'historical_operation'),('c'*32,'historical_configuration')]:
                b._save_draft(dict(id=identity,kind=kind,initial=snapshot,parameters=parameters,execution_backend='narrative',
                    construction={'source':'dsh_native_skill'}),world)
            self.assertEqual([r['id']for r in b.completed_configurations(snapshot,force_scope='campaign',window=selected)],['b'*32])
            self.assertEqual([r['id']for r in b.pending_configurations(snapshot,force_scope='campaign',window=selected)],['c'*32])

    def test_browser_number_lexemes_create_from_the_exact_verified_draft(self):
        from fastapi.testclient import TestClient
        from backend import main,scenario_builder as b
        snapshot,params=inputs();params['area']['radius_km']=float(params['area']['radius_km'])
        with tempfile.TemporaryDirectory()as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder+'/sessions'}):
            staged=b.stage_historical(snapshot,params,construction={'source':'dsh_native_skill'},execution_backend='narrative')
            script='process.stdin.setEncoding("utf8");let s="";process.stdin.on("data",x=>s+=x);process.stdin.on("end",()=>process.stdout.write(JSON.stringify(JSON.parse(s))));'
            wire=json.loads(subprocess.run(['node','-e',script],input=json.dumps(staged['parameters'],ensure_ascii=False),text=True,capture_output=True,check=True).stdout)
            self.assertNotEqual(type(wire['area']['radius_km']),type(staged['parameters']['area']['radius_km']))
            client=TestClient(main.app);reply=client.post('/api/sessions',json=dict(scenario='真实Node数值往返',battle=BATTLE,
                product_mode='historical',historical_parameters=wire,scenario_draft_id=staged['id'],execution_backend='narrative'))
            self.assertEqual(reply.status_code,200,reply.text);sid=reply.json()['session_id']
            try:
                actual=main._SESSIONS[sid]['historical_definition']
                expected=historical_operations.from_binding(dict(format=historical_operations.FORMAT,initial=snapshot,parameters=staged['parameters']))
                self.assertEqual(json.dumps(actual,sort_keys=True),json.dumps(expected,sort_keys=True))
                bad=copy.deepcopy(wire);bad['rules']['bridge_enabled']=0
                refused=client.post('/api/sessions',json=dict(scenario='拒收布尔伪装',battle=BATTLE,product_mode='historical',
                    historical_parameters=bad,scenario_draft_id=staged['id'],execution_backend='narrative'))
                self.assertEqual(refused.status_code,422)
            finally:main._SESSIONS.pop(sid,None)

    def test_failed_native_load_keeps_frozen_input_but_cannot_create_a_game(self):
        from fastapi.testclient import TestClient
        from backend import main, scenario_builder as b
        snapshot,params=inputs()
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder+'/sessions'}):
            with patch.object(b,'_load_world',side_effect=RuntimeError('actual native load failure')):
                with self.assertRaises(b.HistoricalLoadError) as caught:
                    b.stage_historical(snapshot,params,construction={'source':'dsh_native_skill'})
            saved=b.load(caught.exception.configuration_id)
            self.assertEqual(saved['kind'],'historical_configuration')
            self.assertEqual(saved['initial'],snapshot)
            self.assertEqual([r['id'] for r in b.pending_configurations(snapshot)],[saved['id']])
            client=TestClient(main.app)
            response=client.post('/api/sessions',json={'scenario':'unloaded','battle':BATTLE,
                'product_mode':'historical','execution_backend':'afsim','historical_parameters':saved['parameters'],
                'scenario_draft_id':saved['id']})
            self.assertEqual(response.status_code,422)
            with patch.object(b,'_load_world',return_value={'status':'completed','returncode':0}), \
                 patch.object(b.h,'_run_brain',side_effect=AssertionError('Retry must not regenerate inputs')):
                retried=client.post('/api/historical-scenarios/retry-load',json={'configuration_id':saved['id']})
            self.assertEqual(retried.status_code,200,retried.text)
            self.assertEqual(retried.json()['parameters'],saved['parameters'])
            self.assertEqual(retried.json()['kind'],'historical_operation')
            self.assertNotIn(saved['id'],[r['id'] for r in b.pending_configurations(snapshot)])

    def test_explicit_source_version_exposes_full_campaign_without_changing_default(self):
        from fastapi.testclient import TestClient
        from backend import main, scenario_builder as b
        battle = '抗日战争-车桥战役-1944.03.05至1944.03.06'
        old = b.historical_basis(battle)
        reply = TestClient(main.app).get('/api/historical-scenarios/basis',
            params={'battle': battle, 'version': '1.1.0', 'phase_id': 'core_march5_6'})
        self.assertEqual(reply.status_code, 200, reply.text)
        view = reply.json()
        self.assertEqual(view['initial']['version'], '1.1.0')
        self.assertEqual(len(view['actors']), 15)
        self.assertIn('campaign', view['configuration_template'])
        self.assertEqual(view['objective_guidance']['profile'], 'assault')
        self.assertIn('阻援', view['objective_guidance']['objective_label'])
        self.assertEqual({v['version'] for v in view['versions']}, {'1.0.0','1.1.0','1.2.0','1.3.0'})
        self.assertEqual(next(v['version'] for v in view['versions'] if v['default']), '1.0.0')
        self.assertEqual(b.historical_basis(battle)['initial'], old['initial'])
        for version in ('missing', '../index'):
            invalid = TestClient(main.app).get('/api/historical-scenarios/basis',
                params={'battle': battle, 'version': version})
            self.assertEqual(invalid.status_code, 422)

    def test_build_keeps_the_explicit_source_version_before_any_model_call(self):
        from fastapi.testclient import TestClient
        from backend import main, scenario_builder as b
        battle = '抗日战争-车桥战役-1944.03.05至1944.03.06'
        seen = []
        def inspect(basis, *args):
            seen.append(basis['initial'])
            raise ValueError('QA stop before model execution')
        with patch.object(b, 'build_historical_staged', side_effect=inspect):
            response = TestClient(main.app).post('/api/historical-scenarios/build',json={
                'battle': battle, 'version': '1.1.0', 'phase_id': 'core_march5_6',
                'time_step': '30分钟', 'execution_backend': 'afsim'})
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]['version'], '1.1.0')

    def test_basis_exposes_phase_gaps_and_null_inputs_without_a_teaching_seed(self):
        from backend import scenario_builder as b
        with patch('gentactix.scenario_basis.exercise_seed', side_effect=AssertionError('No CA seed')):
            unavailable = b.historical_basis(BATTLE, 'campaign_opening')
            self.assertFalse(unavailable['ready'])
            self.assertIn('参战', unavailable['error'])
            automatic = b.historical_basis(BATTLE)
            self.assertTrue(automatic['ready'])
            self.assertEqual(automatic['initial']['phase_id'], 'taierzhuang_opening')
            self.assertIn('默认选择', automatic['scope'])
            ready = b.historical_basis(BATTLE, 'taierzhuang')
        self.assertTrue(ready['ready'])
        self.assertEqual(set(ready['configuration_template']['actors']), set(inputs()[1]['actors']))
        self.assertTrue(all(u['personnel'] is None and u['position']['lat'] is None
                            for u in ready['configuration_template']['actors'].values()))
        self.assertEqual(ready['initial']['definition_hash'], inputs()[0]['definition_hash'])

    def test_native_builder_tools_read_the_historical_skill_and_validate_actual_ids(self):
        from backend import scenario_builder as b
        snapshot, params = inputs()
        context = {'scenario_composer': {'kind': 'historical_operation', 'initial': snapshot,
                                         'basis': b.historical_basis(BATTLE, 'taierzhuang')}}
        params['goal']['team']=context['scenario_composer']['basis']['configuration_template']['goal']['team']
        skill = b.execute_tool(context, {'tool': 'read_scenario_skill'})
        self.assertEqual(skill['skill'], 'historical-unit-configuration')
        self.assertIn('真实ID', skill['content'])
        view = b.execute_tool(context, {'tool': 'get_scenario_basis'})
        self.assertNotIn('definition', view)
        self.assertEqual({r['id'] for r in view['actors']}, set(params['actors']))
        good = b.execute_tool(context, {'tool': 'validate_scenario_configuration', 'args': {'configuration': params}})
        self.assertTrue(good['valid'])
        bad = copy.deepcopy(params); bad['actors'].pop('ww2.jp.seya_detachment')
        self.assertFalse(b.execute_tool(context, {'tool': 'validate_scenario_configuration',
                                               'args': {'configuration': bad}})['valid'])

    def test_staged_historical_definition_is_frozen_and_can_create_without_live_profiles(self):
        from fastapi.testclient import TestClient
        from backend import main, scenario_builder as b
        snapshot, params = inputs()
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'GENTACTIX_SESSION_DIR': folder+'/sessions'}), \
             patch.object(b.afsim_world, 'run_scene', side_effect=AssertionError('No AFSIM for DSH-only')):
            staged = b.stage_historical(snapshot, params, construction={'source': 'dsh_native_skill'}, execution_backend='narrative')
            params = staged['parameters']
            self.assertEqual(staged['kind'], 'historical_operation')
            self.assertIsNone(staged['afsim'])
            client = TestClient(main.app)
            with patch.object(historical_initial, 'DATA_ROOT', historical_initial.DATA_ROOT/'absent'):
                reply = client.post('/api/sessions', json={'scenario': '冻结历史配置', 'battle': BATTLE,
                    'product_mode': 'historical', 'historical_parameters': params,
                    'scenario_draft_id': staged['id'], 'execution_backend': 'narrative'})
            self.assertEqual(reply.status_code, 200, reply.text)
            sid = reply.json()['session_id']
            try:
                session = main._SESSIONS[sid]
                self.assertEqual(session['historical_definition'], historical_operations.definition(snapshot, params))
                self.assertEqual(session['scenario_construction']['kind'], 'historical_operation')
                for changes in ({'execution_backend': 'afsim'}, {'historical_parameters': {**params, 'assumptions': 'changed'}}):
                    payload = {'scenario': '拒收过期验证', 'battle': BATTLE, 'product_mode': 'historical',
                               'historical_parameters': params, 'scenario_draft_id': staged['id'], 'execution_backend': 'narrative', **changes}
                    self.assertEqual(client.post('/api/sessions', json=payload).status_code, 422)
            finally:
                main._SESSIONS.pop(sid, None)

    def test_displayed_goal_is_generated_from_computed_criteria_not_model_claims(self):
        from backend import scenario_builder as b
        snapshot, params = inputs()
        params['goal']['description'] = '声称守住任何城市四个回合即可胜利，模型未实际实现'
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'GENTACTIX_SESSION_DIR': folder+'/sessions'}):
            staged = b.stage_historical(snapshot, params, construction={'source': 'dsh_native_skill'}, execution_backend='narrative')
        self.assertNotIn('任何城市', staged['preview_world']['mission']['definition']['goal'])
        self.assertIn('600米', staged['parameters']['goal']['description'])
        self.assertIn('第2回合', staged['parameters']['goal']['description'])

    def test_normal_historical_entry_rejects_a_teaching_mission_or_unbound_generation(self):
        from fastapi.testclient import TestClient
        from backend import main
        client = TestClient(main.app)
        for engine in ('narrative', 'afsim'):
            for extra in ({}, {'mission_id': 'CA-AJ18-v1'}):
                reply = client.post('/api/sessions', json={'scenario': '不能以教学编组替代历史初态',
                    'battle': BATTLE, 'product_mode': 'historical', 'execution_backend': engine, **extra})
                self.assertEqual(reply.status_code, 422, reply.text)
                self.assertIn('历史', reply.json()['detail'])

    def test_missing_profile_is_a_visible_capability_gap(self):
        from fastapi.testclient import TestClient
        from backend import main
        # Keep this negative path even though the current catalog is now covered.
        rows=historical_initial.catalog()
        rows=[{**r,'status':'not_profiled'} if r['battle']=='长平之战' else r for r in rows]
        with patch.object(historical_initial,'catalog',return_value=rows):
            response = TestClient(main.app).get('/api/historical-scenarios/basis', params={'battle': '长平之战'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['ready'])
        self.assertIsNone(response.json()['initial'])
        self.assertTrue(response.json()['error'])

    def test_native_generation_is_not_accepted_without_real_skill_tool_evidence(self):
        from fastapi.testclient import TestClient
        from backend import main, scenario_builder as b
        from types import SimpleNamespace
        import json
        _, params = inputs()
        with patch.object(b.h, '_run_brain', return_value=SimpleNamespace(final_response=json.dumps({'configuration': params}))), \
             patch.object(b, 'stage_historical', side_effect=AssertionError('No stage without native tool events')):
            response = TestClient(main.app).post('/api/historical-scenarios/build', json={
                'battle': BATTLE, 'phase_id': 'taierzhuang', 'execution_backend': 'narrative'})
        self.assertEqual(response.status_code, 502, response.text)
        self.assertIn('调用证据', response.json()['detail'])


if __name__ == '__main__': unittest.main()
