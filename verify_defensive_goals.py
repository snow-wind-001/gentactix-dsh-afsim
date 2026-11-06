"""Defensive goals distinguish deployment contact from a physical breakthrough.

The locations, strengths and clock intervals below are software QA estimates,
not reconstructed historical positions or losses. Goal scoring runs no physics.
"""
import copy
import functools
import json
from pathlib import Path
import subprocess
import unittest

from gentactix import campaign_estimates as estimates, campaign_plan as plan
from gentactix import historical_operations as ho, missions
from tools.qa.campaign_plan_fixture import inputs
from verify_campaign_plan import step

RED = 'ww2.cn.division159'
BLUE = 'ww2.jp.division106'


def defensive_inputs():
    source, parameters = inputs()
    graph = parameters['campaign_plan']
    north = graph['nodes'][0]
    north['condition'].update(kind='defend', minimum_personnel=200, against_node='blue_exit')
    north['condition']['region']['radius_km'] = 2
    north['hold_seconds'] = 3600
    graph['nodes'][-1]['hold_seconds'] = 14400
    parameters['actors'][RED]['position'] = copy.deepcopy(north['condition']['region']['center'])
    parameters['actors'][BLUE]['position'] = dict(
        lat=parameters['actors'][RED]['position']['lat'],
        lng=parameters['actors'][RED]['position']['lng'] + .006)
    return source, parameters


def node(world, identity='north'):
    return next(n for n in plan.definition(world)['nodes'] if n['id'] == identity)


def predicate(world):
    return plan._predicate(world, node(world), plan._units(world))


@functools.lru_cache(maxsize=1)
def rendered_inputs():
    """Render the actual editor, including its script setup, through Vue SSR."""
    script = r"""
const fs=require('node:fs'), {parse,compileScript}=require('@vue/compiler-sfc');
const ts=require('typescript'), {createSSRApp}=require('vue'), {renderToString}=require('vue/server-renderer');
const file='src/components/CampaignGoalInputs.vue';
const {descriptor}=parse(fs.readFileSync(file,'utf8'),{filename:file});
const compiled=compileScript(descriptor,{id:'defensive-goal-inputs-test',inlineTemplate:true});
const code=ts.transpileModule(compiled.content,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const output={exports:{}};
new Function('require','module','exports',code)(require,output,output.exports);
const input=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const results={};for(const [name,value]of Object.entries(input)){
results[name]=await renderToString(createSSRApp(output.exports.default,{value,disabled:false}));
}process.stdout.write(JSON.stringify(results));})().catch(e=>{process.stderr.write(String(e));process.exitCode=1;});
"""
    _, parameters = defensive_inputs()
    defensive = parameters['campaign_plan']
    legacy = inputs()[1]['campaign_plan']
    result = subprocess.run(['node', '-e', script], input=json.dumps(dict(defensive=defensive, legacy=legacy)),
        cwd=Path(__file__).resolve().parent / 'frontend', capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class DefensiveGoalTests(unittest.TestCase):
    def make(self, edit=None):
        source, parameters = defensive_inputs()
        if edit:
            edit(parameters)
        return ho.initial(source, parameters)

    def test_frontline_contact_does_not_mean_core_breakthrough(self):
        world = self.make()
        truth, metrics, _, _ = predicate(world)
        self.assertTrue(truth)
        self.assertEqual(metrics['own_personnel_in_region'], 300)
        self.assertEqual(metrics['enemy_personnel_in_region'], 300)
        self.assertEqual(metrics['against_node'], 'blue_exit')
        self.assertFalse(metrics['breakthrough'])
        old_control = copy.deepcopy(node(world))
        old_control['condition'].pop('against_node')
        old_control['condition']['kind'] = 'control'
        self.assertFalse(plan._predicate(world, old_control, plan._units(world))[0])

    def test_core_entry_interrupts_defense_before_enemy_hold_completes(self):
        world = self.make()
        after = step(world, {BLUE: node(world, 'blue_exit')['condition']['region']['center']})
        red = after['campaign_plan']['nodes']['north']
        blue = after['campaign_plan']['nodes']['blue_exit']
        self.assertFalse(red['condition'])
        self.assertTrue(red['metrics']['breakthrough'])
        self.assertEqual(red['metrics']['enemy_personnel_in_core'], 300)
        self.assertEqual(blue['held_seconds'], 0)
        self.assertEqual(blue['status'], 'holding')

    def test_breach_resets_hold_and_enemy_exit_starts_a_new_sample(self):
        world = self.make()
        front = copy.deepcopy(next(u for u in world['blue_units'] if u['historical_unit_id'] == BLUE))
        a = step(world)
        b = step(a)
        self.assertEqual(b['campaign_plan']['nodes']['north']['held_seconds'], 1800)
        c = step(b, {BLUE: node(world, 'blue_exit')['condition']['region']['center']})
        self.assertEqual(c['campaign_plan']['nodes']['north']['held_seconds'], 0)
        d = step(c, {BLUE: {key: front[key] for key in ('lat', 'lng')}})
        self.assertEqual(d['campaign_plan']['nodes']['north']['held_seconds'], 0)
        e = step(d)
        self.assertEqual(e['campaign_plan']['nodes']['north']['held_seconds'], 1800)
        f = step(e)
        self.assertEqual(f['campaign_plan']['nodes']['north']['status'], 'completed')
        self.assertEqual(f['mission']['status'], 'active', 'Other directions are still unmet')

    def test_breach_uses_the_opponents_frozen_minimum_personnel(self):
        def edit(parameters):
            blue = parameters['campaign_plan']['nodes'][-1]
            blue['condition']['minimum_personnel'] = 301
            parameters['actors'][BLUE]['position'] = copy.deepcopy(blue['condition']['region']['center'])
        world = self.make(edit)
        truth, metrics, _, _ = predicate(world)
        self.assertTrue(truth)
        self.assertEqual(metrics['enemy_personnel_in_core'], 300)
        self.assertEqual(metrics['enemy_core_minimum_personnel'], 301)

    def test_enemy_node_activation_and_latched_status_do_not_hide_physical_breach(self):
        def edit(parameters):
            blue = parameters['campaign_plan']['nodes'][-1]
            blue.update(not_before_seconds=7200, latch=True)
            parameters['actors'][BLUE]['position'] = copy.deepcopy(blue['condition']['region']['center'])
        after = step(self.make(edit))
        self.assertEqual(after['campaign_plan']['nodes']['blue_exit']['status'], 'waiting_time')
        self.assertFalse(after['campaign_plan']['nodes']['north']['condition'])

    def test_insufficient_ready_defenders_and_suppression_prevent_holding(self):
        world = self.make(lambda p: p['campaign_plan']['nodes'][0]['condition'].update(minimum_personnel=301))
        self.assertFalse(predicate(world)[0])
        world = self.make()
        next(u for u in world['red_units'] if u['historical_unit_id'] == RED)['formation']['suppression'] = 65
        self.assertFalse(predicate(world)[0])

    def test_future_arrival_cannot_contribute_ready_defenders(self):
        world = self.make(lambda p: p['campaign']['arrivals'][RED].update(not_before='1938-10-07T02:00'))
        after = step(world)
        state = after['campaign_plan']['nodes']['north']
        self.assertEqual(state['status'], 'waiting_arrival')
        self.assertEqual(state['metrics']['own_personnel_in_region'], 0)

    def test_outside_operation_zone_cannot_hold_a_deployment_region(self):
        source, parameters = defensive_inputs()
        center = copy.deepcopy(parameters['area']['center'])
        parameters['actors'][BLUE]['position'] = copy.deepcopy(center)
        outside = dict(lat=center['lat'] + .012, lng=center['lng'])
        parameters['operation_boundary'] = dict(version='operation-boundary-1', center=center,
            radius_km=1, assumption='QA作战区边界，非史实', routes=[dict(id='red-exit', team='red',
                inside=copy.deepcopy(center), outside=copy.deepcopy(outside), corridor_km=.08,
                assumption='QA登记通路，非史实')])
        parameters['campaign_plan']['nodes'][0]['condition']['region']['radius_km'] = .1
        world = ho.initial(source, parameters)
        # Observe a later exit; opening placement must still be inside the zone.
        next(u for u in world['red_units'] if u['historical_unit_id'] == RED).update(outside)
        truth, metrics, status, _ = predicate(world)
        self.assertFalse(truth)
        self.assertEqual(metrics['own_personnel_in_region'], 0)
        self.assertEqual(status, 'blocked')

    def test_rear_reserve_inside_deployment_region_cannot_hold(self):
        from gentactix import unit_participation
        from verify_unit_participation import physical, order
        world = self.make()
        unit = next(u for u in world['red_units'] if u['historical_unit_id'] == RED)
        point = dict(lat=unit['lat'] + .0002, lng=unit['lng'])
        after = physical(world, unit['name'], point)
        unit_participation.advance(world, after, [order(unit['name'], point)], 1800,
                                   source='dsh_model_estimate')
        self.assertEqual(unit_participation.unit_view(after, next(u for u in after['red_units']
            if u['historical_unit_id'] == RED), 'red')['status'], 'reserve')
        truth, metrics, status, _ = predicate(after)
        self.assertFalse(truth)
        self.assertEqual(metrics['own_personnel_in_region'], 0)
        self.assertEqual(status, 'blocked')

    def test_invalid_reference_targets_are_rejected_without_recursive_evaluation(self):
        for reference in ('unknown', 'north', 'south', 'preserve'):
            with self.subTest(reference=reference), self.assertRaisesRegex(ValueError, '防御|对抗|突破'):
                self.make(lambda p: p['campaign_plan']['nodes'][0]['condition'].update(against_node=reference))
        for kind in ('control', 'preserve', 'defend'):
            source, parameters = defensive_inputs()
            target = parameters['campaign_plan']['nodes'][-1]
            if kind == 'preserve':
                target['condition'] = dict(kind=kind, minimum_fraction=.5)
            else:
                target['condition']['kind'] = kind
                if kind == 'defend':
                    target['condition']['against_node'] = 'north'
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, '防御|对抗|突破'):
                ho.initial(source, parameters)

    def test_scoring_is_idempotent_and_never_changes_physical_ledgers(self):
        world = self.make()
        before = copy.deepcopy(world)
        predicate(world)
        self.assertEqual(world, before)
        after = step(world)
        scored = copy.deepcopy(after)
        missions.evaluate(after)
        self.assertEqual(after, scored)
        for field in ('red_units', 'blue_units', 'supply_nodes', 'combined_arms'):
            self.assertEqual(after[field], world[field])
        self.assertTrue(missions.validate(after))

    def test_fixed_estimate_template_cannot_redirect_the_defense_to_another_axis(self):
        from tools.qa.wanjialing_estimate_fixture import inputs as estimated_inputs
        source, parameters = estimated_inputs()
        cfg = parameters['campaign_scope']['window']['definition']['parameter_estimates']
        for nodes in (cfg['goal_template']['nodes'], parameters['campaign_plan']['nodes']):
            nodes[0]['condition'].update(kind='defend', against_node='blue_exit')
        estimates.validate_parameters(source, parameters)
        parameters['campaign_plan']['nodes'][0]['condition']['against_node'] = 'blue_relief'
        before = copy.deepcopy(parameters)
        with self.assertRaisesRegex(ValueError, '目标|对抗|突破'):
            estimates.validate_parameters(source, parameters)
        self.assertEqual(parameters, before)

    def test_template_rejects_bad_binding_even_when_numeric_fields_are_unfilled(self):
        from tools.qa.wanjialing_estimate_fixture import inputs as estimated_inputs
        source, parameters = estimated_inputs()
        window = parameters['campaign_scope']['window']['definition']
        cfg = window['parameter_estimates']
        cfg['goal_template']['nodes'][0]['condition'].update(kind='defend', against_node='red_block')
        before = copy.deepcopy(cfg)
        with self.assertRaisesRegex(ValueError, '防御|对抗|突破'):
            estimates.validate_definition(cfg, window, source, list(parameters['actors']))
        self.assertEqual(cfg, before)

    def test_formal_split_preserves_the_same_hold_and_counts_disjoint_descendants(self):
        from gentactix import formation_continuity as continuity, synthetic_history
        from verify_formation_continuity import proposal
        source, parameters = defensive_inputs()
        binding = ho.initial(source, parameters)['mission']['definition']['historical_calculation']
        config = synthetic_history.seed(binding)['configuration']
        world = missions.from_definition(synthetic_history.definition(binding, config))
        world = step(step(world))
        before = copy.deepcopy(world)
        prepared = continuity.prepare(world, proposal(world), team='red')['world']
        self.assertTrue(predicate(prepared)[0])
        self.assertEqual(predicate(prepared)[1]['own_personnel_in_region'], 300)
        self.assertEqual(prepared['campaign_plan']['nodes']['north'], world['campaign_plan']['nodes']['north'])
        self.assertEqual(world, before)
        self.assertEqual(sum(len(g) for g in plan.selection_groups(prepared, node(prepared))), 2)

    def test_new_window_is_explicit_and_keeps_previous_versions_sources_and_envelopes(self):
        from gentactix import campaign_windows as windows
        from tools.build_defensive_campaign import build
        old = windows.load('WH-northern-sep17-18', '1.1.0')
        default = windows.pin('WH-northern-sep17-18')
        new = build()
        self.assertEqual(windows.load('WH-northern-sep17-18', '1.2.0'), new)
        self.assertEqual(new['historical_initial'], old['historical_initial'])
        for field in ('bounds', 'units', 'sectors', 'milestones', 'phase_ids'):
            self.assertEqual(new[field], old[field])
        for field in ('area', 'actors', 'goal_regions'):
            self.assertEqual(new['parameter_estimates'][field], old['parameter_estimates'][field])
        graph = new['parameter_estimates']['goal_template']
        for identity, target in [('red_mountain', 'blue_mountain'), ('red_plain', 'blue_plain')]:
            condition = next(n['condition'] for n in graph['nodes'] if n['id'] == identity)
            self.assertEqual((condition['kind'], condition['against_node']), ('defend', target))
        self.assertEqual(windows.load('WH-northern-sep17-18', '1.1.0'), old)
        self.assertEqual(windows.pin('WH-northern-sep17-18'), default)

    def test_editor_explains_contact_and_names_the_bound_opposing_core(self):
        html = rendered_inputs()['defensive']
        self.assertIn('部署区允许接敌', html)
        self.assertIn('保持部署人数', html)
        self.assertIn('蓝方到达估计突围地域', html)
        self.assertIn('不等待对方保持计时', html)

    def test_legacy_editor_does_not_show_a_defensive_binding(self):
        html = rendered_inputs()['legacy']
        self.assertIn('最少到达人员', html)
        self.assertNotIn('部署区允许接敌', html)

    def analysis_session(self, world):
        return dict(id='defensive-goal-analysis-qa', war_state=world,
                    turn_count=world['mission']['turn'], time_step='30分钟', execution_backend='afsim')

    def test_analysis_prompt_distinguishes_deployment_enemy_and_core_enemy(self):
        from backend import afsim_state
        text = afsim_state.analysis_prompt(self.analysis_session(self.make()), '为什么防守目标未完成？')
        for term in ('enemy_personnel_in_region', 'enemy_personnel_in_core', '不能互换', '不等待对方'):
            self.assertTrue(term in text, 'Readonly defense analysis lacks: ' + term)

    def test_visible_goal_facts_keep_contact_separate_from_core_breach(self):
        from backend import afsim_state
        world = step(self.make())
        saved = copy.deepcopy(world)
        text = afsim_state.analysis_facts(self.analysis_session(world))
        self.assertIn('部署区敌军300人', text)
        self.assertIn('突破核心敌军0人', text)
        self.assertIn('北侧方向控制', text)
        self.assertIn('蓝方到达估计突围地域', text)
        self.assertEqual(world, saved)
        breached = step(world, {BLUE: node(world, 'blue_exit')['condition']['region']['center']})
        text = afsim_state.analysis_facts(self.analysis_session(breached))
        self.assertIn('突破核心敌军300人', text)
        self.assertIn('达到门槛即中断', text)
        self.assertEqual(breached['campaign_plan']['nodes']['blue_exit']['held_seconds'], 0)

    def test_pending_goal_facts_preserve_unknown_metrics_instead_of_zero(self):
        from backend import afsim_state
        text = afsim_state.analysis_facts(self.analysis_session(self.make()))
        self.assertIn('防御目标尚未采样', text)
        self.assertNotIn('部署区敌军0人', text)
        self.assertNotIn('突破核心敌军0人', text)

    def test_legacy_control_analysis_keeps_its_original_fact_scope(self):
        from backend import afsim_state
        world = ho.initial(*inputs())
        session = self.analysis_session(world)
        self.assertNotIn('防御部署区', afsim_state.analysis_prompt(session, '当前态势'))
        self.assertNotIn('防御目标尚未采样', afsim_state.analysis_facts(session))


if __name__ == '__main__':
    unittest.main()
