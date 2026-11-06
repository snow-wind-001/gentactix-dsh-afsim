"""Explicit boat capacity, conserved manifests and native transport boundaries."""
import copy
import unittest

from gentactix import historical_operations as ho, missions
from tools.qa.historical_crossing_fixture import inputs
from verify_formation_parts import partition_input


def ferry_inputs():
    snapshot, params = inputs()
    params['clock']['time_step'] = '1分钟'
    params['goal']['deadline_turn'] = 20
    params['partitions'] = partition_input(params)
    params['partitions']['groups']['lm.red.cmc_column']['parts'][1]['position'] = {'lat': 27.3145, 'lng': 107.402}
    params['facility']['progress'] = 0
    params['facility']['crossing_model']['ferry'] = {
        'version': 'formation-ferry-1', 'assumption': 'QA舟艇能力估计，非历史船数或水文。',
        'boats': [{'id': 'raft1', 'name': '计算竹筏1', 'team': 'red', 'seats': 5,
                   'equipment_work_capacity': 0, 'speed_mps': .5, 'load_seconds': 10,
                   'unload_seconds': 10, 'initial_bank': 'a', 'assumption': 'QA五人载荷；不是史实军委纵队先遣舟。'}]}
    return snapshot, params


class FerryTests(unittest.TestCase):
    def test_optional_boats_are_frozen_inputs_and_not_extra_people(self):
        from gentactix import ferries
        snapshot, params = ferry_inputs()
        frozen = copy.deepcopy(snapshot)
        frozen_parameters = copy.deepcopy(params)
        world = ho.initial(snapshot, params)
        state = ferries.state(world)
        self.assertEqual(len(state['boats']), 1)
        self.assertEqual(state['boats'][0]['phase'], 'idle')
        self.assertIsNone(state['boats'][0]['passenger'])
        self.assertEqual(len(missions.units(world)), 6)
        self.assertEqual(sum(u['personnel']['current'] for u in world['red_units']), 4600)
        self.assertEqual(snapshot, frozen)
        self.assertEqual(params, frozen_parameters)

    def test_invalid_boat_capacity_speed_identity_and_states_rejected(self):
        from gentactix import ferries
        snapshot, params = ferry_inputs()
        for kind in ('seats', 'speed_mps', 'id'):
            p = copy.deepcopy(params)
            boat = p['facility']['crossing_model']['ferry']['boats'][0]
            boat[kind] = {'seats': 0, 'speed_mps': float('nan'), 'id': 'bad|id'}[kind]
            with self.subTest(kind=kind), self.assertRaises(ValueError): ho.initial(snapshot, p)
        world = ho.initial(snapshot, params)
        world['combined_arms']['bridge']['ferry_state']['boats'][0]['passenger'] = 'invented'
        with self.assertRaises(ValueError): ferries.validate(world)

    def test_native_scene_uses_surface_platform_and_real_embark_callbacks(self):
        from backend import afsim_world
        world = ho.initial(*ferry_inputs())
        unit = world['red_units'][1]
        scene = afsim_world.compile_scene(world, [{'unit': unit['name'], 'action': 'move', 'lat': 27.3151, 'lng': 107.402}], 60, native_rules=True)
        self.assertEqual(scene['motion_revision'], 9)
        self.assertIn('WSF_SURFACE_MOVER', scene['script'])
        self.assertIn('GTXFERRY|', scene['script'])
        self.assertIn('GtxFerryTick', scene['script'])
        self.assertIn('GoToPoint', scene['script'])

    def test_old_crossing_worlds_do_not_gain_boats(self):
        from gentactix import ferries
        from backend import afsim_world
        world = ho.initial(*inputs())
        self.assertIsNone(ferries.state(world))
        self.assertEqual(afsim_world.motion_revision(world), 7)
        self.assertNotIn('ferry_state', world['combined_arms']['bridge'])

    def proposal(self):
        from gentactix import formation_parts, crossings, ferries
        from verify_dsh_resources import model_result
        world=ho.initial(*ferry_inputs());unit=world['red_units'][1]
        result=model_result(world)
        order={'unit':unit['name'],'action':'move','lat':27.3151,'lng':107.402}
        result['orders']=[order if o['unit']==unit['name'] else o for o in result['orders']]
        for row,(_,u) in zip(result['resource_ledger']['units'],missions.units(world)):
            row['food_spent']=(4 if u['name']==unit['name'] else 2)*formation_parts.scale(u)
        update=next(r for r in result['unit_updates'] if r['unit']==unit['name'])
        update.update(lat=27.3147,lng=107.402,logistics={'food':76,'ammo':80})
        update['crossing']={'served_work':5,'last_work':5,'status':'transit',
            'events':[{'phase':'entered','seconds':1,'lat':27.3145,'lng':107.402}]}
        state=copy.deepcopy(ferries.state(world));boat=state['boats'][0]
        boat.update(lat=27.3147,phase='outbound',passenger=unit['name'],manifest_personnel=5)
        state['events']=[{'boat_id':'raft1','unit':unit['name'],'phase':phase,'seconds':t,'lat':27.3145,'lng':107.402}
                         for phase,t in [('loading',1),('boarded',11)]]
        result['combined_arms']={'bridge':{'ferry_state':state,'crossing_receipt':{'used_work':5,'cargo_work':0,'budget_work':250}}}
        return world,result

    def test_dsh_model_declares_boarding_and_native_source_is_not_fabricated(self):
        from backend import dsh_simulation
        from gentactix import ferries
        before,value=self.proposal();frozen=copy.deepcopy(before)
        after=dsh_simulation.apply(before,value,'1分钟')
        self.assertEqual(ferries.state(after)['source'],'dsh_model_estimate')
        self.assertEqual(ferries.state(after)['boats'][0]['manifest_personnel'],5)
        self.assertEqual(after['red_units'][1]['crossing']['status'],'transit')
        self.assertEqual(before,frozen)

    def test_dsh_hold_aboard_retains_physical_transport_without_creating_native_receipts(self):
        from backend import dsh_simulation
        from gentactix import ferries,formation_parts
        from verify_dsh_resources import model_result
        before,value=self.proposal();aboard=dsh_simulation.apply(before,value,'1分钟')
        next_value=model_result(aboard)
        for (_,u),row in zip(missions.units(aboard),next_value['resource_ledger']['units']):row['food_spent']*=formation_parts.scale(u)
        next(r for r in next_value['unit_updates'] if r['unit']==aboard['red_units'][1]['name']).update(lat=27.31497,lng=107.402)
        state=copy.deepcopy(ferries.state(aboard));state['events']=[];state['boats'][0]['lat']=27.31497
        next_value['combined_arms']={'bridge':{'ferry_state':state,'crossing_receipt':{'used_work':0,'cargo_work':0,'budget_work':250}}}
        after=dsh_simulation.apply(aboard,next_value,'1分钟')
        self.assertEqual(after['red_units'][1]['lat'],27.31497)
        self.assertEqual(after['red_units'][1]['crossing']['served_work'],5)
        self.assertEqual(ferries.state(after)['source'],'dsh_model_estimate')

    def test_hold_receipt_explains_why_a_passenger_still_changes_position(self):
        from backend import dsh_simulation
        from gentactix import commands, ferries, formation_parts
        from verify_dsh_resources import model_result
        before, value = self.proposal()
        aboard = dsh_simulation.apply(before, value, '1分钟')
        session = {'id': 'qa-ferry-hold', 'war_state': aboard, 'turn_count': 1,
                   'time_step': '1分钟', 'simulation_mode': 'open', 'execution_backend': 'narrative'}
        view = commands.view(session)
        passenger = ferries.state(aboard)['boats'][0]['passenger']
        identity = next(u['id'] for u in view['units'] if u['name'] == passenger)
        session['command_state'] = commands.replace_queue(session,
            [{'unit_id': identity, 'action': 'hold', 'duration': 'next'}],
            control_team='red', director=True, no_fire=True, intent='QA aboard hold')
        prepared = commands.prepare(session)
        proposed = model_result(aboard)
        for (_, u), row in zip(missions.units(aboard), proposed['resource_ledger']['units']):
            row['food_spent'] *= formation_parts.scale(u)
        next(r for r in proposed['unit_updates'] if r['unit'] == passenger).update(lat=27.31497, lng=107.402)
        state = copy.deepcopy(ferries.state(aboard))
        state['events'] = []
        state['boats'][0]['lat'] = 27.31497
        proposed['combined_arms'] = {'bridge': {'ferry_state': state,
            'crossing_receipt': {'used_work': 0, 'cargo_work': 0, 'budget_work': 250}}}
        after = dsh_simulation.apply(aboard, proposed, '1分钟')
        control, _ = commands.finish(session, prepared, after, executed=proposed['orders'])
        receipt = next(r for r in control['receipts'] if r['unit_id'] == identity and r['turn'] == 2)
        self.assertEqual(receipt['action'], 'hold')
        self.assertEqual(receipt['status'], 'completed')
        self.assertIn('随艇', receipt['reason'])
        self.assertNotEqual(receipt['before_position'], receipt['after_position'])

    def test_actual_advance_entry_includes_boat_contract_and_accepts_checked_proposal(self):
        from unittest.mock import patch
        from backend import dsh_simulation
        before,value=self.proposal()
        with patch.object(dsh_simulation.h,'get_ai_response',return_value=value) as model:
            result,_,_=dsh_simulation.advance({'war_state':before,'time_step':'1分钟'},None,None)
        self.assertIn('formation-ferry-1',model.call_args.args[0])
        self.assertIn('remaining_s',model.call_args.args[0])
        self.assertEqual(result['updated_state']['red_units'][1]['crossing']['status'],'transit')

    def test_actual_top_level_receipt_failure_has_actionable_path_and_schema_shaped_retry(self):
        from unittest.mock import patch
        from backend import dsh_simulation
        before,good=self.proposal();bad=copy.deepcopy(good)
        bad['crossing_receipt']=bad['combined_arms']['bridge'].pop('crossing_receipt')
        with self.assertRaisesRegex(ValueError,'crossing_receipt.*combined_arms.bridge'):
            dsh_simulation.apply(before,bad,'1分钟')
        with patch.object(dsh_simulation.h,'get_ai_response',side_effect=[bad,good]) as model:
            dsh_simulation.advance({'war_state':before,'time_step':'1分钟'},None,None)
        feedback=model.call_args.args[0]
        self.assertIn('combined_arms.bridge.crossing_receipt',feedback)
        self.assertNotIn('"bridge_changes":',feedback)

    def test_actual_boarded_event_in_crossing_list_points_to_the_correct_namespace(self):
        from backend import dsh_simulation
        before,value=self.proposal()
        value['unit_updates'][1]['crossing']['events'][0]['phase']='boarded'
        with self.assertRaisesRegex(ValueError,'crossing.events.*entered.*exited.*ferry_state.events'):
            dsh_simulation.apply(before,value,'1分钟')

    def test_actual_started_trip_and_leg_countdown_are_not_completed_landings(self):
        from backend import dsh_simulation
        before,value=self.proposal()
        value['combined_arms']['bridge']['ferry_state']['boats'][0]['trips']=1
        with self.assertRaisesRegex(ValueError,'raft1.*trips.*0.*landed'):
            dsh_simulation.apply(before,value,'1分钟')
        before,value=self.proposal()
        value['combined_arms']['bridge']['ferry_state']['boats'][0]['remaining_s']=82
        with self.assertRaisesRegex(ValueError,'remaining_s.*装卸.*0'):
            dsh_simulation.apply(before,value,'1分钟')

    def test_landing_waits_for_unloading_and_cannot_rewrite_the_return_bank(self):
        from backend import dsh_simulation
        from gentactix import ferries, formation_parts
        from verify_dsh_resources import model_result
        before, value = self.proposal()
        midway = dsh_simulation.apply(before, value, '1分钟')
        def held(world):
            result = model_result(world)
            for (_, unit), row in zip(missions.units(world), result['resource_ledger']['units']):
                row['food_spent'] *= formation_parts.scale(unit)
            return result
        approaching = held(midway)
        next(r for r in approaching['unit_updates'] if r['unit'] == midway['red_units'][1]['name']).update(lat=27.31497, lng=107.402)
        state = copy.deepcopy(ferries.state(midway)); state['events'] = []; state['boats'][0]['lat'] = 27.31497
        approaching['combined_arms'] = {'bridge': {'ferry_state': state,
            'crossing_receipt': {'used_work': 0, 'cargo_work': 0, 'budget_work': 250}}}
        before = dsh_simulation.apply(midway, approaching, '1分钟')
        result = held(before); name = before['red_units'][1]['name']
        next(r for r in result['unit_updates'] if r['unit'] == name).update(lat=27.3151, lng=107.402,
            crossing={'served_work': 5, 'last_work': 0, 'status': 'completed',
                      'events': [{'phase': 'exited', 'seconds': 40, 'lat': 27.3151, 'lng': 107.402}]})
        state = copy.deepcopy(ferries.state(before))
        state['events'] = [{'boat_id': 'raft1', 'unit': name, 'phase': 'landed', 'seconds': 40, 'lat': 27.3151, 'lng': 107.402}]
        state['boats'][0].update(lat=27.31501, bank='b', from_bank='a', phase='returning', passenger=None,
            manifest_personnel=0, manifest_equipment_work=0, trips=1)
        result['combined_arms'] = {'bridge': {'ferry_state': state,
            'crossing_receipt': {'used_work': 0, 'cargo_work': 0, 'budget_work': 250}}}
        self.assertEqual(ferries.state(dsh_simulation.apply(before, result, '1分钟'))['boats'][0]['from_bank'], 'a')
        invalid = copy.deepcopy(result)
        invalid['combined_arms']['bridge']['ferry_state']['boats'][0]['from_bank'] = 'b'
        with self.assertRaisesRegex(ValueError, 'from_bank|出发岸'):
            dsh_simulation.apply(before, invalid, '1分钟')
        invalid = copy.deepcopy(result)
        invalid['combined_arms']['bridge']['ferry_state']['events'][0]['seconds'] = 30
        with self.assertRaisesRegex(ValueError, '最早.*卸载'):
            dsh_simulation.apply(before, invalid, '1分钟')

    def test_missing_events_teleport_and_premature_landing_are_rejected(self):
        from backend import dsh_simulation
        for kind in ('missing','events','teleport','landing'):
            before,value=self.proposal();boat=value['combined_arms']['bridge']['ferry_state']['boats'][0]
            if kind=='missing':value['combined_arms']['bridge'].pop('ferry_state')
            elif kind=='events':value['combined_arms']['bridge']['ferry_state']['events']=[]
            elif kind=='teleport':boat['lat']=27.3151;value['unit_updates'][1]['lat']=27.3151
            elif kind=='landing':value['combined_arms']['bridge']['ferry_state']['events'].append(
                {'boat_id':'raft1','unit':before['red_units'][1]['name'],'phase':'landed','seconds':20,'lat':27.3151,'lng':107.402})
            with self.subTest(kind=kind),self.assertRaises(ValueError):dsh_simulation.apply(before,value,'1分钟')

    def test_idle_boat_cannot_drift_or_report_a_second_manifest(self):
        from gentactix import ferries
        world=ho.initial(*ferry_inputs());world['combined_arms']['bridge']['ferry_state']['boats'][0]['lat']=27.3147
        with self.assertRaisesRegex(ValueError,'漂移'):ferries.validate(world)

    def test_an_oversized_formation_cannot_silently_queue_forever(self):
        world=ho.initial(*ferry_inputs())
        with self.assertRaisesRegex(ValueError,'容量'):
            missions.validate_orders(world,[{'unit':world['red_units'][0]['name'],'action':'move','lat':27.3151,'lng':107.402}],'1分钟')


if __name__ == '__main__':
    unittest.main()
