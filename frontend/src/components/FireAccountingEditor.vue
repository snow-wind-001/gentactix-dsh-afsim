<script setup lang="ts">
import type {FireAccountingConfig,FireDynamicsConfig} from '../types';
const props=defineProps<{modelValue?:FireAccountingConfig;dynamics?:FireDynamicsConfig;disabled?:boolean}>();
const emit=defineEmits<{'update:modelValue':[value:FireAccountingConfig|undefined];'update:dynamics':[value:FireDynamicsConfig|undefined]}>();
function toggle(enabled:boolean){emit('update:modelValue',enabled?{version:'classified-indirect-1',
 assumption:'演习聚合计量假设：通用工作量代表直射轻武器弹药；炮击、压制按分类炮弹扣账，未经口径、炮班操作或历史弹耗标定。'}:undefined);}
function toggleDensity(enabled:boolean){emit('update:dynamics',enabled?{version:'live-footprint-density-1',
 assumption:'演习过程假设：双方同批射击前，按现存人员和实际坐标格更新同根编组共享密度；不是区域重叠、溅射或历史效能标定。'}:undefined);}
function toggleCarry(enabled:boolean){if(props.dynamics)emit('update:dynamics',{...props.dynamics,version:enabled?'live-footprint-density-2':'live-footprint-density-1'});}
</script>

<template>
 <div class="fire-accounting-editor" data-testid="fire-accounting-editor">
  <label><input type="checkbox" :checked="!!modelValue" :disabled="disabled" @change="toggle(($event.target as HTMLInputElement).checked)">炮击按分类炮弹记账</label>
  <template v-if="modelValue">
   <p>通用弹药工作量只用于直射轻武器；炮击与压制扣实际炮弹，不额外扣直射工作量。人员、火炮、装填、目标与时间仍约束开火。</p>
   <label>计量假设与适用范围<textarea :value="modelValue.assumption" maxlength="4000" rows="2" :disabled="disabled" @input="emit('update:modelValue',{...modelValue,assumption:($event.target as HTMLTextAreaElement).value})"></textarea></label>
  </template>
  <p v-else>沿用原计量：地面射击消耗通用工作量，炮击另扣分类炮弹。</p>
  <label><input type="checkbox" :checked="!!dynamics" :disabled="disabled" aria-label="动态目标密度" @change="toggleDensity(($event.target as HTMLInputElement).checked)">按现存人员更新目标密度（新规则）</label>
  <template v-if="dynamics">
   <p>双方同批射击前更新密度；同根部队在相同坐标格、相同展开面积时共享密度，移动后重新分组。此选择独立于炮弹计量。</p>
   <label><input type="checkbox" aria-label="连续压制余量" :checked="dynamics.version==='live-footprint-density-2'" :disabled="disabled" @change="toggleCarry(($event.target as HTMLInputElement).checked)">跨轮保留压制余量</label>
   <p v-if="dynamics.version==='live-footprint-density-2'" role="status">已选连续压制：按实际时长恢复并保留小数余量，避免短回合重复取整。此项不代表完整机动、保障或历史效能已验收。</p>
   <p v-else>沿用第一版动态密度；压制仍按轮回传整数，短回合可能加快恢复。</p>
   <label>过程假设与适用范围<textarea :value="dynamics.assumption" maxlength="4000" rows="2" :disabled="disabled" @input="emit('update:dynamics',{...dynamics,assumption:($event.target as HTMLTextAreaElement).value})"></textarea></label>
  </template>
  <p v-else>沿用轮初固定目标密度；该旧规则已发现毁伤随回合切分变化。</p>
  <small>修改后须重新验证配置；不换算既有库存或迁移已运行战局，仍需历史效能标定。</small>
 </div>
</template>

<style scoped>
.fire-accounting-editor{border-top:1px solid var(--line);padding-top:12px;margin-top:12px;font-size:12px}
label{display:flex;align-items:center;gap:8px}label:has(textarea){display:grid}p,small{color:var(--muted);line-height:1.6}textarea{width:100%;box-sizing:border-box}
</style>
