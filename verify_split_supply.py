"""Independent food/ammo accounts preserve native execution and old saves."""
import copy
import unittest
from gentactix import historical_operations as ho, missions
from tools.qa.historical_operational_fixture import inputs


def config():
    return {'version':'split-stocks-1','food_mass_share':.5,'priority':'food',
            'assumption':'QA transport mass allocation; not a historical ration weight.'}


def world():
    source,params=inputs();params['supply_distribution']=config()
    for actor in params['actors'].values():
        actor['logistics']={'food':0,'ammo':100};actor['ground_control_radius_km']=0
    return ho.initial(source,params)


class SplitSupplyTests(unittest.TestCase):
    def test_new_configuration_template_and_prompt_use_split_contract(self):
        from backend import dsh_simulation
        source,_=inputs();template=ho.configuration_template(source)
        self.assertEqual(template['supply_distribution']['version'],'split-stocks-1')
        message=dsh_simulation.prompt(world())
        self.assertIn('dsh-resource-ledger-2',message)
        self.assertIn('food_received',message)
        self.assertNotIn('每份同时带1粮食和1弹药',message)

    def test_readonly_budget_uses_food_stock_not_mass_equivalent(self):
        from gentactix import sustainment,split_supply
        w=world();node=w['supply_nodes'][0];node['commodities']['food']=1
        node['stock']=split_supply.equivalent(config(),**node['commodities'])
        value=sustainment.assess(w)
        self.assertEqual(value['teams']['red']['warehouse_food'],1)
        self.assertEqual(value['teams']['red']['full_ammo_blocks_food_count'],0)
        self.assertEqual(value['teams']['red']['max_covered_hold_rounds'],.5)

    def test_observation_exposes_mass_conversion_and_report_separates_arrivals(self):
        from backend import afsim_state
        w=world();context=afsim_state.mission_context(w)
        self.assertEqual(context['supply_accounting']['ton_per_supply_unit'],w['mission']['definition']['combined_rules']['ton_per_supply_unit'])
        self.assertFalse(context['supply_accounting']['budget_is_execution_trigger'])
        w['mission']['ledger']=[{'unit':w['red_units'][0]['name'],'delivery':4,'food_received':8,'ammo_received':0}]
        missions.evaluate(w)
        text=missions.report(w)
        self.assertIn('粮食到货8',text);self.assertIn('弹药到货0',text);self.assertIn('运输质量当量4',text)

    def test_synthetic_derivative_preserves_split_stock_configuration(self):
        from gentactix import synthetic_history
        w=world();binding=w['mission']['definition']['historical_calculation']
        seed=synthetic_history.seed(binding);after=missions.from_definition(synthetic_history.definition(binding,seed['configuration']))
        self.assertEqual(after['mission']['definition']['supply_distribution'],config())
        self.assertTrue(all(n['commodities']=={'food':480,'ammo':480} for n in after['supply_nodes']))

    def test_frozen_independent_stock_and_legacy_absence(self):
        w=world();self.assertTrue(missions.validate(w))
        self.assertEqual(w['mission']['definition']['supply_distribution'],config())
        for n in w['supply_nodes']:self.assertEqual(n['commodities'],{'food':480,'ammo':480})
        source,params=inputs();old=ho.initial(source,params)
        self.assertNotIn('supply_distribution',old['mission']['definition'])
        self.assertTrue(all('commodities' not in n for n in old['supply_nodes']))

    def test_bad_stock_or_configuration_is_rejected(self):
        for change in ({'food_mass_share':0},{'food_mass_share':True},{'priority':'invented'},{'assumption':''}):
            source,params=inputs();params['supply_distribution']={**config(),**change}
            with self.assertRaises(ValueError):ho.initial(source,params)
        w=world();w['supply_nodes'][0]['commodities']['food']-=2
        with self.assertRaisesRegex(ValueError,'分类粮弹'):missions.validate(w)

    def test_dsh_food_delivery_is_independent_and_conserved(self):
        from gentactix import resource_accounts
        from verify_dsh_resources import model_result
        from backend import dsh_simulation
        w=world();proposal=model_result(w);proposal['resource_ledger']['version']='dsh-resource-ledger-2'
        nodes={n['id']:n for n in w['supply_nodes']};draws={k:0 for k in nodes}
        for (_,u),update,row in zip(missions.units(w),proposal['unit_updates'],proposal['resource_ledger']['units']):
            row.update(delivery=1,food_received=2,ammo_received=0,food_spent=2,supply_status='未切断')
            update['logistics']={'food':0,'ammo':100}
            draws[u['supply_node_id']]+=2
        proposal['supply_nodes']=[{**copy.deepcopy(n),'stock':n['stock']-draws[n['id']]/2,
            'commodities':{'food':n['commodities']['food']-draws[n['id']],'ammo':n['commodities']['ammo']}} for n in nodes.values()]
        original=copy.deepcopy(w);after=dsh_simulation.apply(w,proposal,'30分钟')
        self.assertEqual(w,original)
        self.assertEqual(after['mission']['ledger'][0]['food_received'],2)
        self.assertEqual(after['dsh_execution']['resource_ledger_version'],'dsh-resource-ledger-2')
        self.assertEqual(after['mission']['ledger'][0]['delivery_basis'],'declared_mass_equivalent_split_stock')
        transport=copy.deepcopy(w)
        for _,u in missions.units(transport):
            for equipment in u['equipment']:
                if equipment['category']=='transport':
                    equipment['destroyed']+=equipment['operational'];equipment['operational']=0
        with self.assertRaisesRegex(ValueError,'运输载重'):
            resource_accounts.validate_transition(transport,after,proposal['resource_ledger'],after['mission']['last_orders'])
        bad=copy.deepcopy(proposal);bad['resource_ledger']['units'][0]['ammo_received']=2
        with self.assertRaises(ValueError):dsh_simulation.apply(w,bad,'30分钟')
        missing=copy.deepcopy(proposal);missing['resource_ledger']['units'][0].pop('food_received')
        with self.assertRaises(ValueError):dsh_simulation.apply(w,missing,'30分钟')


if __name__=='__main__':unittest.main()
