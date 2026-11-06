"""Frozen public exercise references survive card updates; no live model calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gentactix import combined_arms, missions, scenario_basis

BATTLE = '抗日战争-武汉会战-1938.06至1938.10'
OLD_HASH = 'b35ae4dd6f307e86242057ca7737da0e7a45b884373d3db77d59f0cb7e423300'


class ExerciseBasisVersionTests(unittest.TestCase):
    def test_current_reference_remains_the_default(self):
        current = scenario_basis.basis(BATTLE)
        self.assertEqual(scenario_basis.resolve(BATTLE, current['basis_hash']), current)

    def test_archived_reference_reconstructs_the_frozen_definition(self):
        reference = scenario_basis.resolve(BATTLE, OLD_HASH)
        self.assertEqual(reference['basis_hash'], scenario_basis.digest(
            {k: v for k, v in reference.items() if k != 'basis_hash'}))
        base = next(s for s in combined_arms.catalog() if s['battle'] == BATTLE)
        configuration = combined_arms.configuration(base['id'])
        configuration['historical_basis'] = {'battle': BATTLE, 'basis_hash': OLD_HASH}
        for team in ('red', 'blue'):
            source = next(r for r in reference['units'] if r['team'] == team)
            configuration['teams'][team] = configuration['teams'][team][:1]
            configuration['teams'][team][0].update(name=source['name'], basis_id=source['id'])
        before = copy.deepcopy(configuration)
        expected = combined_arms.configure_definition(base, configuration, reference=reference)
        self.assertEqual(combined_arms.configure(base['id'], configuration), expected)
        world = missions.initial(base['id'], configuration=configuration)
        missions.validate(world)
        self.assertEqual(world['mission']['definition'], expected)
        self.assertEqual(configuration, before)

    def test_archive_cannot_substitute_a_different_battle(self):
        with self.assertRaises(ValueError):
            scenario_basis.resolve('抗日战争-万家岭战役-1938.09下旬至1938.10', OLD_HASH)

    def test_unregistered_or_non_digest_reference_is_rejected(self):
        for digest in ('0' * 64, '../escape', None, 123, OLD_HASH.upper()):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                scenario_basis.resolve(BATTLE, digest)

    def test_modified_archive_is_rejected_without_falling_back(self):
        reference = scenario_basis.resolve(BATTLE, OLD_HASH)
        reference['units'][0]['name'] = '篡改参考'
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / (OLD_HASH + '.json')).write_text(
                json.dumps(reference, ensure_ascii=False), encoding='utf-8')
            with patch.object(scenario_basis, 'ARCHIVE', Path(directory)):
                with self.assertRaises(ValueError):
                    scenario_basis.resolve(BATTLE, OLD_HASH)


if __name__ == '__main__':
    unittest.main()
