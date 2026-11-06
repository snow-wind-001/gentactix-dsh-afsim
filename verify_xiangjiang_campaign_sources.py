"""Sourced campaign processes do not become invented same-day deployments."""
import copy
import unittest

from gentactix import campaign_scope, historical_initial as hi
from gentactix import historical_links as links, historical_operations as ho, history_replay
from verify_historical_measurements import fixture

BATTLE = '红军长征-湘江战役-1934.11.25至1934.12.01'
VERSION = '1.2.0'
OLD_DIGEST = 'a98ebae62974e529b3a104a993e43f0510b251957d8b6c2064209972f7b2c2df'


class ReductionScopeTests(unittest.TestCase):
    def test_partial_documentation_and_all_period_reduction_are_distinct_personnel_statistics(self):
        for statistic in ('documented_partial_reduction', 'reported_reduction'):
            d, _, row = fixture(); row['statistic'] = statistic
            with self.subTest(statistic=statistic):
                self.assertTrue(hi.validate_definition(d))
                self.assertIn('不', links.MEASUREMENT_STATISTIC_NOTES[statistic])
                for metric in ('artillery', 'food'):
                    bad = copy.deepcopy(d)
                    target = next(p for p in bad['phases'] if p.get('measurements'))['measurements'][0]
                    target.update(metric=metric)
                    target['quantity']['unit'] = links.MEASUREMENT_UNITS[metric]
                    with self.assertRaisesRegex(ValueError, '人员'):
                        hi.validate_definition(bad)


class XiangjiangCampaignSourcesTests(unittest.TestCase):
    def definition(self):
        return hi.definition(BATTLE, VERSION)

    def test_old_versions_default_and_old_october_statistics_are_immutable(self):
        self.assertEqual(hi.definition(BATTLE)['version'], '1.0.0')
        old = hi.definition(BATTLE, '1.1.0')
        self.assertEqual(hi.digest(old), OLD_DIGEST)
        new = self.definition()
        for identity in ('oct8_strength_reference', 'xinxu_nov28', 'guanghuapu_nov30_morning'):
            self.assertEqual(next(p for p in old['phases'] if p['id'] == identity),
                             next(p for p in new['phases'] if p['id'] == identity))

    def test_three_fronts_columns_and_rearguard_have_sourced_identities_without_counts_or_poses(self):
        d = self.definition(); self.assertTrue(hi.validate_definition(d))
        units = {u['id']: u for u in d['units']}
        for identity in ('division1', 'division2', 'regiment4', 'regiment5', 'regiment6',
                         'division13', 'division34', 'regiment100', 'regiment101', 'regiment102',
                         'field_column1', 'field_column2', 'corps5_hq'):
            self.assertIn('lm.red.' + identity, units)
        self.assertEqual(len(units), 39)
        self.assertTrue(all(f['value'] is None for u in units.values() for f in u['facts'].values()))
        for identity in ('corps1', 'corps5', 'division2', 'division34'):
            self.assertEqual(units['lm.red.' + identity]['children_coverage']['status'], 'partial')
        self.assertFalse(any(d['coverage'][k] for k in ('order_of_battle_complete', 'opening_deployment_complete', 'strength_complete')))

    def test_each_new_day_is_reference_only_and_never_admits_a_fake_battle(self):
        d = self.definition()
        days = [p for p in d['phases'] if p['id'].startswith('day_')]
        self.assertEqual(len(days), 7)
        self.assertEqual([p['date']['label'] for p in days],
                         ['1934-11-25', '1934-11-26', '1934-11-27', '1934-11-28',
                          '1934-11-29', '1934-11-30', '1934-12-01'])
        for p in days:
            self.assertNotIn('execution_window', p)
            snapshot = hi.initial(BATTLE, p['id'], version=VERSION)['historical_initial']
            with self.assertRaises(ValueError): ho.configuration_template(snapshot)
            self.assertIsNone(ho.objective_guidance(snapshot))

    def test_local_configuration_still_has_the_original_four_actors_and_new_version_goal_pin(self):
        for phase in ('xinxu_nov28', 'guanghuapu_nov30_morning'):
            old = hi.initial(BATTLE, phase, version='1.1.0')['historical_initial']
            new = hi.initial(BATTLE, phase, version=VERSION)['historical_initial']
            self.assertEqual(ho.partition(new), ho.partition(old))
            self.assertEqual(ho.configuration_template(new)['actors'], ho.configuration_template(old)['actors'])
            self.assertEqual(ho.objective_guidance(new)['binding']['initial_definition_hash'], hi.digest(self.definition()))
        self.assertEqual(len(ho.partition(hi.initial(BATTLE, 'xinxu_nov28', version=VERSION)['historical_initial'])), 4)

    def test_late_main_arrival_and_rearguard_command_do_not_become_earlier_whole_division_presence(self):
        d = self.definition(); operations = {o['id']: o for p in d['phases'] for o in p.get('operations', [])}
        early = operations['LM01-Nov27-jiaoshanpu-detachments']
        self.assertIn('lm.red.regiment5', early['unit_ids'])
        self.assertIn('lm.red.regiment6', early['unit_ids'])
        self.assertNotIn('lm.red.division1', early['unit_ids'])
        self.assertIn('一个', early['limitations'])
        late = operations['LM01-Nov30-division1-main-arrival']
        self.assertIn('lm.red.division1', late['unit_ids'])
        self.assertEqual(late['date']['label'], '1934-11-30 凌晨')
        command = operations['LM01-Nov30-rearguard-relief-order']
        self.assertEqual(command['kind'], 'command')
        self.assertIn('不证明', command['limitations'])

    def test_chapter_replay_binds_each_frame_and_keeps_unknown_current_people_and_positions(self):
        pinned = history_replay.pin(BATTLE, version=VERSION)
        self.assertEqual(len(pinned['pack']['events']), 27)
        all_dates = []
        for index in range(27):
            world = history_replay.frame_pinned(pinned, index)
            operation = world['history_replay']['source_operation']
            all_dates.append(operation['date']['label'][:10])
            related = {u['historical_unit_id'] for team in ('red', 'blue') for u in world[team + '_units']
                       if u['frame_operation_ids']}
            self.assertEqual(related, set(operation['unit_ids']))
            self.assertTrue(all(u['lat'] is None and u['lng'] is None and u['personnel']['current'] is None
                                for team in ('red', 'blue') for u in world[team + '_units']))
        self.assertEqual(all_dates, sorted(all_dates))
        self.assertEqual(world['history_replay']['status'], 'completed')
        self.assertEqual(len(history_replay.pin(BATTLE, version='1.1.0')['pack']['events']), 16)

    def test_paged_source_observation_restores_exact_binding_without_modifying_a_frame(self):
        d = self.definition(); snapshot = hi.initial(BATTLE, 'day_19341130', version=VERSION)['historical_initial']
        session = {'war_state': hi._materialize(d, 'day_19341130')}; before = copy.deepcopy(session)
        args = dict(kind='operations', limit=2); rows = []
        while args:
            result = links.observation(session, args); rows += result['operations']; args = result['next_args']
            self.assertEqual(result['definition_hash'], snapshot['definition_hash'])
        self.assertEqual(len(rows), 7)
        self.assertEqual(session, before)
        with self.assertRaisesRegex(ValueError, '版本'):
            links.observation(session, dict(kind='operations', definition_hash=OLD_DIGEST))

    def test_known_morning_evening_and_late_crossing_constraints_hold_in_frame_order(self):
        pinned = history_replay.pin(BATTLE, version=VERSION)
        order = {e['event_key']: i for i, e in enumerate(pinned['pack']['events'])}
        self.assertLess(order['LM01-Nov30-division1-main-arrival'], order['LM01-Nov30-column1-crossing'])
        self.assertLess(order['LM01-Nov30-column1-crossing'], order['LM01-Nov30-column2-crossing'])
        self.assertLess(order['LM01-Nov30-column1-crossing'], order['LM01-Nov30-guanghuapu-relief'])
        self.assertLess(order['LM01-Dec1-corps5-crossing'], order['LM01-Dec1-corps8-crossing'])
        self.assertLess(order['LM01-Dec1-corps8-crossing'], order['LM01-Dec1-main-crossing-reference'])

    def test_headquarters_crossing_does_not_claim_the_whole_corps_or_rearguard_crossed(self):
        d = self.definition(); operations = {o['id']: o for p in d['phases'] for o in p.get('operations', [])}
        crossing = operations['LM01-Dec1-corps5-crossing']
        self.assertEqual(set(crossing['unit_ids']), {'lm.red.corps5_hq', 'lm.red.division13'})
        hq = next(u for u in d['units'] if u['id'] == 'lm.red.corps5_hq')
        self.assertEqual(hq['role'], 'command')
        for identity in ('lm.red.corps5', 'lm.red.division34'):
            self.assertNotIn(identity, crossing['unit_ids'])

    def test_loss_measurements_are_partial_or_total_reduction_and_never_reported_casualties(self):
        d = self.definition(); phase = next(p for p in d['phases'] if p['id'] == 'loss_scope_reference')
        rows = phase['measurements']; self.assertEqual(len(rows), 3)
        self.assertEqual({r['statistic'] for r in rows}, {'documented_partial_reduction', 'reported_reduction'})
        partial = next(r for r in rows if r['statistic'] == 'documented_partial_reduction')
        self.assertEqual(partial['quantity'], dict(relation='approx', lower=9400, upper=9400, unit='persons'))
        self.assertTrue(all('阵亡' in r['limitations'] and '配额' in r['limitations'] for r in rows))
        self.assertTrue(all(not d['sources'][e['source_id']]['original_archive_examined'] for r in rows for e in r['evidence']))

    def test_campaign_candidate_ancestors_and_columns_are_not_double_counted(self):
        snapshot = hi.initial(BATTLE, 'campaign_reference', version=VERSION)['historical_initial']
        candidates = campaign_scope.select(snapshot)
        self.assertIn('lm.red.regiment5', candidates)
        self.assertNotIn('lm.red.corps1', candidates)
        self.assertNotIn('lm.red.division2', candidates)
        self.assertNotIn('lm.red.field_column1', candidates)
        self.assertNotIn('lm.red.cmc_column1', candidates)
        coverage = campaign_scope.coverage(snapshot)
        self.assertTrue(all(r['children_coverage'] != 'complete' for r in coverage))

    def test_each_mode_and_engine_receives_the_same_frozen_historical_definition(self):
        baseline = hi.initial(BATTLE, 'day_19341130', version=VERSION)
        for purpose in ('analysis', 'historical', 'synthetic'):
            for engine in ('afsim', 'narrative'):
                self.assertEqual(hi.initial(BATTLE, 'day_19341130', version=VERSION, purpose=purpose, engine=engine), baseline)

    def test_publisher_rebuilds_the_exact_version_and_never_rewrites_existing_versions(self):
        from tools import upgrade_xiangjiang_campaign as publisher
        self.assertEqual(publisher.build(), self.definition())


if __name__ == '__main__': unittest.main()
