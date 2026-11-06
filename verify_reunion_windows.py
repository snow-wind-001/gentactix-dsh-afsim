"""Source-bound LM15 reunion windows must not merge dates, places or units."""
import copy
import unittest

from gentactix import historical_initial as hi, historical_operations as ho, campaign_windows as cw

BATTLE='红军长征-甘孜会师至三大主力会师-1936.07.01至1936.10.22'
CASES={
 'LM15-ganzi-jul1-2':('ganzi_assembly',{'re.red.corps2','re.red.corps6'}),
 'LM15-huining-oct9-10':('huining_assembly',{'re.red.division1','re.red.division2','re.red.division73','re.red.army4','re.red.army31'}),
 'LM15-jiangtaibao-oct22':('jiangtaibao_meeting',{'re.red.corps2','re.red.division2'}),
}


class ReunionWindowTests(unittest.TestCase):
    def snapshot(self,phase):return hi.initial(BATTLE,phase,version='1.1.0')['historical_initial']

    def test_three_registered_windows_have_independent_source_rosters_and_geography(self):
        centers=[]
        for identity,(phase,actors)in CASES.items():
            with self.subTest(identity=identity):
                s=self.snapshot(phase);pin=cw.pin(identity)
                self.assertEqual(set(cw.select(s,pin)),actors)
                p=next(p for p in s['definition']['phases']if p['id']==phase)
                centers.append(p['geographic_scope']['center'])
                self.assertEqual(p['interaction']['active_teams'],['red'])
                self.assertEqual(p['interaction']['kind'],'non_contact_transfer')
                self.assertTrue(pin['definition']['milestones'])
        self.assertEqual(len({(c['lat'],c['lng'])for c in centers}),3)
        self.assertGreater(abs(centers[1]['lng']-centers[2]['lng']),.5)

    def test_default_and_original_published_source_remain_unchanged(self):
        s=hi.initial(BATTLE,'ganzi_assembly')['historical_initial']
        self.assertEqual(s['version'],'1.0.0')
        self.assertEqual({u['id']for u in s['definition']['units']},{'re.red.corps2','re.red.corps6','re.red.army32'})

    def test_headquarters_never_become_physical_actors_or_known_strengths(self):
        for phase,_ in CASES.values():
            s=self.snapshot(phase)
            self.assertTrue(all(f['value']is None for u in s['definition']['units']for f in u['facts'].values()))
            self.assertFalse(s['definition']['coverage']['strength_complete'])
        for identity,(phase,_)in CASES.items():
            s=self.snapshot(phase);units={u['id']:u for u in s['definition']['units']}
            self.assertTrue(all(units[u]['role']!='command'for u in cw.select(s,cw.pin(identity))))

    def test_jiangtaibao_does_not_teleport_next_day_xinglong_corps(self):
        s=self.snapshot('jiangtaibao_meeting');d=cw.pin('LM15-jiangtaibao-oct22')['definition']
        self.assertNotEqual(d['units']['re.red.corps6']['representation'],'actor')
        phase=next(p for p in s['definition']['phases']if p['id']=='xinglong_followup')
        operations=phase['operations'];self.assertTrue(any('1936-10-23'in o['date']['label']and 're.red.corps6'in o['unit_ids']and 're.red.division1'in o['unit_ids']for o in operations))
        self.assertTrue(all('兴隆' in p['name']for o in operations for p in o['places']))

    def test_partial_army_hierarchy_is_preserved_without_parent_child_double_count(self):
        s=self.snapshot('huining_assembly');pin=cw.pin('LM15-huining-oct9-10');units={u['id']:u for u in s['definition']['units']}
        self.assertEqual(units['re.red.army4.division10']['parent_id'],'re.red.army4')
        self.assertEqual(units['re.red.army4']['children_coverage']['status'],'partial')
        row=pin['definition']['units']['re.red.army4.division10']
        self.assertEqual(row['representation'],'covered_reference');self.assertEqual(row['represented_by'],'re.red.army4')
        self.assertNotIn('re.red.army4.division10',cw.select(s,pin))

    def test_oct8_subdivision_record_is_not_upgraded_to_oct9_10_deployment(self):
        s=self.snapshot('huining_assembly');u=next(u for u in s['definition']['units']if u['id']=='re.red.army4.division10')
        presence=next(p for p in u['presence']if p['phase_id']=='huining_assembly')
        self.assertEqual(presence['status'],'campaign_participant')
        self.assertEqual(cw.pin('LM15-huining-oct9-10')['definition']['units'][u['id']]['presence_basis'],'prior_reference')

    def test_past_and_outside_references_are_not_mislabeled_as_future_participants(self):
        s=self.snapshot('jiangtaibao_meeting');d=cw.pin('LM15-jiangtaibao-oct22')['definition']
        self.assertEqual(d['units']['re.red.army31']['representation'],'outside_window')
        self.assertIn(d['units']['re.red.army31']['presence_basis'],('prior_reference','not_applicable'))
        self.assertIn('outside_window',cw.REPRESENTATIONS)

    def test_outside_reference_cannot_hide_a_source_reported_present_unit(self):
        s=self.snapshot('huining_assembly');d=copy.deepcopy(cw.pin('LM15-huining-oct9-10')['definition'])
        row=d['units']['re.red.army31'];row.update(representation='outside_window',presence_basis='prior_reference',represented_by=None)
        with self.assertRaisesRegex(ValueError,'在场|窗口'):cw.validate_definition(d,s)

    def test_template_requires_explicit_estimates_and_keeps_solo_scope(self):
        for identity,(phase,actors)in CASES.items():
            s=self.snapshot(phase);p=ho.configuration_template(s,'campaign',window=cw.pin(identity),termination_mode='objectives')
            self.assertEqual(set(p['actors']),actors)
            self.assertTrue(all(a['personnel']is None and a['position']=={'lat':None,'lng':None} for a in p['actors'].values()))
            self.assertEqual(p['goal']['termination_mode'],'objectives')
            self.assertEqual(p['campaign_scope']['window']['id'],identity)
            self.assertTrue(all(n['team']=='red'for n in s['definition']['units']))

    def test_builder_pins_new_source_and_leaves_old_explicit_version_rejected(self):
        from backend.scenario_builder import historical_basis
        for identity,(phase,actors)in CASES.items():
            b=historical_basis(BATTLE,force_scope='campaign',campaign_window_id=identity,termination_mode='objectives')
            self.assertTrue(b['ready'],b['error']);self.assertEqual(b['initial']['version'],'1.1.0')
            self.assertEqual(b['initial']['phase_id'],phase);self.assertEqual(set(b['configuration_template']['actors']),actors)
            with self.assertRaises(ValueError):historical_basis(BATTLE,force_scope='campaign',version='1.0.0',campaign_window_id=identity,termination_mode='objectives')

    def test_campaign_does_not_silently_relax_the_explicit_objective_driven_contract(self):
        from backend.scenario_builder import historical_basis
        b=historical_basis(BATTLE,force_scope='campaign',campaign_window_id='LM15-huining-oct9-10',termination_mode='deadline')
        self.assertFalse(b['ready']);self.assertIn('目标完成',b['error'])


if __name__=='__main__':unittest.main()
