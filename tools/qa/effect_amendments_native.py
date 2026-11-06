"""Actual Native explicit-edit protocol probe on a retained22-actor world.

The all-hold candidate is a deterministic QA fixture. This tests Native public
evidence replay, not independent model physics or historical effectiveness.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if not args.live:parser.error('--live required')
    root=args.out.resolve()
    if root.exists():parser.error('Preserve previous evidence')
    root.mkdir(parents=True)
    for name,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                        ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+name]=str(root/suffix)
    from backend import harness_engine as h,runtime_bridge,turn_preview as p,effect_amendments as a
    from backend.main import _native_tool_dispatch
    from tools.qa.turn_preview_page_fixture import candidate
    from gentactix import missions
    current=json.loads(args.input.read_text());saved=copy.deepcopy(current)
    observer=h.RunObserver('Native22 explicit effect amendments, readonly protocol QA')
    good=candidate(current['war_state']);bad=copy.deepcopy(good)
    bad['unit_updates'][0]['logistics']['food']+=1
    ctx=p.context(current,None,fixed_orders=good['orders'],operation_id=observer.operation_id)
    preflight=p.execute(ctx,dict(tool=p.TOOL,args=dict(candidate=bad)))
    assert not preflight['ok'] and 'candidate_ref' in preflight
    calls=[];started=time.monotonic()
    result=dict(passed=False,actual_model=True,physical_turn=False,independent_effect_generation=False,
        scope='Actual retained T3 world; fixed all-hold QA candidate with one deliberately wrong food field; model must amend from public Native evidence',
        input_hash=hashlib.sha256(args.input.read_bytes()).hexdigest(),policy=h.role_policy('engine',tools=True,process=True))
    def dispatch(context,payload):
        frozen=copy.deepcopy(context)
        reply=_native_tool_dispatch(context,payload)
        assert context==frozen
        calls.append(dict(tool=payload['tool'],args=copy.deepcopy(payload.get('args')),response=reply,
            linked_pairs=len(payload.get('candidate_events',payload.get('preview_events',[])))//2))
        (root/'tool-calls.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2))
        print(payload['tool'],reply.get('ok'),str(reply.get('error',''))[:120],flush=True)
        return reply
    runtime_bridge.register_dispatcher(dispatch)
    prompt=('这是只读Native协议验收，不是历史战役验收，也不提交原战局。下列候选是测试夹具，其中只有一个food字段故意不符资源账。'
        '第一步必须原样调用preview_turn_effects，不能预先改候选；收到错误与candidate_ref后，仅调用amend_turn_effects显式修正相应food字段。'
        '禁止重发完整候选，禁止用新工具重新造世界。修订成功后按next_units_args沿next_args读完，再通过submit_turn_report提交简短中文候选报告。'
        '报告仅写双方待命及粮食按规则消耗，不声称历史结论。不得输出隐藏推理。'+p.INSTRUCTION+'\n测试候选：\n'+json.dumps(bad,ensure_ascii=False))
    (root/'prompt.txt').write_text(prompt)
    try:
        final=h.get_ai_response(prompt,observer=observer,native_context=ctx)
        value,proof=p.resolve(final,observer,ctx)
        assert value=={**p.normalize(ctx,good),'report':final['report']}
        assert sum(c['tool']==p.TOOL for c in calls)==1
        assert any(c['tool']==a.AMEND_TOOL and c['response'].get('ok') for c in calls)
        assert any(c['tool']==p.READ_TOOL and c['response'].get('offset',0)>=16 for c in calls)
        assert proof['report_source']=='dsh_native_report_tool'
        assert current==saved
        full_chars=sum(len(json.dumps(c['args'],ensure_ascii=False)) for c in calls if c['tool']==p.TOOL)
        edits_chars=sum(len(json.dumps(c['args'],ensure_ascii=False)) for c in calls if c['tool']==a.AMEND_TOOL)
        result.update(passed=True,source_session_unchanged=True,proof=proof,full_argument_chars=full_chars,
            amendments_argument_chars=edits_chars,main_prompt_chars=len(prompt),final=final)
    except Exception as exc:
        result['error']=str(exc)
        raise
    finally:
        result.update(seconds=round(time.monotonic()-started,3),calls=len(calls),meta=observer.meta())
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        (root/'public-runs.json').write_text(json.dumps(observer.runs,ensure_ascii=False,indent=2))
        h.close_harness()


if __name__=='__main__':main()
