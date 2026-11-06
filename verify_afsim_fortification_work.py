"""Native construction receipts must be complete, bound, exact and conserved."""
import copy
import unittest

from backend import afsim_fortification_work as native
from gentactix import fortification_work as work
from verify_fortification_work import control, receipt


def wire(model, row=None):
    row=receipt() if row is None else row
    fields={**{k:v for k,v in row.items() if k!='after'},**row['after']}
    return ('GTXFT|'+row['entity_id']+'|'+'|'.join(str(fields[k]) for k in native.FIELDS)
            +'\nGTXFTMETA|'+model['binding_digest']+'|'+str(model['elapsed_ms'])
            +'|'+str(len(model['controls'])))


class NativeFortificationWorkTests(unittest.TestCase):
    def test_existing_afsim_platform_identifier_is_accepted_without_renaming(self):
        from backend import afsim_world
        scene=afsim_world.compile_scene({'red_units':[{'name':'QA施工编组','type':'步兵',
            'lat':29.3,'lng':115.5}],'blue_units':[]},[],900)
        c=control();c['entity_id']=next(iter(scene['entities']))
        self.assertTrue(native.compile_component([c],900000))

    def test_native_receipt_decodes_only_a_complete_checked_result(self):
        component=native.compile_component([control()],900000);model=component['model']
        saved=copy.deepcopy(model);rows=native.parse(wire(model),model)
        self.assertEqual(rows['g00000000000000000001'],receipt())
        self.assertEqual(model,saved)

    def test_runtime_script_error_rejects_even_apparently_valid_balances(self):
        model=native.compile_component([control()],900000)['model']
        with self.assertRaisesRegex(ValueError,'Native.*错误'):
            native.parse('***** ERROR: Script Exception:\n'+wire(model),model)

    def test_bindings_distinguish_equal_duration_but_different_input_stock(self):
        a=native.compile_component([control()],900000)
        other=control();other['state']['materials']-=1
        b=native.compile_component([other],900000)
        self.assertNotEqual(a['model']['binding_digest'],b['model']['binding_digest'])
        with self.assertRaises(ValueError):native.parse(wire(a['model']),b['model'])

    def test_unknown_missing_duplicate_or_wrong_duration_receipts_are_rejected(self):
        model=native.compile_component([control()],900000)['model'];text=wire(model)
        for bad in (text.splitlines()[0],text.splitlines()[1],text+'\n'+text,
                    text.replace('GTXFT|g00000000000000000001','GTXFT|g00000000000000000002'),
                    text.replace('|900000|','|900001|',1)):
            with self.subTest(value=bad),self.assertRaises(ValueError):native.parse(bad,model)

    def test_native_numerical_outputs_cannot_create_resources_or_change_gain(self):
        model=native.compile_component([control()],900000)['model']
        for key in ('materials','material_credit_work','base_ticks','work_added'):
            row=receipt()
            if key in row['after']:row['after'][key]+=1
            else:row[key]+=1
            with self.subTest(key=key),self.assertRaises(ValueError):native.parse(wire(model,row),model)

    def test_mutating_the_input_under_a_copied_digest_is_not_an_authenticated_binding(self):
        model=native.compile_component([control()],900000)['model'];text=wire(model)
        model['controls'][0]['current']=2999
        with self.assertRaises(ValueError):native.parse(text,model)

    def test_compiler_rejects_duplicate_entities_nonintegers_and_precision_overflow(self):
        c=control()
        for args in (([],900000),([c,c],900000),([c],True)):
            with self.subTest(args=args),self.assertRaises(ValueError):native.compile_component(*args)
        c['state'].update(root_committed=10_000_000,committed=10_000_000)
        c['current']=10_000_000
        with self.assertRaisesRegex(ValueError,'整数精度'):
            native.compile_component([c],work.MAX_ELAPSED_MS)

    def test_model_is_detached_from_inputs_and_hooks_require_explicit_binding(self):
        c=control();old=copy.deepcopy(c);result=native.compile_component([c],900000)
        self.assertEqual(c,old);result['model']['controls'][0]['state']['materials']=0
        self.assertEqual(c,old)
        self.assertIn('GtxFortificationWork',result['functions'])
        self.assertTrue(result['setup_lines']);self.assertTrue(result['receipt_lines'])
        self.assertNotIn('script',result)  # No implicitly enabled world executor.

    def test_micro_work_remainders_survive_public_json_native_fields(self):
        c=control();row=receipt(ms=1000,base=10_005_333,credit=59984,added=16)
        row['after'].update(point_remainder=1000,work_remainder=2_400_000)
        model=native.compile_component([c],1000)['model']
        self.assertEqual(native.parse(wire(model,row),model)[c['entity_id']],row)


if __name__=='__main__':unittest.main()
