"""Source corrections must stay additive and must not imply new deployments."""
import copy
import unittest
from unittest.mock import patch

from gentactix import historical_initial as hi, historical_links as links
from gentactix import historical_operations as ho, history_replay
from tools.upgrade_wanjialing import BATTLE


class WanjialingRevisionTests(unittest.TestCase):
    def snapshot(self, phase='campaign_reference'):
        return hi.initial(BATTLE, phase, version='1.2.0')['historical_initial']

    def test_corrected_artillery_is_a_new_identity_in_new_version_only(self):
        from tools.upgrade_wanjialing import build
        self.assertEqual(hi.definition(BATTLE, '1.1.0'), build())
        self.assertEqual(hi.definition(BATTLE)['version'], '1.0.0')
        units = {u['id']: u for u in self.snapshot()['definition']['units']}
        self.assertIn('ww2.cn.artillery1.company6', units)
        self.assertNotIn('ww2.cn.artillery4.company6', units)
        self.assertEqual(units['ww2.cn.artillery1.company6']['name'], '炮兵第1团第6连')

    def test_partial_142_is_separate_and_not_an_opening_actor(self):
        s = self.snapshot('oct7_attack'); units = {u['id']: u for u in s['definition']['units']}
        part = units['ww2.cn.division142.wjl_part']
        self.assertEqual(part['parent_id'], 'ww2.cn.division142')
        self.assertEqual(units[part['parent_id']]['children_coverage']['status'], 'partial')
        self.assertNotIn(part['id'], ho.partition(s))
        self.assertEqual(len(ho.configuration_template(s)['actors']), 6)
        self.assertEqual(ho.objective_guidance(s)['binding']['initial_version'], '1.2.0')

    def test_departure_is_not_contact_and_stays_hour_precision(self):
        _, op = links.find(self.snapshot(), 'WJL-Oct8-142-departure')
        self.assertEqual(op['unit_ids'], ['ww2.cn.division142.wjl_part'])
        self.assertEqual(op['kind'], 'movement')
        self.assertEqual(op['date']['precision'], 'hour')
        self.assertIn('11时', op['date']['label'])
        self.assertIn('出击', op['description'])
        self.assertIn('接敌', op['limitations'])
        self.assertTrue(all(p['position'] is None for p in op['places']))

    def test_reference_days_cannot_be_silently_promoted_to_initial_states(self):
        for phase in ('oct6_orders', 'oct8_counterattacks', 'oct9_final_orders', 'oct10_attacks'):
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                ho.partition(self.snapshot(phase))

    def test_oct9_order_preparation_and_fire_are_separate_source_events(self):
        s = self.snapshot()
        ids = [('WJL-Oct9-orders', '15时'), ('WJL-Oct9-preparation', '18时'), ('WJL-Oct9-fire', '19时')]
        for identity, time in ids:
            _, op = links.find(s, identity)
            self.assertIn(time, op['date']['label'])
            self.assertEqual(op['date']['precision'], 'hour')
        self.assertEqual(links.find(s, ids[0][0])[1]['kind'], 'command')
        self.assertEqual(links.find(s, ids[2][0])[1]['kind'], 'attack')

    def test_oct10_is_not_scripted_as_full_annihilation_or_campaign_end(self):
        _, op = links.find(self.snapshot(), 'WJL-Oct10-residual')
        self.assertIn('仍有残敌', op['description'])
        self.assertIn('不等于', op['description'])
        self.assertTrue(all(u['facts'][field]['value'] is None
            for u in self.snapshot()['definition']['units']
            for field in ('personnel', 'equipment', 'position')))
        self.assertFalse(self.snapshot()['definition']['sources']['WJL_GUO']['original_archive_examined'])

    def test_frozen_replay_binds_new_events_and_preserves_missing_facts(self):
        pinned = history_replay.pin(BATTLE, version='1.2.0')
        event_ids = set(); frames = []
        with patch.object(history_replay, 'dataset', side_effect=AssertionError('frozen')):
            for cursor in range(len(pinned['pack']['events'])):
                world = history_replay.frame_pinned(pinned, cursor)
                self.assertTrue(history_replay.validate(world))
                op = world['history_replay'].get('source_operation')
                if op:
                    event_ids.add(op['id']); frames.append(world)
                self.assertTrue(all(u['lat'] is None and u['personnel']['current'] is None
                    for u in world['red_units'] + world['blue_units']))
        self.assertIn('WJL-Oct8-142-departure', event_ids)
        self.assertIn('WJL-Oct10-residual', event_ids)
        self.assertEqual(len(event_ids), 17)
        self.assertTrue(frames)

    def test_native_source_pages_preserve_current_phase_and_do_not_change_state(self):
        session = {'war_state': {'historical_initial': self.snapshot('oct8_counterattacks')}}
        before = copy.deepcopy(session); args = {'limit': 1}; seen = []
        while args:
            response = links.observation(session, args)
            self.assertEqual(response['phase_id'], 'oct8_counterattacks')
            seen += [op['id'] for op in response['operations']]
            args = response['next_args']
        self.assertEqual(len(seen), 4)
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(session, before)

    def test_filtered_read_exposes_literal_match_and_full_phase_retry(self):
        session = {'war_state': {'historical_initial': self.snapshot('oct9_final_orders')}}
        args = {'kind': 'operations', 'query': '10月9日 攻击 准备', 'limit': 2}
        response = links.observation(session, args)
        self.assertEqual(response['total'], 0)
        self.assertEqual(response['query_semantics'], 'literal_substring')
        self.assertEqual(response['unfiltered_total'], 3)
        retry = response['unfiltered_args']
        self.assertEqual(retry['query'], '')
        self.assertEqual(retry['phase_id'], 'oct9_final_orders')
        self.assertEqual(retry['definition_hash'], response['definition_hash'])
        self.assertEqual(links.observation(session, retry)['total'], 3)

    def test_retry_preserves_unit_filter_and_original_args(self):
        session = {'war_state': {'historical_initial': self.snapshot('oct8_counterattacks')}}
        args = {'query': '*', 'unit_id': 'ww2.cn.division142.wjl_part', 'limit': 1}
        before = copy.deepcopy(args); response = links.observation(session, args)
        self.assertEqual(response['unfiltered_total'], 1)
        retry = links.observation(session, response['unfiltered_args'])
        self.assertEqual(retry['total'], 1)
        self.assertEqual(retry['operations'][0]['id'], 'WJL-Oct8-142-departure')
        self.assertEqual(args, before)

    def test_next_page_freezes_resolved_phase_when_current_frame_changes(self):
        session = {'war_state': {'historical_initial': self.snapshot('oct8_counterattacks')}}
        first = links.observation(session, {'limit': 2})
        session['war_state']['historical_initial'] = self.snapshot('oct9_final_orders')
        following = links.observation(session, first['next_args'])
        self.assertEqual(following['phase_id'], 'oct8_counterattacks')
        self.assertEqual({op['id'] for op in following['operations']},
            {'WJL-Oct8-142-departure', 'WJL-Oct8-japanese-situation'})


if __name__ == '__main__':
    unittest.main()
