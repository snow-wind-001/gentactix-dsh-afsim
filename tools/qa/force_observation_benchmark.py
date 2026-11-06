"""Offline paging and 100 split/merge operations over the 79-leaf QA fixture."""
import json
from pathlib import Path
import platform
import time

from tools.qa.large_formation_fixture import inputs
from gentactix import historical_operations as ho,force_organization as forces,missions


def main():
    root=Path('.cache/qa/force-observation-2026-10-31');root.mkdir(parents=True,exist_ok=True)
    snapshot,parameters=inputs();world=ho.initial(snapshot,parameters)
    s=dict(id='force-page-qa',turn_count=0,role_epoch=0,product_mode='historical',simulation_mode='open',
           time_step='30分钟',execution_backend='narrative',war_state=world)
    original=missions.digest(s);metrics=[]
    for limit in (1,12,32):
        timings=[]
        for _ in range(5):
            start=time.perf_counter();response=forces.observation(s,{'kind':'members','limit':limit})
            timings.append(round((time.perf_counter()-start)*1000,3))
        metrics.append({'limit':limit,'returned':len(response['items']),
            'json_bytes':len(json.dumps(response,ensure_ascii=False).encode()),'latency_ms_samples':timings})
    args={'kind':'members','limit':12};members=[];pages=0
    while args:
        response=forces.observation(s,args);members+=response['items'];pages+=1;args=response['next_args']
    assert len(members)==79 and len({r['command_id'] for r in members})==79
    assert original==missions.digest(s)
    paging={'scope':'79 source identities with QA numbers; five samples per page size, no model calls',
        'page_metrics':metrics,'full_world_json_bytes':len(json.dumps(world,ensure_ascii=False).encode()),
        'all_members':79,'pages_at_12':pages,'world_unchanged':True}
    (root/'paging-benchmark.json').write_text(json.dumps(paging,ensure_ascii=False,indent=2)+'\n')
    ids=[r['command_id'] for r in members if r['team']=='red'][:2]
    s['force_organization']=forces.detach(s,ids,'初始群','QA已有叶子，不改变物理账')
    created={s['force_organization']['groups'][0]['id']};timings=[]
    for number in range(50):
        for kind in ('detach','merge'):
            start=time.perf_counter()
            if kind=='detach':value=forces.detach(s,[ids[0]],'分遣'+str(number),'QA临时抽调')
            else:value=forces.merge(s,[g['id'] for g in s['force_organization']['groups']],
                                    '合编'+str(number),'QA恢复统一指挥，未集结瞬移')
            timings.append((time.perf_counter()-start)*1000)
            latest=value['groups'][-1]['id'];assert latest not in created;created.add(latest)
            s['force_organization']=value
            assert missions.digest(s['war_state'])==missions.digest(world)
    forces.validate(s);group=s['force_organization']['groups'][0]
    assert set(forces.member_ids(s,group['id']))==set(ids)
    ordered=sorted(timings)
    reorg={'passed':True,'scope':'79 numerical QA leaves; 100 metadata transactions, no engine or model calls',
        'platform':platform.platform(),'python':platform.python_version(),'operations':100,
        'created_ids':len(created),'no_reused_ids':True,'physical_world_unchanged':True,
        'transaction_ms':{'p50':round(ordered[49],3),'p95':round(ordered[94],3),'max':round(max(ordered),3)},
        'organization_json_bytes':len(json.dumps(s['force_organization'],ensure_ascii=False).encode()),
        'final_organization_revision':s['force_organization']['revision']}
    (root/'reorg-100.json').write_text(json.dumps(reorg,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'paging':paging,'reorganization':reorg},ensure_ascii=False))


if __name__=='__main__':main()
