"""Bounded current stock claims from actual refused reports; no model calls."""
import copy
import json
from pathlib import Path
import unittest

from gentactix import reporting


class InventoryClaimTests(unittest.TestCase):
    def setUp(self):
        self.world = dict(red_units=[dict(name='炮兵第2团第3营', logistics=dict(food=8, ammo=24),
                                        formation=dict(shells=114)),
                                    dict(name='炮兵第1团第6连', logistics=dict(food=8, ammo=24),
                                         formation=dict(shells=38))],
                          blue_units=[dict(name='日军第106师团', logistics=dict(food=0, ammo=0),
                                           formation=dict(shells=0))])

    def issues(self, text, world=None):
        world = self.world if world is None else world
        before = copy.deepcopy(world)
        issues = [i for i in reporting.inspect(text, world) if i['code'] == 'inventory_claim']
        self.assertEqual(world, before)
        return issues

    def test_four_actual_refused_public_reports_with_positive_stocks(self):
        fixture = json.loads(Path('tools/qa/fixtures/negative_inventory_claims.json').read_text())
        self.assertEqual(len(fixture['reports']), 4)
        for row in fixture['reports']:
            with self.subTest(report=row['report'][-100:]):
                self.assertFalse(self.issues(row['report'], fixture['state']))

    def test_exact_named_resource_lists_check_every_quantity(self):
        for text in ('炮兵第2团第3营炮弹与弹药工作量均未耗尽。',
                     '炮兵第2团第3营与炮兵第1团第6连弹药均未耗尽。',
                     '炮兵第2团第3营粮食与弹药工作量均未耗尽。'):
            with self.subTest(text=text):
                self.assertFalse(self.issues(text))
        self.world['red_units'][0]['formation']['shells'] = 0
        self.assertTrue(self.issues('炮兵第2团第3营炮弹与弹药工作量均未耗尽。'))
        self.assertFalse(self.issues('炮兵第2团第3营弹药工作量未耗尽。'))

    def test_zero_unknown_and_invalid_stock_cannot_support_a_negative_claim(self):
        for value in (0, None, False, '24', float('inf'), -1):
            with self.subTest(value=value):
                world = copy.deepcopy(self.world)
                world['red_units'][0]['logistics']['ammo'] = value
                self.assertTrue(self.issues('炮兵第2团第3营弹药未耗尽。', world))
        self.world['red_units'][0]['formation'].pop('shells')
        self.assertTrue(self.issues('炮兵第2团第3营炮弹未耗尽。'))

    def test_markdown_actor_block_never_uses_target_inventory(self):
        text = '- 炮兵第2团第3营对日军第106师团：实施炮击。炮弹与弹药工作量均未耗尽。'
        self.assertFalse(self.issues(text))
        self.world['red_units'][0]['logistics']['ammo'] = 0
        self.world['blue_units'][0]['logistics']['ammo'] = 24
        self.assertTrue(self.issues(text))

    def test_scoped_block_pronouns_require_the_actor_kind_and_no_subject_switch(self):
        self.assertFalse(self.issues('- 炮兵第2团第3营对日军第106师团：炮击结束。该营的炮弹与弹药工作量均未耗尽。'))
        self.assertTrue(self.issues('- 炮兵第1团第6连对日军第106师团：炮击结束。该营的弹药未耗尽。'))
        self.assertTrue(self.issues('- 炮兵第2团第3营对日军第106师团：日军第106师团随后开火。弹药未耗尽。'))
        self.assertTrue(self.issues('- 炮兵第2团第3营：炮击结束。敌方弹药未耗尽。'))

    def test_unknown_aliases_global_subjects_and_other_blocks_are_not_licensed(self):
        for text in ('全军弹药未耗尽。', '弹药未耗尽。', '伪炮兵第2团第3营弹药未耗尽。',
                     '未知旅与炮兵第2团第3营弹药未耗尽。',
                     '- 炮兵第2团第3营：炮击结束。\n- 战局评价：弹药未耗尽。'):
            with self.subTest(text=text):
                self.assertTrue(self.issues(text))

    def test_comma_continuation_requires_a_named_inventory_or_reload_fact(self):
        self.assertFalse(self.issues('- 炮兵第2团第3营：轮末剩余装填时间为0，炮弹与弹药工作量均未耗尽。'))
        self.assertTrue(self.issues('- 炮兵第2团第3营：未知旅开火，弹药未耗尽。'))

    def test_current_inventory_never_proves_past_future_or_hypothetical_stock(self):
        for text in ('上一轮炮兵第2团第3营弹药未耗尽。',
                     '- 炮兵第2团第3营：炮击结束。下一轮弹药未耗尽。',
                     '- 炮兵第2团第3营：炮击结束。如果弹药未耗尽，继续射击。'):
            with self.subTest(text=text):
                self.assertTrue(self.issues(text))

    def test_one_supported_negative_cannot_hide_a_false_later_statement(self):
        text = '炮兵第2团第3营弹药未耗尽；日军第106师团弹药未耗尽。'
        issues = self.issues(text)
        self.assertTrue(issues)
        self.assertIn('日军第106师团弹药未耗尽', issues[0]['quote'])
        self.assertNotIn('炮兵第2团第3营', issues[0]['quote'])

    def test_named_shell_depletion_requires_actual_zero_shells(self):
        self.assertTrue(self.issues('炮兵第2团第3营炮弹耗尽。'))
        self.world['red_units'][0]['formation']['shells'] = 0
        self.assertFalse(self.issues('炮兵第2团第3营炮弹耗尽。'))
        self.assertFalse(self.issues('日军第106师团弹药耗尽。'))
        self.assertTrue(self.issues('日军第106师团弹药未耗尽。'))

    def test_capability_and_permissions_are_not_inferred_from_inventory(self):
        self.assertFalse(self.issues('炮弹最高射程为8公里。'))
        self.assertTrue(self.issues('炮兵第2团第3营获得开火权。'))
        self.assertTrue(self.issues('炮兵第2团第3营库存未耗尽。'))

    def test_native_rejection_identifies_the_public_claim_without_state_changes(self):
        from verify_native_report_submission import NativeReportSubmissionTests
        f = NativeReportSubmissionTests(); f.setUp()
        try:
            name = f.s['war_state']['red_units'][0]['name']
            final = {**f.final, 'report': name + '弹药工作量未耗尽。'}
            saved = copy.deepcopy((f.s, f.o.runs, final))
            accepted = f.submit(final)
            self.assertTrue(accepted['ok'], accepted)
            rejected = f.submit({**final, 'report': '全军弹药未耗尽。'})
            self.assertFalse(rejected['ok'])
            issue = next(i for i in rejected['issues'] if i['code'] == 'inventory_claim')
            self.assertIn('全军弹药未耗尽', issue['quote'])
            self.assertEqual((f.s, f.o.runs, final), saved)
        finally:
            f.tearDown()


class InventoryContinuationTests(unittest.TestCase):
    """Real T5 stock clause, with bounded subjects and independent stock types."""

    def setUp(self):
        self.before = dict(red_units=[dict(name='第90师', logistics=dict(ammo=28, food=12),
                                          formation=dict(shells=92))],
                           blue_units=[dict(name='日军第106师团', logistics=dict(ammo=0, food=0),
                                            formation=dict(shells=0))])
        self.after = copy.deepcopy(self.before)
        self.after['red_units'][0]['logistics']['ammo'] = 5
        self.after['red_units'][0]['formation']['shells'] = 0
        self.quote = '第90师弹药工作量由28降至5，随队炮弹归零'

    def issues(self, text, *, previous=True):
        saved = copy.deepcopy((self.before, self.after))
        issues = [i for i in reporting.inspect(text, self.after, self.before if previous else None)
                  if i['code'] == 'inventory_claim']
        self.assertEqual((self.before, self.after), saved)
        return issues

    def test_actual_t5_ammo_transition_and_shell_depletion_clause(self):
        self.assertFalse(self.issues(self.quote))

    def test_current_numeric_stock_can_anchor_without_a_previous_world(self):
        for text in ('第90师弹药工作量为5，随队炮弹归零。',
                     '第90师弹药工作量剩余5，炮弹归零。',
                     '第90师弹药工作量为5，粮食工作量为12，随队炮弹归零。'):
            with self.subTest(text=text):
                self.assertFalse(self.issues(text, previous=False))

    def test_nonzero_unknown_or_invalid_classified_stock_still_refuses(self):
        for value in (1, None, False, '0', float('inf'), -1):
            with self.subTest(value=value):
                self.after['red_units'][0]['formation']['shells'] = value
                self.assertTrue(self.issues(self.quote))

    def test_ammo_work_is_never_classified_shells(self):
        self.assertTrue(self.issues('第90师炮弹归零，弹药工作量归零。'))
        self.after['red_units'][0]['logistics']['ammo'] = 0
        self.after['red_units'][0]['formation']['shells'] = 1
        self.assertTrue(self.issues('第90师弹药工作量为0，随队炮弹归零。'))

    def test_transition_anchor_requires_matching_before_and_after_values(self):
        for text in (self.quote.replace('28', '27'), self.quote.replace('至5', '至6'),
                     self.quote.replace('降至', '升至')):
            with self.subTest(text=text):
                self.assertTrue(self.issues(text))
        self.assertTrue(self.issues(self.quote, previous=False))

    def test_current_numeric_anchor_must_match_its_own_resource(self):
        self.assertTrue(self.issues('第90师弹药工作量为0，随队炮弹归零。'))
        self.assertTrue(self.issues('第90师粮食工作量为5，随队炮弹归零。'))

    def test_unknown_target_or_intervening_prose_does_not_bind_a_subject(self):
        for text in ('未知旅弹药工作量为5，随队炮弹归零。',
                     '伪第90师弹药工作量为5，随队炮弹归零。',
                     '第90师对日军第106师团弹药工作量为0，随队炮弹归零。',
                     '第90师弹药工作量为5，未知旅开火，随队炮弹归零。',
                     '第90师弹药工作量为5，敌方随队炮弹归零。'):
            with self.subTest(text=text):
                self.assertTrue(self.issues(text))

    def test_temporal_or_cross_sentence_continuations_are_not_inferred(self):
        for text in ('上一轮'+self.quote, '如果'+self.quote,
                     self.quote.replace('，随队', '，下一轮随队'),
                     self.quote.replace('，随队', '。随队'),
                     self.quote.replace('，随队', '；随队'),
                     self.quote.replace('，随队', '\n随队')):
            with self.subTest(text=text):
                self.assertTrue(self.issues(text))

    def test_one_supported_clause_does_not_license_a_later_wrong_claim(self):
        issues = self.issues(self.quote+'；日军第106师团弹药未耗尽。')
        self.assertTrue(issues)
        self.assertIn('日军第106师团弹药未耗尽', issues[0]['quote'])
        self.assertNotIn('第90师', issues[0]['quote'])


if __name__ == '__main__':
    unittest.main()
