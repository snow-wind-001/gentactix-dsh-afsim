"""Independent aviation identities and resources; no implicit historical fleet."""
import copy
import unittest
from gentactix import air_assets


def definition():
    def pool(name,team,count=4):
        return {'name':name,'team':team,'historical_unit_id':name,'initial':{'committed':count,'ordnance':12,'fuel':24},
            'entry':{'lat':27.1,'lng':110.5},'rules':copy.deepcopy(air_assets.DEFAULT_RULES),
            'assumption':'QA估计，不是历史实到、飞行性能或效能标定；油弹为工作单位。',
            'evidence':[{'source_id':'QA','locator':'Explicit fixture identity; not a published historical assertion'}]}
    return {'format':air_assets.FORMAT,'pools':{'qa.red.air1':pool('qa.red.air1','red'),
        'qa.red.air2':pool('qa.red.air2','red',6),'qa.blue.air1':pool('qa.blue.air1','blue',2)}}


class AirAssetTests(unittest.TestCase):
    def test_each_pool_keeps_its_own_identity_and_initial_inventory(self):
        d=definition();before=copy.deepcopy(d);s=air_assets.initial(d)
        self.assertEqual(d,before);self.assertEqual(s['pools']['qa.red.air2']['committed'],6)
        self.assertEqual(s['assets']['red']['ready'],10);self.assertEqual(s['assets']['blue']['ready'],2)
        self.assertEqual(s['pools']['qa.blue.air1']['historical_unit_id'],'qa.blue.air1')

    def test_pool_state_validation_checks_own_inventory_and_aggregate_view(self):
        d=definition();s=air_assets.initial(d);air_assets.validate_state(d,s)
        for kind in ('missing_pool','planes','stock','identity','aggregate','hash'):
            bad=copy.deepcopy(s)
            if kind=='missing_pool':bad['pools'].pop('qa.red.air1')
            if kind=='planes':bad['pools']['qa.red.air1']['ready']+=1
            if kind=='stock':bad['pools']['qa.red.air1']['fuel']=25
            if kind=='identity':bad['pools']['qa.red.air1']['team']='blue'
            if kind=='aggregate':bad['assets']['red']['ready']=20
            if kind=='hash':bad['config_hash']='other'
            with self.subTest(kind=kind),self.assertRaises(ValueError):air_assets.validate_state(d,bad)

    def test_faction_and_ambiguity_are_explicit_and_never_choose_another_fleet(self):
        d=definition();s=air_assets.initial(d)
        with self.assertRaises(ValueError):air_assets.select(d,s,'red')
        with self.assertRaises(ValueError):air_assets.select(d,s,'red','qa.blue.air1')
        p,model=air_assets.select(d,s,'blue');self.assertEqual(p,'qa.blue.air1')
        self.assertEqual(model['initial']['committed'],2)
        self.assertEqual(air_assets.select(d,s,'red','qa.red.air2')[0],'qa.red.air2')

    def test_empty_blue_side_stays_zero_without_an_implicit_fleet(self):
        d=definition();d['pools']={k:v for k,v in d['pools'].items() if v['team']=='red'}
        s=air_assets.initial(d);self.assertEqual(s['assets']['blue']['committed'],0)
        with self.assertRaises(ValueError):air_assets.select(d,s,'blue')

    def test_invalid_quantities_entries_rules_and_injection_ids_are_rejected(self):
        for kind in ('bool','nan','package','zero_speed','bad_id','empty_source','empty_assumption'):
            d=definition();p=d['pools']['qa.red.air1']
            if kind=='bool':p['initial']['committed']=True
            if kind=='nan':p['entry']['lat']=float('nan')
            if kind=='package':p['rules']['package']=0
            if kind=='zero_speed':p['rules']['speed_mps']=0
            if kind=='bad_id':d['pools']['x|bad']=d['pools'].pop('qa.red.air1')
            if kind=='empty_source':p['evidence']=[]
            if kind=='empty_assumption':p['assumption']=''
            with self.subTest(kind=kind),self.assertRaises(ValueError):air_assets.initial(d)

    def test_native_losses_do_not_reassign_or_replenish_another_pool(self):
        d=definition();s=air_assets.initial(d);p=s['pools']['qa.red.air2'];p.update(ready=5,destroyed=1,sorties=2,ordnance=10,fuel=20)
        s['assets']=air_assets.aggregate(s['pools']);air_assets.validate_state(d,s)
        self.assertEqual(s['pools']['qa.red.air1']['ready'],4)
        self.assertEqual(s['assets']['red']['ready'],9)

if __name__=='__main__':unittest.main()
