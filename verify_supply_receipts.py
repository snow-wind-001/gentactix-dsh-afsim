"""Native classified receipt evidence and bounded resource-delta observations."""
import copy
import json
import unittest

from backend import afsim_combined, afsim_state, afsim_world
from gentactix import historical_operations, missions, combat_effects
from tools.qa.historical_operational_fixture import inputs


class SupplyReceiptTests(unittest.TestCase):
    def data(self):
        w=historical_operations.initial(*inputs());scene=afsim_world.compile_scene(w,[],1800,native_rules=True)
        model=scene['native_model'];rows={};receipts={}
        for identity,e in scene['entities'].items():
            u=next(v for _,v in missions.units(w) if v['name']==e['name'])
            rows[identity]={**u['formation'],'shots':0,'aa_spent':0,'repaired':0}
            receipts[identity]={k:0 for k in ('fuel_liters','spares','materials','shells','aa_rounds')}
        return w,scene,model,rows,receipts,copy.deepcopy(w['combined_arms']['depots'])

    def test_native_compiler_emits_classified_receipts_without_changing_combat_profile(self):
        w,scene,model,*_=self.data()
        self.assertEqual(model['supply_receipt_revision'],1)
        self.assertEqual(model['combat_profile']['version'],combat_effects.reference(w)['version'])
        self.assertEqual(model['script'].count('GTXCSUPPLY|'),3)

    def test_fractional_cargo_cannot_transfer_fractional_discrete_stocks(self):
        w,scene,model,*_=self.data()
        # A fractional food/ammo work amount also occurs for unpartitioned
        # formations. Discrete shells/spares must be rounded BEFORE both ends
        # of the transfer, not independently truncated when emitting telemetry.
        for i in range(len(scene['entities'])):
            self.assertIn(f'Math.Floor(delivery{i}*',model['script'])
        self.assertNotIn('Math.Min(delivery0*12,',model['script'])

    def test_receipts_reconcile_shells_after_firing_and_late_delivery(self):
        _,scene,model,rows,received,pools=self.data();identity=next(iter(rows))
        rows[identity].update(shells=24,shots=120)
        received[identity]['shells']=24;pools['red']['shells']-=24
        events=[{'unit':scene['entities'][identity]['name'],'action':'bombard'}]
        afsim_combined.validate_supply_receipts(received,rows,pools,events,model,scene)
        received[identity]['shells']=23
        with self.assertRaisesRegex(ValueError,'到货.*守恒'):
            afsim_combined.validate_supply_receipts(received,rows,pools,events,model,scene)

    def test_new_receipt_contract_does_not_treat_missing_data_as_zero(self):
        _,scene,model,rows,_,pools=self.data()
        with self.assertRaisesRegex(ValueError,'到货.*缺'):
            afsim_combined.validate_supply_receipts({},rows,pools,[],model,scene)
        legacy=copy.deepcopy(model);legacy.pop('supply_receipt_revision',None)
        afsim_combined.validate_supply_receipts({},rows,pools,[],legacy,scene)
        model['supply_receipt_revision']=2
        with self.assertRaisesRegex(ValueError,'到货.*版本'):
            afsim_combined.validate_supply_receipts({},rows,pools,[],model,scene)

    def test_duplicate_and_negative_native_receipts_are_rejected(self):
        _,scene,model,*_=self.data();identity=next(iter(scene['entities']))
        line=f'GTXCSUPPLY|{identity}|0|0|0|0|0'
        for text in (line+'\n'+line,line.replace('|0|0|0|0|0','|0|0|0|-1|0')):
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,'到货'):
                afsim_combined.parse(text,model,scene)

    def test_compact_changes_keep_resources_without_copying_large_sources(self):
        fields={'formation':{'before':{'shells':120,'source':'PRIVATE-SOURCE'*1000},
                             'after':{'shells':24,'last_execution':{'received_shells':24,'shots':120}}},
                'logistics':{'before':{'ammo':80,'food':80},'after':{'ammo':74,'food':80}}}
        s={'id':'a123456789ab','turn_count':1,'trajectory':[{'turn':1,'changes':[{'name':'炮兵连','team':'red','fields':fields}]}]}
        original=copy.deepcopy(s);row=afsim_state.changes(s)['changes'][0]['change']
        self.assertEqual(row['numeric_deltas']['formation.shells'],{'before':120,'after':24})
        self.assertEqual(row['numeric_deltas']['logistics.ammo'],{'before':80,'after':74})
        text=json.dumps(row,ensure_ascii=False)
        self.assertNotIn('PRIVATE-SOURCE',text);self.assertLess(len(text),2500);self.assertEqual(s,original)

    def test_program_facts_report_observed_receipts_but_do_not_invent_legacy_zeros(self):
        w,*_=self.data();s={'war_state':w,'turn_count':0,'trajectory':[]}
        self.assertNotIn('炮弹到货',afsim_state.analysis_facts(s))
        w['red_units'][0]['formation']['last_execution']={'received_shells':24}
        self.assertIn('炮弹到货24发',afsim_state.analysis_facts(s))


if __name__=='__main__':unittest.main()
