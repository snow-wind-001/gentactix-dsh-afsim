"""Source-backed cross-formation tasks and withdrawal references, not forced play."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from gentactix import historical_initial as hi, historical_links as links
from gentactix import historical_operations as ho, history_replay
from tools.upgrade_wanjialing import BATTLE


class WanjialingCampaignSourcesTests(unittest.TestCase):
    def snapshot(self, phase='campaign_reference'):
        return hi.initial(BATTLE, phase, version='1.3.0')['historical_initial']

    def test_new_version_is_reproducible_and_does_not_promote_default(self):
        from tools.upgrade_wanjialing_130 import build
        self.assertEqual(self.snapshot()['definition'], build())
        self.assertEqual(hi.definition(BATTLE)['version'], '1.0.0')
        from tools.upgrade_wanjialing_120 import build as old_build
        self.assertEqual(hi.definition(BATTLE, '1.2.0'), old_build())

    def test_japanese_attachment_does_not_change_administrative_parent(self):
        s = self.snapshot('sep28_isolation'); units = {u['id']:u for u in s['definition']['units']}
        self.assertEqual(units['ww2.jp.regiment149']['parent_id'], 'ww2.jp.division101')
        self.assertEqual(units['ww2.jp.regiment123']['parent_id'], 'ww2.jp.division106')
        phase = next(p for p in s['definition']['phases'] if p['id'] == s['phase_id'])
        attachment = next(r for r in phase['relations'] if r['child_id'] == 'ww2.jp.regiment149')
        self.assertEqual(attachment['parent_id'], 'ww2.jp.division106')
        self.assertEqual(attachment['kind'], 'operational_command')
        self.assertTrue(all(u['children_coverage']['status'] == 'partial' for u in units.values()
                            if u['id'] in ('ww2.jp.division101', 'ww2.jp.division106')))

    def test_oct2_orders_are_two_axes_and_not_proof_of_arrival(self):
        s = self.snapshot('oct2_encirclement')
        _, east = links.find(s, 'WJL-Oct2-east-order'); _, west = links.find(s, 'WJL-Oct2-west-order')
        self.assertIn('ww2.cn.army74', east['unit_ids'])
        self.assertIn('ww2.cn.division187', east['unit_ids'])
        self.assertIn('ww2.cn.division_new13', west['unit_ids'])
        self.assertIn('ww2.cn.division_reserve6', west['unit_ids'])
        self.assertEqual(east['kind'], 'command'); self.assertEqual(west['kind'], 'command')
        with self.assertRaises(ValueError): ho.partition(s)
        self.assertIn('到场', east['limitations'])

    def test_interdiction_order_keeps_partial_units_and_distinct_foe(self):
        _, event = links.find(self.snapshot(), 'WJL-Oct6-relief-blocking')
        self.assertEqual(event['kind'], 'interception')
        self.assertIn('ww2.cn.division91', event['unit_ids'])
        self.assertIn('ww2.cn.division_reserve6', event['unit_ids'])
        self.assertIn('ww2.jp.division27', event['unit_ids'])
        self.assertIn('投入范围未载', event['description'])
        self.assertIn('不改变', event['limitations'])

    def test_post_oct10_redeployment_and_oct17_retreat_are_not_clocked_effects(self):
        s = self.snapshot()
        _, event = links.find(s, 'WJL-Oct12-redeployment')
        self.assertEqual(event['date']['precision'], 'day')
        self.assertEqual(event['kind'], 'command')
        _, withdrawal = links.find(s, 'WJL-Oct17-withdrawal')
        self.assertEqual(withdrawal['date']['precision'], 'day')
        self.assertEqual(withdrawal['kind'], 'withdrawal')
        self.assertIn('不强制', withdrawal['limitations'])
        self.assertNotIn('00:00', withdrawal['date']['label'])
        self.assertFalse(s['definition']['sources']['WJL_GUO']['original_archive_examined'])

    def test_oct16_division61_is_not_silently_merged_into_division60(self):
        s = self.snapshot(); units = {u['id']:u for u in s['definition']['units']}
        _, event = links.find(s, 'WJL-Oct16-retrograde')
        self.assertIn('ww2.cn.division61', event['unit_ids'])
        self.assertNotIn('ww2.cn.division60', event['unit_ids'])
        self.assertEqual(units['ww2.cn.division61']['team'], 'red')
        self.assertIsNone(units['ww2.cn.division61']['parent_id'])

    def test_facts_and_old_opening_selection_remain_honest(self):
        s = self.snapshot('oct7_attack')
        self.assertEqual(len(ho.partition(s)), 6)
        self.assertTrue(all(u['facts'][key]['value'] is None
                            for u in s['definition']['units'] for key in ('personnel','equipment','position')))
        self.assertEqual(ho.objective_guidance(s)['binding']['initial_version'], '1.3.0')

    def test_new_operations_are_in_pinned_replay_and_require_no_live_source(self):
        pinned = history_replay.pin(BATTLE, version='1.3.0'); saved = copy.deepcopy(pinned)
        ids = [e.get('event_key') for e in pinned['pack']['events']]
        expected = ['WJL-Sep28-149-attachment', 'WJL-Oct2-east-order', 'WJL-Oct2-west-order',
                    'WJL-Oct6-relief-blocking', 'WJL-Oct12-redeployment', 'WJL-Oct17-withdrawal']
        self.assertTrue(set(expected) <= set(ids))
        self.assertEqual([ids.index(i) for i in expected], sorted(ids.index(i) for i in expected))
        with patch.object(history_replay, 'dataset', side_effect=AssertionError('frozen source')):
            for key in expected:
                w = history_replay.frame_pinned(pinned, ids.index(key))
                self.assertTrue(history_replay.validate(w))
                self.assertEqual(w['history_replay']['source_operation']['id'], key)
                self.assertTrue(all(u['lat'] is None and u['personnel']['current'] is None
                                    for u in w['red_units'] + w['blue_units']))
        self.assertEqual(pinned, saved)

    def test_native_evidence_paging_keeps_version_and_is_readonly(self):
        s = {'war_state': {'historical_initial': self.snapshot('oct2_encirclement')}}
        saved = copy.deepcopy(s); seen = []; args = {'limit':1}
        while args:
            page = links.observation(s, args)
            self.assertEqual(page['definition_hash'], s['war_state']['historical_initial']['definition_hash'])
            seen.extend(o['id'] for o in page['operations']); args = page['next_args']
        self.assertEqual(set(seen), {'WJL-Oct2-east-order', 'WJL-Oct2-west-order'})
        self.assertEqual(s, saved)

    def test_previous_replay_versions_do_not_receive_future_source_events(self):
        for version in ('1.0.0', '1.1.0', '1.2.0'):
            with self.subTest(version=version):
                pack=history_replay.pin(BATTLE,version=version)['pack']
                self.assertNotIn('WJL-Oct17-withdrawal', {e.get('event_key') for e in pack['events']})
                self.assertEqual(len(pack['events']), len(history_replay.dataset(BATTLE)['events']))

    def test_new_pinned_events_do_not_duplicate_old_links(self):
        pack=history_replay.pin(BATTLE,version='1.3.0')['pack']
        ids=[e['event_key'] for e in pack['events'] if e.get('event_key')]
        expected={o['id'] for p in self.snapshot()['definition']['phases'] for o in p.get('operations',[])}
        self.assertEqual(set(ids), expected)
        self.assertEqual(len(ids), len(expected))

    def test_extension_must_not_silently_deduplicate_corrupt_editorial_events(self):
        pack=history_replay.dataset(BATTLE)
        existing=next(e for e in pack['events'] if e.get('event_key')=='WJL-Oct7-shibao')
        pack['events'].append(copy.deepcopy(existing))
        with patch.object(history_replay,'dataset',return_value=pack):
            with self.assertRaisesRegex(ValueError,'重复|多个'):
                history_replay.pin(BATTLE,version='1.3.0')


if __name__ == '__main__': unittest.main()
