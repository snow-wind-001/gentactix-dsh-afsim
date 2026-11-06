<script setup lang="ts">
import type {SupplySchedule} from '../types';
const props=defineProps<{modelValue?:SupplySchedule;disabled?:boolean;compatible:boolean;nodeIds:string[]}>();
const emit=defineEmits<{'update:modelValue':[value:SupplySchedule|undefined]}>();
const fields:[keyof Omit<SupplySchedule,'version'|'assumption'|'warehouse_tons_per_hour'>,string,number,number,number][]=[
 ['period_seconds','补给周期（秒）',60,86400,60],['passive_work_per_hour','普通保障上限（工作量/小时）',0,1000,.1],
 ['resupply_work_per_hour','主动补给上限（工作量/小时）',0,1000,.1],['convoy_speed_kph','运输周转速度（公里/小时）',.01,200,.1],
 ['loading_hours','每次装卸周转时间（小时）',.01,24,.01]];
function toggle(enabled:boolean){emit('update:modelValue',enabled?{
 version:'scheduled-supply-1',period_seconds:3600,passive_work_per_hour:4,resupply_work_per_hour:16,
 convoy_speed_kph:15,loading_hours:.25,warehouse_tons_per_hour:Object.fromEntries(props.nodeIds.map(id=>[id,100])),
 assumption:'未标定教学初值：按固定周期提供聚合补给服务，假定运输管线已运行；吨位是模型换算，不表示实际车队在途、真实道路或史实运输量。'}:undefined);}
function update(key:keyof SupplySchedule,value:number|string){if(props.modelValue)emit('update:modelValue',{...props.modelValue,[key]:value});}
function updateNode(id:string,value:number){if(props.modelValue)emit('update:modelValue',{...props.modelValue,warehouse_tons_per_hour:{...props.modelValue.warehouse_tons_per_hour,[id]:value}});}
</script>
<template>
 <details class="schedule-editor" data-testid="supply-schedule-editor">
  <summary>定时补给 · {{modelValue?'按固定时点配送':'沿用轮末配送'}}</summary>
  <label class="toggle"><input aria-label="按固定时点配送补给" type="checkbox" :checked="!!modelValue" :disabled="disabled||(!modelValue&&!compatible)" @change="toggle(($event.target as HTMLInputElement).checked)">按固定时点配送补给</label>
  <p>到货时点随战局累计时间推进；六小时内可以多次到货，不能用后到的物资支付此前消耗。同一仓库的单位共用装卸能力。</p>
  <p v-if="!compatible" role="status">需先启用按时耗粮和分类粮弹，并关闭尚未接入本模型的跨河设施约束。</p>
  <template v-if="modelValue">
   <div class="fields"><label v-for="[key,label,min,max,step] in fields" :key="key">{{label}}<input :aria-label="label" type="number" :value="modelValue[key]" :min="min" :max="max" :step="step" :disabled="disabled" @input="update(key,($event.target as HTMLInputElement).valueAsNumber)"></label>
    <label v-for="(rate,id) in modelValue.warehouse_tons_per_hour" :key="id">{{id==='red-historical-supply'?'红方仓库':id==='blue-historical-supply'?'蓝方仓库':id}}装卸能力（模型吨/小时）<input :aria-label="`${id}装卸能力`" type="number" min="0" max="1000000" step="1" :value="rate" :disabled="disabled" @input="updateNode(String(id),($event.target as HTMLInputElement).valueAsNumber)"></label>
   </div>
   <label>周期服务与运输估计依据<textarea :value="modelValue.assumption" rows="3" :disabled="disabled" @input="update('assumption',($event.target as HTMLTextAreaElement).value)"></textarea></label>
   <p>初值仅供试算，须重新验证。运输按距离、车辆、周转速度与装卸时间约束；具名车队在途、运输燃油和跨河共享容量另需建模。</p>
  </template>
 </details>
</template>
<style scoped>
.schedule-editor{border-block:1px solid #31515e;padding:12px 0;margin:12px 0;color:#c9dbe4;font-size:12px;line-height:1.65}summary{cursor:pointer;color:#dfc991}.toggle{display:flex;align-items:center;gap:8px;margin:10px 0}.toggle input{width:auto;margin:0}p{color:#a6bcc8}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 16px}label{display:block}input,textarea{display:block;width:100%;box-sizing:border-box;margin-top:4px}textarea{margin-bottom:10px}@media(max-width:480px){.fields{grid-template-columns:1fr}}
</style>
