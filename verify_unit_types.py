"""Shared native-builder and renderer unit-type vocabulary regressions."""
import subprocess
import unittest
from pathlib import Path
from gentactix.unit_types import classify_unit


class UnitTypeTests(unittest.TestCase):
    def test_armor_shorthand_and_canonical_ids_are_resolved(self):
        for text in ('装甲', '装甲排', '装甲部队', 'armor', '  ARMOR  ', '坦克装甲兵'):
            with self.subTest(text=text):
                self.assertEqual(classify_unit(text)['id'], 'armor')

    def test_exact_aliases_do_not_capture_specialist_substrings(self):
        for text, expected in (('装甲步兵','mechanized'),('装甲侦察','recon'),('装甲运输','transport'),
                               ('反坦克','anti_tank'),('机枪','machine_gun'),('towed_artillery','towed_artillery')):
            with self.subTest(text=text):
                self.assertEqual(classify_unit(text)['id'], expected)
        self.assertIsNone(classify_unit('未登记的未来兵种'))

    def test_frontend_classifier_and_symbols_use_the_same_aliases(self):
        root=Path(__file__).resolve().parent
        value=subprocess.run(['node','tools/qa/unit_types.mjs'],cwd=root,text=True,capture_output=True,timeout=30)
        self.assertEqual(value.returncode,0,value.stdout+value.stderr)


if __name__=='__main__':unittest.main()
