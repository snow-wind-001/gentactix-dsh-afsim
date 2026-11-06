"""Read-only parameter projection keeps zero, unknown and extension values."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parent


class ParameterProjectionTests(unittest.TestCase):
    def run_case(self,source):
        script="""const fs=require('fs'),ts=require('./frontend/node_modules/typescript'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('frontend/src/unitParameters.ts','utf8');const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const context={exports:{},require};vm.runInNewContext(code,context);const p=context.exports;
"""+source
        result=subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_zero_unknown_boolean_and_original_precision_remain_distinct(self):
        self.run_case("""const rows=p.parameterRows({personnel:{current:0,committed:null},formation:{motorized:false},id:'9007199254740993',position:30.1234567890123});
const values=Object.fromEntries(rows.map(r=>[r.path,r.value]));assert.equal(values['personnel.current'],0);assert.equal(values['personnel.committed'],null);assert.equal(values['formation.motorized'],false);assert.equal(values.id,'9007199254740993');assert.equal(values.position,30.1234567890123);
assert.equal(p.parameterValue(0),'0');assert.equal(p.parameterValue(null),'未记录');assert.equal(p.parameterValue(false),'否');assert.equal(p.parameterValue(''),'未填写');""")

    def test_arrays_empty_containers_and_new_fields_are_all_accessible(self):
        self.run_case("""const input={equipment:[{category:'artillery',operational:0,damage_load:.375}],future_extension:{new_mode:'停机',disabled:false},empty:[],empty_object:{}};
const rows=p.parameterRows(input),keys=rows.map(r=>r.path);assert.equal(keys.length,7);assert(keys.includes('equipment[0].damage_load'));assert(keys.includes('future_extension.new_mode'));assert(keys.includes('empty'));assert(keys.includes('empty_object'));assert.equal(rows.find(r=>r.path==='equipment[0].damage_load').value,.375);""")

    def test_chinese_labels_raw_paths_and_values_can_find_a_parameter(self):
        self.run_case("""const rows=p.parameterRows({formation:{fuel_liters:0,signal:75},call_sign:'长江一号'});
assert.equal(p.filterParameters(rows,'燃油')[0].path,'formation.fuel_liters');assert.equal(p.filterParameters(rows,'signal')[0].value,75);assert.equal(p.filterParameters(rows,'长江')[0].path,'call_sign');assert.equal(p.filterParameters(rows,'不存在').length,0);assert.equal(p.filterParameters(rows,'').length,3);""")

    def test_equipment_unavailable_ratio_requires_complete_consistent_counts(self):
        self.run_case("""assert.equal(p.equipmentUnavailablePct({committed:10,operational:7,damaged:2,destroyed:1}),30);assert.equal(p.equipmentUnavailablePct({committed:10,operational:10,damaged:0,destroyed:0}),0);for(const e of [{},{committed:0,operational:0,damaged:0,destroyed:0},{committed:10,operational:7,damaged:null,destroyed:3},{committed:10,operational:7,damaged:4,destroyed:1},{committed:10,operational:10,damaged:-1,destroyed:1}])assert.equal(p.equipmentUnavailablePct(e),null);""")

    def test_physical_fuel_and_fatigue_display_preserves_carry_and_missing_values(self):
        self.run_case("""const f=Object.freeze({fuel_liters:1999,fatigue:60,fuel_credit_microliters:910603,fatigue_carry_ticks:125000});
const row=p.physicalFormationValues(f);assert.equal(row.fuel_liters,1999.910603);assert.equal(row.fatigue,60.125);assert.equal(row.precision,'physical');
assert.equal(p.physicalFormationValues({fuel_liters:0,fatigue:0}).fuel_liters,0);assert.equal(p.physicalFormationValues({fatigue:12.25}).fatigue,12.25);assert.equal(p.physicalFormationValues(undefined).fuel_liters,null);
for(const bad of [{fuel_liters:1999,fatigue:60,fuel_credit_microliters:910603},{...f,fatigue_carry_ticks:1000000},{...f,fuel_credit_microliters:-1},{...f,fatigue:100,fatigue_carry_ticks:1}]){const r=p.physicalFormationValues(bad);assert.equal(r.precision,'unknown');assert.equal(r.fuel_liters,null);assert.equal(r.fatigue,null);}
assert.equal(p.parameterLabel('formation.fuel_credit_microliters'),'编组状态 › 燃油小数余量（微升）');""")

    def test_inspector_template_compiles_with_all_parameter_groups(self):
        self.run_case("""const sfc=require('./frontend/node_modules/@vue/compiler-sfc');const inspectorSource=fs.readFileSync('frontend/src/components/UnitInspector.vue','utf8');const parsed=sfc.parse(inspectorSource);assert.equal(parsed.errors.length,0);const compiled=sfc.compileScript(parsed.descriptor,{id:'unit-inspector-qa',inlineTemplate:true});assert(compiled.content.includes('tabpanel'));""")

    def test_selected_unit_context_includes_its_exact_campaign_actor(self):
        self.run_case("""const actor={active:true,base_entrenchment:30,fortification_integrity:0,base_protection:1.5,captured_this_turn:0,fortification_components:[{base_entrenchment:30,fortification_integrity:20},{base_entrenchment:50,fortification_integrity:0}]};
const unit={name:'第159师',supply_node_id:'s1'},node={id:'s1',stock:0},world={campaign:{actors:{'第159师':actor,'其他部队':{active:false}}},supply_nodes:[node],mission:{definition:{combined_rules:{version:'qa'}}},combat_reference:{source:'QA'}};
const before=JSON.stringify({world,unit});Object.freeze(actor.fortification_components[0]);Object.freeze(actor.fortification_components[1]);Object.freeze(actor.fortification_components);Object.freeze(actor);
const projection=p.unitParameterContext(world,unit,{unit_id:'qa'});assert.equal(projection.campaign_actor,actor);assert.equal(projection.supply_node,node);assert.equal(projection.unit,unit);assert.equal(projection.rules.version,'qa');assert.equal(projection.command.unit_id,'qa');
const rows=p.parameterRows(projection);assert.equal(rows.find(r=>r.path==='campaign_actor.fortification_components[1].fortification_integrity').value,0);assert.equal(rows.find(r=>r.path==='campaign_actor.base_protection').value,1.5);assert.equal(JSON.stringify({world,unit}),before);""")

    def test_campaign_context_never_substitutes_another_or_historical_unit(self):
        self.run_case("""const world={campaign:{actors:{'另一部队':{active:true}}},supply_nodes:[{id:'other',stock:100}]};
for(const unit of [null,{name:'未知部队',historical_unit_id:'另一部队',supply_node_id:'missing'}]){const context=p.unitParameterContext(world,unit);assert.equal(context.campaign_actor,undefined);assert.equal(context.supply_node,undefined);}
assert.equal(p.unitParameterContext({}, {name:'未初始化单位'}).campaign_actor,undefined);""")

    def test_paired_fortifications_remain_searchable_as_read_only_state(self):
        self.run_case("""const rows=p.parameterRows({campaign_actor:{base_entrenchment:10,fortification_integrity:20,base_protection:1.125,captured_this_turn:0,active:false,fortification_components:[{base_entrenchment:10,fortification_integrity:100},{base_entrenchment:30,fortification_integrity:20}]}});
assert.equal(p.filterParameters(rows,'工事完整度').length,3);assert.equal(p.filterParameters(rows,'工事分组参数').length,4);assert.equal(p.parameterLabel('campaign_actor.base_protection'),'战役过程状态 › 原始防护系数');assert.equal(p.parameterValue(p.filterParameters(rows,'active')[0].value),'否');assert.equal(p.parameterValue(p.filterParameters(rows,'captured_this_turn')[0].value),'0');""")

    def test_projection_does_not_mutate_or_render_html_from_source(self):
        self.run_case("""const input={source:'<img src=x onerror=alert(1)>',personnel:{current:8,committed:10}};const before=JSON.stringify(input);Object.freeze(input.personnel);Object.freeze(input);const rows=p.parameterRows(input);assert.equal(JSON.stringify(input),before);assert.equal(rows.find(r=>r.path==='source').value,input.source);assert.equal(p.parameterValue(rows[0].value),input.source);""")


if __name__=='__main__':unittest.main(verbosity=2)
