"""Real native load probe from an untouched earned pending checkpoint."""
import argparse
import copy
import json
import os
from pathlib import Path
from unittest.mock import patch


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true');args=p.parse_args()
    if not args.live:p.error('--live required')
    base=Path('.cache/qa/deferred-support-2026-11-03');root=base/'native-pending-probes';root.mkdir(exist_ok=False)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
    from backend import afsim_world,harness_engine
    from gentactix import missions
    snapshot=json.loads((base/'afsim/expected-pending-cold.json').read_text());before=snapshot['war_state'];original=copy.deepcopy(before)
    unit=next(u for _,u in missions.units(before) if u.get('runtime_allocation',{}).get('support_remainder_policy'))
    assert unit['sustainment']['noncombat_remainder']==1.2 and unit['personnel']['current']==10000
    result=dict(passed=False,cases=[],actual_native=True,live_model_calls=False,manual_load_injection=False,
                scope='Native probes of actual earned checkpoint; no host session commit or full campaign/history acceptance.')
    try:
        for seconds in (.001,1800):
            scene=afsim_world.compile_scene(before,[dict(unit=u['name'],action='hold')for _,u in missions.units(before)],seconds,native_rules=True)
            with patch.object(missions,'advance',side_effect=AssertionError('No Python physics')),patch.object(harness_engine,'get_ai_response',side_effect=AssertionError('No LLM')):
                _,evidence=afsim_world.run_scene({},scene)
            identity=next(i for i,row in scene['entities'].items()if row['name']==unit['name'])
            nutrition=evidence['native_effects']['combined_arms']['nutrition'][identity]
            expected_loss,expected_load=(0,1.2)if seconds<1 else(2,.4)
            assert nutrition['noncombat_delta']==expected_loss and abs(nutrition['noncombat_remainder']-expected_load)<1e-6
            if seconds<1:assert nutrition['demand']==nutrition['consumed']==0
            assert evidence['returncode']==0 and before==original
            item=dict(seconds=seconds,nutrition=nutrition,returncode=evidence['returncode'],source_unchanged=True)
            result['cases'].append(item)
            (root/(str(seconds)+'s.json')).write_text(json.dumps(dict(scene=scene,evidence=evidence),ensure_ascii=False,indent=2)+'\n')
            print('PASS actual pending native probe',seconds,'seconds',nutrition,flush=True)
        result['passed']=True
    except Exception as exc:
        result['error']=str(exc);raise
    finally:
        harness_engine.close_harness();(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
