"""Exercise the actual UI-generated historical draft through both executors."""
import argparse
import copy
import json
from pathlib import Path
import time
import uuid

from tools.qa.catalog_expansion_live import call, fire_orders, revision, advance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    if not parser.parse_args().live:
        parser.error('Use --live against owned isolated API18998')
    root = Path('.cache/qa/catalog-expansion/builder-followup'); root.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path('.cache/qa/catalog-expansion/browser-builder-live-result.json').read_text())
    assert manifest['passed']
    health = call('GET', '/api/health')
    assert not health['build']['restart_required']
    assert Path(f"/proc/{health['build']['pid']}/cmdline").read_bytes().split(b'\0')[1] == b'.cache/qa/ww2-phases/launch.py'
    def save(name, value):
        (root / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    result = {'passed':False, 'scope':'actual DSH skill draft with declared QA inputs, not historical calibration'}
    try:
        native = call('GET', '/api/sessions/' + manifest['session_id'])
        assert native['turn_count'] == 0
        parameters = copy.deepcopy(json.loads(Path('.cache/qa/catalog-expansion/actual-builder-draft.json').read_text())['parameters'])
        op = uuid.uuid4().hex
        save('validation-request', {'operation_id':op})
        draft = call('POST', '/api/historical-scenarios/validate', {'parent_draft_id':manifest['draft_id'],
            'parameters':parameters, 'execution_backend':'narrative', 'operation_id':op})
        save('narrative-draft', draft)
        created = call('POST', '/api/sessions', {'scenario':'正常DSH skill历史局部配置的双引擎QA；不是史实兵力或损失复原',
            'battle':draft['initial']['definition']['battle'], 'product_mode':'historical', 'simulation_mode':'open',
            'execution_backend':'narrative', 'persist_roles':False, 'historical_parameters':draft['parameters'],
            'scenario_draft_id':draft['id'], 'time_step':'15分钟'})
        sid = created['session_id']; result.update(native_session=manifest['session_id'], narrative_session=sid)
        save('result',result)
        narrative = call('POST', '/api/sessions/' + sid + '/init')
        assert native['war_state']['historical_initial'] == narrative['war_state']['historical_initial']
        for engine, initial in [('afsim',native),('narrative',narrative)]:
            sid = initial['session_id']; view = call('GET', '/api/sessions/'+sid+'/commands')
            call('PUT','/api/sessions/'+sid+'/commands',{**revision(view), 'orders':fire_orders(view),
                'control_team':'red','director':True,'no_fire':False,'unit_agents':[],
                'intent':'QA双方互相直接射击，执行已验证的15分钟步长，保持原始史料未知值。'})
            print('START',engine,sid,flush=True); start=time.monotonic()
            current=advance(sid,'双方按已确认fire命令交火；精确推进15分钟。以当前计算配置和实际命令为依据，'
                '不要把历史总损失当成本轮配额。无航空、火炮、渡河、增援或临时补充，源未知事实不改写。'
                'AFSIM关闭时结果标记DSH估计，提交实际模型估计的完整两方效果、资源账与交战记录，不能冒称原生遥测。')
            save(engine+'-turn1',current); world=current['war_state']
            assert current['turn_count']==1 and world['simulation_clock']['elapsed_seconds']==900
            assert world['historical_initial']==initial['war_state']['historical_initial']
            for team in ('red','blue'):
                for u in world[team+'_units']:
                    p=u['personnel'];assert p['committed']==sum(p[k] for k in ('current','casualties','noncombat_losses'))
            if engine=='afsim':assert world['afsim']['model_skipped']
            else:
                assert world['dsh_execution']['effects_source']=='dsh_model_estimate'
                assert not world.get('afsim')
            result[engine]={'seconds':round(time.monotonic()-start,3),'time':world['current_time'],
                'losses':{t:sum(u['personnel']['casualties'] for u in world[t+'_units']) for t in ('red','blue')}}
            save('result',result);print('PASS',engine,result[engine],flush=True)
        result['passed']=True;save('result',result)
    except Exception as exc:
        result['error']=str(exc);save('result',result);raise


if __name__=='__main__':main()
