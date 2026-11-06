"""DSH proposals must account for gross transfers and known action costs."""
import copy
import unittest
from unittest.mock import patch

from gentactix import historical_operations, missions
from tools.qa.historical_operational_fixture import inputs


def model_result(before,action='hold',delivery=0,*,seconds=None):
    """Explicit QA estimate; not a product executor or inferred model receipt."""
    from gentactix import sim_clock
    seconds=sim_clock.duration_seconds(before['mission']['definition']['time_step']) if seconds is None else seconds
    rows=[];ledger=[];orders=[];nodes=copy.deepcopy(before['supply_nodes'])
    split=before['mission']['definition'].get('supply_distribution')
    for _,u in missions.units(before):
        alive=u['personnel']['current']>0
        amount=delivery if alive else 0
        food=min(4 if action=='move' else 2,u['logistics']['food']+amount) if alive else 0
        rows.append({'unit':u['name'],'logistics':{'food':u['logistics']['food']+amount-food,'ammo':u['logistics']['ammo']+amount},
            'formation':{'intel_age_min':u['formation']['intel_age_min']+seconds/60}})
        ledger.append({'unit':u['name'],'delivery':amount,'food_spent':food,'ammo_spent':0,
            'supply_status':'未切断' if amount else '已切断','received':{},'spent':{}})
        if split:ledger[-1].update(food_received=amount,ammo_received=amount)
        if alive:orders.append({'unit':u['name'],'action':action})
        node=next(n for n in nodes if n['id']==u['supply_node_id']);node['stock']-=amount
        if split:
            for key in ('food','ammo'):node['commodities'][key]-=amount
    return {'unit_updates':rows,'orders':orders,'supply_nodes':nodes,
        'resource_ledger':{'version':'dsh-resource-ledger-2' if split else 'dsh-resource-ledger-1','units':ledger}}


class DSHResourceTests(unittest.TestCase):
    def setUp(self):self.before=historical_operations.initial(*inputs())

    def apply(self,result,before=None):
        from backend import dsh_simulation as d
        with patch.object(missions,'advance',side_effect=AssertionError('No Python executor')):
            return d.apply(before or self.before,result,'30分钟')

    def test_missing_ledger_rejects_the_actual_unchanged_food_failure(self):
        value={'unit_updates':[{'unit':u['name']} for _,u in missions.units(self.before)],
            'orders':[{'unit':u['name'],'action':'hold'} for _,u in missions.units(self.before)]}
        with self.assertRaisesRegex(ValueError,'收支'):self.apply(value)

    def test_model_food_consumption_is_preserved_without_mutating_inputs(self):
        value=model_result(self.before);snapshot=copy.deepcopy(value);prior=copy.deepcopy(self.before)
        after=self.apply(value)
        self.assertEqual(after['red_units'][0]['logistics']['food'],self.before['red_units'][0]['logistics']['food']-2)
        self.assertEqual(value,snapshot);self.assertEqual(self.before,prior)
        self.assertEqual(after['mission']['ledger'][0]['food_spent'],2)
        self.assertEqual(after['dsh_execution']['resource_ledger_version'],'dsh-resource-ledger-1')
        self.assertNotIn('afsim',after)

    def test_food_kept_unchanged_is_rejected_even_with_a_claimed_ledger(self):
        value=model_result(self.before)
        value['unit_updates'][0]['logistics']['food']=self.before['red_units'][0]['logistics']['food']
        with self.assertRaisesRegex(ValueError,'收支'):self.apply(value)
        value['resource_ledger']['units'][0]['food_spent']=0
        with self.assertRaisesRegex(ValueError,'粮食消耗'):self.apply(value)

    def test_gross_delivery_remains_known_when_consumption_hides_net_increase(self):
        value=model_result(self.before,delivery=2);after=self.apply(value)
        row=after['mission']['ledger'][0]
        self.assertEqual(row['delivery'],2);self.assertEqual(row['food_spent'],2)
        self.assertEqual(after['red_units'][0]['logistics']['food'],self.before['red_units'][0]['logistics']['food'])
        self.assertEqual(after['supply_nodes'][0]['stock'],value['supply_nodes'][0]['stock'])
        self.assertEqual(row['source'],'dsh_model_estimate')

    def test_depot_cannot_refill_or_fund_multiple_units_twice(self):
        value=model_result(self.before,delivery=2);value['supply_nodes']=copy.deepcopy(self.before['supply_nodes'])
        with self.assertRaisesRegex(ValueError,'仓库.*守恒'):self.apply(value)
        value=model_result(self.before);value['supply_nodes'][0]['stock']+=1
        with self.assertRaisesRegex(ValueError,'仓库.*守恒'):self.apply(value)

    def test_duplicate_missing_unknown_and_invalid_ledger_versions_are_rejected(self):
        for kind in ('duplicate','missing','unknown','version','extra'):
            value=model_result(self.before);ledger=value['resource_ledger']
            if kind=='duplicate':ledger['units'][1]=copy.deepcopy(ledger['units'][0])
            elif kind=='missing':ledger['units'].pop()
            elif kind=='unknown':ledger['units'][0]['unit']='unknown'
            elif kind=='version':ledger['version']='future'
            else:ledger['units'][0]['native_receipt']=True
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'收支'):self.apply(value)

    def test_boolean_negative_nonfinite_and_string_quantities_are_rejected(self):
        for amount in (True,-1,float('nan'),float('inf'),'2'):
            value=model_result(self.before);value['resource_ledger']['units'][0]['delivery']=amount
            with self.subTest(amount=amount),self.assertRaisesRegex(ValueError,'收支'):self.apply(value)

    def test_cut_unknown_or_excessive_delivery_is_not_a_supply_receipt(self):
        for status,amount in (('已切断',2),('未知',2),('未切断',3)):
            value=model_result(self.before,delivery=amount);value['resource_ledger']['units'][0]['supply_status']=status
            with self.subTest(status=status,amount=amount),self.assertRaisesRegex(ValueError,'到货'):self.apply(value)

    def test_ammunition_spent_and_received_are_independent_and_balance(self):
        value=model_result(self.before,delivery=2);value['resource_ledger']['units'][0]['ammo_spent']=7
        value['unit_updates'][0]['logistics']['ammo']-=7
        after=self.apply(value);self.assertEqual(after['mission']['ledger'][0]['ammo_spent'],7)
        value['unit_updates'][0]['logistics']['ammo']+=1
        with self.assertRaisesRegex(ValueError,'收支'):self.apply(value)

    def test_late_delivery_cannot_fund_more_firing_than_starting_ammunition(self):
        before=copy.deepcopy(self.before);before['red_units'][0]['logistics']['ammo']=1
        value=model_result(before,delivery=2);value['resource_ledger']['units'][0]['ammo_spent']=3
        value['unit_updates'][0]['logistics']['ammo']=0
        with self.assertRaisesRegex(ValueError,'轮初.*弹药'):self.apply(value,before)

    def test_no_food_means_zero_spent_without_inventing_casualties(self):
        before=copy.deepcopy(self.before);before['red_units'][0]['logistics']['food']=0
        after=self.apply(model_result(before),before)
        self.assertEqual(after['mission']['ledger'][0]['food_spent'],0)
        self.assertEqual(after['red_units'][0]['personnel'],before['red_units'][0]['personnel'])

    def test_move_uses_existing_four_work_unit_demand(self):
        value=model_result(self.before,'move')
        for row,u in zip(value['orders'],[u for _,u in missions.units(self.before)]):row.update(lat=u['lat'],lng=u['lng'])
        after=self.apply(value);self.assertEqual(after['mission']['ledger'][0]['food_spent'],4)
        value['resource_ledger']['units'][0]['food_spent']=2
        value['unit_updates'][0]['logistics']['food']+=2
        with self.assertRaisesRegex(ValueError,'粮食消耗'):self.apply(value)

    def test_classified_received_stocks_require_a_matching_team_depot_draw(self):
        value=model_result(self.before,delivery=2);value['unit_updates'][0]['formation'].update(shells=self.before['red_units'][0]['formation']['shells']+10)
        value['resource_ledger']['units'][0]['received']={'shells':10}
        with self.assertRaisesRegex(ValueError,'分类仓库.*守恒'):self.apply(value)
        value['combined_arms']={'depots':copy.deepcopy(self.before['combined_arms']['depots'])}
        value['combined_arms']['depots']['red']['shells']-=10
        after=self.apply(value);self.assertEqual(after['mission']['ledger'][0]['received']['shells'],10)
        self.assertNotIn('received_shells',after['red_units'][0]['formation'].get('last_execution',{}))

    def test_classified_ammunition_cannot_use_late_deliveries(self):
        value=model_result(self.before,delivery=2);old=self.before['red_units'][0]['formation']['shells']
        value['resource_ledger']['units'][0].update(received={'shells':10},spent={'shells':old+5})
        value['unit_updates'][0]['formation'].update(shells=5)
        value['combined_arms']={'depots':copy.deepcopy(self.before['combined_arms']['depots'])}
        value['combined_arms']['depots']['red']['shells']-=10
        with self.assertRaisesRegex(ValueError,'轮初.*shells'):self.apply(value)

    def test_motorized_displacement_requires_declared_fuel_consumption(self):
        snapshot,params=inputs();selected=historical_operations.partition(snapshot)
        identity=next(u['id'] for u in snapshot['definition']['units'] if u['id'] in selected and u['team']=='blue')
        params['actors'][identity]['formation'].update(motorized=True,fuel_liters=2000)
        params['actors'][identity]['equipment']['transport']=4
        before=historical_operations.initial(snapshot,params);unit=next(u for _,u in missions.units(before) if u['historical_unit_id']==identity)
        value=model_result(before);order=next(r for r in value['orders'] if r['unit']==unit['name'])
        order.update(action='move',lat=unit['lat']+.0005,lng=unit['lng'])
        row=next(r for r in value['unit_updates'] if r['unit']==unit['name']);row.update(lat=order['lat'],lng=order['lng'])
        row['logistics']['food']-=2;ledger=next(r for r in value['resource_ledger']['units'] if r['unit']==unit['name']);ledger['food_spent']=4
        with self.assertRaisesRegex(ValueError,'燃油消耗'):self.apply(value,before)
        ledger['spent']={'fuel_liters':1};row['formation'].update(fuel_liters=unit['formation']['fuel_liters']-1)
        self.apply(value,before)

    def test_model_cannot_forge_a_native_execution_receipt(self):
        value=model_result(self.before)
        value['unit_updates'][0]['formation']={'last_execution':{'turn':1,'action':'hold','received_shells':999}}
        with self.assertRaisesRegex(ValueError,'原生'):self.apply(value)

    def test_insufficient_food_spends_only_available_stock_across_turns(self):
        before=copy.deepcopy(self.before);before['red_units'][0]['logistics']['food']=3
        first=self.apply(model_result(before),before)
        self.assertEqual(first['red_units'][0]['logistics']['food'],1)
        second=self.apply(model_result(first),first)
        self.assertEqual(second['mission']['ledger'][0]['food_spent'],1)
        self.assertEqual(second['red_units'][0]['logistics']['food'],0)
        self.assertEqual(second['red_units'][0]['personnel'],before['red_units'][0]['personnel'])

    def test_existing_feedback_retry_corrects_an_omitted_ledger(self):
        from backend import dsh_simulation as d
        good=model_result(self.before);bad=copy.deepcopy(good);bad.pop('resource_ledger')
        original=copy.deepcopy(self.before)
        with patch.object(d.h,'get_ai_response',side_effect=[bad,good]) as model:
            result,_,_=d.advance({'war_state':self.before,'time_step':'30分钟'},None,None)
        self.assertEqual(model.call_count,2);self.assertIn('收支',model.call_args.args[0])
        self.assertEqual(result['updated_state']['mission']['ledger'][0]['food_spent'],2)
        self.assertEqual(self.before,original)

    def test_two_invalid_candidates_stop_without_repairing_the_world(self):
        from backend import dsh_simulation as d
        bad=model_result(self.before);bad['unit_updates'][0]['logistics']['food']+=2
        original=copy.deepcopy(self.before)
        with patch.object(d.h,'get_ai_response',side_effect=[bad,bad]) as model:
            with self.assertRaisesRegex(ValueError,'重试后仍失败'):
                d.advance({'war_state':self.before,'time_step':'30分钟'},None,None)
        self.assertEqual(model.call_count,2);self.assertEqual(self.before,original)

    def test_resource_retry_reports_both_stock_values_without_repairing_candidate(self):
        from backend import dsh_simulation as d
        good=model_result(self.before);bad=copy.deepcopy(good)
        old=self.before['red_units'][0]['formation']['fuel_liters']
        bad['resource_ledger']['units'][0]['spent']={'fuel_liters':1}
        prior=copy.deepcopy(self.before);candidate=copy.deepcopy(bad)
        with patch.object(d.h,'get_ai_response',side_effect=[bad,good]) as model:
            result,_,_=d.advance({'war_state':self.before,'time_step':'30分钟'},None,None)
        feedback=model.call_args.args[0]
        self.assertIn('期末='+str(old),feedback)
        self.assertIn('应为='+str(old-1),feedback)
        self.assertEqual(result['updated_state']['red_units'][0]['formation']['fuel_liters'],old)
        self.assertEqual(self.before,prior);self.assertEqual(bad,candidate)

    def test_prompt_does_not_treat_every_moving_infantry_unit_as_motorized(self):
        from backend import dsh_simulation as d
        text=d.prompt(self.before)
        self.assertIn('本单位formation.motorized',text)
        self.assertIn('徒步单位不因move自动耗油',text)

    def test_classified_depot_refill_is_not_an_estimated_receipt(self):
        value=model_result(self.before)
        value['combined_arms']={'depots':copy.deepcopy(self.before['combined_arms']['depots'])}
        value['combined_arms']['depots']['blue']['fuel_liters']+=1
        with self.assertRaisesRegex(ValueError,'分类仓库.*守恒'):self.apply(value)

    def test_prompt_requires_explicit_receipts_and_shares_native_food_demand(self):
        from backend import dsh_simulation as d
        from gentactix import resource_accounts
        text=d.prompt(self.before)
        self.assertIn('resource_ledger',text);self.assertIn('dsh-resource-ledger-1',text)
        self.assertIn('food_spent',text);self.assertIn('delivery',text)
        self.assertEqual(resource_accounts.food_demand('move'),4);self.assertEqual(resource_accounts.food_demand('hold'),2)

    def test_connectivity_feedback_lists_the_exact_enum_values(self):
        value=model_result(self.before);value['resource_ledger']['units'][0]['supply_status']='无到货'
        with self.assertRaises(ValueError) as caught:self.apply(value)
        for status in ('未切断','已切断','未知'):self.assertIn(status,str(caught.exception))

    def test_prompt_distinguishes_status_enum_from_estimate_provenance(self):
        from backend import dsh_simulation
        text=dsh_simulation.prompt(self.before)
        self.assertIn('supply_status只能填未切断、已切断、未知',text)


if __name__=='__main__':unittest.main()
