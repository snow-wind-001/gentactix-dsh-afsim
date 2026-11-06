"""Source-phase attendance, explicit exclusions and immutable legacy snapshots."""
import copy
import unittest
from unittest.mock import patch

from gentactix import historical_initial as h, historical_operations as op

XZ='抗日战争-徐州会战总览-1938.01至1938.05'
PXG='抗日战争-平型关伏击战-1937.09.25'


class HistoricalAttendanceTests(unittest.TestCase):
    def test_xuzhou_opening_does_not_deploy_later_sakamoto_detachment(self):
        snapshot=h.initial(XZ,'taierzhuang_opening')['historical_initial']
        ids=op.partition(snapshot)
        self.assertEqual(set(ids),{'ww2.cn.division31','ww2.jp.seya_detachment'})
        unit=next(u for u in snapshot['definition']['units'] if u['id']=='ww2.jp.sakamoto_detachment')
        self.assertEqual(next(r['status'] for r in unit['presence'] if r['phase_id']=='taierzhuang_opening'),'later_participant')

    def test_later_phase_cannot_start_before_its_source_dates(self):
        from tools.qa.historical_operational_fixture import inputs
        snapshot,params=inputs();params['clock']['start']='1938-03-23 00:00'
        with self.assertRaisesRegex(ValueError,'日期'):op.initial(snapshot,params)
        params['clock']['start']='1938-03-31 12:00'
        self.assertTrue(op.initial(snapshot,params)['mission']['id'].startswith('HO-'))

    def test_legacy_xuzhou_definition_remains_readable_without_rebinding(self):
        old=h.initial(XZ,'taierzhuang',version='1.0.0')
        self.assertEqual(h.restore(old['historical_initial']),old)
        self.assertEqual(old['historical_initial']['version'],'1.0.0')
        self.assertNotEqual(h.definition(XZ)['version'],'1.0.0')

    def test_pingxingguan_has_sourced_ground_units_and_explicit_outside_references(self):
        snapshot=h.initial(PXG,'qiaogou')['historical_initial']
        selected=set(op.partition(snapshot));units={u['id']:u for u in snapshot['definition']['units']}
        self.assertEqual({units[i]['team'] for i in selected},{'red','blue'})
        self.assertTrue({'ww2.cn.regiment685','ww2.cn.regiment686','ww2.cn.regiment687','ww2.cn.regiment688'}<=selected)
        self.assertNotIn('ww2.cn.115.independent',selected)
        self.assertNotIn('ww2.cn.115.cavalry',selected)
        self.assertTrue(all(units[i]['evidence'] for i in selected))
        self.assertFalse(snapshot['definition']['coverage']['opening_deployment_complete'])

    def test_phase_aircraft_require_separate_parameters_and_never_become_ground_units(self):
        snapshot=h.initial(PXG,'qiaogou')['historical_initial']
        future=next(u for u in snapshot['definition']['units'] if u['role']=='aviation')
        self.assertNotIn(future['id'],op.partition(snapshot))
        changed=copy.deepcopy(snapshot)
        row=next(u for u in changed['definition']['units'] if u['id']==future['id'])
        row['presence']=[{**p,'status':'reported_present'} if p['phase_id']=='qiaogou' else p for p in row['presence']]
        changed['definition_hash']=h.digest(changed['definition'])
        self.assertNotIn(future['id'],op.partition(changed))
        self.assertIn(future['id'],op.aviation_partition(changed))
        with self.assertRaisesRegex(ValueError,'完整历史初态'):
            op.configuration_template(changed)
        # Aviation admission is tested on an explicitly modified QA source,
        # without borrowing the published source's objective guidance.
        with patch.object(op,'objective_guidance',return_value=None):
            template=op.configuration_template(changed)
        self.assertIsNone(template['aviation'][future['id']]['initial']['committed'])
        self.assertNotIn('aviation',op.configuration_template(snapshot))

    def test_source_area_reference_bounds_estimated_initial_positions(self):
        from tools.qa.pingxingguan_fixture import inputs
        snapshot,params=inputs()
        self.assertTrue(op.initial(snapshot,params))
        params['actors']['ww2.cn.regiment686']['position']={'lat':39.46,'lng':114.14}
        params['area']['radius_km']=50
        with self.assertRaisesRegex(ValueError,'来源部署区域'):op.initial(snapshot,params)

    def test_coarse_deployment_area_does_not_become_a_known_unit_position(self):
        world=h.initial(PXG,'qiaogou')
        unit=next(u for u in world['red_units'] if u['historical_unit_id']=='ww2.cn.regiment686')
        self.assertIsNone(unit['lat']);self.assertIsNone(unit['lng'])
        self.assertEqual(unit['deployment']['value']['kind'],'deployment_area_reference')

    def test_ground_only_window_does_not_silently_pass_unsupported_air_arrival(self):
        from tools.qa.pingxingguan_fixture import inputs
        snapshot,params=inputs();params['goal']['deadline_turn']=13
        with self.assertRaisesRegex(ValueError,'计算窗口'):op.initial(snapshot,params)

    def test_api_basis_discloses_retained_references_and_scope_boundary(self):
        from backend import scenario_builder as b
        value=b.historical_basis(PXG,'qiaogou')
        self.assertTrue(value['ready'])
        self.assertEqual(len(value['actors']),6)
        self.assertEqual(len(value['excluded_references']),3)
        self.assertEqual(value['execution_window']['end'],'1937-09-25T13:00')
        self.assertIn('不是',b.execute_tool({'scenario_composer':{'kind':'historical_operation'}},{'tool':'read_scenario_skill'})['content'])

    def test_calculation_window_requires_provenance_and_naive_time(self):
        original=h.definition(PXG)
        for kind in ('unproven','timezone','wrong_kind'):
            record=copy.deepcopy(original);window=record['phases'][1]['execution_window']
            if kind=='unproven':window['evidence']=[]
            if kind=='timezone':window['end']='1937-09-25T13:00+08:00'
            if kind=='wrong_kind':window['kind']='historical_exact_boundary'
            with self.subTest(kind=kind),self.assertRaises(ValueError):h.validate_definition(record)

    def test_foot_units_do_not_share_the_convoy_fuel_pause(self):
        from tools.qa.pingxingguan_fixture import inputs
        from backend import afsim_world
        snapshot,params=inputs();params['rules']['motorized']=True
        for identity,row in params['actors'].items():row['formation']['motorized']=identity.startswith('ww2.jp.')
        world=op.initial(snapshot,params);red=world['red_units'][0]
        scene=afsim_world.compile_scene(world,[{'unit':red['name'],'action':'move','lat':red['lat']+.001,'lng':red['lng']}],1800,native_rules=True)
        self.assertNotIn('double needed0=',scene['script'])
        self.assertIn('ca_fuel_liters',scene['script'])

    def test_observation_distinguishes_configured_initial_and_current_locations(self):
        from tools.qa.pingxingguan_fixture import inputs
        from backend import afsim_state
        snapshot,params=inputs();world=op.initial(snapshot,params)
        original=copy.deepcopy(world['red_units'][1]);world['red_units'][1]['lat']+=.001
        world['simulation_clock']={'elapsed_seconds':1800}
        view=afsim_state.observation({'id':'abcdef123456','war_state':world,'time_step':'30分钟','turn_count':1},{'limit':6})
        row=next(u for u in view['units'] if u['name']==original['name'])
        self.assertEqual(row['configured_initial_position'],{k:original[k] for k in ('lat','lng')})
        self.assertNotEqual(row['position'],row['configured_initial_position'])
        self.assertEqual(view['historical_calculation']['execution_window']['end'],'1937-09-25T13:00')
        self.assertEqual(view['elapsed_seconds'],1800)


if __name__=='__main__':unittest.main()
