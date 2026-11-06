"""Map display clustering preserves identities and physical coordinates."""
import copy,json,subprocess,unittest

class MapUnitTests(unittest.TestCase):
    def call(self,kind,value):
        p=subprocess.run(['node','tools/qa/map_units_contract.mjs'],input=json.dumps({'kind':kind,'value':value}),text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr);return json.loads(p.stdout)

    def groups(self,points):return self.call('groups',{'points':points,'width':400,'height':300})

    def test_transitive_overlap_includes_the_entire_component(self):
        result=self.groups([{'id':i,'x':x,'y':70} for i,x in [('a',50),('b',80),('c',110)]])
        self.assertEqual([g['ids'] for g in result],[['a','b','c']])

    def test_symbol_corner_overlap_is_not_a_radius_test(self):
        result=self.groups([{'id':'a','x':50,'y':50},{'id':'b','x':80,'y':80},{'id':'c','x':200,'y':200}])
        self.assertEqual([g['ids'] for g in result],[['a','b'],['c']])

    def test_visibility_includes_partial_symbols_and_excludes_far_units(self):
        result=self.groups([{'id':'edge','x':-10,'y':50},{'id':'far','x':-50,'y':50},{'id':'other','x':450,'y':50}])
        self.assertEqual([g['ids'] for g in result],[['edge']])

    def test_groups_are_order_independent_without_mutating_points(self):
        points=[{'id':i,'x':60,'y':60} for i in ['c','a','b']];before=copy.deepcopy(points)
        self.assertEqual(self.groups(points),self.groups(list(reversed(points))));self.assertEqual(points,before)

    def test_registered_ids_keep_team_and_unknown_deployment_separate(self):
        snap={'war_state':{'red_units':[{'name':'同名单位','historical_unit_id':'red-source','lat':38,'lng':115}],
            'blue_units':[{'name':'同名单位','historical_unit_id':'blue-source','lat':None,'lng':None}]},
            'plotting':{'units':[{'team':'red','name':'同名单位','id':'red-key'},{'team':'blue','name':'同名单位','id':'blue-key'}]}}
        rows=self.call('entries',snap)
        self.assertEqual([r['id'] for r in rows],['red-key','blue-key']);self.assertIsNone(rows[1]['position'])
        self.assertEqual(rows[0]['source_id'],'red-source');self.assertEqual(rows[1]['source_id'],'blue-source')

    def test_computed_parts_of_one_parent_are_distinct_selection_targets(self):
        snap={'war_state':{'red_units':[{'name':'甲-分队一','historical_unit_id':'parent','calculation_unit_id':'part-a','lat':38,'lng':115},
            {'name':'甲-分队二','historical_unit_id':'parent','calculation_unit_id':'part-b','lat':38,'lng':115}],'blue_units':[]}}
        rows=self.call('entries',snap);self.assertEqual(len({r['id'] for r in rows}),2)
        self.assertEqual({r['source_id'] for r in rows},{'parent'})

    def test_pending_state_remains_explicit_without_moving_the_unit(self):
        snap={'war_state':{'red_units':[{'name':'甲','lat':38,'lng':115}],'blue_units':[],
            'campaign':{'actors':{'甲':{'active':False}}}}}
        row=self.call('entries',snap)[0];self.assertEqual(row['status'],'待入场 · 计算部署')
        self.assertEqual(row['position'],{'lat':38,'lng':115})

if __name__=='__main__':unittest.main()
