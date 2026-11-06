"""Inventory sourced parent/child options; never invent force or deployment facts."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from gentactix import historical_initial as hi, historical_operations as ho


def inspect(battle,version):
    definition=hi.definition(battle,version);units=definition['units'];children={}
    for unit in units:children.setdefault(unit['parent_id'],[]).append(unit)
    candidates=[];nonphysical=[]
    for phase in definition['phases']:
        if phase['id']=='campaign_reference':continue
        def present(unit):
            return any(p['phase_id']==phase['id'] and p['status']=='reported_present' for p in unit['presence'])
        parents=[]
        for parent in units:
            if parent['role'] not in ('formation','support') or not present(parent):continue
            available=[u for u in children.get(parent['id'],[]) if present(u)]
            physical=[u['id'] for u in available if u['role'] in ('formation','support')]
            nonphysical.extend(dict(phase_id=phase['id'],parent_id=parent['id'],child_id=u['id'],role=u['role'])
                for u in available if u['role'] not in ('formation','support'))
            if not physical:continue
            status=parent.get('children_coverage',{}).get('status','unknown')
            parents.append(dict(phase_id=phase['id'],parent_id=parent['id'],parent_name=parent['name'],
                child_ids=physical,coverage=status,
                requires_residual=status!='complete' or set(physical)!={u['id'] for u in children.get(parent['id'],[])},
                personnel_facts_known=sum(u['facts']['personnel']['value'] is not None for u in available),
                equipment_facts_known=sum(u['facts']['equipment']['value'] is not None for u in available)))
        if not parents:continue
        snapshot=hi.initial(battle,phase['id'],version=version)['historical_initial']
        try:selected=set(ho.partition(snapshot));error=None
        except ValueError as exc:selected=None;error=str(exc)
        for parent in parents:
            parent['local_entry_includes_parent']=parent['parent_id'] in selected if selected is not None else None
            parent['local_entry_error']=error
        candidates.extend(parents)
    return dict(profile_id=definition['id'],battle=battle,version=version,definition_hash=hi.digest(definition),
        reference_units=len(units),parent_phase_candidates=candidates,nonphysical_present_children=nonphysical)


def audit():
    profiles=[];all_versions=[];errors=[]
    for row in hi.catalog():
        versions=[]
        for path in sorted((hi.DATA_ROOT/row['profile_id']).glob('*.json')):
            try:result=inspect(row['battle'],path.stem)
            except (ValueError,KeyError,TypeError) as exc:
                errors.append(dict(profile_id=row['profile_id'],version=path.stem,error=str(exc)));continue
            all_versions.append(result);versions.append(result)
        default=next((r for r in versions if r['version']==row['version']),None)
        if default is None:raise ValueError('默认来源不可读取：'+row['battle'])
        pairs=default['parent_phase_candidates'];known=Counter(p['coverage'] for p in pairs)
        profiles.append(dict(profile_id=row['profile_id'],battle=row['battle'],default_version=row['version'],
            default_definition_hash=default['definition_hash'],reference_units=default['reference_units'],
            default_parent_phase_pairs=len(pairs),any_version_parent_phase_pairs=sum(len(v['parent_phase_candidates']) for v in versions),
            complete_coverage_pairs=known['complete'],partial_coverage_pairs=known['partial'],unknown_coverage_pairs=known['unknown'],
            default_requires_residual_pairs=sum(p['requires_residual'] for p in pairs),
            local_entry_includes_parent_pairs=sum(p['local_entry_includes_parent'] is True for p in pairs),
            source_task=('若需历史分兵，补下级番号、隶属、逐阶段在场和覆盖边界；非交战场景按任务适配' if not pairs else
                         '复核已列下级与余部，准备显式父级窗口；逐单位兵额、装备和部署仍需来源或估计')))
    return dict(scope='Local source structure only; not historical verification, deployment, loaded roster or complete-runtime acceptance',
        profile_count=len(profiles),valid_version_count=len(all_versions),invalid_versions=errors,
        default_profiles_with_parent_candidates=sum(p['default_parent_phase_pairs']>0 for p in profiles),
        any_version_profiles_with_parent_candidates=sum(p['any_version_parent_phase_pairs']>0 for p in profiles),
        default_parent_phase_pairs=sum(p['default_parent_phase_pairs'] for p in profiles),
        default_complete_coverage_pairs=sum(p['complete_coverage_pairs'] for p in profiles),
        nonphysical_present_children=[dict(battle=r['battle'],version=r['version'],**p) for r in all_versions for p in r['nonphysical_present_children']],
        profiles=profiles,versions=all_versions)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    result=audit();args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    with args.out.with_suffix('.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(result['profiles'][0]));writer.writeheader();writer.writerows(result['profiles'])
    print(json.dumps({k:v for k,v in result.items() if k not in ('profiles','versions','nonphysical_present_children')},ensure_ascii=False))
