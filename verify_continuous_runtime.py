"""Normal Native assembly is opt-in until complete runtime admission is proved."""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import afsim_world,afsim_continuous_motion as cm,dsh_simulation,scenario_builder
from gentactix import missions
from verify_scheduled_physical import world

FLAG='GENTACTIX_NATIVE_CONTINUOUS_PREVIEW'


class ContinuousRuntimeTests(unittest.TestCase):
    def preview_session(self):
        from gentactix import commands
        session=dict(id='e31000000001',war_state=world(),turn_count=0,role_epoch=0,
            time_step='5分钟',product_mode='historical',simulation_mode='open',execution_backend='afsim')
        session['command_state']=commands.replace_queue(session,[],control_team='red',director=True,no_fire=True,intent='预览分段机动QA')
        identity=next(i for i,(entry,u) in commands.resolve_units(session).items() if entry['team']=='red')
        return session,identity

    def test_unconfirmed_continuous_preview_uses_a_segment_and_committed_intent_keeps_goal(self):
        from gentactix import commands
        session,identity=self.preview_session();unit=commands.resolve_units(session)[identity][1]
        destination=dict(lat=unit['lat']+.05,lng=unit['lng']);saved=copy.deepcopy(session)
        draft=dict(unit_id=identity,action='move',duration='until_arrived',destination=destination)
        preview=commands.step_order(session,draft)
        self.assertLessEqual(commands.distance(unit,preview),commands.move_budget(session,unit,'red',destination)+.001)
        self.assertNotIn('intent_id',preview)
        committed=commands.step_order(session,{**draft,'id':'a'*32})
        self.assertEqual({k:committed[k] for k in ('lat','lng')},destination)
        self.assertEqual(committed['intent_id'],'a'*32)
        self.assertEqual(session,saved)

    def test_far_group_advance_preview_preserves_goal_and_can_enter_the_existing_queue(self):
        from gentactix import commands,force_organization as forces,force_tasks
        session,identity=self.preview_session();unit=commands.resolve_units(session)[identity][1]
        session['force_organization']=forces.detach(session,[identity],'远程机动群','预览回归，不是历史编制')
        group=session['force_organization']['groups'][-1]['id'];destination=dict(lat=unit['lat']+.05,lng=unit['lng'])
        task=dict(kind='advance',destination=destination);saved=copy.deepcopy(session)
        preview=force_tasks.preview(session,group,task)
        self.assertEqual(preview['rows'][0]['status'],'ready')
        self.assertEqual(preview['rows'][0]['order']['action'],'move')
        self.assertEqual(preview['rows'][0]['order']['destination'],destination)
        self.assertEqual(session,saved)
        session['command_state']=force_tasks.commit(session,group,task,preview['preview_hash'])
        prepared=commands.prepare(session);order=next(r['order'] for r in prepared['manual'] if r['command']['unit_id']==identity)
        self.assertEqual({k:order[k] for k in ('lat','lng')},destination)
        self.assertIn('intent_id',order)

    def test_admission_preserves_explicit_native_preview_and_legacy_model_creation(self):
        from fastapi.testclient import TestClient
        from backend import main as api
        from tools.qa.historical_operational_fixture import BATTLE
        value=world();original=value['mission']['definition']['historical_calculation']['parameters']
        with tempfile.TemporaryDirectory() as directory:
            env={'GENTACTIX_SESSION_DIR':str(Path(directory)/'sessions'),
                 'GENTACTIX_TRACE_DIR':str(Path(directory)/'traces')}
            with patch.dict(os.environ,env),patch.dict(api._SESSIONS,{},clear=True),TestClient(api.app) as client:
                for backend,version,flag in [('afsim','movement-feedback-2','1'),('narrative','movement-feedback-1','0')]:
                    parameters=copy.deepcopy(original);parameters['movement_feedback']['version']=version
                    with patch.dict(os.environ,{FLAG:flag}),self.subTest(backend=backend):
                        response=client.post('/api/sessions',json=dict(scenario='Explicit admission compatibility',
                            battle=BATTLE,product_mode='historical',simulation_mode='open',execution_backend=backend,
                            historical_parameters=parameters,time_step='5分钟',persist_roles=False,use_rag=False))
                        self.assertEqual(response.status_code,200,response.text[:400])
                        session=api._SESSIONS[response.json()['session_id']]
                        self.assertIsNone(session['war_state'])
                        self.assertTrue((Path(directory)/'sessions'/(session['id']+'.json')).exists())

    def test_raw_creation_rejects_unadmitted_executor_before_saving_session(self):
        from fastapi.testclient import TestClient
        from backend import main as api
        from tools.qa.historical_operational_fixture import BATTLE
        value=world();parameters=value['mission']['definition']['historical_calculation']['parameters']
        with tempfile.TemporaryDirectory() as directory:
            env={'GENTACTIX_SESSION_DIR':str(Path(directory)/'sessions'),
                 'GENTACTIX_TRACE_DIR':str(Path(directory)/'traces')}
            with patch.dict(os.environ,env),patch.dict(api._SESSIONS,{},clear=True),TestClient(api.app) as client:
                for backend,flag in [('narrative','0'),('narrative','1'),('afsim','0')]:
                    count=len(api._SESSIONS)
                    with patch.dict(os.environ,{FLAG:flag}),self.subTest(backend=backend,flag=flag):
                        response=client.post('/api/sessions',json=dict(scenario='Explicit admission regression',
                            battle=BATTLE,product_mode='historical',simulation_mode='open',execution_backend=backend,
                            historical_parameters=parameters,time_step='5分钟',persist_roles=False,use_rag=False))
                        self.assertEqual(response.status_code,422,response.text[:400])
                        self.assertIn('尚未验收',response.json()['detail'])
                        self.assertEqual(len(api._SESSIONS),count)
                self.assertFalse(list(Path(directory).rglob('*.json')))

    def test_saved_unadmitted_world_cannot_initialize_as_model_ready(self):
        from fastapi.testclient import TestClient
        from backend import main as api
        value=world();definition=value['mission']['definition']
        session=api._new_session('Old unadmitted configuration','5分钟',False,definition['battle'],False,False)
        session.update(mission_id=definition['id'],historical_definition=definition,product_mode='historical',
            execution_backend='narrative',simulation_mode='open',persist_roles=False)
        with tempfile.TemporaryDirectory() as directory:
            env={FLAG:'1','GENTACTIX_SESSION_DIR':str(Path(directory)/'sessions'),
                 'GENTACTIX_TRACE_DIR':str(Path(directory)/'traces')}
            with patch.dict(os.environ,env),patch.dict(api._SESSIONS,{session['id']:session},clear=True),TestClient(api.app) as client:
                response=client.post('/api/sessions/'+session['id']+'/init')
                self.assertEqual(response.status_code,422,response.text[:400])
                self.assertIn('尚未验收',response.json()['detail'])
                self.assertIsNone(session['war_state'])
                self.assertFalse(list(Path(directory).rglob('*.json')))

    def test_optin_normal_one_millisecond_load_uses_the_same_bound_component(self):
        value=world();saved=copy.deepcopy(value)
        with patch.dict(os.environ,{FLAG:'1'}):
            scene=afsim_world.compile_scene(value,[],.001,native_rules=True)
        self.assertEqual(value,saved)
        self.assertEqual(scene['motion_revision'],12)
        self.assertTrue(scene['experimental_continuous'])
        self.assertEqual(scene['native_model']['continuous_motion']['seconds'],.001)
        self.assertNotIn('1.0.0',scene['script'])
        self.assertIn('GTXCNSEG|',scene['script'])
        self.assertEqual(len(scene['entities']),len(missions.units(value)))

    def test_optin_normal_moving_scene_starts_at_retained_task_speed(self):
        value=world();u=value['red_units'][0]
        order=dict(unit=u['name'],action='move',lat=u['lat']+.05,lng=u['lng'],intent_id='e'*32)
        u['formation']['motion_task']=cm.intent(u,order,30000)
        u['formation']['motion_task'].update(status='moving',wait_remaining_ms=0,speed_mps=.3,feedback_remaining_ms=5000)
        with patch.dict(os.environ,{FLAG:'1'}):
            scene=afsim_world.compile_scene(value,[order],300,native_rules=True)
        self.assertIn('update_interval 1.000000 sec',scene['script'])
        self.assertIn('speed 0.300000000000 m/s',scene['script'])
        self.assertNotIn('time_to_point',scene['script'])
        control=next(c for c in scene['native_model']['continuous_motion']['controls'].values() if c['name']==u['name'])
        self.assertEqual(control['task']['target'],{k:order[k] for k in ('lat','lng')})
        self.assertEqual(control['task']['wait_remaining_ms'],0)

    def test_candidate_does_not_unlock_model_effects_or_non_native_scenes(self):
        value=world();saved=copy.deepcopy(value)
        with patch.dict(os.environ,{FLAG:'1'}):
            for fn in [lambda:dsh_simulation.apply(value,{},'5分钟'),lambda:dsh_simulation.prompt(value),
                       lambda:afsim_world.compile_scene(value,[],300,native_rules=False)]:
                with self.subTest(fn=fn),self.assertRaises(ValueError):fn()
        self.assertEqual(value,saved)

    def test_default_admission_is_still_closed(self):
        with patch.dict(os.environ,{FLAG:'0'}),self.assertRaisesRegex(ValueError,'整局执行链尚未验收'):
            afsim_world.compile_scene(world(),[],300,native_rules=True)

    def test_no_silent_fallback_when_physical_dependencies_are_missing(self):
        for key in ('support_dynamics','supply_distribution','supply_schedule'):
            value=world();value['mission']['definition'].pop(key)
            with patch.dict(os.environ,{FLAG:'1'}),self.subTest(key=key),self.assertRaisesRegex(ValueError,'保障|粮弹|补给'):
                afsim_world.compile_scene(value,[],300,native_rules=True)

    def test_shared_crossings_and_air_actors_are_not_admitted_as_ground_motion(self):
        for kind in ('crossing','air'):
            value=world()
            if kind=='crossing':value['combined_arms']['bridge']['crossing_model']={'version':'unverified'}
            else:value['red_units'][0]['type']='战斗机'
            with patch.dict(os.environ,{FLAG:'1'}),self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'通路|渡|地面|航空'):
                afsim_world.compile_scene(value,[],300,native_rules=True)

    def test_narrative_draft_cannot_bypass_model_admission_through_native_loading(self):
        with patch.dict(os.environ,{FLAG:'1'}),self.assertRaises(ValueError):
            scenario_builder._load_world(world(),{},'narrative',None)

    def test_load_probe_is_the_only_fractional_duration_exception(self):
        from verify_continuous_motion_integration import compile_world
        _,_,_,model=compile_world(world())
        controls=model['continuous_motion']['controls']
        cm.compile_process(controls,.001,shared=True,fuel_event_times=[(.001,'settlement')])
        for bad in (True,.0005,.002,300.0,float('nan')):
            with self.subTest(bad=bad),self.assertRaises(ValueError):cm.compile_process(controls,bad,shared=True)

    def test_analysis_and_counterfactual_read_actual_fractional_stock(self):
        from backend import afsim_state
        value=world();u=value['red_units'][0]
        u['formation'].update(fuel_liters=0,fuel_credit_microliters=910603,fatigue=60,fatigue_carry_ticks=125000)
        saved=copy.deepcopy(value)
        facts=afsim_state.analysis_facts(dict(id='e28000000001',war_state=value,turn_count=0,time_step='5分钟'))
        self.assertIn('油料0.910603升',facts)
        self.assertIn('疲劳60.125',facts)
        alternate=copy.deepcopy(value);alternate['red_units'][0]['formation']['fuel_credit_microliters']=100000
        compared=missions.compare_states(value,value,alternate,[])
        fuel=next(r for r in compared['metrics'] if r['metric']=='红方地面燃油(升)')
        self.assertAlmostEqual(fuel['factual'],.910603)
        self.assertAlmostEqual(fuel['delta'],-.810603)
        self.assertEqual(value,saved)


if __name__=='__main__':unittest.main()
