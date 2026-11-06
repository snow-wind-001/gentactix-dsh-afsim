"""Continuous motion must preserve intent, fractional state and old versions."""
import copy
import unittest

from gentactix import commands, historical_operations as ho, missions, movement_feedback
from tools.qa.historical_operational_fixture import inputs, NOTE

CONFIG = {'version':'movement-feedback-2', 'assumption':NOTE+' Fixed Native motion cadence; not historical calibration.'}


def world():
    source, parameters = inputs()
    parameters['movement_feedback'] = copy.deepcopy(CONFIG)
    parameters['fire_dynamics'] = {'version':'live-footprint-density-2', 'assumption':NOTE}
    parameters['rules'].update(command_base_s=30, command_signal_s=0, command_distance_s_per_km=0)
    return ho.initial(source, parameters)


class ContinuousMotionTests(unittest.TestCase):
    def test_version_two_is_explicit_and_does_not_rewrite_old_configurations(self):
        old = {'version':'movement-feedback-1','assumption':NOTE}
        saved = copy.deepcopy(old)
        self.assertTrue(movement_feedback.validate_config(old))
        self.assertTrue(movement_feedback.validate_config(CONFIG))
        self.assertEqual(old, saved)
        with self.assertRaises(ValueError):
            movement_feedback.validate_config({**CONFIG, 'version':'movement-feedback-unknown'})

    def test_canonical_initial_fatigue_and_fuel_carries_are_explicit(self):
        value = world()
        for _, unit in missions.units(value):
            self.assertEqual(unit['formation']['fatigue_carry_ticks'], 0)
            self.assertEqual(unit['formation']['fuel_credit_microliters'], 0)
        self.assertTrue(missions.validate(value))

    def test_existing_versions_do_not_gain_motion_carry_fields(self):
        source, parameters = inputs()
        parameters['movement_feedback'] = {'version':'movement-feedback-1','assumption':NOTE}
        value = ho.initial(source, parameters)
        for _, unit in missions.units(value):
            self.assertNotIn('fatigue_carry_ticks', unit['formation'])
            self.assertNotIn('fuel_credit_microliters', unit['formation'])

    def test_fixed_precision_readers_preserve_fractional_physical_balances(self):
        from gentactix import motion_state
        unit = {'formation':{'fatigue':60,'fatigue_carry_ticks':125000,
                             'fuel_liters':1999,'fuel_credit_microliters':800000}}
        saved = copy.deepcopy(unit)
        self.assertEqual(motion_state.fatigue_value(unit), 60.125)
        self.assertEqual(motion_state.fuel_value(unit), 1999.8)
        self.assertEqual(unit, saved)

    def test_fractional_state_cannot_disappear_or_exceed_canonical_bounds(self):
        from gentactix import motion_state
        good = {'formation':{'fatigue':60,'fatigue_carry_ticks':0,
                             'fuel_liters':1,'fuel_credit_microliters':0}}
        motion_state.validate_unit(good)
        for field, bad in [('fatigue_carry_ticks',True),('fatigue_carry_ticks',1000000),
                           ('fuel_credit_microliters',-1),('fuel_credit_microliters',1000000)]:
            value = copy.deepcopy(good)
            value['formation'][field] = bad
            with self.subTest(field=field,bad=bad), self.assertRaises(ValueError):
                motion_state.validate_unit(value)
        missing = copy.deepcopy(good)
        missing['formation'].pop('fuel_credit_microliters')
        with self.assertRaises(ValueError):
            motion_state.validate_unit(missing)

    def test_persistent_move_keeps_intent_identity_for_later_wait_accounting(self):
        value = world()
        session = {'id':'c01700000001','role_epoch':0,'turn_count':0,'war_state':value,
                   'time_step':'30分钟','product_mode':'historical','simulation_mode':'open',
                   'execution_backend':'afsim'}
        entry = commands.view(session)['units'][0]
        unit = commands.resolve_units(session)[entry['id']][1]
        destination = {'lat':unit['lat']+.05,'lng':unit['lng']}
        state = commands.replace_queue(session,[{'unit_id':entry['id'],'action':'move',
            'duration':'until_arrived','destination':destination}],
            control_team='red',director=True,no_fire=False,intent=NOTE)
        raw = commands.step_order(session,state['orders'][0],state)
        self.assertEqual(raw['intent_id'],state['orders'][0]['id'])
        self.assertEqual(movement_feedback.configuration(value)['version'],CONFIG['version'])

    def test_prepared_profile_cannot_fall_through_to_old_native_or_model_physics(self):
        from backend import afsim_world, dsh_simulation
        from verify_dsh_resources import model_result
        value = world(); saved = copy.deepcopy(value)
        with self.assertRaisesRegex(ValueError,'连续机动.*执行|执行.*连续机动'):
            afsim_world.compile_scene(value,[],1800,native_rules=True)
        with self.assertRaisesRegex(ValueError,'连续机动.*执行|执行.*连续机动'):
            dsh_simulation.apply(value,model_result(value),'30分钟')
        with self.assertRaisesRegex(ValueError,'连续机动.*执行|执行.*连续机动'):
            dsh_simulation.prompt(value)
        with self.assertRaisesRegex(ValueError,'连续机动.*执行|执行.*连续机动'):
            dsh_simulation.advance({'war_state':value},{},None)
        self.assertEqual(value,saved)

    def test_selected_world_rejects_missing_carry_and_legacy_world_rejects_injection(self):
        value = world()
        for field in ('fatigue_carry_ticks','fuel_credit_microliters'):
            bad = copy.deepcopy(value); bad['red_units'][0]['formation'].pop(field)
            with self.subTest(field=field),self.assertRaises(ValueError):
                missions.validate(bad)
        source,p = inputs();p['movement_feedback']={'version':'movement-feedback-1','assumption':NOTE}
        old = ho.initial(source,p); old['red_units'][0]['formation']['fuel_credit_microliters']=0
        with self.assertRaises(ValueError):missions.validate(old)

    def test_cold_json_round_trip_preserves_all_precision_fields_and_config(self):
        import json
        value = world(); unit=value['red_units'][0]
        unit['formation'].update(fatigue=67,fatigue_carry_ticks=999999,
                                 fuel_liters=301,fuel_credit_microliters=123457)
        restored=json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False))
        self.assertEqual(restored,value)
        self.assertTrue(missions.validate(restored))

    def test_phase_handoff_preserves_balances_and_rejects_motion_version_changes(self):
        from gentactix import phase_continuity, sim_clock
        from verify_phase_continuity import checkpoint
        source,target=checkpoint(movement_feedback=CONFIG,
            fire_dynamics={'version':'live-footprint-density-2','assumption':NOTE})
        source['current_time'],source['simulation_clock']=sim_clock.target(source,'1小时')
        target['parameters']['clock']['start']=source['current_time']
        source['red_units'][0]['formation'].update(fatigue_carry_ticks=912345,
            fuel_liters=301,fuel_credit_microliters=123457)
        prior=copy.deepcopy(source['red_units'][0]['formation'])
        child=missions.from_definition(phase_continuity.definition(phase_continuity.bind(source,target)))
        for field in ('fatigue','fuel_liters','fatigue_carry_ticks','fuel_credit_microliters'):
            self.assertEqual(child['red_units'][0]['formation'][field],prior[field])
        target['parameters']['movement_feedback']['version']='movement-feedback-1'
        with self.assertRaisesRegex(ValueError,'movement_feedback'):
            phase_continuity.definition(phase_continuity.bind(source,target))

    def test_unit_extremes_are_rejected_without_repair(self):
        from gentactix import motion_state
        for points,carry,fuel in [(100,1,0),(-1,0,0),(True,0,0),(0,0,-1),(0,0,False)]:
            unit={'formation':{'fatigue':points,'fatigue_carry_ticks':carry,
                'fuel_liters':fuel,'fuel_credit_microliters':0}}
            prior=copy.deepcopy(unit)
            with self.subTest(points=points,carry=carry,fuel=fuel),self.assertRaises(ValueError):
                motion_state.validate_unit(unit)
            self.assertEqual(unit,prior)

    def test_parent_observation_reports_physical_fuel_and_precision_without_mutation(self):
        from gentactix import formation_parts
        import verify_formation_parts as fixture
        source,p=fixture.inputs();p['partitions']=fixture.partition_input(p)
        p['movement_feedback']=copy.deepcopy(CONFIG)
        value=ho.initial(source,p)
        members=[u for _,u in missions.units(value) if u.get('formation_part')]
        for u in members:u['formation']['fuel_credit_microliters']=800000
        saved=copy.deepcopy(value)
        row=formation_parts.observation(value)['groups'][0]
        self.assertEqual(row['motion_precision']['fuel_microliters'],
            sum(u['formation']['fuel_liters']*1000000+800000 for u in members))
        self.assertEqual(row['resources']['fuel_liters'],row['motion_precision']['fuel_microliters']//1000000)
        self.assertEqual(value,saved)

    def test_prepared_observation_never_claims_a_verified_legacy_motion_budget(self):
        value=world();prior=copy.deepcopy(value)
        result=movement_feedback.observation(value)
        self.assertEqual(result['version'],CONFIG['version'])
        self.assertFalse(result['execution_ready'])
        self.assertTrue(all('fuel_credit_microliters' in r and 'fatigue_carry_ticks' in r for r in result['units']))
        self.assertTrue(all('effective_ground_km' not in r for r in result['units']))
        self.assertIn('尚未',movement_feedback.causal_instruction(value))
        self.assertEqual(value,prior)

    def test_split_never_duplicates_fractional_fuel_and_merge_keeps_fatigue_pair(self):
        from gentactix import formation_conversion as fc, motion_state
        from verify_formation_conversion import ConversionTests, damaged
        unit=damaged();unit['formation'].update(fatigue_carry_ticks=999999,fuel_credit_microliters=123457)
        saved=copy.deepcopy(unit);proposal=ConversionTests().split(unit)
        self.assertEqual(unit,saved)
        self.assertTrue(fc.verify_proposal(proposal))
        a,b=proposal['after']
        self.assertEqual(sum(motion_state.fuel_load(u) for u in (a,b)),motion_state.fuel_load(unit))
        self.assertTrue(all(u['formation']['fatigue_carry_ticks']==999999 for u in (a,b)))
        a['formation'].update(fatigue=78,fatigue_carry_ticks=1)
        merged=fc.merge_current([a,b],assumption=NOTE,operation_id='e'*32)['after'][0]
        self.assertEqual(motion_state.fuel_load(merged),motion_state.fuel_load(unit))
        self.assertEqual((merged['formation']['fatigue'],merged['formation']['fatigue_carry_ticks']),(78,1))

    def test_merge_normalizes_fuel_credits_without_gaining_or_losing_a_liter(self):
        from gentactix import formation_conversion as fc, motion_state
        from verify_formation_conversion import ConversionTests, damaged
        unit=damaged();unit['formation'].update(fatigue_carry_ticks=0,fuel_credit_microliters=0)
        a,b=ConversionTests().split(unit)['after']
        for u in (a,b):u['formation']['fuel_credit_microliters']=800000
        saved=copy.deepcopy([a,b]);expected=sum(motion_state.fuel_load(u) for u in (a,b))
        proposal=fc.merge_current([a,b],assumption=NOTE,operation_id='f'*32)
        merged=proposal['after'][0]
        self.assertEqual([a,b],saved)
        self.assertEqual(motion_state.fuel_load(merged),expected)
        self.assertEqual(merged['formation']['fuel_credit_microliters'],600000)
        self.assertEqual(proposal['totals_before'],proposal['totals_after'])

    def test_mixed_precision_merge_is_rejected_without_silent_zero_migration(self):
        from gentactix import formation_conversion as fc
        from verify_formation_conversion import ConversionTests, damaged
        a,b=ConversionTests().split()['after']
        a['formation'].update(fatigue_carry_ticks=0,fuel_credit_microliters=0)
        saved=copy.deepcopy([a,b])
        with self.assertRaisesRegex(ValueError,'精度|连续机动'):
            fc.merge_current([a,b],assumption=NOTE,operation_id='f'*32)
        self.assertEqual([a,b],saved)


if __name__ == '__main__':
    unittest.main()
