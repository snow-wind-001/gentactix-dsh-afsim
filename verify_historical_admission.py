"""Blocked defaults expose explicit alternatives without changing historical facts."""
import copy
import unittest
from gentactix import historical_initial
from backend import scenario_builder as builder


def battle(identity):
    return next(r['battle'] for r in historical_initial.catalog() if r['profile_id']==identity)


class HistoricalAdmissionTests(unittest.TestCase):
    def test_jizhong_default_stays_unverified_but_offers_explicit_campaign(self):
        name=battle('AJ15-jizhong');before=historical_initial.definition(name)
        basis=builder.historical_basis(name,termination_mode='objectives')
        self.assertFalse(basis['ready']);self.assertFalse(any(p['ready'] for p in basis['phases']))
        choice=next(c for c in basis['configuration_alternatives'] if c['force_scope']=='campaign')
        self.assertEqual((choice['actor_count'],choice['aviation_count']),(34,1))
        self.assertIn('估计',choice['scope'])
        selected=builder.historical_basis(name,choice['phase_id'],version=choice['version'],force_scope=choice['force_scope'],termination_mode='objectives')
        self.assertTrue(selected['ready']);self.assertIn('availability',selected['configuration_template']['aviation']['ww2.jp.flight29'])
        self.assertEqual(historical_initial.definition(name),before)

    def test_wuhan_legacy_default_is_not_promoted_to_cumulative_same_day_deployment(self):
        name=battle('AJ06-wuhan');before=copy.deepcopy(historical_initial.definition(name))
        basis=builder.historical_basis(name,termination_mode='objectives')
        self.assertFalse(basis['ready']);self.assertEqual(basis['initial']['version'],'1.0.0')
        choice=next(c for c in basis['configuration_alternatives'] if c['version']=='1.1.0' and c['force_scope']=='campaign')
        self.assertEqual(choice['actor_count'],79)
        self.assertEqual(historical_initial.definition(name),before)

    def test_every_suggested_choice_has_a_full_configuration_template(self):
        from gentactix import historical_operations
        for identity in ('AJ06-wuhan','AJ15-jizhong'):
            basis=builder.historical_basis(battle(identity))
            for choice in basis['configuration_alternatives']:
                snapshot=historical_initial.initial(battle(identity),choice['phase_id'],version=choice['version'])['historical_initial']
                template=historical_operations.configuration_template(snapshot,choice['force_scope'])
                self.assertEqual(len(template['actors']),choice['actor_count'])
                self.assertEqual(len(template.get('aviation',{})),choice['aviation_count'])

    def test_ready_request_does_not_automatically_choose_another_scope(self):
        name=battle('AJ15-jizhong')
        value=builder.historical_basis(name,force_scope='campaign')
        self.assertTrue(value['ready']);self.assertEqual(value['configuration_alternatives'],[])
        self.assertEqual(value['force_scope'],'campaign')

    def test_native_unknown_remainder_reports_exact_path_and_remains_atomic(self):
        from backend.scenario_assembly import HistoricalAssembly
        basis=builder.historical_basis(battle('AJ15-jizhong'),force_scope='campaign')
        draft=HistoricalAssembly(basis);before=copy.deepcopy(draft.configuration)
        result=draft._update('globals',{'revision':0,'patch':{'campaign_scope':{'remainders':{'ww2.jp.flight29':{}}}}})
        self.assertFalse(result['updated']);self.assertEqual(result['revision'],0);self.assertEqual(draft.configuration,before)
        issue=result['input_error'];self.assertEqual(issue['code'],'unknown_configuration_field')
        self.assertEqual(issue['path'],['campaign_scope','remainders']);self.assertEqual(issue['unexpected_fields'],['ww2.jp.flight29'])
        self.assertEqual(set(issue['allowed_fields']),set(before['campaign_scope']['remainders']))

    def test_native_object_shape_error_identifies_the_aviation_field(self):
        from backend.scenario_assembly import HistoricalAssembly
        basis=builder.historical_basis(battle('AJ15-jizhong'),force_scope='campaign');draft=HistoricalAssembly(basis)
        result=draft._update('globals',{'revision':0,'patch':{'aviation':{'ww2.jp.flight29':{'availability':'tomorrow'}}}})
        self.assertFalse(result['updated']);issue=result['input_error'];self.assertEqual(issue['code'],'expected_configuration_object')
        self.assertEqual(issue['path'],['aviation','ww2.jp.flight29','availability']);self.assertEqual(issue['expected_type'],'object')

    def test_native_diagnostic_bounds_allowed_keys_without_echoing_values(self):
        from backend.scenario_assembly import _merge_known,ConfigurationPatchError
        base={'root':{str(i):'do-not-echo-this-value' for i in range(100)}}
        with self.assertRaises(ConfigurationPatchError) as caught:_merge_known(base,{'root':{'other':0}})
        issue=caught.exception.input_error
        self.assertEqual(issue['allowed_fields_total'],100);self.assertEqual(len(issue['allowed_fields']),32)
        self.assertNotIn('do-not-echo-this-value',str(issue))


if __name__=='__main__':unittest.main()
