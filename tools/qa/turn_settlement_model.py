"""Actual Native effect preview over an isolated sourced-identity QA world.

Uses the saved model configuration unchanged. Numerical inputs and stages are
software QA estimates; a pass does not certify a historical campaign.
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
    parser.add_argument('--rounds',type=int,default=2,choices=range(1,4))
    args=parser.parse_args()
    if not args.live:parser.error('The configured actual model requires --live')
    root=Path('.cache/qa/turn-settlement-2026-11-01/model')/str(time.time_ns())
    root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from backend import dsh_simulation,harness_engine as h,runtime_bridge
    from backend.main import _native_tool_dispatch
    from gentactix import missions,reporting,turn_settlement
    from tools.qa.campaign_lifecycle_fixture import session
    current=session();current.update(agent_mode='native',mission_id=current['war_state']['mission']['definition']['id'])
    original=copy.deepcopy(current);calls=[];samples=[];observers=[]
    sources=['backend/turn_preview.py','backend/dsh_simulation.py','backend/harness_engine.py',
             'gentactix/turn_settlement.py','gentactix/reporting.py','plugins/dsh-gentactix/index.mjs']
    (root/'source.json').write_text(json.dumps({p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sources},indent=2))
    (root/'initial.json').write_text(json.dumps(current,ensure_ascii=False,indent=2))
    result=dict(passed=False,actual_model=True,actual_afsim=False,scope='Native handshake and host settlement over six sourced identities with estimated QA parameters/stages',
        model=h.LLM_MODEL,base_url=h.LLM_BASE_URL,max_tokens=h.LLM_MAX_TOKENS,context_window=h.CONTEXT_WINDOW,
        policy=h.role_policy('engine',tools=True,process=True),samples=samples,evidence=str(root))
    def dispatch(context,payload):
        frozen=copy.deepcopy(context['session']['war_state'])
        reply=_native_tool_dispatch(context,payload)
        assert context['session']['war_state']==frozen,'Native readonly tool changed its input world'
        calls.append(dict(tool=payload.get('tool'),args=copy.deepcopy(payload.get('args')),response=reply))
        (root/'tool-calls.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2))
        return reply
    runtime_bridge.register_dispatcher(dispatch)
    try:
        assert h.NATIVE_RUNTIME,'Actual Native runtime is required; no legacy fallback'
        for turn in range(1,args.rounds+1):
            observer=h.RunObserver('真实原生过程预览 T+'+str(turn));observers.append(observer)
            frozen=copy.deepcopy(current);before=current['war_state'];start=time.monotonic()
            orders=[dict(unit=u['name'],action='hold') for _,u in missions.units(before)]
            print('Actual Native preview round',turn,'evidence',root,flush=True)
            response,_,_=dsh_simulation.advance(current,None,observer,fixed_orders=orders,
                instruction='六个单位全部待命；无来袭、无新情报、无物资到货或分类物资开支。粮食按已给规则实际耗用。'
                '先调用本次原生过程预览，依据返回的毛收支、目标与阶段结算写报告；不得把未来阶段尚未评分说成条件不满足。')
            (root/f'response-{turn}.json').write_text(json.dumps(response,ensure_ascii=False,indent=2))
            assert current==frozen,'Effect preview or generation changed the source session'
            after=response['updated_state'];proof=response['report_preview']
            assert proof['evidence']=='dsh_public_tool_trajectory'
            assert missions.digest(after)==proof['after_hash']
            summary=turn_settlement.projection(turn_settlement.build(after,before))
            assert missions.digest(summary)==proof['settlement_hash']
            assert all(r['condition'] is None for r in summary['goals'] if not r['condition_sampled'])
            for (_,a),(_,b) in zip(missions.units(before),missions.units(after)):
                assert all(b['personnel'][k]==a['personnel'][k] for k in ('current','committed','casualties','noncombat_losses'))
                # Zero subcategories may become explicit, and provenance may be
                # annotated; compare the actual classified equipment account.
                for x,y in zip(a['equipment'],b['equipment']):
                    assert all(x.get(k)==y.get(k) for k in ('category','committed','operational','damaged','destroyed'))
                assert b['logistics']['food']==a['logistics']['food']-2
                assert b['logistics']['ammo']==a['logistics']['ammo']
                assert abs(b['formation']['intel_age_min']-a['formation']['intel_age_min']-30)<1e-7
            assert after['campaign_lifecycle']['phase_index']==turn
            assert len([r for r in summary['goals'] if r['status']=='completed'])==turn
            public,audit=reporting.render(response['report'],after,before,turn=turn)
            (root/f'after-{turn}.json').write_text(json.dumps(after,ensure_ascii=False,indent=2))
            (root/f'report-{turn}.json').write_text(json.dumps(dict(raw=response['report'],rendered=public,audit=audit,proof=proof),ensure_ascii=False,indent=2))
            assert not audit['issues'],audit['issues']
            sample=dict(turn=turn,seconds=round(time.monotonic()-start,3),proof=proof,settlement=summary,meta=observer.meta())
            samples.append(sample);current=copy.deepcopy(current);current.update(war_state=after,turn_count=turn)
            print('PASS Native tool proof and settlement round',turn,'seconds',sample['seconds'],flush=True)
        assert original==json.loads((root/'initial.json').read_text())
        result.update(passed=True,completed_turn=args.rounds,source_session_unchanged=True,
            successful_preview_calls=sum(c['tool']=='preview_turn_effects' and c['response'].get('ok') for c in calls))
    except Exception as exc:
        result['error']=str(exc)
        raise
    finally:
        result['tool_failures']=[dict(tool=c['tool'],error=c['response'].get('error')) for c in calls if c['response'].get('ok') is False]
        result['native_runs']=sum(len(o.runs) for o in observers)
        result['uninterrupted']=bool(result['passed'] and not result['tool_failures'] and result['native_runs']==args.rounds)
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        (root/'public-runs.json').write_text(json.dumps([r for observer in observers for r in observer.runs],ensure_ascii=False,indent=2))
        h.close_harness()
        print('Evidence:',root,flush=True)


if __name__=='__main__':main()
