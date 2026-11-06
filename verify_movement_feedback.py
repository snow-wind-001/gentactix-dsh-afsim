"""Versioned motion constraints, not a substitute effect/state generator."""
import copy
import math
import unittest

from gentactix import commands, historical_operations as ho, missions
from tools.qa.historical_operational_fixture import inputs
from verify_dsh_resources import model_result


NOTE = 'QA运动约束；数值为计算先验，不是历史或生理标定。'
CONFIG = dict(version='movement-feedback-1', assumption=NOTE)


def world(*, enabled=True, **changes):
    snapshot, params = inputs()
    for actor in params['actors'].values():
        actor['formation']['fatigue'] = 0
    next(iter(params['actors'].values()))['formation']['fatigue'] = 10
    if enabled:
        params['movement_feedback'] = copy.deepcopy(CONFIG)
    for key, value in changes.items():
        params[key] = value
    return ho.initial(snapshot, params)


def session(w):
    return dict(id='movement-feedback-qa', role_epoch=0, turn_count=w['mission']['turn'],
        war_state=w, time_step=w['mission']['definition']['time_step'],
        product_mode='historical', simulation_mode='open', execution_backend='narrative')


def moving(w, km=.1):
    u = w['red_units'][0]; value = model_result(w)
    point = commands.towards(u, dict(lat=u['lat']+.05, lng=u['lng']), km)
    value['orders'][0].update(action='move', **point)
    value['unit_updates'][0].update(point)
    value['unit_updates'][0]['logistics']['food'] -= 2
    value['resource_ledger']['units'][0]['food_spent'] = 4
    rate = sum(e['operational']*{'armor':2,'transport':.1}.get(e['category'],0) for e in u['equipment'])
    cost = math.ceil(missions.distance(u,point)*rate)
    value['unit_updates'][0]['formation']['fuel_liters'] = u['formation']['fuel_liters']-cost
    value['resource_ledger']['units'][0]['spent'] = dict(fuel_liters=cost)
    return value


def motor_ferry_world():
    from verify_ferries import ferry_inputs
    snapshot,p=ferry_inputs();p['movement_feedback']=copy.deepcopy(CONFIG)
    p['actors']['lm.red.cmc_column']['formation']['motorized']=True
    parts=p['partitions']['groups']['lm.red.cmc_column']['parts']
    parts[0]['equipment']['transport']-=1;parts[1]['equipment']['transport']=1
    p['facility']['crossing_model']['ferry']['boats'][0]['equipment_work_capacity']=100
    p['rules'].update(command_base_s=0,command_signal_s=0,command_distance_s_per_km=0)
    return ho.initial(snapshot,p)


class MovementFeedbackTests(unittest.TestCase):
    def test_scheduled_supply_prompt_preserves_movement_and_personnel_projection_contracts(self):
        from verify_supply_schedule import world as scheduled_world
        from backend import dsh_simulation
        w=scheduled_world(food=80,step='1小时')
        w['mission']['definition']['movement_feedback']=copy.deepcopy(CONFIG)
        text=dsh_simulation.prompt(w)
        self.assertIn('【movement-feedback-1】',text)
        self.assertIn('实际陆地公里*fatigue_move_gain',text)
        self.assertIn('personnel_strength_pct',text)
    def test_opt_in_definition_is_frozen_and_old_definition_is_unchanged(self):
        old = world(enabled=False); frozen = copy.deepcopy(old)
        new = world(); self.assertEqual(new['mission']['definition']['movement_feedback'], CONFIG)
        self.assertTrue(missions.validate(new)); self.assertTrue(missions.validate(old))
        self.assertNotIn('movement_feedback', old['mission']['definition']); self.assertEqual(old, frozen)

    def test_unknown_model_and_configuration_fields_do_not_silently_enable(self):
        for config in ({**CONFIG, 'version':'unknown'}, {**CONFIG, 'assumption':''}, {**CONFIG, 'enabled':True}):
            with self.subTest(config=config), self.assertRaises(ValueError): world(movement_feedback=config)

    def test_effective_budget_accounts_for_pause_without_reducing_native_nominal_speed(self):
        from gentactix import movement_feedback as mf
        w = world(); u = w['red_units'][0]; nominal = missions.move_budget(w,u)
        limits = mf.limits(w,u)
        self.assertAlmostEqual(limits['nominal_km'],nominal)
        self.assertGreater(limits['pause_seconds'],0)
        self.assertAlmostEqual(limits['effective_ground_km'], nominal*(1800-limits['pause_seconds'])/1800)
        self.assertAlmostEqual(commands.move_budget(session(w),u,'red'),limits['effective_ground_km'])
        self.assertEqual(missions.move_budget(w,u),nominal)

    def test_until_arrived_uses_effective_segment_and_next_cannot_spend_nominal_budget(self):
        from gentactix import movement_feedback as mf
        w=world(); s=session(w); row=commands.view(s)['units'][0];u=w['red_units'][0]
        destination=dict(lat=u['lat']+.05,lng=u['lng'])
        state=commands.replace_queue(s,[dict(unit_id=row['id'],action='move',destination=destination,duration='until_arrived')],
            control_team='red',director=True,no_fire=False,intent=NOTE)
        raw=commands.step_order(s,state['orders'][0],state)
        effective=mf.limits(w,u,destination)['effective_ground_km']
        self.assertLessEqual(missions.distance(u,raw),effective+1e-6)
        self.assertGreater(missions.distance(u,raw),effective*.99)
        nominal_target=commands.towards(u,destination,missions.move_budget(w,u))
        with self.assertRaises(ValueError):
            missions.validate_orders(w,[dict(unit=u['name'],action='move',**nominal_target)],s['time_step'])

    def test_real_failure_shape_move_without_fatigue_is_rejected_without_state_repair(self):
        from backend import dsh_simulation
        w=world(); value=moving(w); before=copy.deepcopy((w,value))
        with self.assertRaisesRegex(ValueError,'疲劳'): dsh_simulation.apply(w,value,'30分钟')
        self.assertEqual((w,value),before)

    def test_explicit_model_fatigue_is_accepted_and_host_does_not_generate_it(self):
        from backend import dsh_simulation
        from gentactix import movement_feedback as mf
        w=world(); value=moving(w);u=w['red_units'][0]; row=value['unit_updates'][0]
        row['formation']['fatigue']=mf.fatigue_value(w,u,'move',missions.distance(u,row))
        before=copy.deepcopy((w,value));after=dsh_simulation.apply(w,value,'30分钟')
        self.assertEqual(after['red_units'][0]['formation']['fatigue'],row['formation']['fatigue'])
        self.assertEqual(after['dsh_execution']['movement']['version'],mf.VERSION)
        self.assertEqual((w,value),before)

    def test_rest_and_other_actions_obey_existing_recovery_and_no_arbitrary_reset(self):
        from backend import dsh_simulation
        w=world();value=model_result(w)
        with self.assertRaisesRegex(ValueError,'疲劳'):dsh_simulation.apply(w,value,'30分钟')
        value['unit_updates'][0]['formation']['fatigue']=0
        after=dsh_simulation.apply(w,value,'30分钟')
        self.assertEqual(after['red_units'][0]['formation']['fatigue'],0)

    def test_fatigue_ties_match_native_gtx_round_not_unconditional_half_up(self):
        from gentactix import movement_feedback as mf
        w=world();u=w['red_units'][0];gain=w['mission']['definition']['combined_rules']['fatigue_move_gain']
        self.assertEqual(mf.fatigue_value(w,u,'move',.5/gain),10)
        self.assertEqual(mf.fatigue_value(w,u,'move',1.5/gain),12)

    def test_opt_in_command_delay_uses_native_even_ties_and_preserves_legacy_rounding(self):
        from gentactix import fire_process, movement_feedback as mf
        for enabled, expected in ((False,3),(True,2)):
            w=world(enabled=enabled);u=w['red_units'][0]
            cfg=w['mission']['definition']['combined_rules']
            cfg.update(command_base_s=2.5,command_signal_s=0,command_distance_s_per_km=0)
            self.assertEqual(fire_process.delay_seconds(w,u),expected)
            if enabled:self.assertEqual(mf.limits(w,u)['command_delay_seconds'],expected)

    def test_strength_suppression_dead_and_staged_units_bound_ground_motion(self):
        from gentactix import movement_feedback as mf, campaign
        from unittest.mock import patch
        w=world();u=w['red_units'][0];seconds=1800
        u['personnel']['current']=u['personnel']['committed']/4
        self.assertGreaterEqual(mf.limits(w,u)['pause_seconds'],seconds*.75)
        u['formation']['suppression']=100
        self.assertGreaterEqual(mf.limits(w,u)['pause_seconds'],seconds*.75)
        u['personnel']['current']=0
        self.assertEqual(mf.limits(w,u)['effective_ground_km'],0)
        u['personnel']['current']=u['personnel']['committed']
        with patch.object(campaign,'release_seconds',return_value=60):
            self.assertEqual(mf.limits(w,u)['effective_ground_km'],0)

    def test_fuel_floor_limits_motorized_ground_but_no_motor_equipment_is_not_stuck(self):
        from gentactix import movement_feedback as mf
        w=world();u=w['red_units'][0];u['formation'].update(motorized=True,fuel_liters=.99)
        self.assertTrue(any(e['operational'] for e in u['equipment'] if e['category'] in ('armor','transport')))
        self.assertEqual(mf.limits(w,u)['effective_ground_km'],0)
        for e in u['equipment']:
            if e['category'] in ('armor','transport'):e['operational']=0
        self.assertIsNone(mf.limits(w,u)['fuel_ground_km'])
        self.assertGreater(mf.limits(w,u)['effective_ground_km'],0)

    def test_nutrition_is_a_floor_not_a_second_movement_fatigue_increment(self):
        from gentactix import movement_feedback as mf, support_dynamics
        from unittest.mock import patch
        w=world();u=w['red_units'][0];cfg=dict(shortage_fatigue_per_hour=3)
        u['sustainment']=dict(shortage_hours=7.5)
        with patch.object(support_dynamics,'configuration',return_value=cfg):
            # 10 fatigue + round(.5*gain) < hunger floor 22.
            self.assertEqual(mf.fatigue_value(w,u,'move',0),22)
            # Rest recovers by wall-clock fraction, then applies the same floor.
            self.assertEqual(mf.fatigue_value(w,u,'hold',0),22)
            cfg['shortage_fatigue_per_hour']=0
            u['formation']['fatigue']=80
            w['mission']['definition']['time_step']='15分钟'
            recovery=w['mission']['definition']['combined_rules']['fatigue_rest_recovery']
            self.assertEqual(mf.fatigue_value(w,u,'conceal',0),80-recovery/2)
            self.assertEqual(mf.fatigue_value(w,u,'fire',0),80)

    def test_native_telemetry_cannot_omit_duplicate_or_invent_an_actor(self):
        from backend import afsim_movement, afsim_world
        w=world();scene=afsim_world.compile_scene(w,[],1800,native_rules=True)
        model=scene['native_model'];ids=list(scene['entities'])
        lines=[f'GTXMOVEMENT|{i}|0|0|0' for i in ids]
        self.assertEqual(set(afsim_movement.parse('\n'.join(lines),model,scene)),set(ids))
        for bad in (lines[:-1],lines+[lines[0]],lines+['GTXMOVEMENT|invented|0|0|0'],
                    [lines[0].replace('|0|0|0','|nan|0|0'),*lines[1:]]):
            with self.subTest(lines=bad),self.assertRaises(ValueError):
                afsim_movement.parse('\n'.join(bad),model,scene)

    def test_ground_and_fatigue_must_both_validate_before_accepting_native_receipts(self):
        from gentactix import movement_feedback as mf
        w=world();u=w['red_units'][0];after=copy.deepcopy(w)
        orders=[dict(unit=v['name'],action='hold') for _,v in missions.units(w)]
        for _,v in missions.units(after):
            v['formation']['fatigue']=mf.fatigue_value(w,next(a for _,a in missions.units(w) if a['name']==v['name']),'hold',0)
        native={v['name']:dict(ground_km=0,route_km=0,pause_seconds=mf.limits(w,v)['pause_seconds']) for _,v in missions.units(w)}
        mf.validate_transition(w,after,orders,1800,source='qa',native=native)
        native[u['name']]['ground_km']=.000004
        with self.assertRaisesRegex(ValueError,'路程'):mf.validate_transition(w,after,orders,1800,source='qa',native=native)

    def test_carriage_excludes_water_from_passenger_ground_fatigue(self):
        from gentactix import movement_feedback as mf, ferries
        from verify_ferries import FerryTests
        from backend import dsh_simulation
        before,proposal=FerryTests().proposal()
        aboard=dsh_simulation.apply(before,proposal,'1分钟')
        aboard['mission']['definition']['movement_feedback']=copy.deepcopy(CONFIG)
        name=ferries.state(aboard)['boats'][0]['passenger']
        u=next(v for _,v in missions.units(aboard) if v['name']==name)
        following={**u,'lat':27.31497}
        row=mf.travel(aboard,u,following,dict(unit=name,action='hold'))
        self.assertEqual(row['mode'],'carried');self.assertEqual(row['ground_km'],0)
        self.assertGreater(row['route_km'],0)

    def test_fuel_empty_motorized_unit_at_bank_can_request_boat_without_ground_motion(self):
        from gentactix import movement_feedback as mf
        w=motor_ferry_world();s=session(w)
        u=next(v for _,v in missions.units(w) if v['personnel']['committed']==5)
        bank=w['combined_arms']['bridge']['crossing_model']['banks']['b']
        row=next(r for r in commands.view(s)['units'] if r['name']==u['name'])
        self.assertEqual(mf.command_budget(w,u,bank),0)
        cs=commands.replace_queue(s,[dict(unit_id=row['id'],action='move',destination=bank,duration='until_arrived')],
            control_team='red',director=True,no_fire=False,intent=NOTE)
        raw=commands.step_order(s,cs['orders'][0],cs)
        self.assertEqual({k:raw[k] for k in ('lat','lng')},bank)
        missions.validate_orders(w,[raw],s['time_step'])

    def test_already_at_bridge_entry_is_not_mistaken_for_early_approach(self):
        from gentactix import movement_feedback as mf
        from verify_afsim_crossing import fixture
        from unittest.mock import patch
        spec=fixture();spec['movement_feedback']=copy.deepcopy(CONFIG)
        spec['combined_rules']['command_base_s']=2.5
        spec['initial_state']['red_units'][0]['formation']['fatigue']=10
        spec['initial_state']['combined_arms']['rules_hash']=missions.digest(spec['combined_rules'])
        original=missions.definition
        with patch.object(missions,'definition',side_effect=lambda i:copy.deepcopy(spec) if i==spec['id'] else original(i)):
            before=missions.from_definition(spec)
        u=before['red_units'][0];after=copy.deepcopy(before)
        order=dict(unit=u['name'],action='move',lat=27.303,lng=107.4)
        after['red_units'][0]['crossing']=dict(last_work=100,events=[dict(phase='entered',seconds=.002)])
        mf.validate_transition(before,after,[order],1800,source='qa')
        before['red_units'][0]['lat']-=.001;after['red_units'][0]['lat']-=.001
        with self.assertRaisesRegex(ValueError,'抵达渡运入口'):
            mf.validate_transition(before,after,[order],1800,source='qa')


if __name__=='__main__':unittest.main()
