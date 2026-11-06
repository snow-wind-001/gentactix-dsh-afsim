<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch, computed } from 'vue';
import { api } from '../api';
import AviationParametersEditor from './AviationParametersEditor.vue';
import FireAccountingEditor from './FireAccountingEditor.vue';
import type { SyntheticConfiguration, SyntheticFormation, ScenarioBasis, ScenarioDraft, WarState, MapPoint } from '../types';
const props=withDefaults(defineProps<{missionId:string;sourceDraftId?:string;busy:boolean;executionBackend?:'afsim'|'narrative'}>(),{executionBackend:'afsim'});
const emit=defineEmits<{change:[value:SyntheticConfiguration|null];valid:[value:boolean];'draft-id':[value:string|null];preview:[value:WarState|null];selection:[value:{team:string;name:string}|null];'pick-map':[];busy:[label:string];feedback:[message:string]}>();
const basis=ref<ScenarioBasis|null>(null),value=ref<SyntheticConfiguration|null>(null),draft=ref<ScenarioDraft|null>(null);
const loading=ref(false),working=ref(false),error=ref(''),instruction=ref(''),verified=ref('');
watch(error,message=>emit('feedback',message));
const selected=ref<{side:'red'|'blue';index:number}|null>(null);
let operationId='';
const sides=['red','blue'] as const;
const equipment=[{key:'armor',label:'装甲车辆'},{key:'artillery',label:'火炮'},{key:'air_defense',label:'防空装备'},{key:'engineer',label:'工兵作业组'},{key:'transport',label:'运输单元'}] as const;
const stores=[{key:'food',label:'粮食工作量',max:100},{key:'ammo',label:'弹药工作量',max:100},{key:'shells',label:'炮弹（发）',max:1000000},{key:'aa_rounds',label:'防空弹药（发）',max:1000000},{key:'fuel_liters',label:'燃油（升）',max:10000000},{key:'fatigue',label:'初始疲劳',max:100}] as const;
let generation=0,loadingPromise:Promise<void>|undefined;
watch([()=>props.missionId,()=>props.sourceDraftId],([id,source])=>{
 loadingPromise=(async()=>{
 const current=++generation;basis.value=null;value.value=null;draft.value=null;verified.value='';selected.value=null;error.value='';loading.value=true;
 try{
  operationId=crypto.randomUUID().replaceAll('-','');
  let result:ScenarioBasis,inherited:ScenarioDraft|undefined;
  if(source){const derived=await api.deriveHistoricalScenario(source,operationId,props.executionBackend);result=derived;inherited=derived.draft;}
  else result=await api.scenarioBasis(id!);
  if(current===generation){basis.value=result;value.value=result.configuration;
   if(inherited){draft.value=inherited;verified.value=JSON.stringify(inherited.configuration);}}
 }
 catch(e){if(current===generation)error.value=String(e);}finally{if(current===generation)loading.value=false;}
 })();
},{immediate:true});
onBeforeUnmount(()=>{generation++;if((working.value||loading.value)&&operationId)void api.cancelScenario(operationId).catch(()=>{});});
const maxUnitsPerTeam=computed(()=>basis.value?.configuration_limits?.max_units_per_team??12);
const fieldValid=computed(()=>{
 if(!value.value)return false;const rows=sides.flatMap(t=>value.value!.teams[t]);
 return sides.every(t=>value.value!.teams[t].length>=(props.sourceDraftId&&!basis.value?.preview_world[t==='red'?'red_units':'blue_units']?.length?0:1)&&value.value!.teams[t].length<=maxUnitsPerTeam.value)&&new Set(rows.map(u=>u.name)).size===rows.length
  &&rows.every(u=>u.name.trim().length>0&&u.name.length<=60&&Number.isInteger(u.personnel)&&u.personnel>=1&&u.personnel<=100000
   &&equipment.every(e=>Number.isInteger(u.equipment[e.key])&&u.equipment[e.key]>=0&&u.equipment[e.key]<=10000)
   &&stores.every(s=>(s.key==='food'||s.key==='ammo'?Number.isFinite(u[s.key]):Number.isInteger(u[s.key]))&&u[s.key]>=0&&u[s.key]<=s.max)&&u.position&&Number.isFinite(u.position.lat)&&Number.isFinite(u.position.lng));
});
const valid=computed(()=>fieldValid.value&&!!draft.value&&(draft.value.execution_backend||'afsim')===props.executionBackend&&verified.value===JSON.stringify(value.value)&&!working.value&&!loading.value);
const preview=computed<WarState|null>(()=>{
 if(!basis.value||!value.value)return null;const world={...basis.value.preview_world};
 for(const side of sides){const templates=basis.value.preview_world[side+'_units'] as NonNullable<WarState['red_units']>;
  world[side+'_units']=value.value.teams[side].filter(u=>u.position&&Number.isFinite(u.position.lat)&&Number.isFinite(u.position.lng)).map((u,i)=>{
   const origin=templates.find(t=>t.historical_unit_id===u.basis_id)??templates[i%templates.length]!;
   const originalCounts=Object.fromEntries((origin.equipment??[]).map(e=>[e.category,e.committed]));
   const type=u.equipment.armor&&!originalCounts.armor?'装甲兵':u.equipment.artillery&&!originalCounts.artillery?'炮兵':origin.type;
   return {...origin,name:u.name,historical_unit_id:u.name===origin.name?origin.historical_unit_id:undefined,
    type,
    lat:u.position!.lat,lng:u.position!.lng,personnel:{committed:u.personnel,current:u.personnel,casualties:0,noncombat_losses:0},
    equipment:origin.equipment?.map(e=>({...e,committed:u.equipment[e.category as keyof typeof u.equipment],operational:u.equipment[e.category as keyof typeof u.equipment],damaged:0,destroyed:0})),
    logistics:{food:u.food,ammo:u.ammo},formation:origin.formation?{...origin.formation,shells:u.shells,aa_rounds:u.aa_rounds,fuel_liters:u.fuel_liters,fatigue:u.fatigue,
     ...(type!==origin.type?{role:type==='装甲兵'?'armor':'support',...(type==='装甲兵'?{motorized:true}:{})}:{})}:undefined};
  });}
 world.source_note='想定编辑草稿；地图位置为演习部署，未开始战局。';return world;
});
watch([value,valid,draft],()=>{emit('change',value.value?JSON.parse(JSON.stringify(value.value)):null);emit('valid',valid.value);emit('draft-id',valid.value?draft.value!.id:null);},{deep:true,immediate:true});
watch(preview,world=>emit('preview',world),{immediate:true});
watch([selected,value],()=>{const s=selected.value,u=s&&value.value?.teams[s.side][s.index];emit('selection',s&&u?{team:s.side,name:u.name}:null);},{deep:true});
async function generate(){
 if(working.value||props.busy)return;working.value=true;error.value='';emit('busy','DSH正在调用skill生成史实基础演习配置…');
 operationId=crypto.randomUUID().replaceAll('-','');
 try{const r=await api.buildScenario(props.missionId,instruction.value,operationId,props.executionBackend,props.sourceDraftId);value.value=r.configuration;draft.value=r;verified.value=JSON.stringify(r.configuration);selected.value=null;}
 catch(e){error.value=String(e);}finally{working.value=false;emit('busy','');}
}
async function validate(){
 if(!value.value||!draft.value||!fieldValid.value||working.value||props.busy)return;working.value=true;error.value='';emit('busy',props.executionBackend==='afsim'?'AFSIM正在装载验证编辑后的想定…':'正在校验DSH想定配置…');
 operationId=crypto.randomUUID().replaceAll('-','');
 try{const r=await api.validateScenario(props.missionId,value.value,draft.value.id,operationId,props.executionBackend);value.value=r.configuration;draft.value=r;verified.value=JSON.stringify(r.configuration);}
 catch(e){error.value=String(e);}finally{working.value=false;emit('busy','');}
}
function pick(side:'red'|'blue',index:number){if(props.busy||working.value||!draft.value)return;selected.value={side,index};emit('pick-map');}
function selectUnit(team:string,name:string){if(team!=='red'&&team!=='blue')return;const i=value.value?.teams[team].findIndex(u=>u.name===name)??-1;if(i>=0)pick(team,i);}
function placeSelected(point:MapPoint){const s=selected.value;if(s&&value.value&&draft.value&&!props.busy&&!working.value)value.value.teams[s.side][s.index]!.position={...point};}
function add(side:'red'|'blue'){
 if(!value.value)return;const rows=value.value.teams[side];if(!rows.length||rows.length>=maxUnitsPerTeam.value)return;const row:SyntheticFormation=JSON.parse(JSON.stringify(rows[rows.length-1]));let n=rows.length+1;
 const prefix=basis.value?.basis.units.find(u=>u.id===row.basis_id)?.name||(side==='red'?'红方':'蓝方');
 while(sides.some(t=>value.value!.teams[t].some(u=>u.name===`${prefix.slice(0,42)}·演习分队${n}`)))n++;
 row.name=`${prefix.slice(0,42)}·演习分队${n}`;rows.push(row);pick(side,rows.length-1);
}
async function cancel(){if(operationId&&working.value){try{await api.cancelScenario(operationId);}catch(e){error.value=String(e);}}}
async function prepare(){
 if(loadingPromise)await loadingPromise;
 if(working.value||props.busy)return false;
 if(!basis.value||loading.value){if(!error.value)error.value='演习基础读取未完成，请重新选择基础或稍后重试。';return false;}
 if(draft.value&&!fieldValid.value){error.value='配置校验失败：名称须唯一、人员至少1人，人员装备等计数须为整数；粮弹工作量可为小数，库存范围与部署位置须有效。';return false;}
 if(!draft.value)await generate();else if(!valid.value)await validate();
 await nextTick();if(!valid.value&&!error.value)error.value='生成配置尚未通过校验，请检查参数后重试。';return valid.value;
}
defineExpose({selectUnit,placeSelected,cancel,prepare});
</script>

<template>
 <section class="scenario-composer" data-testid="synthetic-setup" aria-label="史实基础合成演习编辑">
  <p v-if="loading" role="status">{{sourceDraftId?'正在从同一历史初态派生并验证…':'正在载入史实基础…'}}</p><p v-if="error" class="bad" role="alert">{{error}}</p>
  <template v-if="basis&&value">
   <strong>史实基础 → DSH skill配置 → 地图编辑 → {{executionBackend==='afsim'?'AFSIM装载验证':'DSH配置校验'}}</strong><p class="note">{{basis.basis.scope}} {{basis.estimates}}</p>
   <details data-testid="scenario-basis"><summary>参战部队与来源（只读基础）</summary><article v-for="u in basis.basis.units" :key="u.id"><b>{{u.team==='red'?'红方':'蓝方'}} · {{u.name}}</b><p>{{u.context}}</p><a v-for="(s,i) in u.sources" :key="i" :href="s.url" target="_blank" rel="noopener noreferrer">{{s.title||s.id}} </a></article><small>缺载项：{{basis.basis.unknowns.join('、')}}</small></details>
   <label>演习变体需求<textarea v-model="instruction" rows="3" maxlength="4000" :disabled="busy||working" placeholder="例如：红方分2个局部编组，各1500人；蓝方保持1个守备编组。装备配发与坐标须注明估计。"></textarea></label>
   <button type="button" @click="generate" :disabled="busy||working||loading" data-testid="generate-scenario">{{working?'正在处理…':'DSH调用skill生成并验证配置'}}</button>
   <p v-if="!draft" class="note">先生成配置，再编辑部署。当前地图为史实基础派生种子预览，未开始推演。</p>
   <template v-else><p :class="valid?'verified':'note'" role="status" data-testid="scenario-validation">{{valid?(executionBackend==='afsim'?'AFSIM已装载核验当前配置；可创建战局。':'DSH生成配置已通过结构与来源校验；未启动AFSIM，可创建战局。'):'配置或引擎有未验证的修改；重新验证后可创建战局。'}}</p><details><summary>DSH生成时说明与当前验证证据</summary><p class="note">说明保留生成时的估计；当前参数以已验证配置为准。</p><p>{{draft.construction.skill}} · {{draft.construction.explanation}}</p><p v-if="draft.afsim">AFSIM {{draft.afsim.version}} · {{draft.afsim.entity_count}}个编组 · 退出码{{draft.afsim.returncode}}</p><p v-else>DSH配置校验；过程效果将在推演时由模型估计。</p><code>{{draft.id}}</code></details></template>
   <AviationParametersEditor v-if="value.aviation" :parameters="value.aviation" :identities="basis.preview_world.historical_initial?.definition.units.filter(u=>u.role==='aviation')" :disabled="busy||working||!draft" />
   <FireAccountingEditor v-model="value.fire_accounting" v-model:dynamics="value.fire_dynamics" :disabled="busy||working||!draft" />
   <p class="note" data-testid="synthetic-team-capacity">每方最多 {{maxUnitsPerTeam}} 个演习编组。新增、删减与换装是演习配置，不改写历史编制。</p>
   <section v-for="side in sides" :key="side" :data-testid="'synthetic-'+side" class="side">
    <header><strong>{{side==='red'?'红方':'蓝方'}} · {{value.teams[side].length}} 个编组</strong><button type="button" :disabled="busy||working||!draft||!value.teams[side].length||value.teams[side].length>=maxUnitsPerTeam" @click="add(side)">添加编组</button></header>
    <p v-if="!value.teams[side].length" class="note" data-testid="synthetic-empty-side">共同初态未在本阶段部署此方部队，不补造敌军。当前派生需要同阵营初态作为改编基础，暂不支持为无基线的一方新增编组。</p>
    <details v-for="(u,index) in value.teams[side]" :key="index" :open="index===0" class="formation"><summary>{{u.name||'未命名编组'}} · {{u.personnel}}人</summary>
     <fieldset :disabled="busy||working||!draft"><div class="unit-heading"><label>演习编组名称<input v-model="u.name" maxlength="60" :aria-label="`${side}-${index}-名称`"></label><button type="button" @click="pick(side,index)" :aria-label="`部署${side}编组${index+1}`">地图部署</button><button type="button" :disabled="value.teams[side].length<=1" @click="value.teams[side].splice(index,1)" :aria-label="`删除${side}编组${index+1}`">删除</button></div>
     <small class="note">来源单位：{{basis.basis.units.find(r=>r.id===u.basis_id)?.name}}；{{u.position?.lat.toFixed(5)}}, {{u.position?.lng.toFixed(5)}}（演习估计/地图编辑）</small>
     <div class="grid"><label>人员（人）<input type="number" v-model.number="u.personnel" min="1" max="100000" :aria-label="`${side}-${index}-人员`"></label><label v-for="e in equipment" :key="e.key">{{e.label}}<input type="number" v-model.number="u.equipment[e.key]" min="0" max="10000" :aria-label="`${side}-${index}-${e.label}`"></label><label v-for="s in stores" :key="s.key">{{s.label}}<input type="number" v-model.number="u[s.key]" min="0" :max="s.max" :step="s.key==='food'||s.key==='ammo'?'any':1" :aria-label="`${side}-${index}-${s.label}`"></label></div></fieldset>
    </details>
   </section>
   <p v-if="!fieldValid" class="bad" role="alert">请检查每方不超过 {{maxUnitsPerTeam}} 个编组、名称唯一、人数至少1人、人员装备等计数为整数；粮弹工作量可为范围内小数，部署位置须有效。</p>
   <button v-if="draft" type="button" @click="validate" :disabled="busy||working||!fieldValid||valid" data-testid="validate-scenario">{{executionBackend==='afsim'?'AFSIM重新装载验证':'重新校验DSH配置'}}</button>
  </template>
 </section>
</template>

<style scoped>
.scenario-composer{border-block:1px solid #294553;padding:14px 0;margin:12px 0;font-size:12px;line-height:1.6}.note{color:#9db6c5}.verified{color:#85cfa9}.side{margin-top:16px}.side header{display:flex;align-items:center;justify-content:space-between;color:#c4dce4}.formation{border-top:1px solid #294553;margin-top:9px;padding:8px 0}summary{cursor:pointer;color:#c1d4dc}fieldset{border:0;padding:10px 0 0;margin:0;min-width:0}.unit-heading{display:flex;align-items:end;gap:8px}.unit-heading label{flex:1;min-width:0}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px 12px;margin-top:9px}label{display:block;font-size:11px;color:#a9c3ce;margin-top:9px}input,textarea{display:block;width:100%;box-sizing:border-box;margin-top:4px}button{font-size:11px;white-space:nowrap}article{margin-block:10px}code{overflow-wrap:anywhere}@media(max-width:600px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.unit-heading{flex-wrap:wrap}.unit-heading label{flex-basis:100%}}
</style>
