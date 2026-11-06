<script setup lang="ts">
import {computed} from 'vue';
import type {ArrivalSchedule,HistoricalInputConstraints} from '../types';
const props=defineProps<{entry:ArrivalSchedule;label:string;references:HistoricalInputConstraints['entries']}>();
const selectedReference=computed(()=>props.references.find(r=>r.id===props.entry.reference_id));
function reference(value:string){
 props.entry.reference_id=value;
 if(selectedReference.value?.reference_kind==='departure')props.entry.event_kind='departure';
}
function kind(value:string){
 if(value==='departure'||value==='battlefield_entry'){
  props.entry.event_kind=value;
  reference(props.entry.reference_id??props.references[0]?.id??'');
 }else{delete props.entry.event_kind;delete props.entry.reference_id;}
}
</script>
<template>
 <label>可行动起点（当地时间）<input v-model="entry.not_before" type="datetime-local" :aria-label="`${label}可行动起点`"></label>
 <template v-if="references.length">
  <label>时点含义<select :value="entry.event_kind??''" :aria-label="`${label}时点含义`" @change="kind(($event.target as HTMLSelectElement).value)"><option value="">尚未声明／继承父级</option><option value="departure">驻地启程</option><option value="battlefield_entry" :disabled="selectedReference?.reference_kind==='departure'">前沿边界入场</option></select></label>
  <label v-if="entry.event_kind">史料时点参考<select :value="entry.reference_id??''" :aria-label="`${label}史料时点参考`" @change="reference(($event.target as HTMLSelectElement).value)"><option value="" disabled>请选择参考</option><option v-for="ref in references" :key="ref.id" :value="ref.id">{{ref.reference_kind==='departure'?'启程':'接敌'}} · {{ref.label}} · {{ref.earliest}} — {{ref.latest}}</option></select></label>
  <p v-if="entry.event_kind==='departure'&&selectedReference?.reference_kind==='departure'" data-testid="departure-reference-note">可启程时间须在所选窗口内；来源未提供接敌时刻或位置。解锁后仍须下达行动命令，不会自动行军或保证接敌。</p>
  <p v-else-if="entry.event_kind==='departure'">从配置位置开始行军，须留足抵达参考区域的时间。后续由实际命令和仿真决定，不保证按时接敌。</p>
  <p v-else-if="entry.event_kind==='battlefield_entry'">单位初始位置须在参考前沿区域内。此前行程不在本局计算范围内，不会到时从驻地瞬移。</p>
  <p v-else>有独立分队时逐队绑定；仅填写时刻不能区分启程与接敌。</p>
 </template>
 <label>{{label}}时点依据<textarea v-model="entry.assumption" rows="2"></textarea></label>
</template>
<style scoped>
label{display:block;color:#aec6d2;margin-top:9px}input,textarea,select{display:block;width:100%;box-sizing:border-box;margin-top:4px}p{color:#9db6c5;line-height:1.6}
</style>
