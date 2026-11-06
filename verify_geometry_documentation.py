"""Keep Korean parameter descriptions aligned with current geometry semantics."""
from pathlib import Path
import unittest

from gentactix import adjudicator, adjudication_lib


class GeometryDocumentationTests(unittest.TestCase):
    def test_all_nine_cards_document_the_current_contact_formula(self):
        cards = sorted(Path('adjudication').glob('抗美援朝-*.md'))
        self.assertEqual(len(cards), 9)
        for path in cards:
            with self.subTest(path=path.name):
                body = path.read_text().split('---', 2)[2]
                self.assertIn('`'+adjudicator.ADJUDICATOR_VERSION+'`', body)
                self.assertIn('敌距 ≤ 可机动距离 + contact_km', body)
                self.assertNotIn('未把 `contact_km`', body)

    def test_unmarked_contact_defaults_are_not_presented_as_historical_calibration(self):
        for path in Path('adjudication').glob('抗美援朝-*.md'):
            with self.subTest(path=path.name):
                spec = adjudication_lib.resolve(path.stem)
                self.assertNotIn('contact_km', spec.explicit)
                self.assertEqual(spec.params['contact_km'], adjudicator.DEFAULT_PARAMS['contact_km'])
                self.assertIn('未标定该键，沿用几何默认接触带', path.read_text())

    def test_docs_distinguish_geometric_contact_from_shooting_and_los(self):
        for path in Path('adjudication').glob('抗美援朝-*.md'):
            with self.subTest(path=path.name):
                body = path.read_text().split('---', 2)[2]
                self.assertIn('接触不等于可开火、命中或杀伤', body)
                self.assertIn('不计算地形视线遮挡（LOS）', body)
                self.assertIn('冻结版本', body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
