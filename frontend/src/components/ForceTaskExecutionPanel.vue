<script setup lang="ts">
import {computed,ref,watch} from 'vue';
import {api} from '../api';
import type {CampaignGoalNode,ForceTaskExecutionDefinition,ForceTaskExecutionMember,ForceTaskPage} from '../types';
const props=defineProps<{sessionId:string;turn:number;revision:number;busy:boolean;team?:string;canArrive:boolean;modelValue:ForceTaskExecutionDefinition|null}>();
const emit=defineEmits<{'update:modelValue':[value:ForceTaskExecutionDefinition|null];changed:[]}>();
const enabled=ref(false),label=ref(''),start=ref(props.turn+1),finish=ref<'turn'|'arrived'|'goal'>('turn'),end=ref(props.turn+3),minimum=ref(1);
const mode=ref<'all'|'any'>('all'),taskIds=ref<string[]>([]),goalIds=ref<string[]>([]),finishGoal=ref('');
const assumption=ref('操作者设置的持续任务条件，非历史命令事实。');
const data=ref<ForceTaskPage|null>(null),members=ref<ForceTaskPage<ForceTaskExecutionMember>|null>(null),memberLabel=ref('');
const goals=ref<CampaignGoalNode[]>([]),working=ref(false),error=ref('');let generation=0;
const statuses:Record<string,string>={queued:'已确认，待发令',waiting_time:'等待起始回合',waiting_dependency:'等待前置',preparing:'准备发令',executing:'持续执行',blocked:'受限',completed:'已完成',failed:'未达判据',cancelled:'已撤销',manual_override:'人工优先',detached:'指挥关系已变',unavailable:'不在场或失能'};
const teamGoals=computed(()=>goals.value.filter(g=>g.team===props.team));
const definition=computed<ForceTaskExecutionDefinition|null>(()=>!enabled.value?null:{version:'force-task-execution-1',label:label.value,not_before_turn:start.value,
 after:{mode:mode.value,task_ids:taskIds.value,goal_ids:goalIds.value},
 finish:finish.value==='arrived'?{kind:'arrived'}:finish.value==='goal'?{kind:'goal',goal_id:finishGoal.value}:{kind:'turn',end_turn:end.value,minimum_executions:minimum.value},assumption:assumption.value});
watch(definition,value=>emit('update:modelValue',value),{deep:true,immediate:true});
watch(()=>props.canArrive,allowed=>{if(!allowed&&finish.value==='arrived')finish.value='turn';});
watch(()=>props.team,()=>{taskIds.value=[];goalIds.value=[];finishGoal.value='';});
watch(()=>props.turn,turn=>{start.value=Math.max(start.value,turn+1);end.value=Math.max(end.value,start.value);});
async function refresh(args:Record<string,string|number>={}){
 const current=++generation;working.value=true;error.value='';members.value=null;
 try{const result=await api.forceTasks(props.sessionId,{limit:8,...args});if(current===generation)data.value=result;}
 catch(e){if(current===generation)error.value=String(e);}finally{if(current===generation)working.value=false;}
}
async function loadGoals(){
 const sid=props.sessionId;const values:CampaignGoalNode[]=[];let args:Record<string,string|number>|null={limit:16};
 try{while(args){const page=await api.campaignObjectives(sid,args);values.push(...page.nodes);args=page.next_args;}if(sid===props.sessionId)goals.value=values;}
 catch{if(sid===props.sessionId)goals.value=[];}
}
watch(()=>[props.sessionId,props.turn,props.revision],()=>{void refresh();void loadGoals();},{immediate:true});
async function showMembers(args:Record<string,string|number>,name:string){
 working.value=true;error.value='';try{members.value=await api.forceTasks<ForceTaskExecutionMember>(props.sessionId,args);memberLabel.value=name;}catch(e){error.value=String(e);}finally{working.value=false;}
}
async function cancel(id:string){
 working.value=true;error.value='';try{const v=await api.forces(props.sessionId);
  await api.cancelForceTask(props.sessionId,{expected_turn:v.turn,revision:v.command_revision,world_version:v.world_version,organization_revision:v.revision,task_id:id});
  emit('changed');await refresh();
 }catch(e){error.value=String(e);}finally{working.value=false;}
}
</script>

<template>
 <section class="execution-tasks" data-testid="force-task-execution">
  <h4>持续任务</h4>
  <p>任务等待和跨轮行动沿现有命令执行。确认进入队列不等于部队实际收令；次数按所选后端回执记录，DSH结果为模型估计，不保证非零战果。人工改令后不会自动重新接管。</p>
  <p v-if="error" role="alert" class="error">{{error}}</p>
  <label><input type="checkbox" v-model="enabled" :disabled="busy||working" aria-label="启用持续任务">将本次分工设为持续任务</label>
  <fieldset v-if="enabled" :disabled="busy||working" class="execution-editor">
   <label>任务名称<input v-model="label" maxlength="120" aria-label="持续任务名称" placeholder="例如：南翼预备队投入"></label>
   <div class="pair"><label>最早执行回合<input type="number" v-model.number="start" :min="turn+1" :max="turn+1000" aria-label="持续任务起始回合"></label>
   <label>完成判据<select v-model="finish" aria-label="持续任务完成判据"><option value="turn">执行至指定回合</option><option value="arrived" :disabled="!canArrive">全部承担者实际到达</option><option value="goal" :disabled="!teamGoals.length">己方目标达成</option></select></label></div>
   <template v-if="finish==='turn'"><div class="pair"><label>结束回合<input type="number" v-model.number="end" :min="start" :max="turn+1000" aria-label="持续任务结束回合"></label><label>每单位最少实际执行次数<input type="number" v-model.number="minimum" min="1" max="1000" aria-label="最少实际执行次数"></label></div><p>受限后的替代待命、等待前置和未交付不计为原动作执行。</p></template>
   <label v-if="finish==='goal'">己方完成目标<select v-model="finishGoal" aria-label="持续任务完成目标"><option value="">选择目标</option><option v-for="goal in teamGoals" :key="goal.id" :value="goal.id">{{goal.label}}</option></select></label>
   <label>前置组合<select v-model="mode" aria-label="任务前置组合"><option value="all">全部满足后执行</option><option value="any">任一满足后执行</option></select></label>
   <details><summary>选择前置任务或目标 · {{taskIds.length+goalIds.length}}项</summary>
    <p>可在下方任务列表翻页选择；未选择前置时按起始回合执行。</p>
    <label v-for="goal in teamGoals" :key="goal.id"><input type="checkbox" :value="goal.id" v-model="goalIds" :aria-label="`前置目标${goal.label}`">目标 · {{goal.label}}</label>
   </details>
   <label>任务依据<textarea v-model="assumption" maxlength="2000" aria-label="持续任务依据"></textarea></label>
  </fieldset>
  <div class="task-heading"><span>已确认 {{data?.total??0}}项</span><button type="button" :disabled="busy||working" @click="refresh()">刷新任务</button></div>
  <p v-if="!data?.total">尚无持续任务；原有单次任务继续沿原命令队列执行。</p>
  <article v-for="task in data?.rows??[]" :key="task.id" :data-execution-task="task.id">
   <header><b>{{task.label}}</b><span>{{statuses[task.status]??task.status}}</span></header>
   <p>{{task.team==='red'?'红方':'蓝方'}} · {{task.member_count}}个冻结承担单位 · {{task.reason}}</p>
   <label v-if="enabled&&task.team===team"><input type="checkbox" :value="task.id" v-model="taskIds" :disabled="busy||working" :aria-label="`前置任务${task.label}`">作为本次前置</label>
   <div class="task-actions"><button type="button" :disabled="busy||working" @click="showMembers(task.member_args,task.label)">查看下级状态</button><button type="button" :disabled="busy||working||!task.can_cancel" :aria-label="`撤销持续任务${task.label}`" @click="cancel(task.id)">撤销任务</button></div>
  </article>
  <div class="task-actions" v-if="data?.total"><button type="button" :disabled="busy||working||!data.offset" @click="refresh({offset:Math.max(0,data.offset-8),limit:8,view_version:data.view_version})">上一页任务</button><button type="button" :disabled="busy||working||!data.next_args" @click="data.next_args&&refresh(data.next_args)">下一页任务</button></div>
  <section v-if="members" class="task-members" aria-label="持续任务成员状态"><b>{{memberLabel}} · 下级状态</b>
   <p v-for="member in members.rows" :key="member.unit_id"><strong>{{member.name}}</strong> · {{statuses[member.status]??member.status}} · 实际执行 {{member.executions}}次<br>{{member.reason}}</p>
   <button type="button" :disabled="busy||working||!members.next_args" @click="members.next_args&&showMembers(members.next_args,memberLabel)">下一页下级</button>
  </section>
 </section>
</template>

<style scoped>
.execution-tasks{margin:16px 0;border-block:1px solid var(--line);padding:12px 0}.execution-tasks h4{margin:0;color:#d9e7ea}.execution-tasks p{color:#9bb1bc}.execution-editor{border:0;padding:0;margin:12px 0}.execution-tasks label{display:block;margin:7px 0}.execution-tasks input:not([type=checkbox]),.execution-tasks textarea,.execution-tasks select{width:100%;box-sizing:border-box;display:block;margin-top:4px}.execution-tasks .pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}.task-heading,.execution-tasks article header,.task-actions{display:flex;align-items:center;justify-content:space-between;gap:8px}.execution-tasks article{padding:10px 0;border-top:1px solid var(--line)}.execution-tasks article header b{color:#e0e9eb}.execution-tasks article header span{color:#b7cbbf}.task-actions{justify-content:flex-start;flex-wrap:wrap}.task-members{padding-top:10px;border-top:1px solid var(--line)}.task-members p{padding:5px 0;border-bottom:1px solid var(--line)}.error{color:#efb1a7}button{font-size:11px}
</style>
