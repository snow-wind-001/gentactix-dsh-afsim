"""Native density receipt consistency, not a stand-in for engine execution."""
import copy
import math
import unittest

from backend import afsim_combined,afsim_world
from gentactix import fire_process,historical_operations as ho,missions
from tools.qa.historical_operational_fixture import inputs,NOTE
from verify_fire_density import CFG


def split_parameters():
    s,p=inputs();p['fire_dynamics']=copy.deepcopy(CFG)
    parent=p['actors']['ww2.jp.seya_detachment'];resources=('fuel_liters','spares','materials','shells','aa_rounds')
    p['partitions']={'version':'formation-partitions-1','groups':{'ww2.jp.seya_detachment':{'assumption':NOTE,
        'parts':[dict(id=name,label=name,personnel=1500,position=copy.deepcopy(parent['position']),
            equipment={k:v//2 for k,v in parent['equipment'].items()},
            resources={k:parent['formation'][k]//2 for k in resources},dispersion_km2=3,assumption=NOTE)for name in ('a','b')]}}}
    return s,p


class DensityReceiptTests(unittest.TestCase):
    def setUp(self):
        self.world=ho.initial(*split_parameters());self.scene=afsim_world.compile_scene(self.world,[],1800,native_rules=True)
        self.model=self.scene['native_model'];self.rows={};self.accounts={}
        by_name={u['name']:u for _,u in missions.units(self.world)}
        factors=fire_process.area_factors(self.world)
        self.parts=[]
        for identity,entry in self.scene['entities'].items():
            u=by_name[entry['name']];a=factors[u['name']]
            committed=round(a['size_factor']*3000);current=round(committed*a['strength_ratio'])
            self.rows[identity]=dict(sample_s=120,lat_cell=fire_process.position_cell(u['lat']),lng_cell=fire_process.position_cell(u['lng']),
                own_current=u['personnel']['current'],eligible=1,footprint_committed=committed,footprint_current=current)
            self.accounts[identity]=dict(current=u['personnel']['current'])
            if u.get('formation_part'):self.parts.append(identity)

    def validate(self):return afsim_combined._validate_density(self.rows,self.model,self.scene,accounts=self.accounts)

    def test_valid_shared_root_sample_is_readonly(self):
        before=copy.deepcopy((self.rows,self.model,self.scene,self.accounts));self.validate()
        self.assertEqual((self.rows,self.model,self.scene,self.accounts),before)

    def test_missing_or_unknown_entity_is_rejected(self):
        for kind in ('missing','extra'):
            self.setUp()
            if kind=='missing':self.rows.pop(next(iter(self.rows)))
            else:self.rows['invented']=copy.deepcopy(next(iter(self.rows.values())))
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'密度'):self.validate()

    def test_an_active_unit_cannot_hide_its_people_as_ineligible(self):
        for identity in self.parts:self.rows[identity].update(eligible=0,footprint_current=0)
        with self.assertRaisesRegex(ValueError,'密度'):self.validate()

    def test_sample_cannot_claim_fewer_living_people_than_the_settled_world(self):
        for identity in self.parts:self.rows[identity].update(own_current=0,footprint_current=0)
        with self.assertRaisesRegex(ValueError,'密度'):self.validate()

    def test_samples_from_different_ticks_are_not_one_footprint(self):
        self.rows[self.parts[0]]['sample_s']=130
        with self.assertRaisesRegex(ValueError,'同一采样'):self.validate()

    def test_nonfinite_outside_or_fractional_counts_fail(self):
        for field,value in (('sample_s',math.nan),('sample_s',1801),('own_current',1.5),('own_current',True),('lat_cell',90000001),('footprint_current',-1)):
            self.setUp();self.rows[self.parts[0]][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.validate()

    def test_shared_population_is_neither_duplicated_nor_dropped(self):
        for value in (1500,3001):
            self.setUp()
            for identity in self.parts:self.rows[identity]['footprint_current']=value
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'不守恒'):self.validate()

    def test_native_moving_parts_must_use_their_current_cells(self):
        self.rows[self.parts[0]]['lat_cell']+=100
        with self.assertRaisesRegex(ValueError,'不守恒'):self.validate()
        for identity in self.parts:
            self.rows[identity].update(footprint_committed=1500,footprint_current=1500)
        self.validate()

    def test_no_root_binding_or_no_final_account_is_not_an_admission(self):
        self.model.pop('density_roots')
        with self.assertRaisesRegex(ValueError,'密度'):self.validate()
        self.setUp();self.accounts.pop(self.parts[0])
        with self.assertRaisesRegex(ValueError,'密度'):self.validate()

    def test_old_model_does_not_accept_new_receipt(self):
        self.model['combat_profile'].pop('fire_dynamics')
        with self.assertRaisesRegex(ValueError,'旧火力'):self.validate()

    def test_coordinate_cells_cover_negative_latitude_and_longitude(self):
        for value in (-89.9999994,-1.0000005,-.0000006,.0000004,179.9999994):
            self.assertEqual(fire_process.position_cell(value),math.floor(value*1e6+.5))


if __name__=='__main__':unittest.main(verbosity=2)
