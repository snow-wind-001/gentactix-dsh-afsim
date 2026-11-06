"""Explicit aviation availability and cumulative-OOB admission, never a history seed."""
import copy
import unittest
from datetime import datetime, timedelta

from gentactix import air_assets, historical_initial, historical_operations as ho, sim_clock
from tools.qa.historical_air_fixture import inputs


def envelope(start, end=None):
    return {'version':'air-availability-1','start':start,'end':end,
            'assumption':'QA estimated availability, not a sourced arrival time or airfield.'}


def timed_world(start=0, end=600):
    snapshot,params=inputs();origin=datetime.fromisoformat(params['clock']['start'])
    params['aviation']['ww2.cacw.group5']['availability']=envelope(
        (origin+timedelta(seconds=start)).isoformat(),
        None if end is None else (origin+timedelta(seconds=end)).isoformat())
    return ho.initial(snapshot,params)


class AirAvailabilityTests(unittest.TestCase):
    def test_unverified_phase_still_refuses_cumulative_aircraft(self):
        battle=next(r['battle'] for r in historical_initial.catalog() if r['profile_id']=='AJ15-jizhong')
        snapshot=historical_initial.initial(battle)['historical_initial']
        with self.assertRaisesRegex(ValueError,'参战尚未核定'):ho.configuration_template(snapshot)

    def test_explicit_campaign_keeps_air_reference_with_required_estimated_schedule(self):
        battle=next(r['battle'] for r in historical_initial.catalog() if r['profile_id']=='AJ15-jizhong')
        snapshot=historical_initial.initial(battle)['historical_initial'];before=copy.deepcopy(snapshot)
        template=ho.configuration_template(snapshot,'campaign')
        self.assertEqual(len(template['actors']),34)
        self.assertIn('ww2.jp.flight29',template['aviation'])
        availability=template['aviation']['ww2.jp.flight29']['availability']
        self.assertEqual(availability['version'],'air-availability-1');self.assertIsNone(availability['start'])
        self.assertEqual(snapshot,before)

    def test_pending_active_expired_choices_use_program_clock_without_inventory_changes(self):
        from gentactix import air_availability
        world=timed_world(60,600);before=air_assets.world_state(world);spec=air_assets.world_definition(world)['pools']['ww2.cacw.group5']
        self.assertEqual(air_assets.available(world,'red'),[])
        self.assertEqual(air_availability.status(world,spec),'pending')
        world['simulation_clock']['elapsed_seconds']=60
        self.assertEqual(air_assets.available(world,'red')[0]['id'],'ww2.cacw.group5')
        world['simulation_clock']['elapsed_seconds']=600
        self.assertEqual(air_assets.available(world,'red'),[])
        self.assertEqual(air_availability.status(world,spec),'expired')
        self.assertEqual(air_assets.world_state(world),before)

    def test_bad_schedule_is_rejected_and_input_not_changed(self):
        from gentactix import air_availability
        good=envelope('1945-04-25T06:00:00','1945-04-25T07:00:00')
        for key,value in [('start',None),('start','1945-04-25'),('start','1945-04-25T06:00:00+08:00'),
                          ('end','1945-04-25T05:00:00'),('assumption',''),('version','other')]:
            bad={**good,key:value};prior=copy.deepcopy(bad)
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):air_availability.validate(bad)
            self.assertEqual(prior,bad)

    def test_open_end_remains_active_and_legacy_has_no_new_time_requirement(self):
        from gentactix import air_availability
        world=timed_world(0,None);spec=air_assets.world_definition(world)['pools']['ww2.cacw.group5']
        world['simulation_clock']['elapsed_seconds']=120*3600
        self.assertEqual(air_availability.status(world,spec),'active')
        plain=ho.initial(*inputs());plain.pop('simulation_clock');plain['current_time']='relative QA'
        self.assertTrue(air_assets.available(plain,'red'))

    def test_available_without_calendar_clock_is_not_guessed(self):
        world=timed_world();world['simulation_clock']['origin_iso']=None
        with self.assertRaisesRegex(ValueError,'时钟'):air_assets.available(world,'red')

    def test_native_compiler_refuses_future_pool_and_short_availability_window(self):
        from backend import afsim_world
        for start,end in [(60,600),(0,30)]:
            world=timed_world(start,end);red=world['red_units'][0]['name'];blue=world['blue_units'][0]['name']
            with self.subTest(start=start,end=end),self.assertRaises(ValueError):
                afsim_world.compile_scene(world,[{'unit':red,'action':'air_support','target':blue,'air_pool':'ww2.cacw.group5'}],1800,native_rules=True)

    def test_dsh_receipt_cannot_return_after_explicit_withdrawal(self):
        from backend import dsh_simulation
        from verify_dsh_aviation import result
        world=timed_world(0,150);proposal=result(world)
        with self.assertRaisesRegex(ValueError,'航空.*时段|可用时段'):dsh_simulation.apply(world,proposal,'30分钟')

    def test_valid_dsh_flight_does_not_freeze_end_of_turn_inventory(self):
        from backend import dsh_simulation
        from verify_dsh_aviation import result
        world=timed_world(0,600);before=copy.deepcopy(world)
        after=dsh_simulation.apply(world,result(world),'30分钟')
        self.assertEqual(after['air_operations']['pools']['ww2.cacw.group5']['sorties'],2)
        self.assertEqual(after['air_operations']['pools']['ww2.cacw.group5']['fuel'],12)
        self.assertEqual(air_assets.available(after,'red'),[])
        self.assertEqual(world,before)

    def test_snapshot_restore_keeps_explicit_schedule_without_live_catalogue(self):
        from unittest.mock import patch
        world=timed_world(60,600);binding=world['mission']['definition']['historical_calculation']
        with patch.object(historical_initial,'DATA_ROOT',historical_initial.DATA_ROOT/'absent'):
            restored=ho.from_binding(binding)
        self.assertEqual(restored,world['mission']['definition'])

    def test_campaign_air_requires_schedule_and_bounds_arrival_without_upgrading_presence(self):
        from verify_historical_operations import aviation_inputs
        snapshot,params=aviation_inputs();before=copy.deepcopy(snapshot)
        params['campaign_scope']={'planning_end':'1938-04-02T00:00:00'}
        with self.assertRaisesRegex(ValueError,'显式声明可用时段'):ho._air_definition(snapshot,params)
        for pool in params['aviation'].values():pool['availability']=envelope('1938-04-01T00:00:00')
        bound=ho._air_definition(snapshot,params)
        self.assertEqual(len(bound['pools']),2);self.assertEqual(snapshot,before)
        params['aviation']['qa.red.air']['availability']['start']='1938-04-03T00:00:00'
        with self.assertRaisesRegex(ValueError,'规划范围'):ho._air_definition(snapshot,params)

    def test_host_observation_distinguishes_allocated_airworthy_and_available(self):
        from gentactix import air_availability
        world=timed_world(60,600);before=copy.deepcopy(world)
        view=air_availability.view(world)['ww2.cacw.group5']
        self.assertEqual(view['status'],'pending');self.assertEqual(view['start'],'1945-04-25T06:01:00')
        self.assertEqual(air_assets.world_state(world)['pools']['ww2.cacw.group5']['ready'],4)
        self.assertEqual(world,before)

    def test_null_aviation_inventory_is_selectable_but_time_is_not_a_numeric_lock(self):
        from gentactix import scenario_constraints
        battle=next(r['battle'] for r in historical_initial.catalog() if r['profile_id']=='AJ15-jizhong')
        snapshot=historical_initial.initial(battle)['historical_initial'];template=ho.configuration_template(snapshot,'campaign')
        rows=scenario_constraints.fields(template);index={tuple(r['path']):r for r in rows}
        for key in ('committed','ordnance','fuel'):
            field=index[('aviation','ww2.jp.flight29','initial',key)]
            self.assertIsNone(field['value']);self.assertTrue(field['integer'])
        self.assertFalse(any(r['path'][:3]==['aviation','ww2.jp.flight29','availability'] for r in rows))


if __name__=='__main__':unittest.main()
