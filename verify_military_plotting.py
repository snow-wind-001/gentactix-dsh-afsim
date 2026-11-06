"""Military plotting contracts: overlays never replace battle or execution state."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gentactix import military_symbols as m, missions, commands


class PlottingTests(unittest.TestCase):
    def setUp(self):
        self.world=missions.initial('CA-AJ18-v1')
        self.session={'id':'abcd12345678','war_state':self.world,'turn_count':0,'simulation_mode':'open','execution_backend':'afsim'}

    def item(self,kind='supply-ammo'):
        return {'id':'a'*32,'symbol_id':kind,'label':'弹药集结点','team':'red','status':'assumed','points':[{'lat':27.45814,'lng':109.6592}],'source':'教学估计','visible':True}

    def test_catalog_retains_reference_boundaries_and_explicit_anchors(self):
        cat=m.catalog();self.assertGreaterEqual(len(cat['symbols']),24)
        self.assertEqual(cat['reference']['independent_examples'],256)
        self.assertFalse(cat['reference']['all_semantically_verified'])
        hq=m.symbol('hq');self.assertGreater(hq['anchor'][1],20)
        self.assertTrue(all(x['geometry'] in ('point','line','area') for x in cat['symbols']))

    def test_role_symbol_uses_operational_equipment_without_changing_unit_type(self):
        u=copy.deepcopy(self.world['red_units'][2]);u['type']='步兵';before=copy.deepcopy(u)
        self.assertEqual(m.unit_symbol(u),'artillery')
        for e in u['equipment']:
            if e['category']=='artillery':e['operational']=0
        self.assertNotEqual(m.unit_symbol(u),'artillery')
        self.assertEqual(before['type'],u['type'])

    def test_overlay_is_independent_of_battle_world_and_command_revision(self):
        before=copy.deepcopy(self.world);v=m.view(self.session)
        state=m.replace(self.session,{'revision':v['revision'],'turn':v['turn'],'world_version':v['world_version'],'items':[self.item()],'unit_symbols':{}})
        self.session['plotting_state']=state
        self.assertEqual(self.world,before);self.assertEqual(m.view(self.session)['revision'],1)
        self.assertEqual(m.view(self.session)['world_version'],v['world_version'])
        with self.assertRaises(m.Conflict):m.replace(self.session,{'revision':0,'turn':0,'world_version':v['world_version'],'items':[],'unit_symbols':{}})

    def test_geometry_and_local_bounds_reject_invalid_or_unknown_values(self):
        for change in [{'symbol_id':'p015-r01-g0001'},{'points':[{'lat':True,'lng':109}]},{'points':[{'lat':float('nan'),'lng':109}]},{'points':[{'lat':40.792,'lng':40.792}]}]:
            with self.subTest(change=change),self.assertRaises(ValueError):m.validate_item({**self.item(),**change},self.session)
        with self.assertRaises(ValueError):m.validate_item(self.item('attack-axis'),self.session)
        a=self.item('attack-axis');a['points'].append({'lat':27.46,'lng':109.66});self.assertEqual(len(m.validate_item(a,self.session)['points']),2)

    def test_render_escapes_labels_and_has_no_active_or_external_svg_content(self):
        text=m.unit_html({'name':'<img src=x onerror=alert(1)>','type':'步兵'},'red')
        self.assertNotIn('<img src=x',text);self.assertIn('&lt;img',text)
        self.assertIn('military-symbol',text);self.assertNotIn('<script',text)
        self.assertEqual(m.unit_symbol({'type':'unknown'}),'unknown')

    def test_dsh_can_only_use_selected_points_or_known_positions(self):
        item={k:v for k,v in self.item().items() if k!='id'}
        bound=m.bind_candidate({'items':[item]},self.session,item['points']);self.assertEqual(len(bound['items']),1)
        item['points']=[{'lat':27.45,'lng':109.65}]
        with self.assertRaisesRegex(ValueError,'选点|已知'):m.bind_candidate({'items':[item]},self.session,[])
        with self.assertRaises(ValueError):m.bind_candidate({'items':[], 'war_state':self.world},self.session,[])

    def test_unknown_unit_override_cannot_silently_create_units(self):
        v=m.view(self.session)
        with self.assertRaises(ValueError):m.replace(self.session,{'revision':0,'turn':0,'world_version':v['world_version'],'items':[],'unit_symbols':{'ghost':'armor'}})
        u=v['units'][0]
        state=m.replace(self.session,{'revision':0,'turn':0,'world_version':v['world_version'],'items':[],'unit_symbols':{u['id']:'engineer'}})
        self.assertEqual(state['unit_symbols'][u['id']],'engineer')

    def test_reference_library_only_serves_indexed_passive_icons(self):
        svg=m.reference_svg('mil-199')
        self.assertIn(b'<svg',svg);self.assertNotIn(b'<script',svg)
        for bad in ('../catalog','p015-r01-g0001','mil-9999'):
            with self.assertRaises(ValueError):m.reference_svg(bad)

    def test_partial_legacy_equipment_and_malformed_reference_do_not_crash(self):
        self.assertEqual(m.unit_symbol({'type':'步兵','equipment':None,'formation':'未记录'}),'infantry')
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'GENTACTIX_PROJECT_ROOT':d}):
            path=Path(d)/'data/military-symbols-v2/icons';path.mkdir(parents=True);(path/'mil-199.svg').write_text('<svg><path>')
            with self.assertRaises(ValueError):m.reference_svg('mil-199')

    def test_native_plotting_role_is_isolated_and_high_effort(self):
        from backend import harness_engine as h, plotting_routes as p
        policy=h.role_policy('map-annotator',tools=True)
        self.assertEqual(set(policy['allowed_tools']),{'read_military_plotting_skill','search_military_symbols','validate_military_plotting'})
        self.assertEqual(policy['reasoning_effort'],'medium')
        context={'military_plotting':{'session':self.session,'points':[]}}
        r=p.execute_tool(context,{'tool':'read_military_plotting_skill','args':{}})
        self.assertIn('search_military_symbols',r['content'])

    def test_all_existing_unit_profiles_have_explicit_display_mappings(self):
        from gentactix.unit_types import UNIT_PROFILES
        for profile in UNIT_PROFILES:
            self.assertIn(profile['id'],m.DATA['unit_profile_symbols'])
            self.assertIn(m.DATA['unit_profile_symbols'][profile['id']],m.SYMBOLS)


class PlottingApiTests(unittest.TestCase):
    def setUp(self):
        from backend import main
        from fastapi.testclient import TestClient
        self.main=main;self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        env=patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':self.temp.name});env.start();self.addCleanup(env.stop)
        registry=patch.dict(main._SESSIONS,{},clear=True);registry.start();self.addCleanup(registry.stop)
        self.client=TestClient(main.app)
        r=self.client.post('/api/sessions',json={'scenario':'军事标图隔离回归','mission_id':'CA-AJ18-v1','execution_backend':'afsim'})
        self.sid=r.json()['session_id'];self.session=main._SESSIONS[self.sid]
        self.session['war_state']=missions.initial('CA-AJ18-v1')
        self.base='/api/sessions/'+self.sid+'/plotting'

    def payload(self):
        v=self.client.get(self.base).json()
        return {k:v[k] for k in ('revision','turn','world_version','items','unit_symbols')}

    def test_save_export_restore_without_advancing_or_changing_war(self):
        before=copy.deepcopy(self.session['war_state']);p=self.payload();p['items']=[PlottingTests.item(self)]
        r=self.client.put(self.base,json=p);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.session['war_state'],before);self.assertEqual(self.session['turn_count'],0)
        export=self.client.get('/api/sessions/'+self.sid+'/export').json()
        self.assertEqual(export['session']['plotting_state']['items'][0]['id'],'a'*32)
        from backend import session_store
        loaded,errors=session_store.load_all();self.assertFalse(errors);self.assertEqual(loaded[self.sid]['plotting_state']['revision'],1)
        self.assertEqual(self.client.put(self.base,json=p).status_code,409)

    def test_failed_disk_write_preserves_prior_overlay_and_world(self):
        p=self.payload();p['items']=[PlottingTests.item(self)];before=copy.deepcopy(self.session['war_state'])
        with patch('backend.session_store.save',side_effect=OSError('disk full')):
            r=self.client.put(self.base,json=p)
        self.assertEqual(r.status_code,503);self.assertNotIn('plotting_state',self.session);self.assertEqual(self.session['war_state'],before)

    def test_direct_model_output_without_skill_events_is_rejected(self):
        from types import SimpleNamespace
        p=self.payload();p={k:p[k] for k in ('revision','turn','world_version')};p.update(text='标注补给点',points=[])
        item={k:v for k,v in PlottingTests.item(self).items() if k!='id'}
        with patch('backend.harness_engine._run_brain',return_value=SimpleNamespace(final_response=json.dumps({'items':[item]}))):
            r=self.client.post(self.base+'/propose',json=p)
        self.assertEqual(r.status_code,502);self.assertIn('工具事件',r.text);self.assertNotIn('plotting_state',self.session)


if __name__=='__main__':unittest.main()
