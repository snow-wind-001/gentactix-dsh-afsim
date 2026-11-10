<script setup lang="ts">
import type {CampaignConfiguration,FormationPartitions,HistoricalScenarioBasis,HistoricalInputConstraints,MapPoint} from '../types';
import ArrivalScheduleEditor from './ArrivalScheduleEditor.vue';
const props=defineProps<{value:CampaignConfiguration;actors:HistoricalScenarioBasis['actors'];partitions?:FormationPartitions;constraints?:HistoricalInputConstraints|null;center:MapPoint;disabled:boolean;objectiveGraph?:boolean;nonContact?:boolean}>();
const emit=defineEmits<{'pick-region':[index:number]}>();
function addRegion(){props.value.objective.relief_regions.push({center:{...props.center},radius_km:1});}
function addPart(id:string,part:string){
 const row=props.value.arrivals[id];if(!row)return;
 (row.parts??={})[part]={not_before:row.not_before,assumption:'继承父单位入场估计；请核对本分队的到场依据。'};
}
function removePart(id:string,part:string){const row=props.value.arrivals[id];if(row?.parts){delete row.parts[part];if(!Object.keys(row.parts).length)delete row.parts;}}
</script>
<template>
 <fieldset :disabled="disabled" class="campaign-editor" data-testid="campaign-editor">
  <legend>战役过程与联合目标</legend>
  <p>{{nonContact?'以下部队激活时点与效能为计算参数；转移范围不设置虚构阻援或受降。':'以下入场时点、工事效能与受降阈值为计算参数，必须保留估计依据。'}}</p>
  <template v-if="!objectiveGraph">
  <label>保留初始投入人数的比例<input v-model.number="value.objective.min_force_fraction" type="number" min="0.001" max="1" step="0.05" aria-label="战役兵力保存比例"></label>
  <div v-for="(region,index) in value.objective.relief_regions" :key="index" class="region" :data-campaign-region="index">
   <strong>阻援区域 {{index+1}}</strong>
   <div class="grid"><label>纬度<input v-model.number="region.center.lat" type="number" min="-90" max="90" step="0.0001" :aria-label="`阻援区域${index+1}纬度`"></label><label>经度<input v-model.number="region.center.lng" type="number" min="-180" max="180" step="0.0001" :aria-label="`阻援区域${index+1}经度`"></label><label>半径 km<input v-model.number="region.radius_km" type="number" min="0.01" max="20" step="0.1" :aria-label="`阻援区域${index+1}半径`"></label></div>
   <button type="button" @click="emit('pick-region',index)">地图设置阻援区域 {{index+1}}</button>
   <button type="button" :disabled="value.objective.relief_regions.length<=1" @click="value.objective.relief_regions.splice(index,1)">移除区域 {{index+1}}</button>
  </div>
  <button type="button" :disabled="value.objective.relief_regions.length>=6" @click="addRegion">增加阻援区域</button>
  <label>联合目标依据<textarea v-model="value.objective.assumption" rows="2"></textarea></label>
  </template>
  <details v-if="!nonContact"><summary>受降条件</summary><label class="toggle"><input v-model="value.surrender.enabled" type="checkbox">启用接近受降</label>
   <div class="grid"><label>接收距离 m<input v-model.number="value.surrender.range_m" type="number" min="1" max="1000"></label><label>压制下限<input v-model.number="value.surrender.suppression_threshold" type="number" min="0" max="100"></label><label>弹药上限<input v-model.number="value.surrender.ammo_threshold" type="number" min="0" max="100"></label></div>
   <p>需要接近目标，并满足压制或缺弹条件之一；实际被俘计入减员，不等于阵亡。</p><label>受降依据<textarea v-model="value.surrender.assumption" rows="2"></textarea></label>
  </details>
  <details v-for="actor in actors" :key="actor.id" :data-campaign-actor="actor.id"><summary>{{actor.team==='red'?'红方':'蓝方'}} · {{actor.name}} · 入场与工事</summary>
   <template v-if="value.arrivals[actor.id]&&value.fortifications[actor.id]">
    <ArrivalScheduleEditor :entry="value.arrivals[actor.id]!" :label="actor.name" :immediate="value.availability_mode==='immediate'" :references="constraints?.entries.filter(r=>r.unit_id===actor.id)??[]" />
    <div v-for="part in partitions?.groups[actor.id]?.parts??[]" :key="part.id" class="part">
     <template v-if="value.arrivals[actor.id]!.parts?.[part.id]"><strong>{{part.label}}</strong><ArrivalScheduleEditor :entry="value.arrivals[actor.id]!.parts![part.id]!" :label="part.label" :immediate="value.availability_mode==='immediate'" :references="constraints?.entries.filter(r=>r.unit_id===actor.id)??[]" /><button type="button" @click="removePart(actor.id,part.id)">恢复继承父单位时点</button></template>
     <button v-else type="button" @click="addPart(actor.id,part.id)">为{{part.label}}单独设置入场</button>
    </div>
    <div class="grid"><label>初始工事完整度<input v-model.number="value.fortifications[actor.id]!.integrity" type="number" min="0" max="100" :aria-label="`${actor.name}工事完整度`"></label><label>每发工事损耗系数<input v-model.number="value.fortifications[actor.id]!.degradation_per_shell" type="number" min="0" max="100" step="0.01"></label></div>
    <label>工事依据<textarea v-model="value.fortifications[actor.id]!.assumption" rows="2"></textarea></label>
   </template>
  </details>
  <label>战役过程范围与限制<textarea v-model="value.assumption" rows="2"></textarea></label>
 </fieldset>
</template>
<style scoped>
.campaign-editor{border:0;border-block:1px solid #294553;padding:14px 0;margin:12px 0;min-width:0}legend,summary{color:#cfdee4}summary{cursor:pointer}p{color:#9db6c5;line-height:1.6}label{display:block;color:#aec6d2;margin-top:9px}input,textarea{display:block;width:100%;box-sizing:border-box;margin-top:4px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px 12px}details,.region{border-top:1px solid #294553;padding:12px 0;margin-top:10px}button{font-size:11px;margin:8px 8px 0 0}.toggle{display:flex;align-items:center;gap:8px}.toggle input{width:auto;margin:0}.part{padding-left:12px;border-left:2px solid #426576}@media(max-width:600px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
