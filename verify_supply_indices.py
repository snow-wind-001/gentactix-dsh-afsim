"""Reproduce the real three-turn resource/display divergence without an API key."""
import copy
import json
from pathlib import Path
import subprocess
import unittest

from gentactix import battlefield, historical_operations, missions, reporting, supply
from tools.qa.historical_operational_fixture import inputs
from verify_dsh_resources import model_result


class SupplyIndexTests(unittest.TestCase):
    def setUp(self):
        snapshot, params = inputs()
        params['goal'].update(termination_mode='objectives', required_turns=10, deadline_turn=20)
        self.before = historical_operations.initial(snapshot, params)

    def test_three_dsh_hold_rounds_refresh_only_the_derived_index(self):
        from backend import dsh_simulation
        prior = copy.deepcopy(self.before)
        world = self.before
        for expected in (78, 76, 74):
            proposal = model_result(world)
            frozen = copy.deepcopy(proposal)
            world = dsh_simulation.apply(world, proposal, '30分钟')
            unit = world['red_units'][0]
            self.assertEqual(unit['logistics'], dict(food=expected, ammo=80))
            self.assertEqual(unit['supply'], expected)
            self.assertEqual(proposal, frozen)
        self.assertEqual(self.before, prior)
        self.assertEqual(world['red_units'][0]['personnel'], prior['red_units'][0]['personnel'])

    def test_lower_ammo_and_untrusted_model_index_use_the_checked_source(self):
        from backend import dsh_simulation
        proposal = model_result(self.before)
        proposal['unit_updates'][0].update(supply=99)
        proposal['unit_updates'][0]['logistics']['ammo'] = 70
        proposal['resource_ledger']['units'][0]['ammo_spent'] = 10
        after = dsh_simulation.apply(self.before, proposal, '30分钟')
        self.assertEqual(after['red_units'][0]['supply'], 70)
        self.assertEqual(after['mission']['ledger'][0]['ammo_spent'], 10)
        self.assertEqual(proposal['unit_updates'][0]['supply'], 99)

    def test_move_and_gross_resupply_derive_the_same_index_contract(self):
        from backend import dsh_simulation
        for action, delivery, expected in [('move', 0, 76), ('resupply', 2, 80)]:
            proposal = model_result(self.before, action, delivery)
            if action == 'move':
                for order, (_, unit) in zip(proposal['orders'], missions.units(self.before)):
                    order.update(lat=unit['lat'], lng=unit['lng'])
            with self.subTest(action=action):
                after = dsh_simulation.apply(self.before, proposal, '30分钟')
                self.assertEqual(after['red_units'][0]['supply'], expected)

    def test_old_saved_world_summary_and_report_are_readonly_and_agree(self):
        world = copy.deepcopy(self.before)
        unit = world['red_units'][0]
        unit['logistics']['food'] = 74
        unit['supply'] = 80
        saved = copy.deepcopy(world)
        view = battlefield.build_battlefield_view(world)
        row = next(r for r in view['operational']['units'] if r['name'] == unit['name'])
        self.assertEqual(row['supply'], 74)
        self.assertIn('补给指数 74', reporting.facts(world))
        self.assertEqual(world, saved)

    def test_missing_or_invalid_classified_values_do_not_become_old_full_supply(self):
        self.assertEqual(supply.index_value({'supply': '80'}), 80)
        self.assertEqual(supply.index_value({'supply': 80, 'logistics': {'food': 0, 'ammo': 70}}), 0)
        for logistics in ({'food': 80}, {'food': None, 'ammo': 70},
                          {'food': True, 'ammo': 70}, {'food': float('nan'), 'ammo': 70},
                          {'food': 101, 'ammo': 70}, None):
            with self.subTest(logistics=logistics):
                self.assertIsNone(supply.index_value({'supply': 80, 'logistics': logistics}))

    def test_frontend_popup_matches_backend_with_unknown_and_legacy_compatibility(self):
        cases = [{'name': '旧局', 'supply': '80'},
                 {'name': '旧不一致局', 'supply': 80, 'logistics': {'food': 74, 'ammo': 80}},
                 {'name': '缺载', 'supply': 80, 'logistics': {'food': 74}},
                 {'name': '耗尽', 'supply': 80, 'logistics': {'food': 0, 'ammo': 80}}]
        process = subprocess.run(['node', 'tools/qa/supply_indices.mjs'],
            input=json.dumps(cases), text=True, capture_output=True, check=True, cwd=Path(__file__).resolve().parent)
        rows = json.loads(process.stdout)
        self.assertEqual([r['value'] for r in rows], [supply.index_value(u) for u in cases])
        self.assertIn('74%', rows[1]['popup'])
        self.assertNotIn('80%', rows[1]['popup'])
        self.assertIn('未记录', rows[2]['popup'])
        self.assertIn('0%', rows[3]['popup'])


if __name__ == '__main__': unittest.main()
