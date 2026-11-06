"""Probe the frozen MCP child and its frozen mission proxy against real AFSIM."""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    from backend import afsim_world
    from verify_afsim_world import world
    from tools.afsim.launch import layout
    directory = ROOT / '.cache/qa/afsim-bridge/frozen'; directory.mkdir(parents=True, exist_ok=True)
    workspace = layout()['workspace'] / 'frozen-probe'; workspace.mkdir(parents=True, exist_ok=True)
    scene = afsim_world.compile_scene(world(), [{'unit':'甲','action':'move','lat':29.911,'lng':102.2308}], 900)
    scenario = workspace / 'probe.afsim'; scenario.write_text(scene['script'])
    messages = [
        {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'frozen-probe','version':'1'}}},
        {'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}},
        {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'run_mission','arguments':{
            'scenario':str(scenario),'background':False,'timeout_sec':30,'include_stdout':True,'stdout_chars':20000,
            'inert_is_failure':False,'no_evidence_is_failure':False,'not_analyzable_is_failure':False}}},
    ]
    env = dict(os.environ, GENTACTIX_PROJECT_ROOT=str(ROOT))
    env.pop('PYTHONPATH', None)
    process = subprocess.run([str(ROOT / 'dist-backend/gentactix-backend/gentactix-backend'), '--afsim-mcp'],
        input='\n'.join(json.dumps(item) for item in messages) + '\n', text=True,
        capture_output=True, env=env, timeout=60)
    (directory / 'stdout.jsonl').write_text(process.stdout)
    (directory / 'stderr.log').write_text(process.stderr)
    if process.returncode:
        raise RuntimeError(f'Frozen MCP exited {process.returncode}; see {directory}')
    replies = {item['id']: item for line in process.stdout.splitlines() if (item := json.loads(line)).get('id')}
    if 'error' in replies[3]:
        raise RuntimeError(replies[3]['error'])
    result = json.loads(replies[3]['result']['content'][0]['text'])
    (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    assert result['returncode'] == 0 and result['simulation_complete'], result.get('message', result)
    text = Path(result['stdout_path']).read_text(errors='replace') if result.get('stdout_path') else result.get('stdout', '')
    if not text:
        text = (workspace / 'mission.log').read_text(errors='replace')
    positions = afsim_world.parse_observations(text, scene)
    report = {'passed':True, 'frozen_mcp':True, 'frozen_mission_proxy':True,
              'real_afsim':True,'tools':len(replies[2]['result']['tools']), 'observed_entities':len(positions),'seconds':900}
    (directory / 'summary.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
