<script setup lang="ts">
import {computed} from 'vue';
import type {SupportDynamics} from '../types';
const props=defineProps<{modelValue?:SupportDynamics;disabled?:boolean;scheduled?:boolean}>();
const emit=defineEmits<{'update:modelValue':[value:SupportDynamics|undefined]}>();
type InputField=[keyof SupportDynamics,string,number,number,number];
const shared:InputField[]=[['move_factor','机动耗粮倍数',1,10,.1],
 ['shortage_fatigue_per_hour','每小时缺粮的疲劳系数',0,100,.1],['recovery_hours_per_fed_hour','供粮每小时消减缺粮时长',0,10,.1],
 ['incapacity_after_hours','非战斗失能起算时长（小时）',1,8760,1],['incapacity_fraction_per_hour','起算后每小时失能比例',0,.1,.0001]];
const fields=computed<InputField[]>(()=>[...(props.modelValue?.version==='personnel-rations-1'?[
 ['ration_kg_per_person_day','每人每日粮食（kg）',.001,100,.01],
 ['food_kg_per_work','粮食质量（kg/工作量）',.001,1e9,.1],
 ['carried_kg_per_committed_person','按投入人数登记的携行容量（kg/人）',.001,1000,.1],
 ] as InputField[]:[['food_work_per_hour','待命耗粮（工作量/小时）',.001,100,.1]] as InputField[]),...shared]);
function toggle(enabled:boolean){
 emit('update:modelValue',enabled?{version:'time-sustainment-1',food_work_per_hour:4,move_factor:2,
  shortage_fatigue_per_hour:2,recovery_hours_per_fed_hour:1,incapacity_after_hours:48,incapacity_fraction_per_hour:.0001,
  assumption:'未标定的教学试算参数：工作量按小时计；起算时长与失能比例用于敏感性分析，不代表史实或医学阈值。'}:undefined);
}
function choose(version:SupportDynamics['version']){
 if(!props.modelValue)return;
 const {food_work_per_hour,ration_kg_per_person_day,food_kg_per_work,carried_kg_per_committed_person,...common}=props.modelValue;
 emit('update:modelValue',{...common,version,...(version==='personnel-rations-1'?{
  ration_kg_per_person_day:.75,food_kg_per_work:125,carried_kg_per_committed_person:.5,
  assumption:'显式教学估计：干粮质量，不是历史实际配给或营养需求；质量换算须匹配运输吨位及粮食份额，携行容量独立检查；缺粮失能尚未标定。'
 }:{food_work_per_hour:4})});
}
function update(key:keyof SupportDynamics,value:number|string){if(props.modelValue)emit('update:modelValue',{...props.modelValue,[key]:value});}
</script>

<template>
 <details class="support-editor" data-testid="support-dynamics-editor">
  <summary>粮秣与缺粮影响 · {{modelValue?'按时间计算':'沿用每回合规则'}}</summary>
  <label class="toggle"><input type="checkbox" :checked="!!modelValue" :disabled="disabled" @change="toggle(($event.target as HTMLInputElement).checked)">按经过时间计算粮秣与缺粮影响</label>
  <p>仅修改本次初态，重新验证后生效。既有存档不迁移；配送方式由“粮弹分类配送”独立设置。</p>
  <template v-if="modelValue">
   <label>耗粮模型<select aria-label="耗粮模型" :value="modelValue.version" :disabled="disabled" @change="choose(($event.target as HTMLSelectElement).value as SupportDynamics['version'])"><option value="time-sustainment-1">按编组工作量（原模型）</option><option value="personnel-rations-1">按人数与粮食质量</option></select></label>
   <p v-if="modelValue.version==='personnel-rations-1'">需求随当前可用人数计算；质量换算须等于运输吨／包×1000×粮食份额。携行容量按投入人数登记，人员减少不会自动删粮。切换不会改写现有库存，请调整库存与容量后重新验证；不是史实配给。</p>
   <div class="fields"><label v-for="[key,label,min,max,step] in fields" :key="key">{{label}}<input type="number" :aria-label="label" :value="modelValue[key]" :min="min" :max="max" :step="step" :disabled="disabled" @input="update(key,($event.target as HTMLInputElement).valueAsNumber)"></label></div>
   <label>参数依据与适用范围<textarea :value="modelValue.assumption" rows="3" :disabled="disabled" @input="update('assumption',($event.target as HTMLTextAreaElement).value)"></textarea></label>
   <p>{{scheduled?'按固定到货时点分段核算；每段先耗粮，再计到货，后到物资不能抵消此前短缺。':'先消耗轮初随队粮，轮末补给不能抵消此前短缺。'}}缺粮累计影响疲劳，超过配置阈值才计非战斗失能；失能不等于阵亡。初始示例数值未经历史或生理标定。</p>
  </template>
 </details>
</template>

<style scoped>
.support-editor{border-block:1px solid #31515e;padding:12px 0;margin:12px 0;color:#c9dbe4;font-size:12px;line-height:1.65}summary{cursor:pointer;color:#dfc991}.toggle{display:flex;align-items:center;gap:8px;margin:10px 0}.toggle input{width:auto;margin:0}p{color:#a6bcc8}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 16px}label{display:block}input,textarea{display:block;width:100%;box-sizing:border-box;margin-top:4px}textarea{margin-bottom:10px}@media(max-width:480px){.fields{grid-template-columns:1fr}}
</style>
