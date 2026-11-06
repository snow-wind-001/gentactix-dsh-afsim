"""Model-estimated flights must preserve identities, reservations and ledgers."""
import copy,unittest
from backend import dsh_simulation
from gentactix import historical_operations as ho,air_assets,missions
from tools.qa.historical_air_fixture import inputs
from verify_dsh_resources import model_result


def result(world,outcome='strike'):
    value=model_result(world);red=world['red_units'][0];blue=world['blue_units'][0]
    value['orders'][0].update(action='air_support',target=blue['name'],air_pool='ww2.cacw.group5')
    s=air_assets.world_state(world);p=s['pools']['ww2.cacw.group5'];spec=air_assets.world_definition(world)['pools']['ww2.cacw.group5']
    flight={'requester':red['name'],'target':blue['name'],'pool_id':'ww2.cacw.group5','outcome':outcome,
            'aircraft_lost':0,'personnel_effect':0,'equipment_effect':0,'events':[]}
    for phase,seconds in [('launch',60),*(([('air_defense',120),('strike',121)]) if outcome=='strike' else [('abort_target_moved',120)]),('returned',180)]:
        point=spec['entry'] if phase in ('launch','returned') else {k:blue[k] for k in ('lat','lng')}
        flight['events'].append({'phase':phase,'seconds':seconds,**point})
    value['aviation']={'missions':[flight],'pools':{i:{k:p[k] for k in ('ready','destroyed','sorties','ordnance','fuel')} for i,p in s['pools'].items()}}
    value['aviation']['pools']['ww2.cacw.group5'].update(sorties=2,fuel=12,ordnance=6 if outcome=='strike' else 8)
    return value


class DSHAviationTests(unittest.TestCase):
    def setUp(self):self.world=ho.initial(*inputs())
    def apply(self,value):return dsh_simulation.apply(self.world,value,'30分钟')

    def test_model_flight_keeps_its_own_source_and_independent_resources(self):
        proposal=result(self.world);before=copy.deepcopy(self.world);after=self.apply(proposal)
        pool=after['air_operations']['pools']['ww2.cacw.group5']
        self.assertEqual(pool['fuel'],12);self.assertEqual(pool['ordnance'],6)
        self.assertEqual(after['red_units'][0]['logistics']['ammo'],before['red_units'][0]['logistics']['ammo'])
        self.assertEqual(after['air_operations']['missions'][0]['source'],'dsh_model_estimate')
        self.assertNotIn('afsim',after);self.assertEqual(self.world,before)

    def test_missing_flight_and_free_or_negative_pool_changes_reject_entire_turn(self):
        for kind in ('missing','no_fuel','sorties','negative','inventory','unknown_pool','duplicate','boolean','text'):
            v=result(self.world);pool=v['aviation']['pools']['ww2.cacw.group5']
            if kind=='missing':v.pop('aviation')
            if kind=='no_fuel':pool['fuel']=16
            if kind=='sorties':pool['sorties']=0
            if kind=='negative':pool['ready']=-1
            if kind=='inventory':pool['ordnance']=9
            if kind=='unknown_pool':v['aviation']['pools']['invented']=pool.copy()
            if kind=='duplicate':v['aviation']['missions']*=2
            if kind=='boolean':pool['ready']=True
            if kind=='text':pool['fuel']='12'
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.apply(v)

    def test_abort_retains_ordnance_but_consumes_fuel_and_records_return(self):
        after=self.apply(result(self.world,'aborted'))
        self.assertEqual(after['air_operations']['pools']['ww2.cacw.group5']['ordnance'],8)
        self.assertEqual(after['air_operations']['pools']['ww2.cacw.group5']['fuel'],12)

    def test_unordered_wrong_target_or_impossible_route_cannot_create_flight(self):
        for kind in ('no_order','own_target','wrong_pool','fast','missing_return','off_route','lost_all_effect'):
            v=result(self.world);flight=v['aviation']['missions'][0]
            if kind=='no_order':v['orders'][0]={'unit':flight['requester'],'action':'hold'}
            if kind=='own_target':flight['target']=flight['requester']
            if kind=='wrong_pool':flight['pool_id']='invented'
            if kind=='fast':flight['events'][-1]['seconds']=1
            if kind=='missing_return':flight['events'].pop()
            if kind=='off_route':flight['events'][1]['lat']+=1
            if kind=='lost_all_effect':
                flight.update(aircraft_lost=2,personnel_effect=1)
                v['aviation']['pools']['ww2.cacw.group5'].update(ready=2,destroyed=2)
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.apply(v)

    def test_air_personnel_effect_requires_matching_target_loss_and_engagement(self):
        v=result(self.world);v['aviation']['missions'][0]['personnel_effect']=4
        with self.assertRaises(ValueError):self.apply(v)
        blue=self.world['blue_units'][0];red=self.world['red_units'][0]
        row=next(r for r in v['unit_updates'] if r['unit']==blue['name'])
        row['personnel']={'current':blue['personnel']['current']-4,'casualties':4,'killed':1,'wounded':3,
                         'missing':0,'captured':0,'unclassified_casualties':0}
        v['engagements']=[{'attacker':red['name'],'attacker_team':'red','attacker_pos':[red['lat'],red['lng']],
            'target':blue['name'],'lat':blue['lat'],'lng':blue['lng'],'weapon_action':'air_support'}]
        after=self.apply(v);self.assertEqual(after['blue_units'][0]['personnel']['casualties'],4)
        self.assertEqual(after['air_operations']['missions'][0]['target_turn_effects']['air_casualties'],4)

    def test_hold_turn_does_not_retain_previous_turn_as_new_air_mission(self):
        after=self.apply(model_result(self.world));self.assertEqual(after['air_operations']['missions'],[])
        self.assertEqual(after['air_operations']['assets']['red']['fuel'],16)
        flown=self.apply(result(self.world));held=dsh_simulation.apply(flown,model_result(flown),'30分钟')
        self.assertEqual(held['air_operations']['missions'],[])
        self.assertEqual(len(held['air_operations']['recent_missions']),1)
        self.assertEqual(held['air_operations']['assets']['red']['fuel'],12)
        self.assertEqual(held['air_operations']['last_turn'],2)

    def test_real_source_identity_does_not_turn_unknown_aircraft_into_a_historical_number(self):
        from gentactix import synthetic_history
        from backend import scenario_builder
        snapshot,p=inputs();original=copy.deepcopy(snapshot)
        air=next(u for u in snapshot['definition']['units'] if u['role']=='aviation')
        self.assertEqual(air['id'],'ww2.cacw.group5');self.assertTrue(all(f['value'] is None for f in air['facts'].values()))
        basis=scenario_builder.historical_basis(snapshot['definition']['battle'])
        self.assertEqual(len(basis['actors']),2);self.assertEqual(len(basis['aviation']),1)
        self.assertFalse(basis['initial']['definition']['coverage']['strength_complete'])
        binding=self.world['mission']['definition']['historical_calculation'];seed=synthetic_history.seed(binding)
        seed['configuration']['aviation'][air['id']]['initial']['committed']=6
        variant=missions.from_definition(synthetic_history.definition(binding,seed['configuration']))
        self.assertEqual(air_assets.world_state(variant)['assets']['red']['ready'],6)
        self.assertEqual(variant['historical_initial'],original)
        self.assertEqual(air_assets.world_state(self.world)['assets']['red']['ready'],4)

    def test_actual_model_nested_casualties_are_a_repairable_validation_error(self):
        for value in ({'killed':4,'wounded':12},'16',True):
            v=model_result(self.world);v['unit_updates'][1]['personnel']={'casualties':value}
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'casualties.*整数'):
                self.apply(v)

    def test_pending_repairs_do_not_count_as_destroyed_air_equipment(self):
        v=result(self.world);v['aviation']['missions'][0]['equipment_effect']=2
        blue=self.world['blue_units'][0];e=next(e for e in blue['equipment'] if e['category']=='artillery')
        v['unit_updates'][1]['equipment']=[{'category':'artillery','operational':e['operational']-2,'damaged':2,'destroyed':0}]
        v['engagements']=[{'attacker':self.world['red_units'][0]['name'],'attacker_team':'red',
            'lat':blue['lat'],'lng':blue['lng'],'weapon_action':'air_support'}]
        with self.assertRaisesRegex(ValueError,'destroyed.*damaged'):self.apply(v)

    def test_prompt_keeps_current_air_balances_without_copying_old_task_output_fields(self):
        flown=self.apply(result(self.world));before=copy.deepcopy(flown)
        task=flown['air_operations']['missions'][0]
        prompt=dsh_simulation.prompt(flown)
        self.assertFalse(task['id'] in prompt,'已提交航空任务不应成为新回合输出模板')
        self.assertIn('ww2.cacw.group5',prompt)
        self.assertIn('"sorties": 2',prompt)
        self.assertEqual(flown,before)

if __name__=='__main__':unittest.main()
