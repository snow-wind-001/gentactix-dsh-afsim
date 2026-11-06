<script setup lang="ts">
import type {SplitSupply} from '../types';
const props=defineProps<{modelValue?:SplitSupply;disabled?:boolean}>();
const emit=defineEmits<{'update:modelValue':[value:SplitSupply|undefined]}>();
function toggle(enabled:boolean){emit('update:modelValue',enabled?{version:'split-stocks-1',food_mass_share:.5,priority:'food',assumption:'教学运输估计：原始补给包拆为等工作量粮弹库存；质量份额与配送优先级以本配置数值和选项为准，不是历史实测物资重量。'}:undefined);}
function update(key:keyof SplitSupply,value:string|number){if(props.modelValue)emit('update:modelValue',{...props.modelValue,[key]:value});}
</script>
<template>
 <details class="split-editor" data-testid="split-supply-editor">
  <summary>粮弹分类配送 · {{modelValue?'独立库存':'绑定补给包'}}</summary>
  <label class="toggle"><input type="checkbox" :checked="!!modelValue" :disabled="disabled" @change="toggle(($event.target as HTMLInputElement).checked)">粮食、弹药分别配送</label>
  <p>满弹仍能补粮，满粮仍能补弹；两类共用路线与运输载重，未运物资留在仓库。仅新初态生效，需重新验证。</p>
  <template v-if="modelValue">
   <label>粮食质量份额<input aria-label="粮食质量份额" type="number" min="0.01" max="0.99" step="0.01" :value="modelValue.food_mass_share" :disabled="disabled" @input="update('food_mass_share',($event.target as HTMLInputElement).valueAsNumber)"></label>
   <label>运力不足时优先配送<select aria-label="运力不足时优先配送" :value="modelValue.priority" :disabled="disabled" @change="update('priority',($event.target as HTMLSelectElement).value)"><option value="food">粮食</option><option value="ammo">弹药</option></select></label>
   <label>物资与运输估计依据<textarea rows="3" :value="modelValue.assumption" :disabled="disabled" @input="update('assumption',($event.target as HTMLTextAreaElement).value)"></textarea></label>
   <p>初始每包拆为各一工作量粮食与弹药；弹药质量份额为 1 − 粮食份额。运行后分别扣仓；质量当量不能当作粮食或弹药到货数。</p>
  </template>
 </details>
</template>
<style scoped>
.split-editor{border-block:1px solid #31515e;padding:12px 0;margin:12px 0;color:#c9dbe4;font-size:12px;line-height:1.65}summary{cursor:pointer;color:#dfc991}label{display:block;margin:10px 0}.toggle{display:flex;align-items:center;gap:8px}.toggle input{width:auto;margin:0}p{color:#a6bcc8}input,select,textarea{display:block;width:100%;box-sizing:border-box;margin-top:4px}
</style>
