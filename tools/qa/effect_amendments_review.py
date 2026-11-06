"""Independent public-evidence review; preserve any original exact-copy QA failure."""
import argparse
import copy
import json
from pathlib import Path
from types import SimpleNamespace


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args()
    root=args.directory
    output=root/'independent-review.json'
    if output.exists():parser.error('Preserve previous review')
    from backend import turn_preview as p,dsh_simulation,effect_amendments as a
    from gentactix import missions
    from tools.qa.turn_preview_page_fixture import candidate
    original=json.loads((root/'result.json').read_text())
    calls=json.loads((root/'tool-calls.json').read_text())
    observer=SimpleNamespace(runs=json.loads((root/'public-runs.json').read_text()))
    session=json.loads(args.input.read_text());saved=copy.deepcopy(session)
    good=candidate(session['war_state'])
    assert calls[0]['tool']==p.TOOL and not calls[0]['response']['ok']
    assert sum(c['tool']==p.TOOL for c in calls)==1
    ctx=p.context(session,None,fixed_orders=good['orders'],operation_id=calls[0]['response']['operation_id'])
    submitted=p.submitted_report(observer,ctx)
    assert submitted
    value,proof=p.resolve(submitted[0],observer,ctx)
    after=dsh_simulation.apply(session['war_state'],value,session['time_step'],require_fire_ledger=True)
    assert missions.digest(after)==proof['after_hash']
    raw=copy.deepcopy(calls[0]['args']['candidate'])
    amendments=[c for c in calls if c['tool']==a.AMEND_TOOL]
    assert len(amendments)==1 and amendments[0]['response']['ok']
    assert amendments[0]['args']['edits']==[dict(op='replace',path='/unit_updates/0/logistics/food',
        value=good['unit_updates'][0]['logistics']['food'])]
    raw=a.edit(raw,amendments[0]['args'])
    assert p.normalize(ctx,raw)=={k:v for k,v in value.items() if k!='report'}
    differences=[]
    def compare(expected,actual,path=''):
        if isinstance(expected,dict) and isinstance(actual,dict):
            assert expected.keys()==actual.keys(),path
            for key in expected:compare(expected[key],actual[key],path+'/'+key)
        elif isinstance(expected,list) and isinstance(actual,list):
            assert len(expected)==len(actual),path
            for index,(x,y) in enumerate(zip(expected,actual)):compare(x,y,path+'/'+str(index))
        elif expected!=actual:
            assert type(expected) in (int,float) and type(actual) in (int,float),path
            assert path.endswith('/logistics/food') and abs(expected-actual)<1e-12,path
            differences.append(dict(path=path,fixture=expected,model=actual,absolute_difference=abs(expected-actual)))
    compare(p.normalize(ctx,good),p.normalize(ctx,raw))
    assert session==saved
    result=dict(original_qa_passed=original['passed'],public_protocol_replay_passed=True,
        all_kernel_guards_passed=True,physical_turn=False,precision_differences=differences,
        explicit_amendments=amendments[0]['args'],proof=proof,
        report_refusals=[c['response'].get('issues') for c in calls if c['tool']==p.REPORT_TOOL and not c['response']['ok']],
        source_session_unchanged=True,
        scope='Original QA result unchanged. Exact public amendment replay and full kernel validation; float representation differences reported, never repaired. Not historical or independent physical-effect acceptance.')
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('PARTIAL: public protocol/full kernel PASS; original QA',original['passed'],'float differences',len(differences))


if __name__=='__main__':main()
