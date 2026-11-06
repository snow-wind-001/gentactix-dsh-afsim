"""One failed candidate exposes independent scheduled-supply bounds, not allocations."""
import copy
import unittest
from unittest.mock import patch

from backend import effect_constraints, turn_preview, dsh_simulation
from gentactix import missions, supply_schedule as schedule
from verify_supply_schedule import world, schedule_ledger, model_proposal


def context(before):
    session = dict(id='scheduled-constraints-qa', role_epoch=0, turn_count=0,
        agent_mode='native', execution_backend='narrative', time_step=before['mission']['definition']['time_step'],
        product_mode='historical', simulation_mode='open', war_state=before)
    return turn_preview.context(session, None, operation_id='scheduled-constraints-op')


def proposal(before):
    value = model_proposal(before)
    value['supply_schedule_ledger'] = schedule_ledger(before, 3600)
    return value


def mutual_cuts(before, *, control_ids=None):
    # Set immutable unit properties through initial parameters, not by editing
    # an already frozen world's equipment/control bindings.
    from tools.qa.historical_operational_fixture import inputs
    from gentactix import historical_operations
    source, parameters = inputs()
    for key in ('support_dynamics','supply_distribution','supply_schedule'):
        parameters[key] = copy.deepcopy(before['mission']['definition'][key])
    parameters['clock']['time_step'] = '1小时'
    center = parameters['area']['center']
    for identity, actor in parameters['actors'].items():
        team = next(t for t,u in missions.units(before) if u['historical_unit_id']==identity)
        actor['position'] = dict(lat=center['lat']+(.001 if team=='red' else -.001),lng=center['lng'])
        actor['ground_control_radius_km'] = .1 if control_ids is None or identity in control_ids else 0
        actor['logistics'] = dict(food=0,ammo=100)
    return historical_operations.initial(source, parameters)


class ScheduledConstraintTests(unittest.TestCase):
    def setUp(self):
        self.world = world(step='1小时')

    def facts(self, value):
        return effect_constraints.diagnose(context(self.world), value)

    def constraints(self, facts, kind):
        return [row for row in facts['constraints'] if row['kind'] == kind]

    def test_one_failed_preview_reports_both_provably_cut_routes(self):
        self.world = mutual_cuts(self.world)
        value = proposal(self.world)
        before = copy.deepcopy((self.world, value))
        reply = turn_preview.execute(context(self.world), dict(tool=turn_preview.TOOL, args={'candidate':value}))
        self.assertFalse(reply['ok'])
        cuts = self.constraints(reply['calculation_diagnostics'], 'known_route_cut')
        self.assertEqual({r['unit'] for r in cuts}, {u['name'] for _,u in missions.units(self.world)})
        self.assertTrue(all(r['seconds'] == 3600 for r in cuts))
        self.assertEqual((self.world, value), before)

    def test_service_and_transport_maxima_are_conditions_not_required_deliveries(self):
        value = proposal(self.world)
        for row in value['supply_schedule_ledger']['units']:
            row['events'][0]['food_received'] = 5000
        facts = self.facts(value)
        limits = self.constraints(facts, 'delivery_capacity')
        self.assertEqual(len(limits), len(missions.units(self.world)))
        for row in limits:
            self.assertEqual(row['maximum_each_work'], 4)
            self.assertGreater(row['maximum_mass_tons'], 0)
            self.assertNotIn('expected', row)
            self.assertNotIn('allocation', row)
        self.assertTrue(any('不能退回旧粮耗' in row['reason'] for row in facts['unavailable']))
        self.assertFalse(any(row['path'].endswith('/food_spent') for row in facts['mismatches']))

    def test_resupply_rate_and_shared_warehouse_are_not_multiplied_by_unit_count(self):
        value = proposal(self.world)
        for order in value['orders']: order['action'] = 'resupply'
        facts = self.facts(value)
        self.assertTrue(all(x['maximum_each_work'] == 16 for x in self.constraints(facts, 'delivery_capacity')))
        warehouses = self.constraints(facts, 'warehouse_capacity')
        self.assertEqual(len(warehouses), len(self.world['supply_nodes']))
        self.assertTrue(all(x['maximum_mass_tons'] == 100 for x in warehouses))

    def test_reordered_units_keep_exact_candidate_paths(self):
        self.world = mutual_cuts(self.world)
        value = proposal(self.world)
        value['supply_schedule_ledger']['units'].reverse()
        facts = self.facts(value)
        for row in self.constraints(facts, 'known_route_cut'):
            index = next(i for i,r in enumerate(value['supply_schedule_ledger']['units']) if r['unit'] == row['unit'])
            prefix = f'/supply_schedule_ledger/units/{index}/events/0'
            self.assertEqual(row['status_path'], prefix+'/supply_status')
            self.assertIn(prefix+'/food_received', row['zero_delivery_paths'])
            self.assertEqual(row['allowed_zero_receipt_statuses'], ['已切断','未知'])

    def test_duplicate_unit_is_unknown_but_other_unit_capacity_still_available(self):
        value = proposal(self.world)
        duplicate = copy.deepcopy(value['supply_schedule_ledger']['units'][0])
        value['supply_schedule_ledger']['units'].append(duplicate)
        facts = self.facts(value)
        caps = self.constraints(facts, 'delivery_capacity')
        self.assertNotIn(duplicate['unit'], {r['unit'] for r in caps})
        self.assertTrue(caps)
        self.assertFalse(self.constraints(facts, 'known_route_cut'))

    def test_invalid_position_and_nonfinite_amounts_do_not_create_fake_facts(self):
        value = proposal(self.world)
        name = value['supply_schedule_ledger']['units'][0]['unit']
        value['supply_schedule_ledger']['units'][0]['events'][0]['position']['lat'] = 'unknown'
        facts = self.facts(value)
        self.assertNotIn(name, {r['unit'] for r in self.constraints(facts,'delivery_capacity')})
        self.assertTrue(self.constraints(facts,'delivery_capacity'))
        value = proposal(self.world)
        value['supply_schedule_ledger']['units'][0]['events'][0]['food_received'] = float('inf')
        # A nonfinite Python input has no JSON candidate hash. Check the pure
        # facts boundary directly; Native JSON rejection remains unchanged.
        bounds, unknown = schedule.candidate_limits(self.world,value['supply_schedule_ledger'],value['orders'],3600)
        cap = next(r for r in bounds if r['kind']=='delivery_capacity' and r['unit'] == name)
        self.assertIsNone(cap['actual_mass_tons'])
        self.assertTrue(unknown)

    def test_targeted_enemy_with_unknown_timed_survival_is_not_a_certain_blocker(self):
        controllers = {self.world[team+'_units'][0]['historical_unit_id'] for team in ('red','blue')}
        self.world = mutual_cuts(self.world, control_ids=controllers)
        value = proposal(self.world)
        for order in value['orders']:
            own_team = next(t for t,u in missions.units(self.world) if u['name'] == order['unit'])
            order.update(action='fire', target=self.world['blue_units' if own_team=='red' else 'red_units'][0]['name'])
        facts = self.facts(value)
        self.assertFalse(self.constraints(facts,'known_route_cut'))
        self.assertTrue(self.constraints(facts,'delivery_capacity'))

    def test_missing_ledger_does_not_guess_event_paths_or_nutrition(self):
        value = proposal(self.world)
        del value['supply_schedule_ledger']
        facts = self.facts(value)
        self.assertEqual(facts['constraints'], [])
        self.assertTrue(facts['unavailable'])
        self.assertFalse(any(row['path'].endswith('/food_spent') for row in facts['mismatches']))

    def test_impossible_timed_movement_is_not_a_known_enemy_position(self):
        value=proposal(self.world)
        unit=self.world['red_units'][0]
        value['orders'][0].update(action='move',lat=unit['lat']+.001,lng=unit['lng'])
        value['supply_schedule_ledger']['units'][0]['events'][0]['position']['lat']+=10
        facts=self.facts(value)
        self.assertNotIn(unit['name'],{r['unit']for r in self.constraints(facts,'delivery_capacity')})
        self.assertFalse(self.constraints(facts,'known_route_cut'))
        self.assertTrue(self.constraints(facts,'delivery_capacity'))

    def test_known_cut_facts_respect_campaign_arrival_time(self):
        from verify_supply_schedule import CampaignSupplyContextTests
        for future in (False,True):
            before=CampaignSupplyContextTests().campaign_world(future=future)
            # Pure rule inputs: no host session or frozen profile is modified.
            before['mission']['definition']['supply_schedule']=copy.deepcopy(self.world['mission']['definition']['supply_schedule'])
            before['mission']['definition']['support_dynamics']=copy.deepcopy(self.world['mission']['definition']['support_dynamics'])
            for _,unit in missions.units(before):
                unit['sustainment']=dict(version='time-sustainment-1',shortage_hours=0,noncombat_remainder=0)
            rows=schedule_ledger(before,3600)
            orders=[dict(unit=u['name'],action='hold')for _,u in missions.units(before)]
            bounds,_=schedule.candidate_limits(before,rows,orders,3600)
            red=next(u['name']for _,u in missions.units(before)if u['historical_unit_id']=='ww2.cn.division159')
            self.assertEqual(any(r['kind']=='known_route_cut'and r['unit']==red for r in bounds),not future)

    def test_zero_unknown_receipts_remain_valid_no_forced_allocation(self):
        self.world = mutual_cuts(self.world)
        ledger = schedule_ledger(self.world, 3600)
        orders = proposal(self.world)['orders']
        for row in ledger['units']:
            for event in row['events']:
                event.update(supply_status='未知', food_received=0)
        schedule.validate_ledger(self.world, ledger, orders, 3600)
        value = proposal(self.world); value['supply_schedule_ledger'] = ledger
        cuts = self.constraints(self.facts(value),'known_route_cut')
        self.assertTrue(cuts)
        self.assertTrue(all(r['allowed_zero_receipt_statuses']==['已切断','未知'] for r in cuts))

    def test_disabled_model_preserves_legacy_diagnostic_shape(self):
        value = proposal(self.world)
        self.world['mission']['definition'].pop('supply_schedule')
        facts = self.facts(value)
        self.assertNotIn('constraints', facts)

    def test_diagnostics_never_call_executor_or_mutate_inputs(self):
        value = proposal(self.world)
        saved = copy.deepcopy((self.world,value))
        with patch.object(dsh_simulation,'apply',side_effect=AssertionError('No executor')):
            facts = self.facts(value)
        self.assertTrue(facts['readonly']); self.assertFalse(facts['complete_validation'])
        self.assertEqual((self.world,value),saved)
        self.assertNotIn('repaired_candidate', facts)


if __name__ == '__main__': unittest.main()
