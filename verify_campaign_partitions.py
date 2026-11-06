"""Explicit large formation capacity retains v1 limits and resource conservation."""
import copy
import unittest
from gentactix import historical_operations as ho,formation_parts as fp,missions
from tools.qa.historical_operational_fixture import inputs


class CampaignPartitionTests(unittest.TestCase):
    def setUp(self):
        self.s,self.p=inputs();groups={}
        for identity,parent in self.p['actors'].items():
            count=32;parts=[]
            for n in range(count):
                part=dict(id=f'part{n}',label=f'计算分队{n+1}',
                    personnel=parent['personnel']//count+(n<parent['personnel']%count),
                    position=copy.deepcopy(parent['position']),
                    equipment={k:v if n==0 else 0 for k,v in parent['equipment'].items()},
                    resources={k:parent['formation'][k] if n==0 else 0 for k in fp.RESOURCES},
                    dispersion_km2=.01,assumption='QA互斥分配，未宣称历史下级番号')
                parts.append(part)
            groups[identity]=dict(parts=parts,assumption='QA32个互斥计算分队，原父单位不重复投入')
        self.p['partitions']=dict(version=fp.CAMPAIGN_VERSION,groups=groups)

    def test_96_leaf_accounting_and_version_survive_round_trip(self):
        w=ho.initial(self.s,self.p);missions.validate(w)
        self.assertEqual(len(w['red_units']),32);self.assertEqual(len(w['blue_units']),64)
        self.assertEqual(sum(u['personnel']['committed'] for _,u in missions.units(w)),10800)
        self.assertEqual(w['formation_groups']['version'],fp.CAMPAIGN_VERSION)
        self.assertEqual(ho.from_binding(w['mission']['definition']['historical_calculation']),w['mission']['definition'])
        for group in w['formation_groups']['groups']:
            self.assertEqual(sum(u['formation']['shells'] for _,u in missions.units(w) if u.get('formation_part',{}).get('group_id')==group['id']),120)

    def test_old_capacity_and_overallocation_still_reject(self):
        old=copy.deepcopy(self.p);old['partitions']['version']=fp.VERSION
        with self.assertRaises(ValueError):ho.initial(self.s,old)
        g=next(iter(self.p['partitions']['groups'].values()));g['parts'][0]['personnel']+=1
        with self.assertRaisesRegex(ValueError,'人员'):ho.initial(self.s,self.p)


if __name__=='__main__':unittest.main()
