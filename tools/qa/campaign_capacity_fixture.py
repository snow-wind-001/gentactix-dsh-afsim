"""Large historical-derived exercise inputs; every numerical value is QA only.

The79 named references come from the existing Wuhan fixture. Removing or adding
exercise units is explicit scenario editing, never a historical OOB claim.
"""
import copy
from gentactix import synthetic_history
from tools.qa.large_formation_fixture import inputs as source_inputs,NOTE


def inputs():
    snapshot,parameters=source_inputs()
    parameters['fire_accounting']={'version':'classified-indirect-1','assumption':NOTE}
    parameters['fire_dynamics']={'version':'live-footprint-density-1','assumption':NOTE}
    return snapshot,parameters


def configuration(binding,red,blue):
    value=synthetic_history.seed(binding)['configuration']
    for team,count in [('red',red),('blue',blue)]:
        originals=copy.deepcopy(value['teams'][team]);rows=value['teams'][team]
        del rows[count:]
        while len(rows)<count:
            index=len(rows);row=copy.deepcopy(originals[index%len(originals)])
            row['name']=f'{team}规模QA新增演习编组{index+1}'
            rows.append(row)
    return value
