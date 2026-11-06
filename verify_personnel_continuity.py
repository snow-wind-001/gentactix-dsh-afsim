"""Cross-module personnel-ration conservation; explicit offline QA fixtures only."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import session_store
from gentactix import (campaign_plan, commands, formation_conversion as fc,
                       historical_operations as ho, missions, phase_continuity,
                       sim_clock, support_dynamics as sd, synthetic_history)
from tools.qa.converted_phases_live import parameters
from verify_converted_phases import conversion
from verify_formation_commit import fixture
from verify_formation_continuity import selected
from verify_formation_session import register
from verify_personnel_rations import parameters as small_parameters


class PersonnelContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'GENTACTIX_SESSION_DIR': self.temp.name + '/sessions',
                                          'GENTACTIX_TRACE_DIR': self.temp.name + '/traces'})
        self.env.start()
        source, p = parameters(personnel_rations=True)
        initial = ho.initial(source, p)
        binding = initial['mission']['definition']['historical_calculation']
        w = missions.from_definition(synthetic_history.definition(binding, synthetic_history.seed(binding)['configuration']))
        # A labelled accounting fixture; the live companion must obtain its
        # losses from the actual model/native execution instead of seeding them.
        selected(w)['personnel'].update(current=9866, casualties=134)
        campaign_plan.initialize(w)
        self.s, self.uid, self.group = fixture(w)
        self.cfg = sd.configuration(w)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def units(self, ids):
        return [commands.resolve_units(self.s)[identity][1] for identity in ids]

    def split(self):
        _, result = conversion(self.s, [self.uid])
        return result['command_map'][self.uid]

    def test_formal_split_preserves_actual_loss_stock_mass_and_person_coupled_demand(self):
        before = copy.deepcopy(selected(self.s['war_state']))
        parts = self.units(self.split())
        self.assertEqual(sum(u['personnel']['current'] for u in parts), 9866)
        self.assertEqual(sum(u['personnel']['casualties'] for u in parts), 134)
        self.assertAlmostEqual(sum(sd.food_mass(self.cfg, u) for u in parts), 2500)
        self.assertAlmostEqual(sum(sd.expected(self.cfg, u, 'hold', 3600)['demand'] for u in parts), 2.4665)
        self.assertAlmostEqual(sd.expected(self.cfg, before, 'hold', 3600)['demand'], 2.4665)
        self.assertAlmostEqual(sum(sd.food_capacity(self.cfg, u) * fc.resource_scale(u) * 125 for u in parts), 5000)

    def test_formal_merge_does_not_restore_casualties_food_or_the_clock(self):
        parts = self.split()
        before = copy.deepcopy(self.s)
        _, result = conversion(self.s, parts, 'merge')
        identity = next(iter(result['command_map'].values()))[0]
        unit = self.units([identity])[0]
        self.assertEqual(unit['personnel']['current'], 9866)
        self.assertEqual(unit['personnel']['casualties'], 134)
        self.assertEqual(sd.food_mass(self.cfg, unit), 2500)
        self.assertEqual(self.s['war_state']['simulation_clock'], before['war_state']['simulation_clock'])
        self.assertEqual(self.s['war_state']['campaign_lifecycle'], before['war_state']['campaign_lifecycle'])
        self.assertEqual(self.s['trajectory'], before['trajectory'])
        self.assertEqual(self.s['history'], before['history'])

    def test_original_task_rebinds_to_children_without_duplicate_executions(self):
        task_id = register(self.s, self.group)
        before = copy.deepcopy(self.s['command_state']['task_plans'][task_id]['execution'])
        parts = self.split()
        task = self.s['command_state']['task_plans'][task_id]['execution']
        self.assertEqual(set(task['member_states']), set(parts))
        self.assertTrue(all(row['executions'] == 0 for row in task['member_states'].values()))
        self.assertEqual(task['status'], before['status'])

    def test_complete_checkpoint_restores_mass_model_loss_and_formal_identity(self):
        self.split()
        before = session_store.serializable(self.s)
        session_store.save(self.s)
        loaded, errors = session_store.load_all()
        self.assertFalse(errors)
        self.assertEqual(json.dumps(session_store.serializable(loaded[self.s['id']]), sort_keys=True),
                         json.dumps(before, sort_keys=True))
        self.assertEqual(sd.configuration(loaded[self.s['id']]['war_state'])['version'], 'personnel-rations-1')

    def test_stock_encoding_requires_explicit_mass_conversion_when_capacity_cannot_fit(self):
        source, p = parameters(personnel_rations=True)
        p['support_dynamics']['carried_kg_per_committed_person'] = 2
        original = copy.deepcopy(p)
        with self.assertRaisesRegex(ValueError, '容量|编码'):
            ho.initial(source, p)
        self.assertEqual(p, original)

    def test_phase_handoff_preserves_new_ration_definition_debt_and_current_strength(self):
        source, p = small_parameters()
        w = ho.initial(source, p)
        w['current_time'], w['simulation_clock'] = sim_clock.target(w, '1小时')
        w['mission'].update(turn=1, status='completed')
        unit = w['red_units'][0]
        unit['personnel'].update(current=5700, casualties=300)
        unit['logistics']['food'] = 1
        unit['sustainment'].update(shortage_hours=3.25, noncombat_remainder=.4)
        p['clock']['start'] = w['current_time']
        target = dict(format=ho.FORMAT, initial=source, parameters=p)
        child = missions.from_definition(phase_continuity.definition(phase_continuity.bind(w, target)))
        now = child['red_units'][0]
        self.assertEqual(now['personnel'], unit['personnel'])
        self.assertEqual(now['sustainment']['shortage_hours'], 3.25)
        self.assertEqual(now['sustainment']['noncombat_remainder'], .4)
        self.assertEqual(sd.food_mass(sd.configuration(child), now), 125)
        self.assertAlmostEqual(sd.expected(sd.configuration(child), now, 'hold', 3600)['demand'], 1.425)
        changed = copy.deepcopy(target)
        changed['parameters']['support_dynamics']['ration_kg_per_person_day'] = 1
        with self.assertRaisesRegex(ValueError, 'support_dynamics'):
            phase_continuity.definition(phase_continuity.bind(w, changed))

    def test_unregistered_integer_loss_debt_is_still_refused_without_mutation(self):
        parts = self.units(self.split())
        parts[0]['sustainment']['noncombat_remainder'] = 1.2
        before = copy.deepcopy(parts)
        with self.assertRaisesRegex(ValueError, '余量|整数'):
            fc._check(parts[0])
        self.assertEqual(parts, before)


if __name__ == '__main__':
    unittest.main()
