"""Resource facts and actionable Native feedback use the current pool state."""
import copy
import json
import unittest

from backend import dsh_simulation
from gentactix import air_assets,air_model_receipts
from tools.qa.fire_effect_fixture import mixed_air_capture


class AviationFeedbackTests(unittest.TestCase):
    def test_wrong_sorties_error_names_pool_field_submitted_and_expected(self):
        w,v,_,_=mixed_air_capture();v['aviation']['pools']['ww2.cacw.group5']['sorties']=8;saved=copy.deepcopy((w,v))
        with self.assertRaises(ValueError) as caught:dsh_simulation.apply(w,v,'30分钟',require_fire_ledger=True)
        for token in ('ww2.cacw.group5','sorties','8','2'):self.assertIn(token,str(caught.exception))
        self.assertEqual((w,v),saved)

    def test_initial_current_resources_are_explicit_without_materializing_or_mutating_world(self):
        w,_,_,_=mixed_air_capture();saved=copy.deepcopy(w);self.assertNotIn('air_operations',w)
        context=air_model_receipts.resource_context(w);row=context['pools']['ww2.cacw.group5']
        self.assertEqual(row['current'],dict(ready=4,destroyed=0,sorties=0,ordnance=8,fuel=16))
        self.assertEqual(row['per_package']['strike'],dict(sorties=2,ordnance=2,fuel=4))
        self.assertIn(json.dumps(context,ensure_ascii=False),air_model_receipts.instruction(w))
        self.assertEqual(w,saved)

    def test_previous_flights_are_current_cumulative_counts_not_initial_defaults(self):
        w,v,_,_=mixed_air_capture();after=dsh_simulation.apply(w,v,'30分钟',require_fire_ledger=True)
        row=air_model_receipts.resource_context(after)['pools']['ww2.cacw.group5']
        self.assertEqual(row['current'],dict(ready=4,destroyed=0,sorties=2,ordnance=6,fuel=12))
        self.assertEqual(row['per_package']['aborted'],dict(sorties=2,ordnance=0,fuel=4))

    def test_multiple_wrong_resource_fields_are_reported_before_generic_inventory_errors(self):
        w,v,_,_=mixed_air_capture();v['aviation']['pools']['ww2.cacw.group5'].update(sorties=8,fuel=80)
        with self.assertRaises(ValueError) as caught:dsh_simulation.apply(w,v,'30分钟',require_fire_ledger=True)
        text=str(caught.exception)
        for token in ('sorties','fuel','80','12'):self.assertIn(token,text)

    def test_edited_package_rules_change_the_quote_instead_of_using_example_constants(self):
        from tools.qa.historical_air_fixture import inputs
        from gentactix import historical_operations as ho
        source,p=inputs();p['aviation']['ww2.cacw.group5']['rules'].update(package=3,fuel_per_aircraft=5)
        context=air_model_receipts.resource_context(ho.initial(source,p))
        self.assertEqual(context['pools']['ww2.cacw.group5']['per_package']['strike'],dict(sorties=3,ordnance=3,fuel=15))


if __name__=='__main__':unittest.main(verbosity=2)
