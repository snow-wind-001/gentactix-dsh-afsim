"""Freeze editorial task guidance per historical version; existing pins stay immutable."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gentactix import historical_initial as hi


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    path=ROOT/'data/historical_objective_bindings.json'
    value=json.loads(path.read_text()) if path.exists() else {'format':'historical-objective-bindings-1','profiles':{}}
    current=json.loads((ROOT/'data/historical_objectives.json').read_text())['profiles']
    missing=[]
    for profile in hi.catalog():
        versions=value['profiles'].setdefault(profile['profile_id'],{})
        for version in hi.versions(profile['battle']):
            key=version['version']
            if key in versions:continue
            missing.append(profile['profile_id']+'/'+key)
            d=hi.definition(profile['battle'],key);phases={}
            for phase in d['phases']:
                row=current.get(d['id'],{}).get(phase['id'])
                if row is None:continue
                ids={e['source_id'] for e in row['evidence']}
                if ids-set(d['sources']):
                    if (d['id'],key,phase['id'])!=('AJ09-changsha2','1.0.0','dayun_sep7'):
                        raise ValueError('目标引用来源缺失，必须人工登记勘误范围：'+d['id']+'/'+key)
                    phases[phase['id']]={'unavailable_reason':'该旧版大云山部队身份及目标来源已勘误；旧事实快照保留，新建请选1.1.0。已冻结计算定义仍可恢复。'}
                else:
                    phases[phase['id']]={'guidance':copy.deepcopy(row),
                        'source_hashes':{i:hi.digest(d['sources'][i]) for i in sorted(ids)}}
            versions[key]={'initial_definition_hash':hi.digest(d),'phases':phases}
    if args.check:
        if missing:raise SystemExit('Missing objective version pins: '+', '.join(missing))
        print('All historical objective versions pinned')
    else:
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        print(f'Pinned {len(missing)} new versions; existing pins preserved')


if __name__=='__main__':main()
