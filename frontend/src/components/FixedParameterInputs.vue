<script setup lang="ts">
import {computed,ref,watch} from 'vue';
import type {HistoricalFixedField,HistoricalFixedInput,HistoricalParameters} from '../types';
const props=defineProps<{modelValue:HistoricalFixedInput[];fields:HistoricalFixedField[];requiredModels:string[];parameters?:HistoricalParameters|null;disabled?:boolean}>();
const emit=defineEmits<{'update:modelValue':[rows:HistoricalFixedInput[]];valid:[value:boolean];apply:[row:HistoricalFixedInput]}>();
const group=ref(''),choice=ref(''),number=ref<number|string>('');
const key=(path:string[])=>JSON.stringify(path);
const index=computed(()=>new Map(props.fields.map(f=>[key(f.path),f])));
const selectedKeys=computed(()=>new Set(props.modelValue.map(r=>key(r.path))));
const compatible=(f:HistoricalFixedField)=>f.required_models.every(m=>props.requiredModels.includes(m));
const available=computed(()=>props.fields.filter(f=>compatible(f)&&!selectedKeys.value.has(key(f.path))));
const groups=computed(()=>[...new Set(available.value.map(f=>f.group))]);
const options=computed(()=>available.value.filter(f=>f.group===group.value));
const field=computed(()=>options.value.find(f=>key(f.path)===choice.value));
watch(groups,values=>{if(!values.includes(group.value))group.value=values[0]??'';},{immediate:true});
watch(options,values=>{if(!values.some(f=>key(f.path)===choice.value))choice.value=values[0]?key(values[0].path):'';},{immediate:true});
watch(field,f=>{number.value=f?.value??'';},{immediate:true});
const numberValid=(n:unknown,f?:HistoricalFixedField)=>typeof n==='number'&&Number.isFinite(n)&&(!f?.integer||Number.isInteger(n));
const canAdd=computed(()=>!!field.value&&numberValid(number.value,field.value));
const issue=computed(()=>props.modelValue.some(r=>{const f=index.value.get(key(r.path));return !f||!compatible(f)||!numberValid(r.value,f);}));
watch(issue,bad=>emit('valid',!bad),{immediate:true});
function add(){if(canAdd.value&&field.value)emit('update:modelValue',[...props.modelValue,{path:[...field.value.path],value:number.value as number}]);}
function update(i:number,value:number){emit('update:modelValue',props.modelValue.map((r,j)=>j===i?{...r,value}:r));}
function remove(i:number){emit('update:modelValue',props.modelValue.filter((_,j)=>i!==j));}
function differs(row:HistoricalFixedInput){if(!props.parameters)return false;let v:unknown=props.parameters;for(const k of row.path){if(!v||typeof v!=='object')return true;v=(v as Record<string,unknown>)[k];}return v!==row.value;}
</script>
<template>
 <details class="fixed-inputs" data-testid="fixed-parameter-inputs">
  <summary>生成前指定数值 <span>{{modelValue.length?`已固定 ${modelValue.length} 项`:'可选'}}</span></summary>
  <p>明确指定的数值由程序约束，DSH填写其余参数。自然语言中的数值不自动固定；这里的输入仍是建模假设，不代表已考证史实。</p>
  <div class="picker">
   <label>配置对象<select v-model="group" aria-label="固定参数配置对象" :disabled="disabled"><option v-for="g in groups" :key="g" :value="g">{{g}}</option></select></label>
   <label>数值项目<select v-model="choice" aria-label="固定参数数值项目" :disabled="disabled"><option v-for="f in options" :key="key(f.path)" :value="key(f.path)">{{f.label}}</option></select></label>
   <label>指定数值<input v-model.number="number" aria-label="固定参数指定数值" type="number" :step="field?.integer?'1':'any'" :disabled="disabled||!field"></label>
   <button type="button" @click="add" :disabled="disabled||!canAdd" data-testid="add-fixed-parameter">固定此值</button>
  </div>
  <p v-if="!modelValue.length" class="muted">未固定任何数值。可先启用下方保障模型，再指定该模型参数；更换战役、版本或阶段会清除本表。</p>
  <ul v-else class="values" aria-label="已固定数值">
   <li v-for="(row,i) in modelValue" :key="key(row.path)" :data-fixed-path="key(row.path)">
    <label>{{index.get(key(row.path))?.label??'当前模板外的固定项目'}}<input type="number" :aria-label="`${index.get(key(row.path))?.label??'固定项目'}固定值`" :value="row.value" :step="index.get(key(row.path))?.integer?'1':'any'" :disabled="disabled" @input="update(i,($event.target as HTMLInputElement).valueAsNumber)"></label>
    <button type="button" :disabled="disabled" @click="remove(i)" :aria-label="`移除${index.get(key(row.path))?.label??'固定项目'}`">移除</button>
    <p v-if="!index.get(key(row.path))||!compatible(index.get(key(row.path))!)" class="bad" role="status">此项目需要相应模型。请启用该模型，或移除此固定值。</p>
    <p v-if="differs(row)" class="bad" role="status">下方编辑值与固定值不同；请修改或移除固定值后重验。<button type="button" :disabled="disabled" @click="emit('apply',row)">应用此固定值</button></p>
   </li>
  </ul>
  <p v-if="issue" class="bad" role="status">请修正固定项目及数值；非有限数、小数人数或未启用模型不能提交。</p>
  <p class="muted">只支持当前模板的数值项。文本、开关、编制结构与历史身份继续使用原配置入口；不从史料总人数自动分摊部队兵额。</p>
 </details>
</template>
<style scoped>
.fixed-inputs{border-block:1px solid #31515e;padding:12px 0;margin:12px 0;color:#c9dbe4;font-size:12px;line-height:1.65}summary{cursor:pointer;color:#dfc991}summary span{margin-left:8px;color:#a6bcc8}.picker{display:grid;grid-template-columns:1fr 1.4fr .7fr auto;gap:10px;align-items:end}label{display:block;min-width:0}input,select{width:100%;box-sizing:border-box;margin-top:4px}.values{padding:0;list-style:none}.values li{display:flex;gap:10px;align-items:end;flex-wrap:wrap;padding:10px 0;border-bottom:1px solid #244452}.values label{flex:1;min-width:180px}.values p{width:100%;margin:0}.muted{color:#a6bcc8}.bad{color:#f3b49c}button{white-space:nowrap}.values p button{margin-left:8px}@media(max-width:700px){.picker{grid-template-columns:1fr 1fr}.picker label:nth-child(2){grid-column:1/-1;grid-row:2}}
</style>
