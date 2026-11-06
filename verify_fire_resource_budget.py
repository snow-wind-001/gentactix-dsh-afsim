"""Opening-stock fire constraints: quantities, timing, parts and read-only access."""
import copy
import unittest

from backend import afsim_state
from gentactix import combined_arms, combat_effects, commands, fire_process, missions, resource_readiness


class FireResourceBudgetTests(unittest.TestCase):
    def setUp(self):
        self.world = missions.initial(combined_arms.demo_definition()['id'])
        self.unit = self.world['red_units'][2]
        gun = next(e for e in self.unit['equipment'] if e['category'] == 'artillery')
        gun.update(committed=3, operational=3, damaged=0, destroyed=0)
        self.unit['logistics']['ammo'] = 2
        self.unit['formation']['shells'] = 54

    def budget(self):
        return resource_readiness.fire_budget(self.world, self.unit)

    def session(self):
        return dict(id='b00000000001', war_state=self.world, time_step='30分钟',
                    turn_count=0, execution_backend='afsim', simulation_mode='open')

    def test_actual_work_limited_case_is_not_reported_as_empty_shells(self):
        value = self.budget()
        self.assertEqual(value['ammo_work'], {'on_hand': 2, 'per_cycle': 1, 'cycles_from_on_hand': 2})
        self.assertEqual(value['indirect']['shells'], 54)
        self.assertEqual(value['indirect']['shells_per_cycle_ceiling'], 6)
        self.assertEqual(value['indirect']['full_salvos_at_ceiling'], 9)
        self.assertEqual(value['delivery_timing'], 'turn_end_only')
        self.assertFalse(value['future_delivery_included'])

    def test_positive_shells_cannot_pay_the_separate_work_budget(self):
        self.unit['logistics']['ammo'] = 0
        value = self.budget()
        self.assertEqual(value['ammo_work']['cycles_from_on_hand'], 0)
        self.assertEqual(value['indirect']['shells'], 54)
        self.assertIn('独立', value['scope'])

    def test_work_budget_does_not_invent_shells_and_partial_salvos_are_distinct(self):
        self.unit['formation']['shells'] = 5
        value = self.budget()
        self.assertEqual(value['indirect']['full_salvos_at_ceiling'], 0)
        self.assertEqual(value['indirect']['remaining_shells'], 5)
        self.assertTrue(value['indirect']['partial_salvo_possible'])
        self.unit['formation']['shells'] = 0
        self.assertFalse(self.budget()['indirect']['partial_salvo_possible'])

    def test_frozen_profile_cost_is_used_instead_of_the_global_default(self):
        reference = combat_effects.reference(self.world)
        reference['ammo_per_cycle'] = .5
        reference['definition_hash'] = combat_effects.digest({k:v for k,v in reference.items() if k!='definition_hash'})
        self.world['combat_reference'] = reference
        self.assertEqual(self.budget()['ammo_work']['cycles_from_on_hand'], 4)
        self.assertEqual(self.budget()['profile_hash'], reference['definition_hash'])

    def test_fragment_work_is_scaled_but_absolute_shells_are_not(self):
        from tools.qa.historical_crossing_fixture import inputs
        from verify_formation_parts import partition_input
        from gentactix import historical_operations
        snapshot, params = inputs(); params['partitions'] = partition_input(params)
        w = historical_operations.initial(snapshot, params)
        u = next(u for _,u in missions.units(w) if u.get('formation_part',{}).get('part_id')=='advance')
        u['logistics']['ammo'] = 2
        value = resource_readiness.fire_budget(w,u)
        self.assertEqual(value['resource_scale'], 5/1600)
        self.assertEqual(value['ammo_work']['cycles_from_on_hand'], 2)
        self.assertEqual(value['ammo_work']['on_hand'], 2*5/1600)
        self.assertEqual(value['ammo_work']['per_cycle'], 5/1600)

    def test_timed_supply_is_not_forecast_or_added_to_opening_stock(self):
        self.world['mission']['definition']['supply_schedule'] = {'version':'scheduled-supply-1'}
        value = self.budget()
        self.assertEqual(value['delivery_timing'], 'within_turn_events')
        self.assertEqual(value['ammo_work']['cycles_from_on_hand'], 2)
        self.assertFalse(value['future_delivery_included'])
        self.assertIn('到货', value['scope'])

    def test_no_issued_guns_is_distinct_from_destroyed_issued_guns(self):
        gun = next(e for e in self.unit['equipment'] if e['category']=='artillery')
        gun.update(operational=0, destroyed=3)
        self.assertEqual(self.budget()['indirect']['operational_guns'], 0)
        self.assertEqual(self.budget()['indirect']['full_salvos_at_ceiling'], 0)
        gun.update(committed=0, destroyed=0)
        self.assertIsNone(self.budget()['indirect'])

    def test_unknown_work_is_unknown_instead_of_zero_or_a_ready_claim(self):
        self.unit['logistics']['ammo'] = None
        value = self.budget()
        self.assertIsNone(value['ammo_work']['on_hand'])
        self.assertIsNone(value['ammo_work']['cycles_from_on_hand'])
        self.assertFalse(value['is_readiness_or_effect_prediction'])

    def test_noncombined_history_does_not_acquire_estimated_fire_resources(self):
        self.assertIsNone(resource_readiness.fire_budget({'red_units':[]}, {'name':'史料未知单位'}))

    def test_compact_observation_defers_budget_to_existing_unit_detail(self):
        session = self.session()
        compact = afsim_state.observation(session, {'limit':16})
        row = next(r for r in compact['units'] if r['name']==self.unit['name'])
        self.assertNotIn('fire_resources',row)
        detail = afsim_state.observation(session, row['detail_query'])['units'][0]
        self.assertEqual(detail['fire_resources'], self.budget())
        shown = next(r for r in commands.view(session)['units'] if r['name']==self.unit['name'])
        self.assertEqual(shown['fire_resources'], detail['fire_resources'])

    def test_observations_and_returned_mutations_do_not_change_frozen_world(self):
        before = copy.deepcopy(self.world)
        value = self.budget(); value['ammo_work']['on_hand']=999
        afsim_state.observation(self.session(), {'limit':1,'detail':True})
        self.assertEqual(self.world,before)

    def test_current_balances_are_labelled_as_settled_not_a_previous_round_opening(self):
        self.world['mission']['turn'] = 6
        value = self.budget()
        self.assertEqual(value['stock_snapshot'], {
            'turn':6, 'current_time':self.world['current_time'],
            'timing':'committed_state_after_turn', 'applies_to':'next_order_from_current_state',
            'settled_deliveries_already_included':True})

    def test_existing_readiness_and_unit_detail_share_the_same_cycle_budget(self):
        self.unit['logistics']['ammo'] = .3
        reference = combat_effects.reference(self.world)
        reference['ammo_per_cycle'] = .1
        reference['definition_hash'] = combat_effects.digest({k:v for k,v in reference.items()if k!='definition_hash'})
        self.world['combat_reference'] = reference
        value = self.budget()
        self.assertEqual(value['ammo_work']['cycles_from_on_hand'], 3)
        row = next(r for r in resource_readiness.assess(self.world)['units']if r['unit']==self.unit['name'])
        self.assertEqual(row['fire_work_minutes'], 3*reference['direct_cycle_s']/60)

    def test_readiness_respects_registered_artillery_reload_period(self):
        self.world['mission']['definition']['combined_rules']['reload_turns'] = 3
        row = next(r for r in resource_readiness.assess(self.world)['units']if r['unit']==self.unit['name'])
        self.assertEqual(row['artillery_minutes'], 12)
        self.assertEqual(row['fire_work_minutes'], 4)

    def test_all_45_compatible_templates_have_explicit_nonhistorical_stock_constraints(self):
        count=0
        for spec in combined_arms.catalog():
            world=missions.initial(spec['id'])
            for _,unit in missions.units(world):
                value=resource_readiness.fire_budget(world,unit)
                self.assertFalse(value['is_readiness_or_effect_prediction'])
                self.assertEqual(value['source'],'configured_model_inputs')
                self.assertEqual(value['ammo_work']['cycles_from_on_hand'],unit['logistics']['ammo']//combat_effects.reference(world)['ammo_per_cycle'])
                count+=1
        self.assertEqual(count,270)


if __name__=='__main__':unittest.main()
