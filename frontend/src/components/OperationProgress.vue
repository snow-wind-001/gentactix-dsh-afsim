<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import type { RuntimeProgress } from '../types';
import { OperationClock } from '../operationClock';

const props = defineProps<{ busy: string; progress: RuntimeProgress; outcome: 'success' | 'failed' | 'cancelled' | null;
  error: string; cancelling: boolean; disconnected: boolean }>();
const state = ref<'idle' | 'running' | 'success' | 'failed' | 'cancelled'>('idle');
const elapsed = ref<number | null>(0), operation = ref('操作');
const operationClock = new OperationClock();
let clock: ReturnType<typeof setInterval> | undefined, hide: ReturnType<typeof setTimeout> | undefined;
function stopClock() { if (clock) clearInterval(clock); clock = undefined; }
function operationName(label: string) {
  if (/推演|重现.*事件/.test(label)) return '推演';
  if (/复盘/.test(label)) return '复盘';
  if (/因果/.test(label)) return '因果分析';
  if (/反事实|命令对照|命令干预/.test(label)) return '只读试算';
  if (/命令解析/.test(label)) return '命令解析';
  if (/思考|问答|咨询/.test(label)) return '问答';
  if (/部署|侦察地形|初始化/.test(label)) return '初始化';
  return '操作';
}
function readClock() {
  const milliseconds = operationClock.elapsed(performance.now());
  elapsed.value = milliseconds === null ? null : Math.floor(milliseconds / 1000);
}
watch([() => props.busy, () => props.progress, () => props.outcome], ([label]) => {
  const now = performance.now();
  if (label) {
    if (state.value !== 'running') {
      if (hide) clearTimeout(hide);
      operationClock.start(now); state.value = 'running';
    }
    operationClock.observe(props.progress, now);
    operation.value = operationName(props.progress.label || label);
    readClock();
    if (!clock) clock = setInterval(readClock, 500);
  } else if (state.value === 'running') {
    if (props.progress.label) operation.value = operationName(props.progress.label);
    operationClock.finish(props.progress, now); readClock(); stopClock();
    state.value = props.outcome || (props.error ? 'failed' : 'idle');
    if (state.value === 'success' || state.value === 'cancelled') hide = setTimeout(() => { state.value = 'idle'; }, 4000);
  } else if (state.value !== 'idle') {
    // A terminal poll may arrive after the HTTP response. Refine, never restart.
    operationClock.finish(props.progress, now); readClock();
  }
}, { immediate: true });
const recovering = computed(() => ['empty_output_recovery', 'json_output_recovery'].includes(props.progress.phase || ''));
const runtimeWaiting = computed(() => ['retry_wait','retrying','compacting','compaction_failed'].includes(props.progress.runtime_state || ''));
const stage = computed(() => {
  if (state.value === 'success') return '已完成';
  if (state.value === 'failed') return '未完成，请查看错误';
  if (state.value === 'cancelled') return '已取消';
  if (props.cancelling) return '正在取消，等待确认';
  if (props.disconnected) return '状态连接暂不可用，仍在等待';
  if (props.progress.phase === 'afsim_execution') return 'AFSIM执行中';
  if (recovering.value) return '正在恢复模型输出';
  if (props.progress.runtime_state === 'retry_wait') return `模型请求等待重试${props.progress.retry_attempt ? ' · 第'+props.progress.retry_attempt+'次' : ''}`;
  if (props.progress.runtime_state === 'retrying') return 'DSH正在重试模型请求';
  if (props.progress.runtime_state === 'compacting') return 'DSH正在压缩上下文';
  if (props.progress.runtime_state === 'compaction_failed') return '上下文压缩未完成，等待运行结果';
  if (props.progress.runtime_state === 'checking') return '模型阶段已结束，正在校验';
  if (props.progress.receiving) return '接收并校验结果';
  if ((props.progress.steps || 0) > 0) return operation.value === '推演' ? 'DSH决策中' : 'DSH处理中';
  return '等待后端响应';
});
const tone = computed(() => state.value !== 'running' ? state.value : props.cancelling || props.disconnected || recovering.value || runtimeWaiting.value ? 'waiting' : props.progress.receiving ? 'receiving' : props.progress.phase === 'afsim_execution' ? 'external' : 'planning');
const duration = computed(() => {
  if (elapsed.value === null) return '--:--';
  const h = Math.floor(elapsed.value / 3600), m = Math.floor(elapsed.value / 60) % 60, s = elapsed.value % 60;
  return (h ? String(h).padStart(2,'0') + ':' : '') + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
});
const summary = computed(() => `${operation.value}${state.value === 'running' ? '中' : state.value === 'success' ? '完成' : state.value === 'cancelled' ? '已取消' : '未完成'}`);
const description = computed(() => `${summary.value} · ${stage.value} · ${elapsed.value === null ? '等待时长未记录' : '已等待 ' + duration.value}${props.progress.steps ? ' · DSH ' + props.progress.steps + '步' : ''}；等待期间不表示完成百分比`);
onBeforeUnmount(() => { stopClock(); if (hide) clearTimeout(hide); });
</script>

<template>
  <div v-show="state !== 'idle'" class="operation-line" :class="tone" data-testid="operation-progress" :data-state="state" :data-stage="tone" :data-clock-source="operationClock.source"
    :role="state === 'running' ? 'progressbar' : 'status'" :aria-label="summary" :aria-valuetext="state === 'running' ? description : undefined" :title="description">
    <span class="operation-trail"></span><span class="operation-sweep"></span>
  </div>
  <Teleport defer to="#workspace-operation-status">
    <span v-if="state !== 'idle'" class="operation-badge" :class="{pending:state==='running'}" data-testid="operation-status" :title="description">
      <i :class="tone" aria-hidden="true"></i><b>{{ summary }}</b><span class="operation-stage">{{ stage }}</span><time data-testid="operation-elapsed">{{ duration }}</time>
    </span>
    <span v-if="state !== 'idle'" class="operation-sr" role="status" aria-live="polite">{{ summary + '，' + stage }}</span>
  </Teleport>
</template>

<style scoped>
.operation-line { --progress-color: #68cbd0; position: absolute; z-index: 1300; top: 0; left: var(--rail); right: var(--rail); height: 3px; overflow: hidden; background: #265064; pointer-events: none; }
.operation-trail { position: absolute; inset: 0; background: var(--progress-color); opacity: .38; }
.operation-sweep { display: block; height: 100%; width: 35%; background: linear-gradient(90deg, transparent, var(--progress-color) 45%, var(--progress-color) 72%, transparent); animation: operation-sweep 1.7s linear infinite; will-change: transform; }
.external { --progress-color: #e6b777; }.waiting { --progress-color: #d4bd78; }.receiving { --progress-color: #92b7e0; }.success { --progress-color: #85cfa9; }.failed { --progress-color: #ef8f87; }.cancelled { --progress-color: #afbbc5; }
.operation-line.success .operation-sweep, .operation-line.failed .operation-sweep, .operation-line.cancelled .operation-sweep { width: 100%; animation: none; background: var(--progress-color); }
.operation-badge { display: inline-flex; align-items: center; gap: 9px; color: #b9d0dc; font-size: 11px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.operation-badge i { --progress-color: #68cbd0; width: 5px; height: 5px; background: var(--progress-color); border-radius: 50%; }
.operation-badge i.external, .operation-badge i.waiting { --progress-color: #e6b777; }.operation-badge i.success { --progress-color: #85cfa9; }.operation-badge i.failed { --progress-color: #ef8f87; }.operation-badge i.cancelled { --progress-color: #afbbc5; }
.operation-badge i.receiving { --progress-color: #92b7e0; }
.operation-badge b { font-weight: 550; color: #deebef; }.operation-stage { color: #9ab6c5; }.operation-badge time { color: #d9d0af; }
.operation-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
@keyframes operation-sweep { from { transform: translateX(-105%); } to { transform: translateX(390%); } }
@media(max-width:1100px) { .operation-stage { display: none; } }
@media(max-width:680px) { .operation-badge:not(.pending) { display: none; }.operation-badge { font-size: 10px; gap: 5px; } }
@media(prefers-reduced-motion:reduce) { .operation-sweep { animation: none; width: 100%; background: var(--progress-color); opacity: .65; } }
</style>
