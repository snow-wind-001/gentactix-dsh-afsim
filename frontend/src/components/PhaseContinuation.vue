<script setup lang="ts">
import { ref, watch } from 'vue';
import { api } from '../api';
import type { Snapshot } from '../types';
const props=defineProps<{sessionId:string;busy:boolean}>();
const emit=defineEmits<{snapshot:[Snapshot];busy:[boolean]}>();
const items=ref<{id:string;label:string;start:string}[]>([]),selected=ref(''),version=ref(''),error=ref('');
const preview=ref<Awaited<ReturnType<typeof api.previewPhase>>|null>(null),pending=ref(false);
watch(()=>props.sessionId,()=>{items.value=[];selected.value='';preview.value=null;error.value='';});
watch(selected,()=>{preview.value=null;error.value='';});
async function load(){pending.value=true;error.value='';try{const r=await api.phaseCandidates(props.sessionId);items.value=r.items;version.value=r.world_version;}catch(e){error.value=String(e);}finally{pending.value=false;}}
async function inspect(){pending.value=true;error.value='';try{preview.value=await api.previewPhase(props.sessionId,selected.value,version.value);}catch(e){error.value=String(e);}finally{pending.value=false;}}
async function start(){if(!preview.value)return;pending.value=true;emit('busy',true);error.value='';try{emit('snapshot',await api.continuePhase(props.sessionId,selected.value,version.value,{organization_revision:preview.value.organization_revision,command_revision:preview.value.command_revision}));}catch(e){error.value=String(e);preview.value=null;}finally{pending.value=false;emit('busy',false);}}
</script>
<template>
 <details data-testid="phase-continuation"><summary>续接已验证阶段</summary>
  <p class="muted">保留实际人员、装备、疲劳、库存及临时任务群。未完成命令按剩余时间续接。目标配置须同版本且时钟相接；时间间隙或计算粒度改变需要先登记。</p>
  <button :disabled="busy||pending" @click="load">查找已验证配置</button>
  <p v-if="!items.length" class="muted">尚未选择可续接配置。可先在想定编辑器生成并验证下一计算窗口。</p>
  <label v-if="items.length">下一阶段<select v-model="selected" aria-label="续接目标阶段"><option value="">请选择</option><option v-for="r in items" :key="r.id" :value="r.id">{{r.label}} · {{r.start}}</option></select></label>
  <button v-if="selected" :disabled="busy||pending" @click="inspect">检查继承账</button>
  <p v-if="preview" role="status">起点 {{preview.start}} · 继承 {{preview.handoff.carried.length}} 个单位 · 新进入 {{preview.handoff.entered.length}} · 退出范围 {{preview.handoff.exited.length}}</p>
  <details v-if="preview" data-testid="phase-command-handoff"><summary>任务交接：续接 {{preview.command_handoff.carried.length}} · 阻塞 {{preview.command_handoff.blocked.length}} · 终止 {{preview.command_handoff.terminated.length}}</summary>
   <p>退出任务群成员 {{preview.command_handoff.exited_members.length}}；原编组记录保留。单位智能体在新阶段重新绑定会话。</p>
   <template v-if="preview.command_handoff.initial_command"><p>{{preview.command_handoff.initial_command.scope}}</p><p v-for="r in preview.command_handoff.initial_command.changes" :key="r.unit_id">{{r.name}}：{{r.before_name}} → {{r.after_name}}</p></template>
   <p v-for="r in preview.command_handoff.blocked" :key="r.command_id">待处理：{{r.reason}}</p>
   <p v-for="r in preview.command_handoff.terminated" :key="r.command_id">任务终止：{{r.reason}}</p>
  </details>
  <details v-if="preview"><summary>单位继承明细</summary>
   <p v-for="r in preview.handoff.carried" :key="r.name">{{r.name}}：现员 {{r.current}}，累计伤亡 {{r.casualties}}；装备状态、疲劳和随队库存一并保留。</p>
   <p v-for="r in preview.handoff.entered" :key="r.name">进入范围：{{r.name}}，采用目标配置的显式估计。</p>
   <p v-for="r in preview.handoff.exited" :key="r.name">退出范围：{{r.name}}，完整前态留在来源检查点。</p>
  </details>
  <button v-if="preview" :disabled="busy||pending" @click="start">{{pending?'正在装载…':'继承并打开下一阶段'}}</button>
  <p v-if="error" role="alert">{{error}}</p>
 </details>
</template>
