"""Native-model compiler and telemetry contracts; real engine parity is separate."""
import copy
import json
import unittest
from unittest.mock import patch
from backend import afsim_rules, afsim_world
from gentactix import missions


class NativeModelTests(unittest.TestCase):
    def setUp(self):
        self.before=missions.initial('AJ15-local-v1')
        self.scene=afsim_world.compile_scene(self.before,[],1800,native_rules=True)
        self.model=self.scene['native_model']
        rows=[f"GTXMODEL|{self.model['input_digest']}"]
        for identity in self.scene['entities']:
            rows.append(f'GTXEFFECT|{identity}|100|0|0|4|0|12|14|10000|12|2|2|0|1')
        rows+=['GTXMISSION|1|1|100|85|0|300|300|0|1|1|0|0','GTXDEPOT|0|114','GTXDEPOT|1|114']
        self.text='\n'.join(rows)

    def test_compiler_does_not_execute_legacy_python_rules(self):
        with patch.object(missions,'advance',side_effect=AssertionError('legacy executor called')):
            value=afsim_rules.compile_model(self.scene,self.before,[])
        self.assertIn('GTXEFFECT|',value['script'])
        self.assertIn('GTXMISSION|',value['script'])
        self.assertIn('GtxBlocked',value['script'])

    def test_decode_preserves_integer_counts_and_provenance(self):
        parsed=afsim_rules.parse(self.text,self.model,self.scene)
        after=afsim_rules.apply_telemetry(json.loads(json.dumps(parsed)),self.model,self.scene,self.before)
        missions.validate(after)
        self.assertEqual(after['mission']['organization'],85)
        self.assertEqual(after['red_units'][0]['personnel']['current'],100)
        self.assertIs(type(after['red_units'][0]['personnel']['current']),int)
        self.assertEqual(after['red_units'][0]['personnel']['source'],self.before['red_units'][0]['personnel']['source'])

    def test_missing_rows_do_not_become_zero_quantities(self):
        for text in ('',self.text.replace('GTXDEPOT|1|114',''),self.text.split('\n',2)[0]):
            with self.assertRaises(ValueError):afsim_rules.parse(text,self.model,self.scene)

    def test_wrong_input_or_turn_is_rejected(self):
        for text in (self.text.replace(self.model['input_digest'],'wrong'),self.text.replace('GTXMISSION|1|','GTXMISSION|2|')):
            with self.assertRaises(ValueError):afsim_rules.parse(text,self.model,self.scene)

    def test_invalid_counts_and_duplicate_telemetry_rejected(self):
        sample=self.text.splitlines()[1]
        for text in (self.text.replace('|100|0|0|4|','|100.5|0|0|4|'),self.text+'\n'+sample,
                     self.text.replace('GTXDEPOT|1|114','GTXDEPOT|1|-1')):
            with self.assertRaises(ValueError):afsim_rules.parse(text,self.model,self.scene)

    def test_validation_only_initial_load_does_not_advance_resources(self):
        before=copy.deepcopy(self.before)
        initial=afsim_world.compile_scene(before,[],.001)
        self.assertNotIn('native_model',initial)
        self.assertEqual(before,self.before)

    def test_native_constraint_error_rejects_even_complete_numeric_results(self):
        with self.assertRaises(ValueError):
            afsim_rules.parse(self.text+'\nGTXERROR|move_budget',self.model,self.scene)


if __name__=='__main__':unittest.main()
