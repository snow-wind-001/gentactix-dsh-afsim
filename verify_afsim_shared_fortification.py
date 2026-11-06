"""Shared Native segment boundary; not whole-world runtime admission."""
import copy
import unittest

from backend import afsim_shared_fortification as native
from verify_shared_fortification import control,changed_state,receipt


def output(model,row):
    values={**{k:v for k,v in row.items()if k!='after'},**row['after'],
            'current':model['controls'][0]['current']}
    fields='|'.join(str(values[key])for key in native.FIELDS)
    return 'GTXSFW|'+row['entity_id']+'|'+fields+'\nGTXSFWMETA|'+model['binding_digest']+'\n'


class SharedNativeTests(unittest.TestCase):
    def test_component_binds_original_materials_and_live_strength(self):
        bound=native.compile_component([control()],3600000)
        self.assertNotIn('gfw_materials"',bound['functions'])
        self.assertIn('ca_materials',bound['functions'])
        self.assertIn('ca_live_strength_ratio',bound['functions'])
        self.assertIn('ca_committed','\n'.join(bound['setup_lines']))
        self.assertIn('GTXERROR|shared_work_binding_changed','\n'.join(bound['receipt_lines']))
        self.assertNotIn('SetAuxData("ca_materials"','\n'.join(bound['setup_lines']))

    def test_valid_rows_are_decoded_and_checked_without_mutating_inputs(self):
        c=control();r=receipt(changed_state(base_ticks=30000000))
        bound=native.compile_component([c],3600000);saved=copy.deepcopy((c,bound))
        result=native.parse(output(bound['model'],r),bound['model'])
        self.assertEqual(result[c['entity_id']],r)
        self.assertEqual((c,bound),saved)

    def test_missing_duplicate_unknown_rows_and_native_errors_reject(self):
        c=control();r=receipt(changed_state(base_ticks=30000000))
        model=native.compile_component([c],3600000)['model'];text=output(model,r)
        for invalid in ['',text+text,text.replace(c['entity_id'],'g'+'f'*20),
                        text+'\nGTXERROR|changed_materials',text+'\n***** ERROR: failure']:
            with self.subTest(text=invalid[-55:]),self.assertRaises(ValueError):native.parse(invalid,model)

    def test_mutated_binding_or_forged_material_credit_reject(self):
        c=control();r=receipt(changed_state(base_ticks=30000000))
        model=native.compile_component([c],3600000)['model'];text=output(model,r)
        changed=copy.deepcopy(model);changed['controls'][0]['materials']+=1
        with self.assertRaises(ValueError):native.parse(text,changed)
        bad=copy.deepcopy(r);bad['after']['material_credit_fraction']=1
        with self.assertRaises(ValueError):native.parse(output(model,bad),model)

    def test_duplicate_entities_overlapping_roots_and_packet_mismatch_reject(self):
        c=control()
        with self.assertRaises(ValueError):native.compile_component([c,c],1)
        other=copy.deepcopy(c);other['entity_id']='g'+'2'*20
        with self.assertRaises(ValueError):native.compile_component([c,other],1)
        c['state'].update(committed=3000);c['current']=3000
        other=copy.deepcopy(c);other['entity_id']='g'+'2'*20
        native.compile_component([c,other],1)
        other['configuration']['material_work_units_per_packet']+=1
        with self.assertRaises(ValueError):native.compile_component([c,other],1)

    def test_segment_clock_and_legacy_receipt_cannot_be_guessed(self):
        for value in [-1,True,1.5]:
            with self.subTest(value=value),self.assertRaises(ValueError):native.compile_component([control()],value)
        model=native.compile_component([control()],3600000)['model']
        with self.assertRaises(ValueError):native.parse('GTXFTMETA|legacy',model)


if __name__=='__main__':unittest.main(verbosity=2)
