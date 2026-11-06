"""Declared depot identity must govern transport, accounts and native receipts."""
import copy
import unittest
from unittest.mock import patch

from backend import afsim_rules, afsim_world, dsh_simulation, afsim_state, afsim_comparison, afsim_combined
from gentactix import missions, supply, combat_effects
from tools.qa.supply_binding_fixture import definition
from verify_dsh_resources import model_result


class SupplyBindingTests(unittest.TestCase):
    def install(self, **options):
        spec = definition(**options)
        original = missions.definition
        registered = patch.object(missions, 'definition', side_effect=lambda identity:
            copy.deepcopy(spec) if identity == spec['id'] else original(identity))
        registered.start()
        self.addCleanup(registered.stop)
        return spec, missions.from_definition(spec)

    def test_oracle_debits_the_bound_branch_and_never_an_unused_team_depot(self):
        _, before = self.install()
        frozen = copy.deepcopy(before)
        geom = {'units': [{'name': u['name'], 'supply': '未切断'} for _, u in missions.units(before)]}
        with patch.object(missions.adjudicator, 'adjudicate', return_value=geom):
            after = missions.advance(before, [], '30分钟')
        nodes = {n['id']: n['stock'] for n in after['supply_nodes']}
        self.assertEqual(nodes['red-depot'], 0)
        self.assertEqual(nodes['qa-red-branch'], 5)
        self.assertEqual(nodes['qa-red-unused'], 99)
        self.assertEqual([r['delivery'] for r in after['mission']['ledger'][:3]], [0, 2, 2])
        self.assertEqual(after['mission']['ledger'][1]['source_node_id'], 'qa-red-branch')
        self.assertEqual(before, frozen)

    def test_selector_is_identity_based_and_does_not_use_list_order(self):
        _, world = self.install(combined=True)
        unit = world['red_units'][1]
        for nodes in (world['supply_nodes'], list(reversed(world['supply_nodes']))):
            source = {**world, 'supply_nodes': nodes}
            self.assertEqual(supply.bound_node(source, 'red', unit)['id'], 'qa-red-branch')

    def test_unknown_enemy_duplicate_and_absent_bindings_fail_closed(self):
        _, world = self.install()
        for mode in ('unknown', 'enemy', 'duplicate', 'absent'):
            candidate = copy.deepcopy(world)
            unit = candidate['red_units'][1]
            if mode == 'unknown': unit['supply_node_id'] = 'missing'
            elif mode == 'enemy': unit['supply_node_id'] = 'blue-depot'
            elif mode == 'duplicate': candidate['supply_nodes'].append(copy.deepcopy(candidate['supply_nodes'][2]))
            else: unit.pop('supply_node_id')
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, '补给.*绑定|绑定.*补给'):
                supply.bound_node(candidate, 'red', unit)

    def test_bad_initial_binding_is_rejected_before_any_executor(self):
        for mode in ('duplicate', 'enemy', 'absent'):
            spec = definition()
            if mode == 'duplicate': spec['initial_state']['supply_nodes'].append(copy.deepcopy(spec['initial_state']['supply_nodes'][0]))
            elif mode == 'enemy': spec['initial_state']['red_units'][0]['supply_node_id'] = 'blue-depot'
            else: spec['initial_state']['red_units'][0].pop('supply_node_id')
            with patch.object(missions, 'definition', return_value=spec):
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, '补给'):
                    missions.from_definition(spec)

    def test_native_receipt_with_right_team_total_but_wrong_warehouse_is_rejected(self):
        _, world = self.install()
        scene = afsim_world.compile_scene(world, [], 1800, native_rules=True)
        model = scene['native_model']
        # Every unit declares one package, but the two red branch draws were
        # charged to the unused red depot. Team totals alone cannot detect this.
        lines = ['GTXMODEL|' + model['input_digest']]
        for identity, entry in scene['entities'].items():
            unit = next(u for _, u in missions.units(world) if u['name'] == entry['name'])
            p = unit['personnel']; e = unit['equipment'][0]
            delivery = 0 if unit is world['red_units'][0] else 1
            values = [p['current'], p['casualties'], p['noncombat_losses'], e['operational'], e['destroyed'],
                      78 + delivery, 80 + delivery, 10000, 78 + delivery, delivery, 2, 0, 1]
            lines.append('GTXEFFECT|' + identity + '|' + '|'.join(map(str, values)))
        lines += ['GTXMISSION|1|0|100|100|0|300|300|0|0|0|0|0',
                  'GTXDEPOT|0|0', 'GTXDEPOT|1|117', 'GTXDEPOT|2|9', 'GTXDEPOT|3|97']
        text = '\n'.join(lines)
        with self.assertRaisesRegex(ValueError, '补给.*守恒|仓库.*守恒'):
            afsim_rules.parse(text, model, scene)
        good = text.replace('GTXDEPOT|2|9', 'GTXDEPOT|2|7').replace('GTXDEPOT|3|97', 'GTXDEPOT|3|99')
        self.assertEqual(afsim_rules.parse(good, model, scene)['depots'][2], 7)

    def test_dsh_accepts_bound_draws_and_rejects_transfer_to_another_own_depot(self):
        _, before = self.install(combined=True)
        # The empty main depot cannot fund a receipt; only branch recipients receive.
        proposal = model_result(before)
        for index in (1, 2):
            row = proposal['resource_ledger']['units'][index]
            row.update(delivery=1, supply_status='未切断')
            proposal['unit_updates'][index]['logistics'] = {'food': 79, 'ammo': 81}
        proposal['supply_nodes'][2]['stock'] -= 2
        after = dsh_simulation.apply(before, proposal, '30分钟')
        self.assertEqual(after['supply_nodes'][2]['stock'], 7)
        self.assertEqual(after['mission']['ledger'][1]['source_node_id'], 'qa-red-branch')
        bad = copy.deepcopy(proposal)
        bad['supply_nodes'][2]['stock'] += 2
        bad['supply_nodes'][3]['stock'] -= 2
        with self.assertRaisesRegex(ValueError, '仓库.*守恒'):
            dsh_simulation.apply(before, bad, '30分钟')

    def test_native_observation_reveals_bound_stock_with_bounded_evidence(self):
        _, world = self.install(combined=True, split=True)
        world['supply_nodes'][2]['source'] = 'NO-UNBOUNDED-SOURCE' * 10000
        session = {'id': 'a123456789ab', 'war_state': world, 'turn_count': 0,
                   'time_step': '30分钟', 'execution_backend': 'afsim'}
        frozen = copy.deepcopy(session)
        page = afsim_state.observation(session)
        row = next(r for r in page['units'] if r['name'] == world['red_units'][1]['name'])
        binding = row['supply_binding']
        self.assertEqual(binding['node_id'], 'qa-red-branch')
        self.assertEqual(binding['stock'], 9)
        self.assertEqual(binding['commodities'], {'food': 9, 'ammo': 9})
        self.assertEqual(binding['classified_stock_scope'], 'team_pool')
        self.assertNotIn('source', binding)
        self.assertEqual(session, frozen)

    def test_supply_rule_change_is_not_attributed_to_changed_commands(self):
        _, before = self.install(combined=True)
        after = copy.deepcopy(before)
        after['afsim'] = {'motion_revision': afsim_world.motion_revision(before),
                          'combat_revision': combat_effects.COMBAT_REVISION,
                          'combat_profile': combat_effects.reference(before),
                          'command_control_revision': afsim_combined.COMMAND_CONTROL_REVISION,
                          'supply_control_revision': 1}
        record = {'before': before, 'after': after, 'time_step': '30分钟'}
        with patch.object(afsim_world, 'run_scene', side_effect=AssertionError('No mixed-version replay')):
            with self.assertRaisesRegex(ValueError, '补给控制.*版本'):
                afsim_comparison.compare({'war_state': before}, record, [])


if __name__ == '__main__': unittest.main()
