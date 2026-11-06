"""Weapon range agreement across commands, native inputs, observations and maps."""
import copy
import json
import math
from pathlib import Path
import subprocess
import unittest

from gentactix import combined_arms, missions, viz
from backend import afsim_state, afsim_world


class WeaponRangeTests(unittest.TestCase):
    def world(self):
        return missions.initial(combined_arms.demo_definition()['id'])

    def test_all_45_synthetic_defaults_keep_direct_and_indirect_inputs_separate(self):
        count=0
        for spec in combined_arms.catalog():
            for world in (missions.initial(spec['id']),missions.from_definition(combined_arms.configure(spec['id'],combined_arms.configuration(spec['id'])))):
                cfg=world['mission']['definition']['combined_rules']
                for _,u in missions.units(world):
                    limits=combined_arms.weapon_limits(world,u)
                    self.assertEqual(limits['fire'],{'min_range_m':0,'max_range_m':u['attack_range']})
                    if any(e['committed'] for e in u['equipment'] if e['category']=='artillery'):
                        self.assertEqual(limits['bombard']['max_range_m'],cfg['artillery_range_m'])
                        self.assertEqual(limits['bombard']['min_range_m'],cfg['artillery_min_range_m'])
                    else:self.assertNotIn('bombard',limits)
                    count+=1
        self.assertEqual(count,540)

    def test_observation_omits_unissued_weapons_and_includes_minimum_range(self):
        w=self.world();u=w['red_units'][2]
        for e in u['equipment']:
            if e['category'] in ('artillery','air_defense'):e.update(committed=0,operational=0,damaged=0,destroyed=0)
        s={'id':'a00123456789','war_state':w,'time_step':'30分钟','turn_count':0,'execution_backend':'afsim','simulation_mode':'open'}
        row=next(r for r in afsim_state.observation(s,{'limit':16})['units'] if r['name']==u['name'])
        self.assertNotIn('bombard',row['weapon_ranges_m'])
        self.assertNotIn('air_defense',row['weapon_ranges_m'])
        self.assertEqual(row['weapon_limits_m']['fire'],{'min_range_m':0,'max_range_m':u['attack_range']})
        self.assertNotIn('bombard',row['actions'])

    def test_warning_preserves_old_range_instead_of_silently_changing_frozen_inputs(self):
        w=self.world();u=w['red_units'][2];u['attack_range']=8000
        before=copy.deepcopy(w)
        warnings=combined_arms.weapon_warnings(w,u)
        self.assertTrue(any('直射' in text and '8000' in text for text in warnings))
        self.assertEqual(combined_arms.weapon_limits(w,u)['fire']['max_range_m'],8000)
        self.assertEqual(w,before)

    def test_nominal_ranges_do_not_claim_empty_or_destroyed_weapons_are_ready(self):
        w=self.world();u=w['red_units'][2];u['logistics']['ammo']=0
        guns=next(e for e in u['equipment'] if e['category']=='artillery')
        guns.update(destroyed=guns['destroyed']+guns['operational'],operational=0)
        s={'id':'a00123456789','war_state':w,'time_step':'30分钟','turn_count':0,'execution_backend':'afsim','simulation_mode':'open'}
        row=next(r for r in afsim_state.observation(s,{'limit':16})['units'] if r['name']==u['name'])
        self.assertIn('bombard',row['weapon_limits_m'])  # Previously issued range remains interpretable.
        self.assertNotIn('bombard',row['actions']);self.assertNotIn('fire',row['actions'])

    def test_observation_distinguishes_event_timestamp_from_firing_duration(self):
        w=self.world();before=copy.deepcopy(w)
        s={'id':'a00123456789','war_state':w,'time_step':'30分钟','turn_count':0,'execution_backend':'afsim','simulation_mode':'open'}
        v=afsim_state.observation(s,{'limit':1})
        self.assertEqual(v['event_time_semantics']['combined_arms.events.seconds'],'turn_offset_seconds')
        self.assertEqual(v['event_time_semantics']['formation.last_execution.active_fire_s'],'duration_seconds')
        self.assertEqual(w,before)

    def test_native_inputs_and_validation_use_the_same_direct_and_indirect_ranges(self):
        from tools.qa.historical_operational_fixture import inputs
        from gentactix import historical_operations
        snapshot,params=inputs();p=params['actors']['ww2.cn.division31'];p['attack_range_m']=800
        params['actors']['ww2.jp.seya_detachment']['position']={**p['position'],'lat':p['position']['lat']+.04}
        w=historical_operations.initial(snapshot,params);u=w['red_units'][0];t=w['blue_units'][0]
        direct={'unit':u['name'],'action':'fire','target':t['name']}
        with self.assertRaisesRegex(ValueError,'射程'):missions.validate_orders(w,[direct],'30分钟')
        order={**direct,'action':'bombard'}
        scene=afsim_world.compile_scene(w,[order],1800,native_rules=True)
        self.assertIn('ca_direct_range_m",(double)(800)',scene['script'])
        self.assertIn('range=12000',scene['script'])
        self.assertEqual(combined_arms.weapon_limits(w,u)['bombard'],{'min_range_m':300,'max_range_m':12000})

    def test_map_uses_actual_weapon_action_instead_of_self_defense_range(self):
        w=self.world();u=w['red_units'][2];u['attack_range']=800
        event={'attacker':u['name'],'attacker_team':'red','attacker_pos':[u['lat'],u['lng']],
               'lat':u['lat']+.04,'lng':u['lng'],'weapon_action':'bombard','radius':99999,'weapon_range_m':99999}
        for action,expected in (('bombard',14400),('suppress',14400),('fire',960)):
            event['weapon_action']=action
            radius,basis=viz.resolve_engagement_radius(event,w,event['lat'],event['lng'])
            self.assertEqual(radius,expected)
            self.assertIn('非杀伤半径',basis)

    def test_high_latitude_sector_center_points_toward_target(self):
        origin=(70,125);target=(70.03,125.08);radius=6000
        points=viz.impact_sector_vertices(*origin,*target,radius)
        center=points[len(points)//2]
        def vector(point):
            phi,lam=map(math.radians,point)
            return (math.cos(phi)*math.cos(lam),math.cos(phi)*math.sin(lam),math.sin(phi))
        a,b,c=map(vector,(origin,target,center))
        arc=math.acos(max(-1,min(1,sum(x*y for x,y in zip(a,c)))))
        self.assertAlmostEqual(arc*6371000,radius,delta=.01)
        normal=(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
        norm=math.sqrt(sum(x*x for x in normal))
        self.assertLess(abs(sum(x*y for x,y in zip(normal,c)))/norm,1e-9)

    def test_vue_and_python_range_and_sector_contracts_match(self):
        w=self.world();u=w['red_units'][2];u['attack_range']=800
        p=subprocess.run(['node','tools/qa/weapon_ranges.mjs'],input=json.dumps(w),text=True,
            cwd=Path(__file__).resolve().parent,capture_output=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        result=json.loads(p.stdout)
        self.assertEqual(result['ranges'],[14400,14400,960])
        expected=viz.impact_sector_vertices(70,125,70.03,125.08,6000)
        for a,b in zip(result['sector'],expected):
            self.assertAlmostEqual(a[0],b[0],places=7);self.assertAlmostEqual(a[1],b[1],places=7)


if __name__=='__main__':unittest.main()
