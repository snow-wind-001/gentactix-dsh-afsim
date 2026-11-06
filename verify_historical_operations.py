"""Historical identity/parameter separation and native model input regressions."""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from gentactix import missions, historical_initial
from tools.qa.historical_operational_fixture import inputs


def aviation_inputs():
    """QA-only added identities; never installed as historical source data."""
    from gentactix import air_assets
    snapshot,params=inputs();unit=copy.deepcopy(snapshot['definition']['units'][0])
    source=unit['evidence'][0]['source_id']
    evidence=[{'source_id':source,'locator':'QA fixture only: fabricated aviation identity, not a source assertion'}]
    for identity,team in (('qa.red.air','red'),('qa.blue.air','blue')):
        air=copy.deepcopy(unit);air.update(id=identity,name=identity,team=team,role='aviation',echelon='QA航空队',parent_id=None,
            evidence=evidence,presence=[{'phase_id':'taierzhuang','status':'reported_present','evidence':evidence}])
        snapshot['definition']['units'].append(air)
    snapshot['definition_hash']=historical_initial.digest(snapshot['definition'])
    params['rules']['air_support']=True
    params['aviation']={i:{'initial':{'committed':4,'ordnance':12,'fuel':24},
        'entry':copy.deepcopy(params['area']['center']),'rules':copy.deepcopy(air_assets.DEFAULT_RULES),
        'assumption':'QA计算估计，不是已考证飞机库存、油弹、机场或效能。'} for i in ('qa.red.air','qa.blue.air')}
    return snapshot,params


class HistoricalOperationsTests(unittest.TestCase):
    def test_phase_aviation_binds_as_separate_resources_not_ground_infantry(self):
        from gentactix import historical_operations as op,air_assets
        from backend import afsim_air
        snapshot,params=aviation_inputs();before=copy.deepcopy(snapshot)
        with self.assertRaisesRegex(ValueError, '目标资料.*初态'):
            op.configuration_template(snapshot)
        # Invented QA air identities have no registered historical task guide.
        # Isolate aviation fields rather than borrowing a real source's pin.
        with patch.object(op,'objective_guidance',return_value=None):
            template=op.configuration_template(snapshot)
        self.assertEqual(set(template['aviation']),{'qa.red.air','qa.blue.air'})
        self.assertIsNone(template['aviation']['qa.red.air']['initial']['committed'])
        world=op.initial(snapshot,params);air=afsim_air.state(world)
        self.assertEqual(snapshot,before);self.assertEqual(len(list(missions.units(world))),3)
        self.assertEqual(set(air['pools']),{'qa.red.air','qa.blue.air'})
        self.assertEqual(air['pools']['qa.blue.air']['team'],'blue')
        self.assertEqual(air_assets.world_definition(world)['pools']['qa.red.air']['evidence'],snapshot['definition']['units'][-2]['evidence'])
        with patch.object(historical_initial,'DATA_ROOT',historical_initial.DATA_ROOT/'absent'):
            self.assertTrue(missions.validate(world))

    def test_aviation_requires_complete_parameters_and_cannot_rewrite_identity(self):
        from gentactix import historical_operations as op
        snapshot,params=aviation_inputs()
        for kind in ('missing','unknown','team','source','null'):
            p=copy.deepcopy(params)
            if kind=='missing':p['aviation'].pop('qa.blue.air')
            if kind=='unknown':p['aviation']['invented']=p['aviation'].pop('qa.red.air')
            if kind=='team':p['aviation']['qa.red.air']['team']='blue'
            if kind=='source':p['aviation']['qa.red.air']['evidence']=[]
            if kind=='null':p['aviation']['qa.red.air']['initial']['committed']=None
            with self.subTest(kind=kind),self.assertRaises(ValueError):op.initial(snapshot,p)

    def test_unverified_aircraft_are_not_advanced_and_no_legacy_fleet_is_invented(self):
        from gentactix import historical_operations as op
        snapshot,params=aviation_inputs()
        for status in ('campaign_participant','unverified'):
            s=copy.deepcopy(snapshot);s['definition']['units'][-1]['presence'][0]['status']=status
            s['definition_hash']=historical_initial.digest(s['definition'])
            with self.subTest(status=status),self.assertRaises(ValueError):op.configuration_template(s)
        plain,p=inputs();p['rules']['air_support']=True
        with self.assertRaises(ValueError):op.initial(plain,p)

    def test_aviation_can_be_disabled_without_destroying_its_frozen_resource_inputs(self):
        from gentactix import historical_operations as op,combined_arms
        from backend import afsim_air
        snapshot,params=aviation_inputs();params['rules']['air_support']=False
        world=op.initial(snapshot,params)
        self.assertEqual(afsim_air.state(world)['assets']['blue']['committed'],4)
        self.assertNotIn('air_support',combined_arms.actions(world,world['blue_units'][0],'blue'))

    def test_indirect_range_cannot_be_used_as_a_new_direct_fire_range(self):
        from gentactix import historical_operations as op
        snapshot, params = inputs()
        actor = params['actors']['ww2.cn.division31']
        actor['type'] = '炮兵'
        actor['attack_range_m'] = 8000
        params['rules']['direct_range_m'] = 1200
        params['rules']['artillery_range_m'] = 12000
        with self.assertRaisesRegex(ValueError, '直射.*间接'):
            op.initial(snapshot, params)

    def test_legacy_frozen_ranges_restore_without_silently_rewriting_the_model(self):
        from gentactix import historical_operations as op
        snapshot, params = inputs()
        params['actors']['ww2.cn.division31']['type'] = '炮兵'
        params['actors']['ww2.cn.division31']['attack_range_m'] = 8000
        legacy = op.definition(snapshot, params, _frozen=True)
        restored = op.from_binding(legacy['historical_calculation'])
        self.assertEqual(restored, legacy)
        self.assertEqual(restored['initial_state']['red_units'][0]['attack_range'], 8000)
        with self.assertRaisesRegex(ValueError, '直射.*间接'):
            op.initial(snapshot, params)

    def test_real_numbered_units_are_built_without_teaching_template_or_renaming(self):
        from gentactix import historical_operations as op
        snapshot, params = inputs(); original = copy.deepcopy(snapshot)
        with patch('gentactix.combined_arms.definition', side_effect=AssertionError('No CA template')):
            world = op.initial(snapshot, params)
        self.assertEqual(snapshot, original)
        self.assertEqual({u['historical_unit_id'] for _,u in missions.units(world)}, set(params['actors']))
        self.assertEqual({u['name'] for _,u in missions.units(world)}, {'第31师','日军濑谷支队','日军坂本支队'})
        self.assertTrue(world['mission']['id'].startswith('HO-'))
        self.assertTrue(missions.validate(world))
        self.assertEqual(world['red_units'][0]['personnel']['current'], 6000)
        self.assertIsNone(next(u for u in snapshot['definition']['units'] if u['id']=='ww2.cn.division31')['facts']['personnel']['value'])
        self.assertEqual(world['red_units'][0]['parameter_sources']['personnel']['kind'], 'model_estimate')

    def test_missing_unknown_parent_duplicate_and_headquarters_actors_are_rejected(self):
        from gentactix import historical_operations as op
        snapshot, original = inputs()
        for kind in ('missing','unknown','parent','headquarters','assumption','phase'):
            params = copy.deepcopy(original)
            if kind=='missing':params['actors'].pop('ww2.jp.seya_detachment')
            if kind=='unknown':params['actors']['invented'] = copy.deepcopy(next(iter(params['actors'].values())))
            if kind=='parent':params['actors']['ww2.jp.division10'] = copy.deepcopy(params['actors']['ww2.jp.seya_detachment'])
            if kind=='headquarters':params['actors']['ww2.cn.warzone5'] = copy.deepcopy(params['actors']['ww2.cn.division31'])
            if kind=='assumption':params['actors']['ww2.cn.division31']['assumption']=''
            if kind=='phase':params['phase_id']='campaign_opening'
            with self.subTest(kind=kind), self.assertRaises(ValueError):op.initial(snapshot,params)

    def test_known_source_fact_cannot_be_silently_replaced_with_an_estimate(self):
        from gentactix import historical_operations as op
        snapshot, params = inputs()
        unit = next(u for u in snapshot['definition']['units'] if u['id']=='ww2.cn.division31')
        unit['facts']['personnel'].update(value=5000,evidence=copy.deepcopy(unit['evidence']))
        snapshot['definition_hash']=historical_initial.digest(snapshot['definition'])
        with self.assertRaises(ValueError):op.initial(snapshot,params)

    def test_frozen_parameters_validate_without_current_data_and_guard_identity(self):
        from gentactix import historical_operations as op
        snapshot, params = inputs();world=op.initial(snapshot,params)
        with patch.object(historical_initial,'DATA_ROOT',historical_initial.DATA_ROOT/'absent'):
            self.assertTrue(missions.validate(world))
        for key in ('historical_unit_id','parent_id','echelon'):
            value=copy.deepcopy(world);value['red_units'][0][key]='invented'
            with self.subTest(key=key),self.assertRaises(ValueError):missions.validate(value)

    def test_native_compiler_reuses_rules_without_fabricating_a_bridge(self):
        from gentactix import historical_operations as op, combined_arms
        from backend import afsim_world
        snapshot,params=inputs();world=op.initial(snapshot,params)
        red=world['red_units'][0];blue=world['blue_units'][0]
        with patch.object(missions,'advance',side_effect=AssertionError('No Python combat')):
            scene=afsim_world.compile_scene(world,[{'unit':red['name'],'action':'fire','target':blue['name']}],1800,native_rules=True)
        self.assertEqual(len(scene['entities']),3)
        self.assertIn('GTXMODEL|',scene['script'])
        self.assertNotIn('build_bridge',combined_arms.actions(world,red,'red'))
        self.assertNotIn('bool cross',scene['script'])
        self.assertFalse('supplyCross' in scene['script'],'未启用设施时不得引用桥梁容量状态')
        self.assertNotIn('.Longitude()>117.73917',scene['script'])

    def test_short_native_moves_use_available_speed_not_an_entire_turn_of_travel(self):
        from gentactix import historical_operations as op
        from backend import afsim_world
        snapshot, params = inputs(); world = op.initial(snapshot, params)
        red = world['red_units'][0]
        scene = afsim_world.compile_scene(world, [{'unit': red['name'], 'action': 'move',
            'lat': red['lat']+.001, 'lng': red['lng']}], 1800, native_rules=True)
        self.assertNotIn('time_to_point 1800', scene['script'])
        self.assertEqual(scene['motion_revision'], afsim_world.NATIVE_MOTION_REVISION)
        self.assertIn('speed 0.833333', scene['script'])

    def test_native_counterfactual_rejects_a_different_motion_model_revision(self):
        from gentactix import historical_operations as op
        from backend import afsim_comparison, afsim_world
        snapshot, params = inputs(); before = op.initial(snapshot, params)
        factual = copy.deepcopy(before); factual['afsim'] = {'motion_revision': 1}
        with patch.object(afsim_world, 'run_scene', side_effect=AssertionError('No mismatched model execution')):
            with self.assertRaisesRegex(ValueError, '运动模型.*版本'):
                afsim_comparison.compare({'war_state': before},
                    {'before': before, 'after': factual, 'time_step': '30分钟'}, [])

    def test_model_inputs_and_goals_are_not_lost_in_native_observation(self):
        from gentactix import historical_operations as op
        from backend import afsim_state
        snapshot,params=inputs();world=op.initial(snapshot,params)
        session={'id':'abcdef123456','war_state':world,'time_step':'30分钟','turn_count':0,'simulation_mode':'open','execution_backend':'afsim'}
        observation=afsim_state.observation(session,{'limit':3})
        self.assertEqual({u['historical_unit_id'] for u in observation['units']},set(params['actors']))
        self.assertEqual(observation['historical_calculation']['profile_id'],snapshot['profile_id'])
        self.assertIn('model_estimate',json.dumps(observation['historical_calculation']))
        self.assertNotIn('definition',json.dumps(observation['historical_calculation']))

    def test_delay_goal_does_not_change_to_assault_when_dsh_is_selected(self):
        from gentactix import historical_operations as op
        snapshot,params=inputs();world=op.initial(snapshot,params)
        world['red_units'][0]['lat']-=.02  # Alive outside objective; still meets delay goal.
        world['mission']['turn']=2
        missions.evaluate(world)
        self.assertEqual(world['mission']['status'],'completed')
        self.assertEqual(world['mission']['winner'],'red')
        self.assertEqual(world['mission']['metrics']['red_in_goal'],0)

    def test_era_clock_zero_divisor_and_unsafe_rule_strings_are_rejected(self):
        from gentactix import historical_operations as op
        snapshot, original=inputs()
        for kind in ('era','clock','divisor','script'):
            params=copy.deepcopy(original)
            if kind=='era':params['rules']['era']='korea'
            if kind=='clock':params['clock']['start']='2099-03-23 00:00'
            if kind=='divisor':params['rules']['ton_per_supply_unit']=0
            if kind=='script':params['rules']['command_base_s']='1; writeln("injected");'
            with self.subTest(kind=kind),self.assertRaises(ValueError):op.initial(snapshot,params)

    def test_individual_speeds_control_movement_instead_of_slowest_actor(self):
        from gentactix import historical_operations as op, commands
        snapshot,params=inputs()
        params['actors']['ww2.jp.seya_detachment']['speed']=12
        world=op.initial(snapshot,params)
        session={'war_state':world,'time_step':'30分钟','turn_count':0}
        self.assertAlmostEqual(commands.move_budget(session,world['red_units'][0],'red'),1.5)
        self.assertAlmostEqual(commands.move_budget(session,world['blue_units'][0],'blue'),6)
        destination={**world['blue_units'][0],'lat':world['blue_units'][0]['lat']+.035}
        missions.validate_orders(world,[{'unit':world['blue_units'][0]['name'],'action':'move',
                                         'lat':destination['lat'],'lng':destination['lng']}],'30分钟')

    def test_calculation_date_respects_the_sourced_ten_day_window(self):
        from gentactix import historical_operations as op
        snapshot,original=inputs()
        for start in ('1938-03-01 00:00','1938-04-20 00:00'):
            params=copy.deepcopy(original);params['clock']['start']=start
            with self.subTest(start=start),self.assertRaises(ValueError):op.initial(snapshot,params)

    def test_reference_participants_cannot_be_deployed_before_sourced_attendance(self):
        from gentactix import historical_operations as op
        from tools.qa.historical_operational_fixture import BATTLE
        snapshot = historical_initial.initial(BATTLE, 'campaign_opening')['historical_initial']
        self.assertTrue(all(u['historical_presence'] == 'unverified'
                            for side in ('red', 'blue')
                            for u in historical_initial.restore(snapshot)[side + '_units']))
        with self.assertRaisesRegex(ValueError, '阶段.*参战'):
            op.partition(snapshot)
        self.assertEqual(len(op.partition(inputs()[0])), 3)

    def test_native_failure_preserves_a_bounded_diagnostic_next_to_scene(self):
        from backend import afsim_world, harness_engine as h
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/'state';state.mkdir()
            log=state/'failure.stdout.txt';log.write_text('***** ERROR: Unknown identifier: supplyCross0\n')
            scene={'script':'end_time 1 sec\n','entities':{},'excluded':[],'seconds':1,'scope':'QA'}
            replies=[{'dispatch_id':'a','payload':{'process_id':'qa-failed'}},
                     {'dispatch_id':'b','payload':{'status':'failed','returncode':1,'stdout_path':str(log)}}]
            with patch('tools.afsim.launch.layout',return_value={'workspace':root/'workspace','state':state}), \
                 patch.object(h,'afsim_call',side_effect=replies):
                with self.assertRaisesRegex(RuntimeError,'Unknown identifier'):
                    afsim_world.run_scene({'id':'qa'},scene)
            artifacts=list((root/'workspace').glob('jobs/*/failure.json'))
            self.assertEqual(len(artifacts),1)
            self.assertEqual(json.loads(artifacts[0].read_text())['returncode'],1)


class HistoricalOperationsApiTests(unittest.TestCase):
    def test_historical_parameters_use_fixed_real_ids_and_survive_checkpoint_restore(self):
        from fastapi.testclient import TestClient
        from backend import main, harness_engine as h, session_store
        from tools.qa.historical_operational_fixture import BATTLE
        _,params=inputs()
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{
                'GENTACTIX_SESSION_DIR':folder+'/sessions','GENTACTIX_TRACE_DIR':folder+'/traces'}), \
             patch.object(h,'get_ai_response_with_retry',side_effect=AssertionError('Fixed input must not generate world')):
            client=TestClient(main.app)
            response=client.post('/api/sessions',json={'scenario':'具名历史部队参数化QA，不是完整徐州验收',
                'battle':BATTLE,'product_mode':'historical','simulation_mode':'open','execution_backend':'narrative',
                'persist_roles':False,'historical_parameters':params})
            self.assertEqual(response.status_code,200,response.text)
            sid=response.json()['session_id']
            try:
                result=client.post('/api/sessions/'+sid+'/init')
                self.assertEqual(result.status_code,200,result.text)
                world=result.json()['war_state']
                self.assertTrue(world['mission']['id'].startswith('HO-'))
                self.assertEqual(world['red_units'][0]['name'],'第31师')
                self.assertEqual(world['red_units'][0]['personnel']['current'],6000)
                sessions,errors=session_store.load_all()
                self.assertFalse(errors)
                self.assertEqual(sessions[sid]['war_state'],world)
            finally:main._SESSIONS.pop(sid,None)


if __name__=='__main__':unittest.main()
