"""Window admission is source-bound, scoped and independent of frozen recovery."""
import copy
import json
import subprocess
import unittest
from unittest.mock import patch

from gentactix import historical_initial as hi, historical_operations as op

BATTLE = '抗日战争-万家岭战役-1938.09下旬至1938.10'
WINDOW = 'WJL-oct6-10'


class CampaignWindowTests(unittest.TestCase):
    def node_roundtrip(self,value):
        script='process.stdin.setEncoding("utf8");let s="";process.stdin.on("data",x=>s+=x);process.stdin.on("end",()=>process.stdout.write(JSON.stringify(JSON.parse(s))));'
        return json.loads(subprocess.run(['node','-e',script],input=json.dumps(value,ensure_ascii=False),text=True,capture_output=True,check=True).stdout)

    def test_new_window_pin_survives_real_node_number_roundtrip(self):
        battle='抗日战争-武汉会战-1938.06至1938.10'
        snapshot=hi.initial(battle,'northern_sep17_18',version='1.2.0')['historical_initial']
        pinned=self.cw.pin('WH-northern-sep17-18','1.1.0')
        wire=self.node_roundtrip(pinned)
        self.assertEqual(self.cw.validate(snapshot,wire),self.cw.validate(snapshot,pinned))
        with patch.object(self.cw,'load',side_effect=AssertionError('Frozen wire pin must be self-contained')):
            self.cw.validate(snapshot,wire,frozen=True)

    def test_legacy_window_pin_keeps_its_typed_offline_validation(self):
        battle='抗日战争-武汉会战-1938.06至1938.10'
        snapshot=hi.initial(battle,'northern_sep17_18',version='1.2.0')['historical_initial']
        d=self.cw.load('WH-northern-sep17-18','1.0.0')
        legacy=dict(format=self.cw.FORMAT,id=d['id'],version=d['version'],definition_hash=hi.digest(d),definition=d)
        before=json.dumps(legacy,ensure_ascii=False,sort_keys=True)
        with patch.object(self.cw,'load',side_effect=AssertionError('No registry access for legacy frozen pin')):
            self.cw.validate(snapshot,legacy,frozen=True)
        self.assertEqual(json.dumps(legacy,ensure_ascii=False,sort_keys=True),before)

    def test_legacy_browser_pin_requires_registered_digest_and_equal_contents(self):
        battle='抗日战争-武汉会战-1938.06至1938.10'
        snapshot=hi.initial(battle,'northern_sep17_18',version='1.2.0')['historical_initial']
        d=self.cw.load('WH-northern-sep17-18','1.0.0')
        legacy=dict(format=self.cw.FORMAT,id=d['id'],version=d['version'],definition_hash=hi.digest(d),definition=d)
        wire=self.node_roundtrip(legacy)
        self.cw.validate(snapshot,wire)
        bad=copy.deepcopy(wire);bad['definition']['label']+='修改'
        with self.assertRaises(ValueError):self.cw.validate(snapshot,bad)
        with patch.object(self.cw,'load',side_effect=AssertionError('Never repair an unverifiable frozen legacy pin')):
            with self.assertRaisesRegex(ValueError,'摘要'):self.cw.validate(snapshot,wire,frozen=True)

    def test_explicit_new_draft_can_rebind_verified_legacy_transport_metadata(self):
        battle='抗日战争-武汉会战-1938.06至1938.10'
        snapshot=hi.initial(battle,'northern_sep17_18',version='1.2.0')['historical_initial']
        d=self.cw.load('WH-northern-sep17-18','1.0.0')
        wire=self.node_roundtrip(dict(format=self.cw.FORMAT,id=d['id'],version=d['version'],definition_hash=hi.digest(d),definition=d))
        before=json.dumps(wire,sort_keys=True)
        rebound=self.cw.transport_pin(snapshot,wire)
        with patch.object(self.cw,'load',side_effect=AssertionError('New draft transport pin must restore without registry')):
            self.cw.validate(snapshot,rebound,frozen=True)
        self.assertEqual(json.dumps(wire,sort_keys=True),before)

    def setUp(self):
        from gentactix import campaign_windows as cw
        self.cw = cw
        self.snapshot = hi.initial(BATTLE, 'oct6_orders', version='1.3.0')['historical_initial']
        self.pin = cw.pin(WINDOW, '1.0.0')

    def test_all_source_identities_accounted_without_post_window_actor(self):
        d = self.pin['definition']
        self.assertEqual(set(d['units']), {u['id'] for u in self.snapshot['definition']['units']})
        ids = self.cw.select(self.snapshot, self.pin)
        self.assertEqual(len(ids), 22)
        self.assertNotIn('ww2.cn.division61', ids)
        self.assertIn('ww2.jp.division106', ids)
        self.assertNotIn('ww2.jp.regiment123', ids)
        self.assertEqual(d['units']['ww2.jp.regiment123']['represented_by'], 'ww2.jp.division106')

    def test_administrative_parent_and_temporary_command_are_not_rewritten(self):
        row = self.pin['definition']['units']['ww2.jp.regiment149']
        self.assertEqual(row['operational_reference'], 'WJL-149-operational-command')
        original = next(u for u in self.snapshot['definition']['units'] if u['id']=='ww2.jp.regiment149')
        self.assertEqual(original['parent_id'], 'ww2.jp.division101')
        self.assertEqual(row['presence_basis'], 'prior_reference')

    def test_selection_rejects_wrong_source_version_or_phase(self):
        old = hi.initial(BATTLE, 'oct6_orders', version='1.2.0')['historical_initial']
        with self.assertRaises(ValueError): self.cw.select(old, self.pin)
        wrong = copy.deepcopy(self.snapshot); wrong['phase_id']='oct7_attack'
        with self.assertRaises(ValueError): self.cw.select(wrong, self.pin)

    def test_changed_hash_or_canonical_body_is_rejected(self):
        bad = copy.deepcopy(self.pin); bad['definition']['label']+='伪改'
        with self.assertRaises(ValueError): self.cw.validate(self.snapshot, bad)
        bad['definition_hash']=hi.digest(bad['definition'])
        with self.assertRaisesRegex(ValueError, '注册'): self.cw.validate(self.snapshot, bad)

    def test_frozen_pin_does_not_read_live_registry(self):
        with patch.object(self.cw, 'load', side_effect=AssertionError('must be offline')):
            self.cw.validate(self.snapshot, self.pin, frozen=True)

    def test_parent_child_double_count_or_missing_reference_is_rejected(self):
        for change in ('double', 'missing'):
            d=copy.deepcopy(self.pin['definition'])
            if change=='double': d['units']['ww2.jp.regiment123']['representation']='actor'
            else: d['units'].pop('ww2.cn.division61')
            with self.assertRaises(ValueError): self.cw.validate_definition(d, self.snapshot)

    def test_task_references_and_uncertain_arrivals_do_not_become_orders(self):
        d=self.pin['definition']
        self.assertEqual(len(d['phase_ids']), 5)
        self.assertTrue(d['milestones'])
        self.assertTrue(all(x['policy']=='reference_only' for x in d['milestones']))
        self.assertEqual(d['units']['ww2.cn.division142.wjl_part']['presence_basis'], 'departure_only')
        self.assertTrue(all(x['position'] is None for x in d['sectors']))

    def test_template_has_window_roster_null_estimates_and_explicit_remainders(self):
        p=op.configuration_template(self.snapshot, 'campaign', window=self.pin)
        self.assertEqual(len(p['actors']),22)
        self.assertEqual(p['campaign_scope']['version'],'campaign-oob-window-1')
        self.assertEqual(p['campaign_scope']['window'],self.pin)
        self.assertEqual(p['clock']['start'], '1938-10-06T00:00:00')
        self.assertEqual(p['campaign_scope']['planning_end'], '1938-10-11T00:00:00')
        self.assertTrue(all(a['personnel'] is None for a in p['actors'].values()))
        self.assertTrue(all(a['not_before'] is None for a in p['campaign']['arrivals'].values()))
        self.assertNotIn('ww2.jp.division106',p['campaign_scope']['remainders'])
        self.assertIn('ww2.jp.division101',p['campaign_scope']['remainders'])

    def test_existing_cumulative_mode_keeps_legacy_selection(self):
        from gentactix import campaign_scope as cs
        self.assertEqual(len(cs.select(self.snapshot)),23)
        self.assertIn('ww2.cn.division61',cs.select(self.snapshot))
        self.assertEqual(cs.template(self.snapshot)['version'],cs.VERSION)

    def test_builder_pins_window_and_does_not_silently_change_explicit_version(self):
        from backend.scenario_builder import historical_basis
        b=historical_basis(BATTLE,force_scope='campaign',campaign_window_id=WINDOW)
        self.assertTrue(b['ready'],b['error'])
        self.assertEqual(b['initial']['version'],'1.3.0')
        self.assertEqual(b['initial']['phase_id'],'oct6_orders')
        self.assertEqual(len(b['actors']),22)
        self.assertEqual(b['campaign_window'],self.pin)
        self.assertTrue(b['available_campaign_windows'])
        with self.assertRaises(ValueError): historical_basis(BATTLE,force_scope='campaign',version='1.0.0',campaign_window_id=WINDOW)
        with self.assertRaises(ValueError): historical_basis(BATTLE,force_scope='phase',campaign_window_id=WINDOW)

    def test_model_cannot_drop_or_replace_selected_window(self):
        from backend.scenario_builder import historical_basis
        from backend.scenario_assembly import validate_build_constraints
        b=historical_basis(BATTLE,force_scope='campaign',campaign_window_id=WINDOW)
        p=copy.deepcopy(b['configuration_template']);p['goal']['team']='red'
        validate_build_constraints(p,b)
        p['campaign_scope'].pop('window')
        with self.assertRaisesRegex(ValueError,'窗口'):validate_build_constraints(p,b)

    def test_world_uses_admitted_units_and_frozen_restore_without_registry(self):
        from tools.qa.campaign_window_fixture import inputs
        s,p=inputs();world=op.initial(s,p)
        self.assertEqual(len(world['red_units']),17)
        self.assertEqual(len(world['blue_units']),5)
        binding=world['mission']['definition']['historical_calculation']
        with patch.object(self.cw,'load',side_effect=AssertionError('no live window registry')):
            self.assertEqual(op.from_binding(binding),world['mission']['definition'])
        p['actors']['ww2.cn.division61']=copy.deepcopy(next(iter(p['actors'].values())))
        with self.assertRaises(ValueError):op.initial(s,p)

    def test_window_start_and_planning_boundary_cannot_drift(self):
        from tools.qa.campaign_window_fixture import inputs
        for key in ('start','end'):
            s,p=inputs()
            if key=='start':p['clock']['start']='1938-10-07T00:00:00'
            else:p['campaign_scope']['planning_end']='1938-10-18T00:00:00'
            with self.assertRaisesRegex(ValueError,'窗口'):op.initial(s,p)

    def test_window_scope_rejects_null_pin_as_a_domain_error(self):
        from tools.qa.campaign_window_fixture import inputs
        s,p=inputs();p['campaign_scope']['window']=None
        with self.assertRaisesRegex(ValueError,'窗口'):op.initial(s,p)

    def test_native_skill_distinguishes_window_from_cumulative_scope(self):
        from backend.scenario_builder import HISTORICAL_SKILL
        text=HISTORICAL_SKILL.read_text()
        self.assertIn('campaign-oob-window-1',text)
        self.assertIn('readonly_campaign_window',text)
        self.assertIn('window_scope',text)

    def test_native_staged_configuration_keeps_pin_on_host_and_actor_extents_visible(self):
        from backend import scenario_builder as sb, scenario_assembly as sa
        from tools.qa.campaign_window_fixture import inputs
        s,p=inputs();b=sb.historical_basis(BATTLE,force_scope='campaign',campaign_window_id=WINDOW,termination_mode='objectives')
        a=sa.create(b);self.addCleanup(sa.close,a.id)
        v=a.tool('globals','get_scenario_basis',{})
        self.assertNotIn('window',v['configuration']['campaign_scope'])
        self.assertEqual(v['readonly_campaign_window']['definition_hash'],self.pin['definition_hash'])
        g={k:copy.deepcopy(v) for k,v in p.items() if k not in ('format','phase_id','actors')}
        g['campaign_scope'].pop('window')
        result=a.tool('globals','update_scenario_configuration',{'revision':0,'patch':g})
        self.assertTrue(result['updated'],result)
        self.assertEqual(a.configuration['campaign_scope']['window'],self.pin)
        for part in a.parts:
            v=a.tool(part,'get_scenario_basis',{})
            self.assertTrue(all(r['window_scope']['extent'] for r in v['actors']))
            self.assertNotIn('window',v['readonly_global_configuration']['campaign_scope'])
            result=a.tool(part,'update_scenario_configuration',{'revision':a.revision,
                'patch':{'actors':{i:p['actors'][i] for i in a.assigned(part)}}})
            self.assertTrue(result['updated'],result)
        result=a.tool('final','validate_scenario_configuration',{})
        self.assertTrue(result['valid'],result)

    def test_pending_configurations_are_filtered_by_selected_scope_and_window(self):
        from backend import scenario_builder as sb
        import json,tempfile
        from pathlib import Path
        s=self.snapshot;template=op.configuration_template(s,'campaign',window=self.pin)
        template['goal']['termination_mode']='objectives'
        with tempfile.TemporaryDirectory() as tmp,patch.object(sb,'directory',return_value=Path(tmp)):
            for n,window in enumerate((self.pin,None)):
                p=copy.deepcopy(template)
                if window is None:p['campaign_scope'].pop('window')
                identity=str(n)*32
                record=dict(id=identity,kind='historical_configuration',initial=s,parameters=p,execution_backend='narrative')
                (Path(tmp)/(identity+'.json')).write_text(json.dumps(record))
            found=sb.pending_configurations(s,force_scope='campaign',window=self.pin)
            self.assertEqual([r['id'] for r in found],['0'*32])

    def test_normal_basis_route_and_request_schema_preserve_window(self):
        from backend import scenario_builder as sb
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app=FastAPI();app.include_router(sb.build_router(lambda fn:fn))
        with TestClient(app) as c:
            r=c.get('/api/historical-scenarios/basis',params=dict(battle=BATTLE,force_scope='campaign',campaign_window_id=WINDOW))
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()['campaign_window']['id'],WINDOW)
            r=c.get('/api/historical-scenarios/basis',params=dict(battle=BATTLE,force_scope='campaign',campaign_window_id=WINDOW,version='1.0.0'))
            self.assertEqual(r.status_code,422)
        req=sb.HistoricalBuildRequest(battle=BATTLE,phase_id='oct6_orders',force_scope='campaign',campaign_window_id=WINDOW,campaign_window_version='1.0.0')
        self.assertEqual(req.campaign_window_id,WINDOW)


if __name__=='__main__':unittest.main()
