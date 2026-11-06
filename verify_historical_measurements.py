"""Scoped historical quantities must remain references, never live resources."""
import copy
import json
from pathlib import Path
import unittest

from gentactix import historical_initial as hi,historical_links as links

BATTLE='抗日战争-万家岭战役-1938.09下旬至1938.10'


def fixture():
    d=hi.definition(BATTLE,'1.3.0');phase=next(p for p in d['phases'] if p['id']=='oct6_orders')
    row=dict(id='WJL-test-replacement',date=dict(label='10月上旬，确日未载',precision='range'),
        unit_ids=['ww2.jp.uga_detachment'],metric='personnel',
        quantity=dict(relation='eq',lower=2700,upper=2700,unit='persons'),statistic='replacement_basis',
        population='宇贺支队编成基干的补充人员，不是全支队实到或被围师团现员。',
        evidence=[dict(source_id='WJL_GUO',locator='印刷119页上段')],limitations='研究论文转述；未核编成、实到与后续伤亡原表。')
    phase['measurements']=[row]
    return d,phase,row


def session(d):
    return dict(war_state=hi._materialize(d,'oct6_orders'),use_rag=False,product_mode='analysis',simulation_mode='replay')


class HistoricalMeasurementTests(unittest.TestCase):
    def test_replacement_basis_does_not_become_current_personnel_or_mutate_state(self):
        d,_,_=fixture();self.assertTrue(hi.validate_definition(d));s=session(d);saved=copy.deepcopy(s)
        response=links.observation(s,dict(kind='measurements',limit=1))
        self.assertEqual(response['measurements'][0]['statistic'],'replacement_basis')
        self.assertEqual(response['measurements'][0]['quantity']['lower'],2700)
        self.assertEqual(s,saved)
        self.assertTrue(all(u['facts']['personnel']['value'] is None for u in d['units']))
        self.assertIn('不是',response['scope']);self.assertTrue(response['readonly'])

    def test_ordered_interval_and_retreating_horses_keep_population_and_units(self):
        d,p,row=fixture()
        party={**copy.deepcopy(row),'id':'WJL-test-party','statistic':'ordered_detachment',
            'quantity':dict(relation='range',lower=200,upper=500,unit='persons'),
            'population':'每个参加攻击的师挑选的奋勇队，不是全师人数。'}
        horses={**copy.deepcopy(row),'id':'WJL-test-horses','metric':'horses','statistic':'reported_retreat_group',
            'quantity':dict(relation='gt',lower=300,upper=None,unit='horses'),
            'population':'一批北退残部的马匹，不是全师团运输车辆。'}
        p['measurements']+=[party,horses];self.assertTrue(hi.validate_definition(d))
        r=links.observation(session(d),dict(kind='measurements',limit=8))
        self.assertEqual(r['total'],3);self.assertEqual(r['measurements'][1]['quantity']['upper'],500)
        self.assertIsNone(r['measurements'][2]['quantity']['upper'])
        self.assertEqual(r['measurements'][2]['quantity']['unit'],'horses')

    def test_invalid_quantity_units_sources_identity_and_unbounded_rows_rejected(self):
        for defect in ('source','unit','metric','statistic','range','exact','gt','bool','nan','fractional','stock_metric','equipment_metric','metric_unit','date','population','rows','duplicate'):
            d,p,row=fixture()
            if defect=='source':row['evidence'][0]['source_id']='missing'
            elif defect=='unit':row['unit_ids']=['invented']
            elif defect=='metric':row['metric']='tanks_assumed_from_horses'
            elif defect=='statistic':row['statistic']='current_live_state'
            elif defect=='range':row['quantity'].update(relation='range',lower=500,upper=200)
            elif defect=='exact':row['quantity']['upper']=2701
            elif defect=='gt':row['quantity'].update(relation='gt',upper=2701)
            elif defect=='bool':row['quantity']['lower']=True
            elif defect=='nan':row['quantity']['lower']=float('nan')
            elif defect=='fractional':row['quantity'].update(lower=2700.5,upper=2700.5)
            elif defect=='stock_metric':row['statistic']='reported_stock'
            elif defect=='equipment_metric':row['statistic']='reported_equipment'
            elif defect=='metric_unit':row['quantity']['unit']='horses'
            elif defect=='date':row['date']['precision']='second_guessed'
            elif defect=='population':row['population']=''
            elif defect=='rows':p['measurements']=[row]*129
            elif defect=='duplicate':next(q for q in d['phases'] if q['id']=='oct7_attack')['measurements']=[copy.deepcopy(row)]
            with self.subTest(defect=defect),self.assertRaises(ValueError):hi.validate_definition(d)

    def test_phase_paging_and_definition_are_bound_even_after_current_phase_changes(self):
        d,p,row=fixture();p['measurements'].append({**copy.deepcopy(row),'id':'WJL-test-second'})
        s=session(d);first=links.observation(s,dict(kind='measurements',limit=1))
        self.assertEqual(first['total'],2);args=first['next_args'];self.assertEqual(args['phase_id'],'oct6_orders')
        s['war_state']=hi._materialize(d,'oct7_attack')
        second=links.observation(s,args);self.assertEqual(second['phase_id'],'oct6_orders')
        self.assertEqual(second['measurements'][0]['id'],'WJL-test-second');self.assertIsNone(second['next_args'])
        with self.assertRaisesRegex(ValueError,'版本'):links.observation(s,{**args,'definition_hash':'wrong'})

    def test_literal_empty_filter_does_not_imply_absent_sources(self):
        d,_,_=fixture();s=session(d);r=links.observation(s,dict(kind='measurements',query='*',limit=1))
        self.assertEqual(r['total'],0);self.assertEqual(r['unfiltered_total'],1)
        recovered=links.observation(s,r['unfiltered_args']);self.assertEqual(recovered['total'],1)
        filtered=links.observation(s,dict(kind='measurements',unit_id='ww2.cn.army74'));self.assertEqual(filtered['total'],0)

    def test_existing_plugin_tool_routes_numeric_references_with_rag_disabled(self):
        from backend import agent_tools
        d,_,_=fixture();s=session(d);old=copy.deepcopy(s)
        r=agent_tools.exec_retrieve_history(s,dict(kind='measurements',limit=1))
        self.assertTrue(r['ok']);self.assertEqual(r['total'],1);self.assertEqual(s,old)

    def test_old_versions_keep_hash_and_missing_measurements_mean_unknown_not_zero(self):
        for version in ('1.0.0','1.3.0'):
            path=hi.DATA_ROOT/'AJ07-wanjialing'/(version+'.json');raw=json.loads(path.read_text())
            before=hi.digest(raw);self.assertTrue(hi.validate_definition(raw));self.assertEqual(hi.digest(raw),before)
            phase=raw['phases'][1]['id'];s={'war_state':hi._materialize(raw,phase)}
            response=links.observation(s,dict(kind='measurements'));self.assertEqual(response['total'],0)
            self.assertIn('缺载',response['scope'])
        self.assertEqual(hi.definition(BATTLE)['version'],'1.0.0')

    def test_new_public_version_window_and_guidance_bind_same_sources_without_promoting_default(self):
        from gentactix import campaign_windows as cw,historical_operations as ho,history_replay
        source=hi.initial(BATTLE,'oct7_attack',version='1.4.0')['historical_initial']
        guidance=ho.objective_guidance(source)
        self.assertEqual(guidance['binding']['initial_version'],'1.4.0')
        self.assertEqual(guidance['binding']['initial_definition_hash'],source['definition_hash'])
        start=hi.initial(BATTLE,'oct6_orders',version='1.4.0')['historical_initial'];window=cw.pin('WJL-oct6-10','1.4.0')
        self.assertEqual(len(cw.validate(start,window,frozen=True)),22)
        pinned=history_replay.pin(BATTLE,version='1.4.0')
        self.assertEqual(pinned['initial']['version'],'1.4.0')
        self.assertEqual(hi.definition(BATTLE)['version'],'1.0.0')

    def test_six_reviewed_quantities_do_not_replace_unknown_initial_counts_or_estimates(self):
        from gentactix import campaign_windows as cw,historical_operations as ho
        d=hi.definition(BATTLE,'1.4.0');measurements=[m for p in d['phases'] for m in p.get('measurements',[])]
        self.assertEqual(len(measurements),6)
        self.assertEqual({m['statistic'] for m in measurements},{'replacement_basis','ordered_detachment','reported_enemy_group','reported_retreat_group'})
        self.assertTrue(all(u['facts']['personnel']['value'] is None and u['facts']['equipment']['value'] is None for u in d['units']))
        self.assertEqual(next(m for m in measurements if m['metric']=='horses')['quantity']['relation'],'gt')
        s=hi.initial(BATTLE,'oct6_orders',version='1.4.0')['historical_initial']
        parameters=ho.configuration_template(s,'campaign',window=cw.pin('WJL-oct6-10','1.4.0'),termination_mode='objectives')
        self.assertEqual(parameters['actors']['ww2.jp.uga_detachment']['personnel'],2900)
        self.assertIn('不是史实',parameters['actors']['ww2.jp.uga_detachment']['assumption'])


if __name__=='__main__':unittest.main(verbosity=2)
