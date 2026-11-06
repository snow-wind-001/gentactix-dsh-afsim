<script setup lang="ts">
import {computed,ref} from 'vue';
import type {FormationPartitions,HistoricalActorParameters,FormationPartInput,PartEquipment,PartResources} from '../types';
import {formationPartIssues,partEquipmentKeys,partResourceKeys} from '../formation-parts';
const props=defineProps<{modelValue?:FormationPartitions;actors:Record<string,HistoricalActorParameters>;basis:{id:string;name:string;team:string}[];disabled:boolean}>();
const emit=defineEmits<{'update:modelValue':[value:FormationPartitions|undefined];select:[value:{actorId:string;partId:string}]}>();
const parentId=ref(''),amount=ref(5);
const names=computed(()=>Object.fromEntries(props.basis.map(u=>[u.id,u.name])));
const issues=computed(()=>formationPartIssues(props.modelValue,props.actors));
const equipmentLabels:Record<string,string>={armor:'装甲',artillery:'火炮',air_defense:'防空',engineer:'工兵组',transport:'运输单元'};
const resourceLabels:Record<string,string>={fuel_liters:'燃油 升',spares:'备件 件',materials:'材料 包',shells:'炮弹 发',aa_rounds:'防空弹 发'};
const draft=():FormationPartitions=>JSON.parse(JSON.stringify(props.modelValue??{version:'formation-partitions-1',groups:{}}));
function change(id:string,partId:string,key:keyof FormationPartInput,value:unknown){
  const next=draft(),part=next.groups[id]?.parts.find(p=>p.id===partId);if(!part)return;
  Object.assign(part,{[key]:value});emit('update:modelValue',next);
}
function numberField(id:string,partId:string,key:'equipment'|'resources',field:string,value:string){
  const next=draft(),part=next.groups[id]?.parts.find(p=>p.id===partId);if(!part)return;
  (part[key] as Record<string,number>)[field]=Number(value);emit('update:modelValue',next);
}
function detach(){
  const id=parentId.value,p=props.actors[id],n=amount.value;if(!p||!Number.isInteger(n)||n<1)return;
  const next=draft();let group=next.groups[id];
  if(!group){
    group={assumption:'用户明确划分的互斥计算分队；不是新增历史番号，部署与配发为计算估计。',parts:[{
      id:'main',label:'主队',personnel:p.personnel,position:{...p.position},equipment:{...p.equipment},
      resources:Object.fromEntries(partResourceKeys.map(k=>[k,Number(p.formation[k])])) as PartResources,
      dispersion_km2:Number(p.formation.dispersion_km2),assumption:'父单位扣除分遣后的计算主队。'}]};
    next.groups[id]=group;
  }
  const main=group.parts[0]!;if(group.parts.length>=(next.version==='formation-partitions-2'?32:8)||main.personnel<=n)return;
  let index=1;while(group.parts.some(p=>p.id===`part${index}`))index++;
  const area=Math.max(.001,main.dispersion_km2*n/main.personnel);main.personnel-=n;
  main.dispersion_km2=Math.max(.001,main.dispersion_km2-area);
  group.parts.push({id:`part${index}`,label:`分遣${index}`,personnel:n,position:{...main.position},
    equipment:Object.fromEntries(partEquipmentKeys.map(k=>[k,0])) as PartEquipment,
    resources:Object.fromEntries(partResourceKeys.map(k=>[k,0])) as PartResources,
    dispersion_km2:area,assumption:'用户划出的计算分队；初始装备及绝对库存为0，部署须在地图明确选择。'});
  emit('update:modelValue',next);
}
function merge(id:string,partId:string){
  const next=draft(),group=next.groups[id];if(!group)return;
  const main=group.parts[0]!,part=group.parts.find(p=>p.id===partId);if(!part||part===main)return;
  main.personnel+=part.personnel;main.dispersion_km2+=part.dispersion_km2;
  for(const k of partEquipmentKeys)main.equipment[k]+=part.equipment[k];
  for(const k of partResourceKeys)main.resources[k]+=part.resources[k];
  group.parts=group.parts.filter(p=>p!==part);if(group.parts.length===1)delete next.groups[id];
  emit('update:modelValue',Object.keys(next.groups).length?next:undefined);
}
</script>

<template>
 <details class="part-editor" data-testid="formation-parts-editor">
  <summary>分岸与分遣配置 · {{Object.keys(modelValue?.groups??{}).length}}个父单位</summary>
  <p>分队各有位置、命令和战损账，父单位只作汇总。人员、装备、绝对库存必须守恒；这不是舟筏航行或历史精确部署模型。</p>
  <fieldset :disabled="disabled">
   <label>计算容量<select :value="modelValue?.version??'formation-partitions-1'" aria-label="计算编制容量" @change="{const v=draft();v.version=($event.target as HTMLSelectElement).value as FormationPartitions['version'];emit('update:modelValue',v)}"><option value="formation-partitions-1">局部 · 每父8分队 / 每方24叶子</option><option value="formation-partitions-2">会战 · 每父32分队 / 每方256叶子</option></select></label>
   <div class="fields"><label>划分父单位<select v-model="parentId" aria-label="划分父单位"><option value="">选择具名单位</option><option v-for="u in basis" :key="u.id" :value="u.id">{{u.team==='red'?'红方':'蓝方'}} · {{u.name}}</option></select></label>
    <label>从主队划出 人<input v-model.number="amount" type="number" min="1" aria-label="从主队划出人数"></label>
    <button type="button" @click="detach" :disabled="!parentId||!Number.isInteger(amount)||amount<1||amount>=(modelValue?.groups[parentId]?.parts[0]?.personnel??actors[parentId]?.personnel??0)">划出计算分队</button>
   </div>
   <section v-for="(g,id) in modelValue?.groups" :key="id" class="group" :data-partition-parent="id">
    <strong>{{names[id]??id}} · 总投入 {{actors[id]?.personnel}} 人</strong>
    <p>粮弹仍表示各分队的0–100保障覆盖；到货与消耗按人数占比折成父编组工作量，不把两份80相加为160。</p>
    <label>划分依据<textarea :value="g.assumption" @input="{const v=draft();v.groups[id]!.assumption=($event.target as HTMLTextAreaElement).value;emit('update:modelValue',v)}"></textarea></label>
    <article v-for="(part,index) in g.parts" :key="part.id" class="part" data-testid="formation-part-row" :data-part-id="part.id">
     <div class="part-title"><b>{{names[id]}} · {{part.label}}（计算分队）</b><button type="button" @click="emit('select',{actorId:String(id),partId:part.id})" :aria-label="`地图部署${names[id]}${part.label}`">地图部署</button><button v-if="index>0" type="button" @click="merge(String(id),part.id)">并回主队</button></div>
     <p>{{part.position.lat.toFixed(5)}}, {{part.position.lng.toFixed(5)}} · {{(100*part.personnel/(actors[id]?.personnel||1)).toFixed(2)}}% 初始人员占比</p>
     <div class="fields"><label>计算名称<input :value="part.label" maxlength="40" @input="change(String(id),part.id,'label',($event.target as HTMLInputElement).value)"></label>
      <label>人员 人<input :value="part.personnel" type="number" min="1" @input="change(String(id),part.id,'personnel',Number(($event.target as HTMLInputElement).value))"></label>
      <label>展开 km²<input :value="part.dispersion_km2" type="number" min="0.001" step="0.001" @input="change(String(id),part.id,'dispersion_km2',Number(($event.target as HTMLInputElement).value))"></label>
     </div>
     <details><summary>装备与绝对库存配发</summary><div class="fields">
      <label v-for="k in partEquipmentKeys" :key="k">{{equipmentLabels[k]}}<input :value="part.equipment[k]" type="number" min="0" @input="numberField(String(id),part.id,'equipment',k,($event.target as HTMLInputElement).value)"></label>
      <label v-for="k in partResourceKeys" :key="k">{{resourceLabels[k]}}<input :value="part.resources[k]" type="number" min="0" @input="numberField(String(id),part.id,'resources',k,($event.target as HTMLInputElement).value)"></label>
     </div></details>
     <label>分队估计依据<textarea :value="part.assumption" @input="change(String(id),part.id,'assumption',($event.target as HTMLTextAreaElement).value)"></textarea></label>
    </article>
   </section>
   <p v-for="issue in issues" :key="issue" role="status" class="bad">{{issue}}；调整后重新校验。</p>
  </fieldset>
 </details>
</template>

<style scoped>
.part-editor{border-top:1px solid var(--line);padding-top:12px;margin:12px 0}summary{cursor:pointer;font-weight:600}.group,.part{border-top:1px solid var(--line);padding-top:12px;margin-top:12px}.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:10px;align-items:end}.part-title{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.part-title b{flex:1;min-width:150px}label{display:block;font-size:12px;margin:8px 0}input,select,textarea{display:block;width:100%;margin-top:5px;box-sizing:border-box}fieldset{border:0;padding:0;min-width:0}p{font-size:12px;color:var(--muted);line-height:1.7}.bad{color:#ffb4a8}
</style>
