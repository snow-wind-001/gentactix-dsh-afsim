"""Read-only45profile catalogue check; no model, native execution or history claims."""
import json
import os
import argparse
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',default='.cache/qa/fixed-parameters-2026-11-01/catalogue')
    out=Path(parser.parse_args().out).resolve()
    out.mkdir(parents=True,exist_ok=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),
                       ('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')]:
        os.environ['GENTACTIX_'+key]=str(out/suffix)
    from backend import scenario_builder
    from gentactix import historical_initial
    rows=[]
    for item in historical_initial.catalog():
        if item['status']!='profiled':continue
        for version in historical_initial.versions(item['battle']):
            data=historical_initial.definition(item['battle'],version['version'])
            for phase in data['phases']:
                for scope in ('phase','campaign'):
                    basis=scenario_builder.historical_basis(item['battle'],phase['id'],version=version['version'],force_scope=scope)
                    row={'profile':item['profile_id'],'version':version['version'],'phase':phase['id'],'scope':scope,
                         'ready':basis['ready'],'reason':basis['error'],'field_count':0}
                    if basis['ready']:
                        fields=basis['fixed_parameter_fields'];paths=[tuple(f['path']) for f in fields]
                        assert len(paths)==len(set(paths))
                        assert all(f['label'] and f['group'] and type(f['integer']) is bool for f in fields)
                        names={u['id'] for u in basis['actors']}
                        assert all(p[0]!='actors' or p[1] in names for p in paths)
                        row.update(field_count=len(fields),actors=len(names))
                    rows.append(row)
    result={'passed':True,'model_calls':0,'native_execution':False,'profile_count':len({r['profile'] for r in rows}),
            'versions':len({(r['profile'],r['version']) for r in rows}),'configurations_checked':len(rows),
            'ready_configurations':sum(r['ready'] for r in rows),'declared_not_ready':sum(not r['ready'] for r in rows),
            'maximum_field_count':max((r['field_count'] for r in rows),default=0),
            'scope':'Current UI numeric catalogues and declared unsupported scopes, not45full historical simulations',
            'rows':rows}
    result['profiles_with_ready_choice']=len({r['profile'] for r in rows if r['ready']})
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))


if __name__=='__main__':main()
