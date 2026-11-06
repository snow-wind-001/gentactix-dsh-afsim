"""Replayable actor estimates, explicit and separate from immutable source facts."""
import argparse
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gentactix import historical_initial as hi,campaign_windows as cw
from tools.build_wanjialing_priors import build as public_priors
from tools.upgrade_wanjialing import BATTLE


def build():
    d=public_priors();d.update(version='1.3.0',label='万家岭：10月6—10日地面会战 · 可重放估计基线')
    cfg=d['parameter_estimates']
    for n,(identity,row) in enumerate(cfg['actors'].items()):
        support=row['role']=='support';point=copy.deepcopy(row['position']['center']);point['lat']+=(n%3)*.001
        equipment=dict(armor=0,artillery=row['equipment']['artillery']['minimum'] if support else 2,air_defense=0,engineer=2,transport=12)
        row['input_prior']=dict(personnel=(row['personnel']['minimum']+row['personnel']['maximum'])//2,position=point,
            equipment=equipment,type='炮兵' if support else '步兵',speed=3,attack_range_m=300 if support else 800,ground_control_radius_km=.2,
            logistics={'food':15 if identity=='ww2.jp.division106' else 80,'ammo':25 if identity=='ww2.jp.division106' else 80},
            formation=dict(role=row['role'],fatigue=10,suppression=0,entrenchment=10,dispersion_km2=.2 if support else 4,protection=.15,
                fuel_liters=0,spares=20,materials=16,shells=equipment['artillery']*150,aa_rounds=0,reload_remaining=0,
                intel_age_min=10,intel_confidence=80,signal=80,motorized=False),
            assumption=row['assumption']+' 人工选择区间中部及明确装备、随队覆盖作为可重放模型输入，不是史实实有数；由DSH读取、调整并确认。')
    d['limitations']+=' 本版单位数值基线为明确的人工计算先验，来源事实仍未知；DSH负责复核与必要修改，不宣称数值来自历史原件。'
    s=hi.initial(BATTLE,'oct6_orders',version='1.3.0')['historical_initial'];cw.validate_definition(d,s)
    return d


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');args=p.parse_args()
    value=build();path=cw.DATA_ROOT/'WJL-oct6-10/1.3.0.json'
    if path.exists():
        if json.loads(path.read_text())!=value:raise SystemExit('Existing actor prior version differs; create a new version')
        print('Wanjialing1.3 replayable priors match; historical facts unchanged')
    elif args.check:raise SystemExit('Wanjialing1.3 priors missing')
    else:path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');print('Created1.3 explicit actor priors; not historical strengths')


if __name__=='__main__':main()
