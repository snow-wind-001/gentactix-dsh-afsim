"""Compact native observations retain decision data and explicit detail access."""
import copy
import json
import unittest

from backend import afsim_state
from gentactix import missions


class ObservationTests(unittest.TestCase):
    def test_decision_projection_preserves_before_after_and_missing_budget(self):
        from gentactix import commands
        s = self.session()
        s['turn_count'] = 2
        state = commands.state(s)
        identity = next(iter(commands.resolve_units(s, state)))
        state['receipts'] = [{'unit_id':identity, 'turn':2, 'action':'resupply',
            'observation_version':'before-fingerprint', 'before_logistics':{'food':8,'ammo':100},
            'after_logistics':{'food':14,'ammo':100},
            'decision_context':{'turn':1,'remaining_turns':7,'unit_hold_food_budget':14}}]
        s['command_state'] = state
        decision = afsim_state.observation(s)['units'][0]['last_decision']
        self.assertEqual(decision['observation_version'], 'before-fingerprint')
        self.assertEqual(decision['before_logistics']['food'], 8)
        self.assertEqual(decision['decision_context']['unit_hold_food_budget'], 14)
        state['receipts'][0].pop('decision_context')
        self.assertNotIn('decision_context', afsim_state.observation(s)['units'][0]['last_decision'])

    def test_split_mass_exposes_food_and_ammo_shares_but_legacy_does_not_invent_them(self):
        from tools.qa.remaining_initial_fixture import inputs
        from gentactix import historical_operations as ho
        s, p = inputs('长平之战', 'encirclement')
        w = ho.initial(s,p)
        accounting = afsim_state.mission_context(w)['supply_accounting']
        self.assertEqual(accounting['food_mass_share'], .5)
        self.assertEqual(accounting['ammo_mass_share'], .5)
        self.assertEqual(accounting['food_tons_per_work'], .5*p['rules']['ton_per_supply_unit'])
        legacy = afsim_state.mission_context(self.session()['war_state'])['supply_accounting']
        self.assertNotIn('food_mass_share', legacy)

    def session(self):
        world = missions.initial('CA-AJ18-v1')
        return {'id': 'a123456789ab', 'war_state': world, 'turn_count': 0,
                'time_step': '30分钟', 'execution_backend': 'afsim'}

    def test_default_equipment_is_numeric_and_full_provenance_is_retrievable(self):
        session = self.session()
        unit = session['war_state']['red_units'][0]
        for gear in unit['equipment']:
            gear['source'] = 'LONG-EQUIPMENT-PROVENANCE' * 300
            gear['damage_load'] = .25
        frozen = copy.deepcopy(session)
        page = afsim_state.observation(session)
        row = page['units'][0]
        self.assertNotIn('LONG-EQUIPMENT-PROVENANCE', json.dumps(page))
        for source, observed in zip(unit['equipment'], row['equipment']):
            for key in ('category', 'name', 'committed', 'operational', 'damaged', 'destroyed', 'damage_load'):
                self.assertEqual(observed[key], source[key])
        detail = afsim_state.observation(session, row['detail_query'])['units'][0]
        self.assertEqual(detail['equipment'], unit['equipment'])
        self.assertEqual(session, frozen)

    def test_compact_receipt_keeps_zero_unknown_clock_and_delivery_semantics(self):
        session = self.session()
        unit = session['war_state']['red_units'][0]
        unit['formation'].update(protection=.41, dispersion_km2=2.5,
            last_execution={'turn': 0, 'action': 'hold', 'source': 'native',
                'fire_cycles': 0, 'active_fire_s': 0, 'delay_s': 400,
                'received_shells': 0, 'distance_milli': 12000, 'blocked': 0,
                'verbose_note': 'LONG-RECEIPT-PROVENANCE' * 1000})
        row = afsim_state.observation(session)['units'][0]
        receipt = row['formation']['last_execution']
        self.assertNotIn('verbose_note', receipt)
        self.assertEqual(receipt['received_shells'], 0)
        self.assertNotIn('received_fuel_liters', receipt)
        self.assertEqual(receipt['active_fire_s'], 0)
        self.assertEqual(receipt['delay_s'], 400)
        self.assertEqual(receipt['distance_milli'], 12000)
        self.assertEqual(row['formation']['protection'], .41)
        self.assertEqual(row['formation']['dispersion_km2'], 2.5)
        detailed = afsim_state.observation(session, row['detail_query'])['units'][0]
        self.assertEqual(detailed['formation'], unit['formation'])

    def test_unknown_equipment_counts_remain_unknown_and_rows_are_not_dropped(self):
        # Legacy records are outside the active combined-arms input schema;
        # the projection itself must still preserve unknown/absent fields.
        gear = [{'name': '旧未分类装备', 'operational': None, 'source': '缺载'}]
        rows = afsim_state._equipment_observation(gear)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['operational'])
        self.assertNotIn('category', rows[0])
        self.assertNotIn('destroyed', rows[0])

    def test_partition_assumption_is_not_repeated_as_default_context(self):
        session = self.session()
        unit = session['war_state']['red_units'][0]
        unit['calculation_unit_id'] = 'parent::child'
        unit['formation_part'] = {'version': 'formation-parts-1', 'group_id': 'parent',
            'part_id': 'child', 'numerator': 50, 'denominator': 100,
            'parent_name': '来源父级', 'assumption': 'LONG-PARTITION-PROVENANCE' * 1000}
        row = afsim_state.observation(session)['units'][0]
        self.assertNotIn('assumption', row['formation_part'])
        self.assertEqual(row['normalized_resource_scale'], .5)
        detail = afsim_state.observation(session, row['detail_query'])['units'][0]
        self.assertEqual(detail['formation_part'], unit['formation_part'])

    def test_detail_is_boolean_and_default_reports_projection_scope(self):
        for bad in ('false', 1, None, {}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                afsim_state.observation(self.session(), {'detail': bad})
        view = afsim_state.observation(self.session())
        self.assertEqual(view['observation_detail'], 'compact')
        self.assertIn('detail', view['projection_note'])
        self.assertEqual(afsim_state.observation(self.session(), {'detail': True})['observation_detail'], 'full_unit_detail')


if __name__ == '__main__':
    unittest.main()
