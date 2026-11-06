"""Opt-in legacy-budget and resource-feedback checks using existing SDK paths."""
import argparse
import copy
import json
from pathlib import Path

ROOT=Path('.cache/qa/sustainment-feedback-2026-11-02/live')


def save(name,value):
    path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise ValueError('Preserve existing evidence: '+str(path))
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def session(parts=1):
    from verify_legacy_sustainment import partitioned
    from gentactix import commands
    w=partitioned(parts=parts,deadline=6,synthetic=True)
    s=dict(id='de'*6,role_epoch=0,war_state=w,turn_count=0,time_step='30分钟',agent_mode='native',
        product_mode='synthetic',simulation_mode='open',execution_backend='afsim',mission_id=w['mission']['id'],
        history=[],decision_log=[],trajectory=[])
    s['command_state']=commands.replace_queue(s,[],control_team='red',director=True,no_fire=False,intent='合成保障QA')
    return s


def holds(s):
    from gentactix import commands
    return [dict(unit_id=i,action='hold',duration='next') for i,(_,u) in commands.resolve_units(s).items() if commands.available(u)]


def facts(s):
    from gentactix import formation_parts
    units=s['war_state']['red_units']
    return dict(turn=s['turn_count'],elapsed_seconds=s['war_state']['simulation_clock']['elapsed_seconds'],
        units=len(units),committed=sum(u['personnel']['committed'] for u in units),current=sum(u['personnel']['current'] for u in units),
        noncombat=sum(u['personnel']['noncombat_losses'] for u in units),
        fraction=sum(u['formation'].get('partition_noncombat_remainder',0) for u in units if formation_parts.is_fragment(u)))


def execute(s,backend,label):
    from backend import formation_execution,harness_engine as h
    from gentactix import formation_session
    before=copy.deepcopy(s);save(label+'/before.json',s);observer=h.RunObserver(label)
    result=formation_execution.trial(s,holds(s),observer,backend=backend,instruction=(
        '合成保障软件QA，非历史饥饿率。双方全部待命，无交战、无航空，不得新增战斗伤亡。'
        '补给仓库存为零、红方随队粮食为零；按已给旧保障预算和分队余量规则提交模型结果。'
        '需要变化的余量必须通过legacy-noncombat-1的sustainment_ledger显式提交，不要直接写formation内部余量。'
        '保持既有损失和投入，不能恢复旧人装，不能把每回合率称作每小时率。使用Native预览及战报。'))
    after=result['session'];assert s==before
    if backend=='afsim':assert 'dsh_execution' not in after['war_state']
    else:assert 'afsim' not in after['war_state']
    formation_session.validate(json.loads(json.dumps(after)))
    save(label+'/after.json',after);save(label+'/result.json',result['result'])
    save(label+'/review.json',dict(passed=True,backend=backend,operation_id=observer.operation_id,
        before=facts(s),after=facts(after),source_unchanged=True,runtime_admitted=False))
    print('PASS actual',label,facts(after),flush=True)
    return after


def native():
    rows=[]
    for parts in (1,4):
        s=session(parts);after=execute(s,'afsim','native-'+str(parts)+'-validated');row=facts(after)
        assert row['noncombat']+row['fraction']==2
        rows.append(row)
    save('native-review.json',dict(passed=True,rows=rows,scope='integer loss plus stored fractional exposure; not identical integer counts each step'))


def chain(resume=False,tag=''):
    from gentactix import formation_conversion as fc,formation_session as fs
    if resume:
        s=json.loads((ROOT/'chain-converted.json').read_text());fs.validate(s)
        assert facts(s)['turn']==1 and facts(s)['current']==5998 and facts(s)['noncombat']==2
    else:
        s=execute(session(),'afsim','chain-1-native');assert facts(s)['noncombat']==2
        parent=s['war_state']['red_units'][0]
        p=fc.split_current(parent,[dict(id='p'+str(i),label='运行中保障'+str(i),committed=1500) for i in range(4)],
            assumption='有损状态的合成软件QA，非历史编制命令',operation_id='d'*32,product_mode='synthetic',historical_snapshot=s['war_state']['historical_initial'])
        s=fs.prepare(s,p,team='red')['session'];save('chain-converted.json',s)
        assert facts(s)['current']==5998 and facts(s)['noncombat']==2
    rows=[];prefix='chain-'+tag if tag else ('chain-feedback' if resume else 'chain')
    for turn,backend,nc,fraction in [(2,'narrative',2,2),(3,'afsim',6,0),(4,'narrative',6,2),(5,'afsim',10,0)]:
        s=execute(s,backend,f'{prefix}-{turn}-{backend}');row=facts(s)
        assert row['noncombat']==nc and row['fraction']==fraction and row['committed']==6000,row
        assert row['noncombat']+row['fraction']==2*turn and row['elapsed_seconds']==turn*1800,row
        rows.append(row)
    save(prefix+'-review.json',dict(passed=True,source_had_real_noncombat_losses=2,backend_switches=4,
        cold_json_validation=True,rows=rows,runtime_admitted=False,scope='isolated registered-roster Native/DSH/WSF continuity, not public save or history calibration'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('case',choices=['native','chain','mixed','observe'])
    parser.add_argument('--live',action='store_true');parser.add_argument('--resume-chain',action='store_true')
    parser.add_argument('--tag',default='');args=parser.parse_args()
    if not args.live:parser.error('Explicit --live is required')
    if args.resume_chain and args.case!='chain':parser.error('--resume-chain requires chain')
    if args.tag and (args.case!='chain' or not all(c.isalnum() or c=='-' for c in args.tag)):
        parser.error('--tag requires chain and a simple alphanumeric/hyphen label')
    from . import formation_execution_live as base,fire_effect_live as previous
    base.ROOT=ROOT;previous.ROOT=ROOT;base.boot()
    from backend import harness_engine as h
    try:
        if args.case=='native':native()
        elif args.case=='chain':chain(args.resume_chain,args.tag)
        elif args.case=='mixed':previous.mixed()
        else:previous.observe()
    finally:h.close_harness()


if __name__=='__main__':main()
