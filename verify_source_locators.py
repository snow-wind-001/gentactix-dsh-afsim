"""Editorial provenance survives generation and retrieval; not a truth oracle."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from gentactix import rag
from tools import render_long_march as lm, render_anti_japanese_war as aj

ROOT = Path(__file__).resolve().parent


class SourceLocatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.outputs = {'long_march': lm.render(), 'anti_japanese_war': aj.render()}

    def test_each_export_keeps_exact_source_locations_and_completeness(self):
        for series, outputs in self.outputs.items():
            data = ROOT / 'data' / series
            scenarios = json.loads((data/'scenarios.json').read_text(encoding='utf-8'))['scenarios']
            for kind, filename in [('forces','forces.csv'), ('events','timeline.csv'), ('figures','figures.csv')]:
                rows = list(csv.DictReader(io.StringIO(outputs[data/filename])))
                originals = [(s, r) for s in scenarios for r in s[kind]]
                self.assertEqual(len(rows), len(originals))
                for row, (scenario, original) in zip(rows, originals):
                    with self.subTest(series=series, scenario=scenario['id'], kind=kind):
                        self.assertIn('source_locator', row)
                        self.assertEqual(json.loads(row['source_locator']), original.get('source_locator', {}))
                        known = original.get('source_locator', {})
                        expected = 'complete' if set(known) == set(original['sources']) else 'partial' if known else 'missing'
                        self.assertEqual(row['locator_status'], expected)

    def test_provenance_is_visible_to_corpus_readers_in_each_series(self):
        for series, outputs in self.outputs.items():
            source = json.loads((ROOT/'data'/series/'scenarios.json').read_text(encoding='utf-8'))
            for scenario in source['scenarios']:
                text = outputs[ROOT/'corpus'/(scenario['name']+'.md')]
                with self.subTest(scenario=scenario['id']):
                    for heading in ['部队来源定位','事件来源定位','数字来源定位']:
                        self.assertIn('## '+heading, text)
                    for kind in ('forces','events','figures'):
                        for row in scenario[kind]:
                            for locator in row.get('source_locator', {}).values():
                                self.assertIn(locator.replace('|', '\\|').replace('\n', '<br>'), text)

    def edited_render(self, edit):
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache') as directory:
            data = Path(directory)
            payload = json.loads((lm.DATA/'scenarios.json').read_text(encoding='utf-8'))
            edit(payload['scenarios'][0]['forces'][0])
            (data/'scenarios.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
            (data/'sources.json').write_bytes((lm.DATA/'sources.json').read_bytes())
            return lm.render(data_dir=data), data, payload

    def test_partial_and_missing_locations_are_not_silently_complete(self):
        def change(row):
            row.update(sources=['S03','S26'],source_locator={'S03':'仅第一份来源的部署段'})
        outputs, data, payload = self.edited_render(change)
        row = next(csv.DictReader(io.StringIO(outputs[data/'forces.csv'])))
        self.assertIn('locator_status', row)
        self.assertEqual(row['locator_status'], 'partial')
        card = outputs[ROOT/'corpus'/(payload['scenarios'][0]['name']+'.md')]
        self.assertIn('S26：定位待补', card)
        self.assertIn('定位字段完整不等于史实已经核实', card)

    def test_unknown_source_keys_are_rejected_with_record_context(self):
        with self.assertRaisesRegex(ValueError, 'LM01.*forces.*S99'):
            self.edited_render(lambda row:row.update(source_locator={'S99':'别的战役'}))

    def test_empty_locations_are_rejected_instead_of_counting_as_evidence(self):
        for value in ('   ', [], {'paragraph':1}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'LM01.*forces.*S03'):
                self.edited_render(lambda row:row.update(source_locator={'S03':value}))

    def test_locator_cell_does_not_break_markdown_or_csv(self):
        locator = '部署段 | 续行\n日期未载'
        outputs, data, payload = self.edited_render(lambda row:row.update(source_locator={'S03':locator}))
        row = next(csv.DictReader(io.StringIO(outputs[data/'forces.csv'])))
        self.assertIn('source_locator', row)
        self.assertEqual(json.loads(row['source_locator']), {'S03':locator})
        text = outputs[ROOT/'corpus'/(payload['scenarios'][0]['name']+'.md')]
        self.assertIn('部署段 \\| 续行<br>日期未载',text)

    def test_generated_lookup_sections_are_retrievable_in_battle_scope(self):
        battle = '红军长征-湘江战役-1934.11.25至1934.12.01'
        hits = rag.search('光华铺 S30 来源定位', battle=battle, top_k=12)
        self.assertTrue(any(h['section'].endswith('来源定位') for h in hits))
        self.assertTrue(all(h['source']==battle+'.md' or h['source'].startswith('红军长征/') for h in hits))

    def test_open_retrieval_excludes_timeline_and_loss_location_derivatives(self):
        battle = '红军长征-湘江战役-1934.11.25至1934.12.01'
        for phase in (None,'init','step'):
            hits = rag.search('事件来源定位 数字来源定位 12月1日17时 红10团伤亡',
                              battle=battle,simulation_mode='open',phase=phase,top_k=30)
            self.assertFalse({'事件来源定位','数字来源定位'} & {h['section'] for h in hits})

    def test_native_source_lookup_includes_scoped_quantity_and_location(self):
        from backend.agent_tools import exec_retrieve_history
        session=dict(battle_choice='红军长征-湘江战役-1934.11.25至1934.12.01',
                     scenario_input='',simulation_mode='replay',use_rag=True,history=[])
        result = exec_retrieve_history(session,dict(query='数字来源定位 红5师 两团 3000 S04'))
        paragraphs = result['passages']
        self.assertTrue(any(p['section']=='数字来源定位' and '3000余人' in p['text'] and '不分摊' in p['text'] for p in paragraphs))
        self.assertTrue({'推演目标、关键决策与反事实','争议与待考','作战过程与指挥时间线'} <= {p['section'] for p in paragraphs})
        self.assertLessEqual(sum(len(p['text']) for p in paragraphs),6400)

    def test_explicit_source_lookup_cannot_disable_rag_or_open_mode_filter(self):
        from backend.agent_tools import exec_retrieve_history
        session=dict(battle_choice='红军长征-湘江战役-1934.11.25至1934.12.01',
                     scenario_input='',simulation_mode='open',use_rag=True,history=[])
        result=exec_retrieve_history(session,dict(query='数字来源定位 红5师 两团 3000 S04'))
        self.assertFalse({'事件来源定位','数字来源定位'} & {p['section'] for p in result['passages']})
        session['use_rag']=False
        self.assertEqual(exec_retrieve_history(session,dict(query='数字来源定位'))['passages'],[])

    def test_unknown_and_scoped_zero_figures_survive_the_export(self):
        outputs = self.outputs['long_march']
        rows = list(csv.DictReader(io.StringIO(outputs[lm.DATA/'figures.csv'])))
        self.assertTrue(any(row['value']=='null' for row in rows))
        zero = [row for row in rows if row['value']=='0']
        self.assertEqual(len(zero),1)
        self.assertEqual((zero[0]['scenario_id'],zero[0]['source_ids']),('LM02','S32'))
        self.assertIn('中流前',zero[0]['scope'])

    def test_first_two_long_march_cards_have_per_source_review_locations(self):
        source = json.loads((lm.DATA/'scenarios.json').read_text(encoding='utf-8'))
        for scenario in source['scenarios'][:2]:
            for kind in ('forces','events','figures'):
                for row in scenario[kind]:
                    with self.subTest(scenario=scenario['id'],kind=kind):
                        self.assertEqual(set(row['sources']),set(row.get('source_locator',{})))
        command = source['scenarios'][0]['forces'][0]
        self.assertIn('S26',command['sources'])

    def test_heavy_column_daily_progress_is_not_a_universal_unit_speed(self):
        source = json.loads((lm.DATA/'scenarios.json').read_text(encoding='utf-8'))['scenarios'][0]
        rows = [e for e in source['events'] if e.get('process_reference')=='central_column_daily_march']
        self.assertEqual({e['date'] for e in rows},{'1934-11-26','1934-11-27','1934-11-28','1934-11-29'})
        for row in rows:
            self.assertIn('军委纵队',row['event'])
            self.assertIn('不是',row['event'])
            self.assertEqual(row['precision'],'日')
            self.assertEqual(row['sources'],['S03'])

    def test_new_xinxu_strength_is_scoped_and_not_distributed_into_regiments(self):
        source = json.loads((lm.DATA/'scenarios.json').read_text(encoding='utf-8'))['scenarios'][0]
        rows = [r for r in source['figures'] if r['metric']=='红5师参战兵力（两团合计）']
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['value'],rows[0]['qualifier'],rows[0]['sources']),(3000,'余人',['S04']))
        self.assertIn('不分摊',rows[0]['note'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
