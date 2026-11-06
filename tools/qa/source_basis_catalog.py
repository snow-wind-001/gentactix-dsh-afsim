"""Load all source-derived exercise seeds into real AFSIM; no model calls.

This validates bootstrap syntax/identity and ledger telemetry, not historical
combat effectiveness, phases or every possible user configuration.
"""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--native',action='store_true');a=p.parse_args()
    if not a.native:p.error('--native is required')
    out=ROOT/'.cache/qa/history-process/source-catalog';out.mkdir(parents=True,exist_ok=True)
    os.environ.update(GENTACTIX_SESSION_DIR=str(out/'sessions'),GENTACTIX_TRACE_DIR=str(out/'traces'),GENTACTIX_DSH_HOME=str(out/'dsh-home'),GENTACTIX_DSH_WORKSPACE=str(out/'workspace'),GENTACTIX_ROLE_INDEX=str(out/'roles.json'),GENTACTIX_DSH_PATCHES='[]')
    from backend import main,scenario_builder as b,harness_engine as h,afsim_world
    from gentactix import combined_arms,scenario_basis,missions
    rows=[]
    try:
        for spec in combined_arms.catalog():
            seed=scenario_basis.exercise_seed(spec['id']);world,scene=b.validate_configuration(spec['id'],seed['configuration'])
            positions,evidence=afsim_world.run_scene({'id':'catalog-'+spec['id']},scene)
            afsim_world.apply_observations(world,positions,scene)
            assert evidence['source']=='dsh_native_mcp_controller' and evidence['returncode']==0
            assert len(positions)==sum(len(world[t+'_units']) for t in ('red','blue'))
            assert len(evidence.get('native_effects',{}).get('units',{}))==len(positions)
            row={'battle':spec['battle'],'passed':True,'entities':len(positions),'wall_ms':evidence['wall_ms'],'artifact':evidence.get('artifact')}
            rows.append(row);print('PASS',spec['battle'],flush=True)
            (out/'result.json').write_text(json.dumps({'count':len(rows),'model_calls':0,'historical_validation':False,'results':rows},ensure_ascii=False,indent=2))
    finally:h.close_harness()
    print('PASSED',len(rows),'source-derived native bootstrap scenes',flush=True)


if __name__=='__main__':main()
