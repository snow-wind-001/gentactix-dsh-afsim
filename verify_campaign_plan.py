"""Typed multi-axis goal DAG: metadata scoring must never execute battle effects."""
import copy
import unittest
from unittest.mock import patch

from gentactix import historical_operations as ho, missions, sim_clock
from tools.qa.campaign_plan_fixture import inputs


def step(before, positions=None):
    after = copy.deepcopy(before)
    for _, unit in missions.units(after):
        if positions and unit['historical_unit_id'] in positions:
            unit.update(positions[unit['historical_unit_id']])
    after['current_time'], after['simulation_clock'] = sim_clock.target(before, '30分钟')
    after['mission']['turn'] += 1
    from gentactix import campaign
    if campaign.definition(after):
        after['campaign']['turn'] = after['mission']['turn']
    missions.evaluate(after)
    return after


class CampaignPlanTests(unittest.TestCase):
    def make(self, edit=None):
        s, p = inputs()
        if edit: edit(p['campaign_plan'])
        return ho.initial(s, p)

    def points(self, world):
        nodes = world['mission']['definition']['campaign_plan']['nodes']
        return {n['id']: copy.deepcopy(n['condition']['region']['center'])
                for n in nodes if 'region' in n['condition']}

    def test_optional_plan_is_frozen_but_never_promoted_to_history(self):
        from gentactix import campaign_plan
        w = self.make(); spec = w['mission']['definition']
        self.assertEqual(campaign_plan.VERSION, 'campaign-objectives-1')
        self.assertEqual(w['campaign_plan']['turn'], 0)
        self.assertEqual(ho.from_binding(spec['historical_calculation']), spec)
        self.assertEqual(w['campaign_plan']['source'], 'host_goal_evaluator')
        self.assertTrue(all(u['facts']['personnel']['value'] is None for u in w['historical_initial']['definition']['units']))
        self.assertTrue(missions.validate(w))

    def test_one_axis_does_not_end_whole_campaign(self):
        w = self.make(); before = copy.deepcopy(w); point = self.points(w)['north']
        after = step(w, {'ww2.cn.division159': point})
        self.assertEqual(after['campaign_plan']['nodes']['north']['status'], 'completed')
        self.assertEqual(after['campaign_plan']['nodes']['south']['status'], 'active')
        self.assertEqual(after['campaign_plan']['nodes']['preserve']['status'], 'waiting_dependency')
        self.assertEqual(after['mission']['status'], 'active')
        self.assertEqual(w, before)

    def test_two_axes_plus_preservation_complete_on_program_conditions(self):
        w = self.make(); points = self.points(w)
        after = step(w, {'ww2.cn.division159': points['north'], 'ww2.cn.division51': points['south']})
        self.assertEqual(after['mission']['status'], 'completed')
        self.assertEqual(after['mission']['winner'], 'red')
        self.assertTrue(after['campaign_plan']['outcomes']['red'])
        self.assertFalse(after['campaign_plan']['outcomes']['blue'])

    def test_blue_has_own_goal_and_not_a_default_awarded_win(self):
        w = self.make(); point = self.points(w)['blue_exit']
        after = step(w, {'ww2.jp.division106': point})
        self.assertEqual(after['mission']['winner'], 'blue')
        self.assertEqual(after['mission']['status'], 'completed')
        self.assertIn('蓝方目标', after['mission']['reason'])

    def test_simultaneous_goals_are_explicit_draw(self):
        w = self.make(); points = self.points(w)
        after = step(w, {'ww2.cn.division159': points['north'], 'ww2.cn.division51': points['south'],
                         'ww2.jp.division106': points['blue_exit']})
        self.assertIsNone(after['mission']['winner'])
        self.assertIn('双方目标同时', after['mission']['reason'])

    def test_maintained_goal_resets_when_enemy_enters(self):
        w = self.make(); points = self.points(w)
        a = step(w, {'ww2.cn.division159': points['north']})
        b = step(a, {'ww2.jp.division106': points['north']})
        self.assertEqual(b['campaign_plan']['nodes']['north']['status'], 'active')
        self.assertFalse(b['campaign_plan']['nodes']['north']['condition'])

    def test_latched_milestone_retains_achievement_but_reports_loss_of_control(self):
        w = self.make(lambda plan: plan['nodes'][0].update(latch=True)); point = self.points(w)['north']
        a = step(w, {'ww2.cn.division159': point})
        b = step(a, {'ww2.jp.division106': point})
        node = b['campaign_plan']['nodes']['north']
        self.assertEqual(node['status'], 'completed')
        self.assertFalse(node['condition'])
        self.assertEqual(node['completed_at'], 1800)

    def test_holding_time_starts_at_first_sample_not_retroactive_whole_turn(self):
        w = self.make(lambda plan: plan['nodes'][0].update(hold_seconds=1800))
        a = step(w, {'ww2.cn.division159': self.points(w)['north']})
        self.assertEqual(a['campaign_plan']['nodes']['north']['status'], 'holding')
        self.assertEqual(a['campaign_plan']['nodes']['north']['held_seconds'], 0)
        b = step(a)
        self.assertEqual(b['campaign_plan']['nodes']['north']['held_seconds'], 1800)
        self.assertEqual(b['campaign_plan']['nodes']['north']['status'], 'completed')

    def test_not_before_does_not_create_arrival_or_earlier_control(self):
        w = self.make(lambda plan: plan['nodes'][0].update(not_before_seconds=3600))
        a = step(w, {'ww2.cn.division159': self.points(w)['north']})
        self.assertEqual(a['campaign_plan']['nodes']['north']['status'], 'waiting_time')
        b = step(a)
        self.assertEqual(b['campaign_plan']['nodes']['north']['completed_at'], 3600)

    def test_any_dependency_and_outcome_are_supported(self):
        def edit(plan):
            plan['nodes'][2]['after']['mode'] = 'any'
        w = self.make(edit); after = step(w, {'ww2.cn.division159': self.points(w)['north']})
        self.assertEqual(after['mission']['winner'], 'red')

    def test_empty_unknown_cyclic_cross_team_or_nonfinite_inputs_are_rejected(self):
        def invalid(kind, plan):
            if kind == 'empty': plan['nodes'] = []
            elif kind == 'unknown': plan['nodes'][0]['unit_ids'] = ['fictional']
            elif kind == 'cycle': plan['nodes'][0]['after']['node_ids'] = ['preserve']
            elif kind == 'cross': plan['nodes'][0]['unit_ids'] = ['ww2.jp.division106']
            elif kind == 'source': plan['nodes'][0]['operation_ids'] = ['fabricated-event']
            elif kind == 'nan': plan['nodes'][0]['condition']['region']['radius_km'] = float('nan')
            elif kind == 'outcome': plan['outcomes']['red']['node_ids'] = ['blue_exit']
        for kind in ('empty', 'unknown', 'cycle', 'cross', 'source', 'nan', 'outcome'):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.make(lambda plan: invalid(kind, plan))

    def test_goal_evaluation_is_idempotent_and_never_changes_physical_ledgers(self):
        w = self.make(); after = step(w)
        saved = copy.deepcopy(after)
        missions.evaluate(after)
        self.assertEqual(after, saved)
        for field in ('red_units', 'blue_units', 'supply_nodes', 'combined_arms'):
            self.assertEqual(after[field], w[field])

    def test_same_turn_changed_physics_cannot_reuse_scored_goal(self):
        w = step(self.make()); w['red_units'][0]['lat'] += .001
        with self.assertRaisesRegex(ValueError, '目标|物理|重复'):
            missions.evaluate(w)

    def test_goal_input_hash_ignores_receipt_provenance_but_keeps_predicate_inputs(self):
        from gentactix import campaign_plan
        w=step(self.make())
        w['red_units'][0]['personnel']['calculation_source']='同一人员数的外部执行回执'
        w['red_units'][0]['formation']['last_execution']={'source':'原生回执附加元数据','turn':1}
        w['red_units'][0]['logistics']['food']=float(w['red_units'][0]['logistics']['food'])
        campaign_plan.validate_state(w)
        w['red_units'][0]['formation']['suppression']=99
        with self.assertRaisesRegex(ValueError,'目标'):
            campaign_plan.validate_state(w)

    def test_graph_status_cannot_be_forged_in_saved_world(self):
        w = step(self.make()); w['campaign_plan']['nodes']['north']['status'] = 'completed'
        with self.assertRaisesRegex(ValueError, '目标|图'):
            missions.validate(w)

    def test_old_worlds_keep_their_previous_goal_policy(self):
        from tools.qa.initial_command_fixture import inputs as old_inputs
        w = ho.initial(*old_inputs()); self.assertNotIn('campaign_plan', w)
        with patch('gentactix.campaign_plan.evaluate', side_effect=AssertionError('Legacy policy')):
            missions.evaluate(w)


if __name__ == '__main__':
    unittest.main()
