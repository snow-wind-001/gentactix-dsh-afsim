"""Public-claim regressions from real Native reports; no model or game writes."""
import copy
import json
from pathlib import Path
import unittest

from backend import dsh_simulation
from gentactix import reporting
from tools.qa.campaign_plan_fixture import world
from verify_campaign_plan_backends import proposal


class ReportClaimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = world()
        cls.after = dsh_simulation.apply(cls.before, proposal(cls.before), '30分钟')

    def check(self, text, *, state=None, previous=None, code=None):
        state = self.after if state is None else state
        previous = self.before if previous is None else previous
        frozen = copy.deepcopy((state, previous))
        public, audit = reporting.render(text, state, previous, turn=1)
        self.assertEqual((state, previous), frozen)
        self.assertEqual(audit['original_text'], text)
        if code is None:
            self.assertEqual(audit['issues'], [], audit['issues'])
            self.assertIn(text, public)
        else:
            self.assertIn(code, {i['code'] for i in audit['issues']})
        return audit

    def test_actual_denial_of_authorized_strength(self):
        self.check('此为投入兵力口径而非核定满编。')

    def test_scoped_strength_denials(self):
        for text in ['这是投入兵力，不是核定满编。', '不能据此认定为满编。',
                     '当前数字并非满编。', '不据此称满编。']:
            with self.subTest(text=text):
                self.check(text)

    def test_denial_does_not_license_a_later_strength_assertion(self):
        for text in ['此为投入兵力口径而非核定满编；蓝方依然满编。',
                     '不能据此认定为满编，但红方全员健在。',
                     '若弹药未到，红方仍是满编。']:
            with self.subTest(text=text):
                self.check(text, code='strength_claim')

    def test_actual_two_registered_goal_directions(self):
        self.check('北侧与南侧两个方向的前置目标尚未达成。')

    def test_full_goal_labels_can_name_the_counted_directions(self):
        self.check('北侧方向控制与南侧方向控制两个方向的目标尚未达成。')

    def test_direction_count_inside_a_registered_label_is_not_a_road_claim(self):
        state = copy.deepcopy(self.after)
        state['mission']['definition']['campaign_plan']['nodes'][2]['label'] = '两个方向控制后保持兵力'
        self.check('两个方向控制后保持兵力尚未完成。', state=state)

    def test_direction_count_still_requires_matching_named_goals(self):
        for text in ['东侧与西侧两个方向的目标尚未达成。',
                     '东北侧与南侧两个方向的目标尚未达成。',
                     '北侧与南侧三个方向的前置目标尚未达成。',
                     '共有两个方向的目标尚未达成。']:
            with self.subTest(text=text):
                self.check(text, code='direction_count')

    def test_ambiguous_direction_aliases_require_full_goal_names(self):
        state = copy.deepcopy(self.after)
        extra = copy.deepcopy(state['mission']['definition']['campaign_plan']['nodes'][0])
        extra.update(id='other-north', label='北侧方向防御', team='blue')
        state['mission']['definition']['campaign_plan']['nodes'].append(extra)
        state['campaign_plan']['nodes']['other-north'] = copy.deepcopy(state['campaign_plan']['nodes']['north'])
        self.check('北侧与南侧两个方向的目标尚未达成。', state=state, code='direction_count')

    def test_goal_count_does_not_authorize_encirclement_or_roads(self):
        for text in ['北侧与南侧两个方向全部被封。',
                     '北侧与南侧两个方向的目标尚未达成，退路只剩一条。']:
            with self.subTest(text=text):
                self.check(text, code='direction_count')

    def test_actual_sampling_and_uncompleted_milestone(self):
        self.check('蓝方到达估计突围地域已激活并完成本轮采样，采样条件未达成，仍未记为已完成里程碑。')

    def test_sampling_completion_does_not_grant_a_goal(self):
        for text in ['北侧方向控制已完成本轮采样，目标尚未完成。',
                     '北侧方向控制完成采样，条件未达成。',
                     '北侧方向控制已完成观察，当前条件不成立。']:
            with self.subTest(text=text):
                self.check(text)

    def test_sampling_claim_requires_an_observed_goal(self):
        self.check('北侧方向控制已完成本轮采样，尚未完成目标。', state=self.before,
                   code='goal_verdict')

    def test_sampled_goal_cannot_be_described_as_unobserved(self):
        for text in ['北侧方向控制尚未完成本轮采样。', '北侧方向控制尚未采样。']:
            with self.subTest(text=text):
                self.check(text, code='goal_verdict')

    def test_future_goal_can_truthfully_be_unsampled(self):
        self.check('北侧方向控制尚未完成本轮采样。', state=self.before)

    def test_true_condition_is_separate_from_milestone(self):
        self.check('两方向达成后保持投入兵力当前条件已达成，目标仍未记为已完成。')
        self.check('两方向达成后保持投入兵力当前条件未达成。', code='goal_verdict')

    def test_negative_milestone_does_not_swallow_a_later_false_assertion(self):
        self.check('北侧方向控制仍未记为已完成，但目前已达成目标。', code='goal_verdict')

    def test_recorded_completion_cannot_be_denied(self):
        state = copy.deepcopy(self.after)
        state['campaign_plan']['nodes']['north'].update(status='completed', condition=True)
        self.check('北侧方向控制仍未记为已完成里程碑。', state=state, code='goal_verdict')

    def test_coordinated_goals_share_the_sampling_and_milestone_claim(self):
        text = ('北侧方向控制、南侧方向控制、蓝方到达估计突围地域三项均已激活并完成本轮采样，'
                '采样条件未达成，仍未记为已完成里程碑。')
        self.check(text)
        state = copy.deepcopy(self.after)
        state['campaign_plan']['nodes']['north'].update(status='completed', condition=True)
        self.check(text, state=state, code='goal_verdict')

    def test_coordinated_sampling_does_not_hide_an_unsampled_first_goal(self):
        state = copy.deepcopy(self.after)
        state['campaign_plan']['nodes']['north'] = copy.deepcopy(self.before['campaign_plan']['nodes']['north'])
        self.check('北侧方向控制、南侧方向控制均已完成采样。', state=state, code='goal_verdict')

    def test_separate_goal_predicates_are_not_shared(self):
        state = copy.deepcopy(self.after)
        state['campaign_plan']['nodes']['south'].update(status='completed', condition=True)
        self.check('北侧方向控制尚未完成，南侧方向控制已完成。', state=state)

    def test_prior_and_conditional_observation_claims_use_their_own_frame(self):
        self.check('轮初北侧方向控制尚未完成采样；轮末北侧方向控制已完成采样。')
        self.check('如果北侧方向控制尚未完成采样，应等待宿主采样。')


class SupportedClaimTests(unittest.TestCase):
    """Real T1/T2 evidence, with explicit unit/time scope and counterexamples."""
    @classmethod
    def setUpClass(cls):
        cls.vectors = json.loads((Path(__file__).parent / 'tools/qa/fixtures/report_supported_claims.json').read_text())

    def check(self, text, *, frame=0, code=None, change=None):
        vector = copy.deepcopy(self.vectors[frame])
        if change:
            change(vector)
        frozen = copy.deepcopy(vector)
        public, audit = reporting.render(text, vector['after'], vector['before'], turn=vector['turn'])
        self.assertEqual(vector, frozen)
        self.assertEqual(audit['original_text'], text)
        if code:
            self.assertIn(code, {r['code'] for r in audit['issues']})
            self.assertNotIn(text, public)
        else:
            self.assertEqual(audit['issues'], [])
            self.assertIn(text, public)
        return public, audit

    def test_named_empty_ammo_can_be_reported_from_actual_stock(self):
        for frame in (0, 1):
            self.check('第159师与日军第106师团的随队弹药工作量耗尽。', frame=frame)

    def test_food_and_ammo_are_checked_independently(self):
        self.check('第159师粮食耗尽。', code='inventory_claim')
        self.check('第159师粮食耗尽。', change=lambda v: v['after']['red_units'][1]['logistics'].update(food=0))

    def test_supply_index_cannot_license_stock_claims(self):
        def change(v):
            unit = v['after']['red_units'][1]
            unit['supply'] = 0
            unit['logistics']['ammo'] = 5
        self.check('第159师弹药耗尽。', change=change, code='inventory_claim')

    def test_all_named_units_must_have_known_zero_stock(self):
        self.check('第90师与第159师弹药耗尽。', code='inventory_claim')
        for value in (None, False, '0', float('nan')):
            with self.subTest(value=value):
                self.check('第159师弹药耗尽。', code='inventory_claim',
                           change=lambda v: v['after']['red_units'][1]['logistics'].update(ammo=value))

    def test_ambiguous_subject_and_other_inventory_assertions_stay_rejected(self):
        for text in ['双方弹药耗尽。', '全军弹药耗尽。', '弹药耗尽。',
                     '第159师弹尽粮绝。', '第159师弹药已满。', '第159师弹药够一次。',
                     '第159师无弹。', '第159师库存耗尽。']:
            with self.subTest(text=text):
                self.check(text, code='inventory_claim')

    def test_a_supported_claim_does_not_license_a_later_false_one(self):
        self.check('第159师弹药耗尽；第90师弹药耗尽。', code='inventory_claim')

    def test_subject_list_cannot_drop_an_unregistered_prefix_or_use_an_alias(self):
        for text in ['未知旅与第159师弹药耗尽。', '伪第159师弹药耗尽。',
                     '第159师投入部弹药耗尽。', '上一轮第159师弹药耗尽。']:
            with self.subTest(text=text):
                self.check(text, code='inventory_claim')

    def test_native_stock_evidence_does_not_require_a_dsh_ledger(self):
        self.check('第159师弹药库存耗尽。', change=lambda v: v['after'].pop('dsh_execution'))

    def test_named_final_interval_can_coexist_with_earlier_firing(self):
        for duration in ('3小时', '三个小时', '180分钟'):
            self.check(f'第159师与日军第106师团在本轮最后{duration}停火。')

    def test_whole_turn_or_overlong_stop_is_still_rejected(self):
        for text in ['第159师整轮停火。', '第159师在本轮最后4小时停火。',
                     '第159师在本轮最后3小时停火，整轮没有开火。',
                     '双方在本轮最后3小时停火。']:
            with self.subTest(text=text):
                self.check(text, code='fire_denial')

    def test_last_shot_cannot_be_replaced_by_active_duration(self):
        def change(v):
            v['after']['dsh_execution']['fire_ledger']['units'][0]['last_fire_s'] = 15000
        self.check('第159师在本轮最后3小时停火。', change=change, code='fire_denial')

    def test_stale_missing_or_wrong_source_ledger_does_not_prove_stop(self):
        for field, value in [('turn', 0), ('source', 'afsim_native'), ('version', 'unknown'), ('units', [])]:
            with self.subTest(field=field):
                self.check('第159师在本轮最后3小时停火。', code='fire_denial',
                           change=lambda v: v['after']['dsh_execution']['fire_ledger'].update({field: value}))

    def test_zero_stock_does_not_prove_when_firing_stopped(self):
        self.check('第159师在本轮最后3小时停火。', code='fire_denial',
                   change=lambda v: v['after']['dsh_execution'].clear())

    def test_missing_or_invalid_timing_cannot_license_a_stop(self):
        for field, value in [('last_fire_s', None), ('last_fire_s', True), ('last_fire_s', float('inf')),
                             ('first_fire_s', 20000), ('fire_cycles', 0), ('stop_reason', 'unknown')]:
            with self.subTest(field=field, value=value):
                self.check('第159师在本轮最后3小时停火。', code='fire_denial',
                           change=lambda v: v['after']['dsh_execution']['fire_ledger']['units'][0].update({field: value}))

    def test_other_actor_or_weapon_cannot_borrow_the_receipt(self):
        self.check('第90师在本轮最后3小时停火。', code='fire_denial')
        def change(v):
            v['after']['engagements'].append(dict(attacker='第159师', weapon_action='bombard'))
        self.check('第159师在本轮最后3小时停火。', change=change, code='fire_denial')

    def test_original_ambiguous_reports_remain_audited_and_evidence_is_visible(self):
        for vector in self.vectors:
            public, audit = reporting.render(vector['original_text'], vector['after'], vector['before'], turn=vector['turn'])
            self.assertEqual(audit['original_text'], vector['original_text'])
            self.assertIn('inventory_claim', {i['code'] for i in audit['issues']})
            self.assertIn('随队库存（模型工作量）', public)
            self.assertIn('弹药0', public)
            if vector['turn'] == 1:
                self.assertIn('末发9480秒', public)
                self.assertIn('DSH过程估计，非AFSIM遥测', public)
            else:
                self.assertNotIn('末发9480秒', public)


if __name__ == '__main__':
    unittest.main(verbosity=2)
