"""Real registered-roster branches through existing AFSIM/DSH pipelines.

Only copied prior QA states are read. Result frames are artifacts, not imported
games or runtime conversion commits. Every local setup is a modeling estimate.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import time

ROOT=Path('.cache/qa/formation-execution-2026-11-02')
SOURCE=Path('.cache/qa/formation-conversion-2026-11-02')


def save(name,value):
    p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():raise ValueError('Preserve evidence: '+str(p))
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def boot():
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str((ROOT/'runtime'/suffix).resolve())
    from backend import main,runtime_bridge
    runtime_bridge.register_dispatcher(main._native_tool_dispatch)


def source():
    c=json.loads((SOURCE/'equipped-afsim/case.json').read_text());p=SOURCE/'api/sessions'/(c['session_id']+'.json')
    return json.loads(p.read_text())['session'],p,hashlib.sha256(p.read_bytes()).hexdigest()


def prepare(parts,target_parts=1):
    from gentactix import commands,formation_conversion as fc,formation_session as fs
    s,_,_=source();s=copy.deepcopy(s)
    u=next(u for u in s['war_state']['red_units'] if u.get('source_historical_unit_id')=='ww2.cn.division159')
    if parts>1:
        total=u['personnel']['committed'];weights=[total//parts+(i<total%parts) for i in range(parts)]
        p=fc.split_current(u,[dict(id='p'+str(i),label='粒度QA'+str(i),committed=n) for i,n in enumerate(weights)],
            assumption='仅实际执行与粒度QA，非历史兵额或部署',operation_id='a'*32,product_mode='synthetic',historical_snapshot=s['war_state']['historical_initial'])
        s=fs.prepare(s,p,team='red')['session']
    if target_parts>1:
        u=next(u for u in s['war_state']['blue_units'] if u.get('source_historical_unit_id')=='ww2.jp.division106')
        total=u['personnel']['committed'];weights=[total//target_parts+(i<total%target_parts) for i in range(target_parts)]
        p=fc.split_current(u,[dict(id='p'+str(i),label='目标粒度QA'+str(i),committed=n) for i,n in enumerate(weights)],
            assumption='仅等总量、同地成对粒度QA，非历史部署',operation_id='b'*32,product_mode='synthetic',historical_snapshot=s['war_state']['historical_initial'])
        s=fs.prepare(s,p,team='blue')['session']
    return s


def drafts(s,action):
    from gentactix import commands
    units=commands.resolve_units(s)
    targets=[i for i,(_,u) in units.items() if u.get('source_historical_unit_id')=='ww2.jp.division106']
    attackers=[i for i,(_,u) in units.items() if u.get('source_historical_unit_id')=='ww2.cn.division159']
    if len(targets)>1 and len(targets)!=len(attackers):raise ValueError('成对对照须覆盖完整且等数的双方分队')
    result=[]
    for identity,(row,u) in units.items():
        if not commands.available(u):continue
        own=u.get('source_historical_unit_id')=='ww2.cn.division159'
        order=dict(unit_id=identity,action=action if own else 'hold',duration='next')
        if own and action in ('fire','bombard','suppress'):order['target_id']=targets[attackers.index(identity)%len(targets)]
        result.append(order)
    return result


def facts(s):
    from gentactix import missions,formation_parts
    w=s['war_state'];out={}
    for team in ('red','blue'):
        units=w[team+'_units']
        out[team]=dict(personnel={k:sum(u['personnel'][k] for u in units) for k in ('committed','current','casualties','noncombat_losses')},
            equipment={c:{k:sum(e[k] for u in units for e in u['equipment'] if e['category']==c) for k in ('committed','operational','damaged','destroyed')}
                for c in ('armor','artillery','air_defense','engineer','transport')},
            stock={k:sum(u['formation'][k] for u in units) for k in ('fuel_liters','spares','materials','shells','aa_rounds')},
            normalized={k:sum(u['logistics'][k]*formation_parts.scale(u) for u in units) for k in ('food','ammo')})
    return dict(turn=s['turn_count'],elapsed_seconds=w['simulation_clock']['elapsed_seconds'],units=len(missions.units(w)),teams=out)


def run(backend,parts,action,*,target_parts=1,tag=''):
    from backend import formation_execution as engine,harness_engine as h
    from gentactix import missions
    name=backend+'-'+str(parts)+'-'+action+('-target'+str(target_parts) if target_parts>1 else '')+('-'+tag if tag else '');folder=ROOT/name
    if folder.exists():raise ValueError('Preserve existing case: '+name)
    s=prepare(parts,target_parts);_,p,before_hash=source();before=copy.deepcopy(s);saved=facts(s)
    save(name+'/before.json',s);observer=h.RunObserver('编组执行QA '+name);start=time.monotonic()
    summary=dict(passed=False,backend=backend,parts=parts,target_parts=target_parts,action=action,actual_engine=backend=='afsim',actual_model=backend=='narrative',before=saved)
    try:
        value=engine.trial(s,drafts(s,action),observer,backend=backend,
            instruction='仅本次隔离QA：保持现有伤损和投入，严格执行已固定的双方命令；正确使用运行中计算分队的根账尺度，不得新增或恢复人员装备。')
        after=value['session'];save(name+'/after.json',after)
        save(name+'/result.json',value['result']);save(name+'/commands.json',dict(orders=value['orders'],decisions=value['decisions']))
        assert s==before and hashlib.sha256(p.read_bytes()).hexdigest()==before_hash
        assert after['turn_count']==s['turn_count']+1
        for team,u in missions.units(after['war_state']):
            old=next(v for side,v in missions.units(s['war_state']) if side==team and v['name']==u['name'])
            assert u['personnel']['committed']==old['personnel']['committed']
            assert u['personnel']['casualties']>=old['personnel']['casualties']
            assert all(e['committed']==o['committed'] for e,o in zip(u['equipment'],old['equipment']))
        if parts>1:
            refused=False
            try:missions.validate(after['war_state'])
            except ValueError:refused=True
            assert refused,'QA execution is not public runtime admission'
        summary.update(passed=True,after=facts(after),source_checkpoint_unchanged=True,
            elapsed_seconds=round(time.monotonic()-start,2),runtime_admitted=False,
            external_execution=value['result'].get('external_execution'),native_operation_id=observer.operation_id)
        print('PASS actual',name,'elapsed',summary['elapsed_seconds'],flush=True)
    finally:save(name+'/review.json',summary)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('backend',choices=['afsim','narrative']);p.add_argument('--parts',type=int,choices=[1,2,4,16],default=2)
    p.add_argument('--action',choices=['hold','fire','bombard','suppress'],default='hold');p.add_argument('--target-parts',type=int,choices=[1,2,4,16],default=1)
    p.add_argument('--tag',default='');p.add_argument('--live',action='store_true');a=p.parse_args()
    if not a.live:p.error('Actual external execution requires --live')
    boot()
    try:run(a.backend,a.parts,a.action,target_parts=a.target_parts,tag=a.tag)
    finally:
        from backend import harness_engine
        harness_engine.close_harness()
