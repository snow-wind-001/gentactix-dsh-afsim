"""Recompile a failed native job from its saved pre-turn snapshot, in isolation."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native',action='store_true')
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--failed-job',type=Path,required=True)
    p.add_argument('--config',type=Path,required=True)
    args=p.parse_args()
    if not args.native:p.error('--native required')
    root=Path('.cache/qa/saved-turn-native-2026-10-29')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from backend import afsim_world,afsim_rules,harness_engine as h,runtime_bridge
    from backend.main import _native_tool_dispatch
    from gentactix import missions,sim_clock
    before=json.loads(args.snapshot.read_text())['war_state'];frozen=copy.deepcopy(before)
    failed=json.loads((args.failed_job/'entities.json').read_text())
    orders=failed['native_model']['orders']
    inputs={str(f.resolve()):hashlib.sha256(f.read_bytes()).hexdigest()
            for f in (args.snapshot,args.failed_job/'entities.json',args.failed_job/'scene.afsim',args.config)}
    result={'passed':False,'inputs':inputs,'model_calls':0,'source_turn':before['mission']['turn'],
            'scope':'original failed native orders; no saved-session mutation or model replanning'}
    runtime_bridge.register_dispatcher(_native_tool_dispatch)
    try:
        with patch.object(missions,'advance',side_effect=AssertionError('Python combat executor forbidden')), \
             patch.object(h,'get_ai_response',side_effect=AssertionError('No LLM in native replay')):
            scene=afsim_world.compile_scene(before,orders,failed['seconds'],native_rules=True)
            assert scene['native_model']['orders']==orders
            assert scene['entities']==failed['entities']
            assert '3e-12' not in scene['script'] and '0.000000000003' in scene['script']
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                afsim_world.apply_observations(before,positions,scene))
            after['current_time'],after['simulation_clock']=sim_clock.target(before,before['mission']['definition']['time_step'])
            after['afsim']=evidence;missions.validate(after)
            assert before==frozen and len(positions)==len(missions.units(before))
            for _,u in missions.units(after):
                person=u['personnel']
                assert person['current']+person['casualties']+person['noncombat_losses']==person['committed']
                for e in u['equipment']:assert e['operational']+e['damaged']+e['destroyed']==e['committed']
            assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest for path,digest in inputs.items())
            (root/'after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
            result.update(passed=True,turn=after['mission']['turn'],native=evidence,entity_count=len(positions))
    finally:
        h.close_harness()
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'passed':result['passed'],'root':str(root)},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
