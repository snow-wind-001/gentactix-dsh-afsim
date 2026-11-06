"""Render the actual AFSIM status template to check execution-scope claims."""
import functools
import json
from pathlib import Path
import subprocess
import unittest


@functools.lru_cache(maxsize=1)
def rendered_states():
    script = r"""
const fs = require('node:fs');
const {parse, compileTemplate} = require('@vue/compiler-sfc');
const ts = require('typescript');
const {createSSRApp} = require('vue');
const {renderToString} = require('vue/server-renderer');
const file = 'src/components/AFSimPanel.vue';
const {descriptor} = parse(fs.readFileSync(file, 'utf8'), {filename: file});
const compiled = compileTemplate({source: descriptor.template.content, filename: file, id: 'afsim-status-test'});
if (compiled.errors.length) throw Error(JSON.stringify(compiled.errors));
const output = ts.transpileModule(compiled.code, {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText;
const componentModule = {exports: {}};
new Function('require', 'module', 'exports', output)(require, componentModule, componentModule.exports);
const component = {props: ['evidence', 'modeled', 'hostGoals'], render: componentModule.exports.render};
const base = {source: 'dsh_native_mcp_controller', status: 'completed', returncode: 0,
  entity_count: 8, seconds: 3600, wall_ms: 1200, effects_source: 'afsim-native-teaching-1'};
const cases = {covered: {...base, model_skipped: true},
  planner: {...base, model_skipped: false, planner_prompt_chars: 1234},
  initial: {...base, phase: 'initial_state_validation', model_skipped: true},
  replay: {...base, phase: 'historical_replay', model_skipped: true}};
(async () => {
  const result = {};
  for (const [name, evidence] of Object.entries(cases)) {
    result[name] = await renderToString(createSSRApp(component, {evidence, modeled: true, hostGoals: true}));
  }
  process.stdout.write(JSON.stringify(result));
})().catch(error => {process.stderr.write(String(error)); process.exitCode = 1;});
"""
    process = subprocess.run(['node', '-e', script],
        cwd=Path(__file__).resolve().parent / 'frontend', capture_output=True, text=True, timeout=30)
    if process.returncode:
        raise AssertionError(process.stderr)
    return json.loads(process.stdout)


class AFSimStatusUITests(unittest.TestCase):
    def test_covered_orders_do_not_claim_unit_agents_were_not_called(self):
        # model_skipped only means all orders covered the global planner's work;
        # real Native unit decisions can already exist for the same frame.
        html = rendered_states()['covered']
        self.assertNotIn('人工命令完整', html)
        self.assertNotIn('未调用模型。', html)
        self.assertIn('全局规划模型', html)
        self.assertIn('单位Agent', html)

    def test_global_planner_preserves_its_recorded_prompt_size(self):
        self.assertIn('1234 字符', rendered_states()['planner'])

    def test_initial_load_does_not_claim_a_completed_physical_turn(self):
        html = rendered_states()['initial']
        self.assertIn('战局时钟尚未推进', html)
        self.assertNotIn('本轮命令已覆盖', html)

    def test_historical_frame_keeps_its_separate_execution_scope(self):
        html = rendered_states()['replay']
        self.assertIn('未调用模型生成状态', html)
        self.assertIn('未运行开放战损规则', html)


if __name__ == '__main__':
    unittest.main()
