"""Typed Native fortification facets: keep full pairs, reject partial receipts."""
import copy
import unittest

from backend import afsim_campaign
from gentactix import campaign


def fixture():
    row=dict(active=True,base_protection=.15,base_entrenchment=10,fortification_integrity=20,captured_this_turn=0,
        fortification_components=[dict(base_entrenchment=10.,fortification_integrity=100.),
                                 dict(base_entrenchment=30.,fortification_integrity=20.)])
    model=dict(campaign_fortification_revision=1,before_campaign={'actors':{'sample':row}})
    scene={'entities':{'A':{'name':'sample'}}}
    text=('GTXCAMPAIGN|A|1|20000000|0|10.000000000000\n'
          'GTXCAMPAIGNCOMP|A|0|10.000000000000|100000000\n'
          'GTXCAMPAIGNCOMP|A|1|30.000000000000|20000000\n'
          'GTXCAMPAIGNGOAL|0|0|1\n')
    return model,scene,text


class FortificationFacetTests(unittest.TestCase):
    def test_complete_receipt_keeps_each_latent_pair_without_mutating_the_input(self):
        model,scene,text=fixture();before=copy.deepcopy(model)
        row=afsim_campaign.parse(text,model,scene)['actors']['A']
        self.assertEqual(row['fortification_components'],model['before_campaign']['actors']['sample']['fortification_components'])
        self.assertEqual(row['base_entrenchment'],10)
        self.assertEqual(row['fortification_integrity'],20)
        self.assertEqual(model,before)

    def test_legacy_integer_receipt_is_unchanged(self):
        text='GTXCAMPAIGN|A|1|20000000|0|10\nGTXCAMPAIGNGOAL|0|0|1\n'
        self.assertEqual(afsim_campaign.parse(text,{}, {'entities':{'A':{'name':'sample'}}})['actors']['A'],
            dict(active=True,fortification_integrity=20.,captured_this_turn=0,base_entrenchment=10))

    def test_missing_duplicate_or_unknown_component_is_rejected(self):
        model,scene,text=fixture();line='GTXCAMPAIGNCOMP|A|1|30.000000000000|20000000\n'
        for bad in (text.replace(line,''),text+line,text.replace('|A|1|30.','|A|2|30.'),text.replace('GTXCAMPAIGNCOMP|A|0','GTXCAMPAIGNCOMP|B|0')):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):afsim_campaign.parse(bad,model,scene)

    def test_declared_component_contract_cannot_be_missing_or_downgraded(self):
        model,scene,text=fixture()
        for revision in (None,0,2):
            bad=copy.deepcopy(model)
            if revision is None:bad.pop('campaign_fortification_revision')
            else:bad['campaign_fortification_revision']=revision
            with self.subTest(revision=revision):
                with self.assertRaises(ValueError):afsim_campaign.parse(text,bad,scene)

    def test_forged_summary_or_nonfinite_and_out_of_range_fields_are_rejected(self):
        model,scene,text=fixture()
        for old,new in (('20000000|0|10.','19000000|0|10.'),('0|10.000000000000','0|9.000000000000'),
                        ('|30.000000000000|','|nan|'),('|30.000000000000|','|inf|'),
                        ('|30.000000000000|','|100.1|'),('|100000000\n','|100000001\n')):
            with self.subTest(old=old,new=new):
                with self.assertRaises(ValueError):afsim_campaign.parse(text.replace(old,new,1),model,scene)

    def test_envelope_deduplicates_and_removes_only_jointly_dominated_facets(self):
        rows=[dict(base_entrenchment=b,fortification_integrity=i) for b,i in ((10,100),(30,20),(30,20),(40,30),(20,100))]
        saved=copy.deepcopy(rows);parts=campaign.fortification_envelope(rows)
        self.assertEqual(parts,[dict(base_entrenchment=10.,fortification_integrity=100.),dict(base_entrenchment=30.,fortification_integrity=20.)])
        for gain in (0,20,40,100):
            for erosion in (0,10,20,50,100):
                effect=lambda r:min(100,r['base_entrenchment']+gain)*(.25+.75*max(0,r['fortification_integrity']-erosion)/100)
                self.assertEqual(min(map(effect,rows)),min(map(effect,parts)))
        self.assertEqual(rows,saved)

    def test_unexpected_components_on_a_legacy_actor_are_rejected(self):
        _,scene,text=fixture();text=text.replace('10.000000000000\n','10\n',1)
        with self.assertRaises(ValueError):afsim_campaign.parse(text,{},scene)


if __name__=='__main__':unittest.main()
