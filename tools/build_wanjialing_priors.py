"""Optional reviewed global priors; DSH still fills every unknown actor input."""
import argparse
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gentactix import historical_initial as hi,historical_operations as ho,campaign_windows as cw
from tools.build_wanjialing_estimates import build as envelope,CENTER,NOTE
from tools.upgrade_wanjialing import BATTLE


def build():
    d=envelope();d.update(version='1.2.0',label='万家岭：10月6—10日地面会战 · 公共参数基线')
    s=hi.initial(BATTLE,'oct6_orders',version='1.3.0')['historical_initial']
    p=ho.configuration_template(s,'campaign',window=cw.pin('WJL-oct6-10','1.1.0'),termination_mode='objectives')
    note=NOTE+' 公共基线供DSH读取、调整并确认，不是已核史实；单仓、无真实航空与道路的局限仍在。'
    p['clock'].update(assumption=note)
    p['area'].update(center=copy.deepcopy(CENTER),radius_km=40,terrain_factor=1.5,assumption=note)
    p['rules'].update(goal_profile='assault',required_survivors=1,convoy_km_per_turn=8,motorized=False)
    p['campaign_scope']['assumption']=note
    for row in p['campaign_scope']['remainders'].values():row.update(policy='excluded_unquantified',assumption=note+' 未核余部不投入，所列下级不宣称完整父级。')
    for team,row in p['support'].items():
        row.update(position={'lat':CENTER['lat']+(-.08 if team=='red' else .02),'lng':CENTER['lng']},stock=5000 if team=='red' else 800,assumption=note)
        row['inventory']=dict(fuel_liters=0,spares=100,materials=500,shells=5000,aa_rounds=0)
    p['facility'].update(CENTER)
    p['goal'].update(team='red',profile='assault',objective=copy.deepcopy(CENTER),exit={'lat':CENTER['lat'],'lng':CENTER['lng']-.10},radius_km=3,
        deadline_turn=240,required_turns=2,required_survivors=1,termination_mode='objectives',description=note,assumption=note)
    for identity,row in p['campaign']['arrivals'].items():row.update(not_before=p['clock']['start'],assumption=note+' 基线仅假设开局在估计工作区可受令，不等于史实同时在场，也不自动执行未来命令。')
    for identity,row in p['campaign']['fortifications'].items():row.update(integrity=15 if identity.startswith('ww2.jp.') else 5,degradation_per_shell=.05,assumption=note)
    p['campaign']['surrender'].update(enabled=False,range_m=100,suppression_threshold=90,ammo_threshold=0,assumption=note)
    p['campaign']['objective'].update(relief_regions=[{'center':{'lat':CENTER['lat']-.10,'lng':CENTER['lng']-.10},'radius_km':2}],min_force_fraction=.4,assumption=note)
    p['campaign']['assumption']=note
    p['support_dynamics']=dict(version='time-sustainment-1',food_work_per_hour=.7,move_factor=1.5,shortage_fatigue_per_hour=1,
        recovery_hours_per_fed_hour=.5,incapacity_after_hours=48,incapacity_fraction_per_hour=.0005,assumption=note+' 以经过小时计工作量，不是按人数或重量标定的口粮。')
    for node in p['campaign_plan']['nodes']:
        node.update(hold_seconds=3600,assumption=note)
        if node['condition']['kind']=='preserve':node['condition']['minimum_fraction']=.4
        else:
            point=copy.deepcopy(CENTER);radius=3
            if node['id']=='red_block':point={'lat':CENTER['lat']-.10,'lng':CENTER['lng']-.10};radius=2
            elif node['id']=='blue_exit':point={'lat':CENTER['lat'],'lng':CENTER['lng']-.10};radius=2
            node['condition'].update(region={'center':point,'radius_km':radius},minimum_personnel=500)
    p['campaign_plan']['assumption']=note+'按声明代理条件评分，不等于真实解围或占领史实。'
    p['assumptions']=note
    p['campaign_scope'].pop('window')  # Never place the complete window inside itself.
    d['parameter_estimates']['global_priors']={k:copy.deepcopy(v) for k,v in p.items() if k not in ('format','phase_id','actors')}
    d['limitations']+=' 公共参数为可复核的显式估计基线，DSH仍须实际提交有效修订并补22个单位的未知输入；基线不代表历史已经验收。'
    cw.validate_definition(d,s)
    return d


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');args=p.parse_args()
    value=build();path=cw.DATA_ROOT/'WJL-oct6-10/1.2.0.json'
    if path.exists():
        if json.loads(path.read_text())!=value:raise SystemExit('Existing prior version differs; create a new version')
        print('Wanjialing1.2 priors match; all source facts unchanged')
    elif args.check:raise SystemExit('Wanjialing1.2 priors missing')
    else:path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');print('Created optional1.2 global priors; actor inputs stay unknown')


if __name__=='__main__':main()
