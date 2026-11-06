"""Aggregate air missions: contracts, resources, provenance and command controls."""
import copy
import unittest
from unittest.mock import patch
from backend import afsim_air, afsim_world, afsim_rules
from gentactix import missions, commands, fire_control


class AirTests(unittest.TestCase):
    def setUp(self):
        self.world = missions.initial('AJ18-local-v1')
        self.order = {'unit': self.world['red_units'][0]['name'], 'action': 'air_support',
                      'target': self.world['blue_units'][0]['name']}

    def scene(self, orders=None):
        return afsim_world.compile_scene(self.world, orders or [self.order], 1800, native_rules=True)

    def test_native_flight_callbacks_and_separate_aviation_consumables(self):
        scene = self.scene()
        self.assertIn('WSF_AIR_MOVER', scene['script'])
        self.assertIn('execute GtxStrike', scene['script'])
        self.assertIn('execute GtxReturn', scene['script'])
        self.assertEqual(len(scene['native_model']['air']['tasks']), 1)
        self.assertEqual(afsim_air.state(self.world)['assets']['red']['ready'], 8)
        self.assertIn('非历史编制', afsim_air.state(self.world)['assumptions'])

    def test_no_aircraft_for_unsupported_side_or_era(self):
        bad = {**self.order, 'unit': self.world['blue_units'][0]['name'], 'target': self.world['red_units'][0]['name']}
        with self.assertRaisesRegex(ValueError, '航空兵力'): self.scene([bad])
        other = missions.initial('LM02-local-v1') if any(x['id']=='LM02-local-v1' for x in missions.catalog()) else missions.initial('AJ15-local-v1')
        self.assertIsNone(afsim_air.state(other))

    def test_exhausted_or_corrupt_pool_is_rejected_without_mutation(self):
        self.world['air_operations'] = afsim_air.state(self.world)
        self.world['air_operations']['assets']['red']['ready'] = 1
        self.world['air_operations']['assets']['red']['destroyed'] = 7
        before = copy.deepcopy(self.world)
        with self.assertRaisesRegex(ValueError, '航空兵力'): self.scene()
        self.assertEqual(before, self.world)
        self.world['air_operations']['assets']['red']['ready'] = 100
        with self.assertRaises(ValueError): afsim_air.state(self.world)

    def test_friendly_target_and_unfinished_flight_are_rejected(self):
        with self.assertRaises(ValueError): self.scene([{**self.order, 'target': self.world['red_units'][1]['name']}])
        with self.assertRaisesRegex(ValueError, '回合'): afsim_world.compile_scene(self.world,[self.order],10,native_rules=True)

    def test_target_retained_in_visual_queue_and_no_fire_enforced(self):
        s={'war_state':self.world,'time_step':'30分钟','turn_count':0,'simulation_mode':'open',
           'execution_backend':'afsim','id':'air-contract'}
        view=commands.view(s)
        red=next(u for u in view['units'] if u['team']=='red')
        blue=next(u for u in view['units'] if u['team']=='blue')
        draft={'unit_id':red['id'],'action':'air_support','target_id':blue['id'],'duration':'next'}
        cs=commands.replace_queue(s,[draft],control_team='red',director=False,no_fire=False,intent='')
        self.assertEqual(cs['orders'][0]['target_id'],blue['id'])
        with self.assertRaises(ValueError): commands.replace_queue(s,[draft],control_team='red',director=False,no_fire=True,intent='')

    def result(self, aborted=False):
        model=self.scene()['native_model']['air']; task=model['tasks'][0]; identity=task['id']
        phases=['launch','abort_target_moved','returned'] if aborted else ['launch','air_defense','strike','returned']
        lines=[]
        for i,phase in enumerate(phases):
            pos=task['entry'] if phase in ('launch','returned') else task['aim']
            a,b=int(pos['lat']),int(pos['lng'])
            lines.append(f'GTXAIREVENT|{identity}|{phase}|{60000+i*20000}|{a}|{int((pos["lat"]-a)*1e8)}|{b}|{int((pos["lng"]-b)*1e8)}')
        lines.append(f'GTXAIRRESULT|{identity}|'+('0|0|0|0' if aborted else '1|1|6|0'))
        lines+=['GTXAIRPOOL|red|'+('8|0|2|24|44' if aborted else '7|1|2|22|44'),'GTXAIRPOOL|blue|0|0|0|0|0']
        return model,'\n'.join(lines)

    def test_native_pool_and_stage_decode(self):
        model,text=self.result()
        value=afsim_air.decode(text,model,1800)
        self.assertEqual(value['assets']['red']['ready'],7)
        self.assertEqual(value['assets']['red']['ordnance'],22)
        self.assertEqual(value['missions'][0]['personnel_effect'],6)

    def test_abort_spends_fuel_but_neither_bombs_nor_aircraft(self):
        model,text=self.result(True); value=afsim_air.decode(text,model,1800)
        self.assertEqual(value['assets']['red']['ordnance'],24)
        self.assertEqual(value['assets']['red']['fuel'],44)
        self.assertEqual(value['missions'][0]['personnel_effect'],0)

    def test_missing_or_corrupt_native_events_do_not_create_results(self):
        model,text=self.result()
        for bad in (text.replace('returned','missing'),text.replace('GTXAIRPOOL|red|7','GTXAIRPOOL|red|8'),
                    '\n'.join(x for x in text.splitlines() if not x.startswith('GTXAIRRESULT')),
                    text.replace('|60000|','|1900000|')):
            with self.assertRaises(ValueError): afsim_air.decode(bad,model,1800)

    def test_simultaneous_packages_reserve_shared_pool(self):
        self.world['air_operations']=afsim_air.state(self.world)
        self.world['air_operations']['assets']['red'].update(ready=2,destroyed=6)
        other={**self.order,'unit':self.world['red_units'][1]['name']}
        with self.assertRaisesRegex(ValueError,'航空兵力'):self.scene([self.order,other])

    def test_legacy_executor_cannot_silently_replace_native_airstrike(self):
        with self.assertRaisesRegex(ValueError,'AFSIM'): missions.advance(self.world,[self.order],'30分钟')

    def native_text(self):
        scene=self.scene(); model=scene['native_model']; _,air=self.result()
        air=air.replace('|1|1|6|0','|1|1|6|1')
        lines=[air,f'GTXMODEL|{model["input_digest"]}']
        for identity,entry in scene['entities'].items():
            hit=entry['name']==self.order['target']
            lines.append(f'GTXEFFECT|{identity}|'+('94|6|0|3|1|12|14|9400|12|2|2|0|1' if hit else '100|0|0|4|0|12|14|10000|12|2|2|0|1'))
            lines.append(f'GTXATTRIBUTION|{identity}|0|'+('6|1' if hit else '0|0'))
        lines+=['GTXMISSION|1|0|100|100|0|300|294|0|1|0|0|0','GTXDEPOT|0|114','GTXDEPOT|1|114']
        return scene,'\n'.join(lines)

    def test_actual_air_effects_are_distinct_from_ground_gun_geometry(self):
        scene,text=self.native_text()
        after=afsim_rules.decode(text,scene['native_model'],scene,self.world)
        missions.validate(after);fire_control.enforce(after,self.world)
        effect=after['blue_units'][0]['last_combat_effects']
        self.assertEqual(effect['air_casualties'],6)
        self.assertEqual(effect['ground_casualties'],0)
        self.assertEqual(effect['air_equipment_destroyed'],1)
        recent=after['air_operations']['recent_missions'][0]
        self.assertEqual(recent['turn'],1)
        self.assertEqual(recent['target_turn_effects']['air_casualties'],6)

    def test_missing_or_unbalanced_native_attribution_is_rejected(self):
        scene,text=self.native_text()
        for broken in ('\n'.join(l for l in text.splitlines() if not l.startswith('GTXATTRIBUTION')),
                       text.replace('|0|6|1','|0|5|1')):
            with self.assertRaises(ValueError):afsim_rules.parse(broken,scene['native_model'],scene)


class ExplicitAirTests(unittest.TestCase):
    def setUp(self):
        from verify_air_assets import definition
        from gentactix import air_assets, combined_arms
        spec=combined_arms.demo_definition();spec['id']='QA-explicit-air'
        self.definition=definition()
        center=spec['map_center']
        for pool in self.definition['pools'].values():pool['entry']=copy.deepcopy(center)
        self.definition['pools']['qa.blue.air1']['rules']['package']=1
        self.definition['pools']['qa.blue.air1']['rules']['fuel_per_aircraft']=3
        spec['air_definition']=self.definition
        original=missions.definition
        registry=patch.object(missions,'definition',side_effect=lambda i:copy.deepcopy(spec) if i==spec['id'] else original(i))
        registry.start();self.addCleanup(registry.stop)
        self.world=missions.from_definition(spec)
        self.world['air_operations']=air_assets.initial(self.definition)
        self.red=self.world['red_units'][0]['name'];self.blue=self.world['blue_units'][0]['name']

    def orders(self):
        return [{'unit':self.red,'action':'air_support','target':self.blue,'air_pool':'qa.red.air2'},
                {'unit':self.blue,'action':'air_support','target':self.red,'air_pool':'qa.blue.air1'}]

    def model(self):
        return afsim_world.compile_scene(self.world,self.orders(),1800,native_rules=True)['native_model']['air']

    def test_both_factions_use_explicit_pools_and_per_pool_flight_rules(self):
        model=self.model();tasks=model['tasks']
        self.assertEqual([t['pool_id'] for t in tasks],['qa.red.air2','qa.blue.air1'])
        self.assertEqual([t['package'] for t in tasks],[2,1])
        self.assertIn('GTXAIRPOOL|qa.red.air1|',model['script'])
        self.assertIn('GTXAIRPOOL|qa.blue.air1|',model['script'])
        self.assertEqual(afsim_air.state(self.world)['assets']['red']['ready'],10)

    def test_ambiguous_or_enemy_pool_and_non_air_order_pool_are_rejected(self):
        for order in ({k:v for k,v in self.orders()[0].items() if k!='air_pool'},
                      {**self.orders()[0],'air_pool':'qa.blue.air1'},
                      {'unit':self.red,'action':'hold','air_pool':'qa.red.air1'}):
            with self.subTest(order=order),self.assertRaises(ValueError):
                afsim_world.compile_scene(self.world,[order],1800,native_rules=True)

    def test_reservations_do_not_borrow_from_other_pool_and_never_mutate_state(self):
        before=copy.deepcopy(self.world)
        afsim_air.validate_reservations(self.world,self.orders())
        with self.assertRaises(ValueError):
            afsim_air.validate_reservations(self.world,[self.orders()[0]]*4)
        self.assertEqual(self.world,before)

    def test_native_decode_conserves_each_pool_and_rejects_cross_pool_telemetry(self):
        from gentactix import air_assets
        model=self.model();lines=[]
        for task in model['tasks']:
            for i,phase in enumerate(('launch','air_defense','strike','returned')):
                point=task['entry'] if phase in ('launch','returned') else task['aim'];a,b=int(point['lat']),int(point['lng'])
                lines.append(f'GTXAIREVENT|{task["id"]}|{phase}|{60000+i*20000}|{a}|{int((point["lat"]-a)*1e8)}|{b}|{int((point["lng"]-b)*1e8)}')
            lines.append(f'GTXAIRRESULT|{task["id"]}|1|1|0|0')
        lines+=['GTXAIRPOOL|qa.red.air1|4|0|0|12|24','GTXAIRPOOL|qa.red.air2|5|1|2|10|20',
                'GTXAIRPOOL|qa.blue.air1|1|1|1|11|21']
        text='\n'.join(lines);after=afsim_air.decode(text,model,1800)
        air_assets.validate_state(self.definition,after)
        self.assertEqual(after['assets']['red']['ready'],9)
        self.assertEqual(after['pools']['qa.red.air1']['fuel'],24)
        self.assertEqual(after['pools']['qa.blue.air1']['fuel'],21)
        for bad in (text.replace('qa.red.air1|4|0|0|12|24','qa.red.air1|3|1|0|12|24'),
                    text.replace('qa.blue.air1|1|1|1|11|21','blue|1|1|1|11|21'),
                    text.replace('|1|1|0|0','|2|1|0|0')):
            with self.assertRaises(ValueError):afsim_air.decode(bad,model,1800)

    def test_manual_queue_retains_pool_and_exposes_available_pool_choices(self):
        session={'war_state':self.world,'time_step':'30分钟','turn_count':0,'simulation_mode':'open',
                 'execution_backend':'afsim','id':'explicit-air'}
        view=commands.view(session);red=next(u for u in view['units'] if u['name']==self.red)
        blue=next(u for u in view['units'] if u['name']==self.blue)
        self.assertEqual([p['id'] for p in red['capabilities']['air_pools']],['qa.red.air1','qa.red.air2'])
        draft={'unit_id':red['id'],'action':'air_support','target_id':blue['id'],'air_pool':'qa.red.air2','duration':'next'}
        cs=commands.replace_queue(session,[draft],control_team='red',director=False,no_fire=False,intent='')
        self.assertEqual(commands.step_order(session,cs['orders'][0],cs)['air_pool'],'qa.red.air2')
        session['command_state']=cs
        changed=commands.replace_queue(session,[{**draft,'id':cs['orders'][0]['id'],'air_pool':'qa.red.air1'}],
            control_team='red',director=False,no_fire=False,intent='')
        self.assertEqual(changed['orders'][0]['air_pool'],'qa.red.air1')
        self.assertNotEqual(changed['orders'][0]['id'],cs['orders'][0]['id'])


if __name__=='__main__': unittest.main()
