"""DSH estimates and native scripts share host goal scoring, not host physics."""
import copy
import os
import tempfile
import unittest
from unittest.mock import patch

from gentactix import campaign_plan as plan, historical_operations as ho, missions, sim_clock, synthetic_history
from tools.qa.campaign_plan_fixture import inputs
from verify_campaign_plan import step
from verify_dsh_resources import model_result


def proposal(world):
    value = model_result(world)
    value['campaign'] = {'actors': {name: {k: copy.deepcopy(row[k]) for k in
        ('active', 'fortification_integrity', 'base_entrenchment', 'captured_this_turn')}
        for name, row in world['campaign']['actors'].items()}}
    return value


class CampaignPlanBackendTests(unittest.TestCase):
    def test_native_old_point_goal_cannot_end_new_dag(self):
        from backend import afsim_world
        world = ho.initial(*inputs())
        native = afsim_world.compile_scene(world, [], 1800, native_rules=True)['native_model']['script']
        self.assertIn('bool terminal=false', native)
        self.assertIn('bool success=false', native)

    def test_dsh_physical_estimate_updates_shared_goal_state_without_model_verdict(self):
        from backend import dsh_simulation
        world = ho.initial(*inputs()); saved = copy.deepcopy(world)
        after = dsh_simulation.apply(world, proposal(world), '30分钟')
        self.assertEqual(after['campaign_plan']['turn'], 1)
        self.assertEqual(after['mission']['status'], 'active')
        self.assertEqual(after['red_units'][0]['logistics']['food'], world['red_units'][0]['logistics']['food'] - 2)
        self.assertTrue(missions.validate(after))
        self.assertIn('目标', missions.report(after))
        self.assertEqual(world, saved)
        forged = proposal(world); forged['campaign_plan'] = after['campaign_plan']
        with self.assertRaisesRegex(ValueError, '顶层字段'):
            dsh_simulation.apply(world, forged, '30分钟')

    def test_old_joint_conditions_can_all_be_true_while_new_axes_still_unmet(self):
        from backend import dsh_simulation
        from gentactix import campaign
        s, p = inputs(); center = p['area']['center']
        p['goal']['radius_km'] = 1
        p['actors']['ww2.jp.division106']['position']['lng'] -= .02
        p['campaign']['objective']['relief_regions'] = [{'center': copy.deepcopy(center), 'radius_km': 1}]
        world = ho.initial(s, p); self.assertTrue(all(campaign.assess(world).values()))
        after = dsh_simulation.apply(world, proposal(world), '30分钟')
        self.assertTrue(all(after['campaign']['objective'].values()))
        self.assertFalse(after['campaign_plan']['outcomes']['red'])
        self.assertEqual(after['mission']['status'], 'active')

    def test_global_required_turns_are_counted_independently_for_both_teams(self):
        s, p = inputs(); p['goal']['required_turns'] = 2; world = ho.initial(s, p)
        points = {n['id']: n['condition'].get('region', {}).get('center') for n in p['campaign_plan']['nodes']}
        a = step(world, {'ww2.cn.division159': points['north'], 'ww2.cn.division51': points['south']})
        self.assertEqual(a['campaign_plan']['side_progress'], {'red': 1, 'blue': 0})
        self.assertEqual(a['mission']['status'], 'active')
        b = step(a); self.assertEqual(b['mission']['winner'], 'red')

    def test_staged_unit_cannot_control_goal_before_its_actual_release(self):
        s, p = inputs(); n = p['campaign_plan']['nodes'][0]
        p['actors']['ww2.cn.division159']['position'] = copy.deepcopy(n['condition']['region']['center'])
        p['campaign']['arrivals']['ww2.cn.division159']['not_before'] = '1938-10-07T01:00'
        w = ho.initial(s, p); a = step(w)
        self.assertEqual(a['campaign_plan']['nodes']['north']['status'], 'waiting_arrival')
        self.assertEqual(step(a)['campaign_plan']['nodes']['north']['status'], 'completed')

    def test_pages_and_members_are_readonly_and_reject_old_state_hash(self):
        w = ho.initial(*inputs()); before = copy.deepcopy(w); args = {'limit': 1}; seen = []
        with self.assertRaisesRegex(ValueError,'翻页'):
            plan.observation(w,offset=1,limit=1)
        while args:
            r = plan.observation(w, **args); seen += [n['id'] for n in r['nodes']]; args = r['next_args']
        self.assertEqual(len(seen), 4); self.assertEqual(len(set(seen)), 4)
        r = plan.observation(w, node_id='preserve', limit=1); args = r['nodes'][0]['member_args']; members = []
        while args:
            r = plan.observation(w, **args); members += r['members']; args = r['next_args']
        self.assertEqual(len(members), 5); self.assertEqual(w, before)
        stale = plan.observation(w, limit=1)['next_args']; new = step(w)
        with self.assertRaisesRegex(ValueError, '变化'):
            plan.observation(new, **stale)

    def test_synthetic_edits_rebind_goals_and_refuse_silently_empty_force(self):
        s, p = inputs(); base = ho.definition(s, p); binding = base['historical_calculation']
        config = synthetic_history.seed(binding)['configuration']
        row = next(u for u in config['teams']['red'] if u['basis_id'] == 'ww2.cn.division159')
        row['name'] = '北侧合成部队'
        extra = copy.deepcopy(row); extra['name'] = '新增北侧合成部队'; config['teams']['red'].append(extra)
        spec = synthetic_history.definition(binding, config); world = missions.from_definition(spec)
        north = next(n for n in spec['campaign_plan']['nodes'] if n['id'] == 'north')
        self.assertEqual(len(north['unit_ids']), 2)
        self.assertTrue(all(i.startswith('exercise.') for i in north['unit_ids']))
        self.assertTrue(missions.validate(world))
        config['teams']['red'] = [u for u in config['teams']['red'] if u['basis_id'] != 'ww2.cn.division159']
        with self.assertRaisesRegex(ValueError, '全部承担单位'):
            synthetic_history.definition(binding, config)

    def test_invalid_plan_at_api_create_is_rejected_before_a_session_exists(self):
        from backend import main
        from fastapi.testclient import TestClient
        s, p = inputs(); p['campaign_plan']['nodes'][0]['unit_ids'] = ['wrong']
        request = dict(scenario='仅软件QA目标图', battle=s['definition']['battle'], time_step='30分钟',
            simulation_mode='open', product_mode='historical', execution_backend='afsim',
            historical_parameters=p,historical_initial_version='1.2.0')
        before = set(main._SESSIONS)
        response = TestClient(main.app).post('/api/sessions', json=request)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn('目标承担单位',response.text)
        self.assertEqual(set(main._SESSIONS), before)

    def test_api_direct_parameters_can_pin_nondefault_initial_version(self):
        from backend import main
        from fastapi.testclient import TestClient
        s,p=inputs();request=dict(scenario='仅软件QA目标图',battle=s['definition']['battle'],time_step='30分钟',
            simulation_mode='open',product_mode='historical',execution_backend='afsim',historical_parameters=p,
            historical_initial_version='1.2.0')
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder+'/sessions','GENTACTIX_TRACE_DIR':folder+'/traces'}):
            response=TestClient(main.app).post('/api/sessions',json=request)
            self.assertEqual(response.status_code,200,response.text);sid=response.json()['session_id']
            try:
                self.assertEqual(main._SESSIONS[sid]['historical_definition']['historical_calculation']['initial']['version'],'1.2.0')
            finally:main._SESSIONS.pop(sid,None)

    def test_native_objective_tool_is_bounded_and_never_exposes_full_world(self):
        from backend import agent_tools
        w=ho.initial(*inputs());session={'id':'goal-tool-qa','war_state':w,'turn_count':0};saved=copy.deepcopy(w)
        value=agent_tools.execute_tool_call(session,w,{'tool':'get_campaign_objectives','args':{'limit':1}})
        self.assertTrue(value['ok']);self.assertEqual(len(value['nodes']),1)
        self.assertNotIn('mission',value);self.assertNotIn('initial_state',str(value))
        self.assertNotIn('unit_ids',value['nodes'][0]);self.assertIn('member_args',value['nodes'][0])
        bad=agent_tools.execute_tool_call(session,w,{'tool':'get_campaign_objectives','args':{'limit':17}})
        self.assertFalse(bad['ok']);self.assertEqual(w,saved)


if __name__ == '__main__':
    unittest.main()
