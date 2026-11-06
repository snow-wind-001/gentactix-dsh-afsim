"""Real isolated DSH process proposals; not historical battle acceptance."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Use --live for real model calls')
    root=Path('.cache/qa/cheqiao-complete/model')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(Path('.cache/qa/ww2-phases/runtime/llm.enc').resolve())
    from backend import dsh_simulation,harness_engine as h
    from gentactix import historical_operations as ho,missions
    from tools.qa.campaign_fixture import inputs
    result={'passed':False,'scope':'isolated process QA with actual DSH; not historical forces or full-battle acceptance','cases':[]}
    policy=h.role_policy('engine');assert policy['reasoning_effort']=='high' and policy['max_tokens']==65536
    def run(label,world,orders):
        observer=h.RunObserver(label);prior=copy.deepcopy(world);started=time.monotonic()
        with patch.object(missions,'advance',side_effect=AssertionError('No Python combat executor')):
            value,_,_=dsh_simulation.advance({'war_state':world,'time_step':'30分钟','turn_count':world['mission']['turn']},None,observer,
                fixed_orders=orders,instruction='这是过程校验。准确保持全部部队和收支；本轮仅执行指定命令，不虚构交战、损失、到货或工程。')
        after=value['updated_state'];assert world==prior;missions.validate(after)
        (root/(label+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        result['cases'].append({'label':label,'elapsed_s':round(time.monotonic()-started,2),
            'turn':after['mission']['turn'],'process':after['campaign'],'model_calls':len(observer.runs)})
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print('PASS',label,flush=True);return after
    try:
        initial=ho.initial(*inputs());orders=[{'unit':u['name'],'action':'hold'} for _,u in missions.units(initial)]
        first=run('waiting',initial,orders)
        name=initial['blue_units'][-1]['name'];assert not first['campaign']['actors'][name]['active']
        second=run('arrival-boundary',first,orders);assert second['campaign']['actors'][name]['active']
        result['passed']=True
    finally:
        h.close_harness()
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        Path('.cache/qa/cheqiao-complete/model-latest.json').write_text(json.dumps({'directory':str(root),'passed':result['passed']})+'\n')


if __name__=='__main__':main()
