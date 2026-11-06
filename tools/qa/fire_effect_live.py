"""Opt-in Native acceptance probes; writes only isolated QA artifacts."""
import argparse
import copy
import json
from pathlib import Path

ROOT=Path('.cache/qa/fire-effect-admission-2026-11-02/live')


def save(name,value):
    path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise ValueError('Preserve existing evidence: '+str(path))
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def mixed():
    from .fire_effect_fixture import mixed_air_capture
    from backend import dsh_simulation,harness_engine as h
    from gentactix import missions
    world,value,target,_=mixed_air_capture()
    s=dict(id='bc'*6,war_state=world,turn_count=0,time_step='30分钟',execution_backend='narrative',
        agent_mode='native',simulation_mode='open')
    before=copy.deepcopy(s);observer=h.RunObserver('航空与受降分项QA')
    save('mixed/before.json',s);save('mixed/fixed-orders.json',value['orders'])
    result,orders,_=dsh_simulation.advance(s,None,observer,fixed_orders=value['orders'],instruction=(
        '这是固定结果的合成软件QA，不是历史重现，也不是物理效能标定。只执行已固定命令。'
        '本次检查明确要求：航空任务personnel_effect=4、equipment_effect=0、aircraft_lost=0；'
        '同一目标本轮captured_this_turn=10，captured累计从已证明零合计的初态增加10；'
        '新增casualties合计14，地面火力减员0。分别对账，不能把被俘算成航空战果。'
        '正确填写航空油弹、完整起飞／打击／返场事件、campaign和归一化分队资源账。'
        '目标的原有缺载分类不任意填0。使用Native预览与正式战报提交。'))
    after=copy.deepcopy(s);after.update(war_state=result['updated_state'],turn_count=1)
    missions.validate(after['war_state']);assert s==before
    receipt=next(r for r in after['war_state']['dsh_execution']['effect_admission']['units'] if r['unit']==target['name'])
    assert (receipt['air_casualties'],receipt['captured'],receipt['ground_casualties'])==(4,10,0),receipt
    save('mixed/after.json',after);save('mixed/result.json',result)
    save('mixed/review.json',dict(passed=True,fixed_test_effects=True,source_world_unchanged=True,
        operation_id=observer.operation_id,orders=orders,receipt=receipt,
        scope='Real Native SDK tool/submission acceptance of explicitly fixed synthetic effects; not independent physics or history'))
    print('PASS actual Native mixed air/capture fixed QA, no ground-loss double counting',flush=True)


def observe():
    from backend import afsim_state,harness_engine as h
    path=ROOT/'mixed/after.json';s=json.loads(path.read_text());before=copy.deepcopy(s)
    target=next(u for u in s['war_state']['blue_units'])
    observer=h.RunObserver('只读效能约束问答QA')
    answer=h.get_ai_response(
        '只读检查：请调用get_afsim_observation读取当前目标单位effect_constraint，不能用旧对话猜测，不能提交候选或下令。'
        '返回扁平JSON，字段unit、ground_casualties、ground_maximum、air_casualties、captured、calibration_proven。'
        'unit使用敌方单位精确名称。要区分实际估计、保守上界、航空、被俘与历史标定证明。',
        role_id=None,observer=observer,native_context=afsim_state.operation_context(s))
    save('mixed/observation-answer.json',answer)
    assert s==before and answer['unit']==target['name']
    expected=dict(ground_casualties=0,ground_maximum=0,air_casualties=4,captured=10,calibration_proven=False)
    assert all(answer.get(k)==v for k,v in expected.items()),answer
    save('mixed/observation-review.json',dict(passed=True,operation_id=observer.operation_id,
        checked_facts=expected,source_world_unchanged=True,scope='Actual model factual reading; public tool calls audited separately'))
    print('PASS actual Native read-only effect constraint facts',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('case',choices=['native','dsh','mixed','observe'])
    parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('Explicit --live is required')
    from . import formation_execution_live as base
    base.ROOT=ROOT;base.boot()
    from backend import harness_engine as h
    try:
        if args.case=='native':
            base.run('afsim',1,'bombard',tag='shared-formulas');base.run('afsim',2,'bombard',tag='shared-formulas')
        elif args.case=='dsh':base.run('narrative',4,'bombard',target_parts=4,tag='bound-final')
        elif args.case=='mixed':mixed()
        else:observe()
    finally:h.close_harness()


if __name__=='__main__':main()
