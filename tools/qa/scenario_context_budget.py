"""Measure bounded configuration views; enlarged fixtures are NOT historical OOBs."""
import copy
import json
from pathlib import Path

from backend import scenario_assembly,scenario_builder
from tools.qa.pingxingguan_fixture import BATTLE


def main():
    basis=scenario_builder.historical_basis(BATTLE,'qiaogou');rows=[]
    for count in (6,120,240):
        candidate=copy.deepcopy(basis)
        # Only exercise the read-view boundary. These extra actors cannot pass
        # source identity validation and must never enter the campaign catalog.
        for i in range(count-6):
            original=basis['actors'][i%6];identity=f'qa.view.{i}'
            candidate['actors'].append({**copy.deepcopy(original),'id':identity,'name':f'QA view actor {i}'})
            candidate['configuration_template']['actors'][identity]=copy.deepcopy(basis['configuration_template']['actors'][original['id']])
        assembly=scenario_assembly.create(candidate)
        try:
            views=[assembly.tool(part,'get_scenario_basis',{}) for part in assembly.parts]
            legacy={k:v for k,v in candidate.items() if k not in ('initial','phases')}
            rows.append({'actors':count,'legacy_full_basis_chars':len(json.dumps(legacy,ensure_ascii=False)),
                'max_assigned_actors':max(len(v['actors']) for v in views),
                'max_actor_view_chars':max(len(json.dumps(v,ensure_ascii=False)) for v in views),
                'global_view_chars':len(json.dumps(assembly.tool('globals','get_scenario_basis',{}),ensure_ascii=False)),
                'native_context_chars':max(len(json.dumps(assembly.context(part))) for part in assembly.parts)})
        finally:scenario_assembly.close(assembly.id)
    assert all(r['max_assigned_actors']<=4 and r['native_context_chars']<250 for r in rows)
    assert rows[-1]['max_actor_view_chars']<rows[0]['max_actor_view_chars']*1.25
    # Global view includes up to 16 known position references. Its size can grow
    # initially to that cap, then must plateau rather than grow with the roster.
    assert rows[-1]['global_view_chars']<rows[-2]['global_view_chars']*1.05
    root=Path('.cache/qa/scenario-staging');root.mkdir(parents=True,exist_ok=True)
    result={'passed':True,'scope':'read-view size and isolation only; 120/240 actor fixtures are non-executable QA inputs, not historical or native simulation acceptance','rows':rows}
    (root/'context-budget.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
