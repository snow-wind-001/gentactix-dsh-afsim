"""Native effect shape feedback reproduces observed drift without repairing candidates."""
import copy
import json
from pathlib import Path
import subprocess
import unittest

from backend import turn_preview as p
from tools.qa.turn_preview_page_fixture import session,candidate


class EffectContractTests(unittest.TestCase):
    def setUp(self):
        self.s=session();self.value=candidate(self.s['war_state'])
        self.ctx=p.context(self.s,None,operation_id='effect-shape-qa')

    def test_unit_name_alias_and_readonly_team_return_precise_paths_without_repair(self):
        from backend import effect_contract as c
        for alias in ('name','unit_name'):
            value=copy.deepcopy(self.value);row=value['unit_updates'][0];row[alias]=row.pop('unit');row['team']='red'
            saved=copy.deepcopy(value)
            with self.assertRaises(c.ShapeError) as caught:c.validate(value)
            issues=caught.exception.issues
            self.assertIn('/unit_updates/0/unit',{r['path'] for r in issues})
            self.assertIn('/unit_updates/0/'+alias,{r['path'] for r in issues})
            self.assertIn('/unit_updates/0/team',{r['path'] for r in issues})
            self.assertEqual(value,saved)

    def test_each_named_array_checks_selector_before_any_dictionary_indexing(self):
        from backend import effect_contract as c
        for container in ('orders','unit_updates','resource_ledger/units','sustainment_ledger/units'):
            value=copy.deepcopy(self.value);x=value
            for key in container.split('/'):x=x[key]
            x[0]['unit_name']=x[0].pop('unit')
            with self.subTest(container=container),self.assertRaises(c.ShapeError) as caught:c.validate(value)
            self.assertIn('/'+container+'/0/unit',{r['path'] for r in caught.exception.issues})

    def test_native_error_keeps_reference_and_structured_issues(self):
        value=copy.deepcopy(self.value);value['unit_updates'][0]['team']='red';saved=copy.deepcopy((self.ctx,value))
        reply=p.execute(self.ctx,dict(tool=p.TOOL,args=dict(candidate=value)))
        self.assertFalse(reply['ok']);self.assertEqual(len(reply['candidate_ref']),64)
        self.assertEqual(reply['operation_id'],'effect-shape-qa')
        self.assertTrue(any(r['path']=='/unit_updates/0/team' for r in reply['issues']))
        self.assertEqual((self.ctx,value),saved)

    def test_orders_alias_wrong_container_and_number_boolean_are_explicit(self):
        from backend import effect_contract as c
        for kind in ('commands','container','boolean'):
            value=copy.deepcopy(self.value)
            if kind=='commands':value['commands']=value.pop('orders')
            elif kind=='container':value['orders']={}
            else:value['unit_updates'][0]['lat']=True
            with self.subTest(kind=kind),self.assertRaises(c.ShapeError):c.validate(value)

    def test_real_native_serialized_candidate_is_rejected_without_implicit_parsing(self):
        args=dict(candidate=json.dumps(self.value,ensure_ascii=False));saved=copy.deepcopy((args,self.ctx))
        reply=p.execute(self.ctx,dict(tool=p.TOOL,args=args))
        self.assertFalse(reply['ok']);self.assertNotIn('candidate_ref',reply)
        self.assertEqual(reply['issues'][0]['path'],'/candidate')
        self.assertIn('对象',reply['issues'][0]['message'])
        self.assertEqual((args,self.ctx),saved)

    def test_valid22_and_legacy_optional_shapes_are_readonly(self):
        from backend import effect_contract as c
        saved=copy.deepcopy(self.value);c.validate(self.value);self.assertEqual(self.value,saved)
        value=copy.deepcopy(self.value);value['sustainment_ledger']=None
        c.validate(value)  # Shape only: semantic version/presence remains the existing kernel's responsibility.

    def test_native_tool_uses_the_same_shared_contract(self):
        from backend import effect_contract as c
        source=Path('plugins/dsh-gentactix/index.mjs').read_text()
        self.assertIn('effectSchema',source)
        self.assertEqual(c.SCHEMA['properties']['unit_updates']['items']['additionalProperties'],False)
        self.assertIn('unit',c.SCHEMA['properties']['orders']['items']['required'])
        completed=subprocess.run(['node','--input-type=module','-e',
            "import {effectSchema} from './plugins/dsh-gentactix/effect-schema.mjs'; process.stdout.write(JSON.stringify(effectSchema));"],capture_output=True,text=True)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout),c.SCHEMA)


if __name__=='__main__':unittest.main()
