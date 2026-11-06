import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { apply } from '../../plugins/dsh-gentactix/index.mjs';

const dir = await mkdtemp(join(tmpdir(), 'gentactix-policy-'));
const token = randomUUID();
process.env.GENTACTIX_CONTROL_TOKEN = token;
process.env.GENTACTIX_TOOL_BRIDGE = 'http://127.0.0.1:1';
process.env.GENTACTIX_CONTROL_FILE = join(dir, 'ready.json');
const listeners = new Map(), registry = new Map(), definitions = new Map();
const ctx = {
  tools: { register(definition) { definitions.set(definition.name, definition); return () => definitions.delete(definition.name); } },
  agents: { get: id => registry.get(id) },
  on(name, fn) {
    if (!listeners.has(name)) listeners.set(name, new Set());
    listeners.get(name).add(fn);
    return () => listeners.get(name).delete(fn);
  },
};
function emit(name, event) { for (const fn of listeners.get(name) ?? []) fn(event); }
function create(id) {
  const masks = new Set();
  const agent = { session: { id }, ctx: { tools: { restrict({ allow }) {
    assert(allow.every(name => definitions.has(name)));
    const value = new Set(allow); masks.add(value); return () => masks.delete(value);
  } } } };
  agent.visible = () => [...definitions.keys()].filter(name => [...masks].every(mask => mask.has(name)));
  registry.set(id, agent);
  emit('agent/created', { agent });
  return agent;
}
try {
  apply(ctx);
  let address;
  for (let i = 0; i < 100; i++) {
    try { address = JSON.parse(await readFile(process.env.GENTACTIX_CONTROL_FILE, 'utf8')); break; }
    catch { await new Promise(resolve => setTimeout(resolve, 10)); }
  }
  assert(address);
  async function call(path, body) {
    const response = await fetch(`http://127.0.0.1:${address.port}${path}`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    return { code: response.status, data: await response.json() };
  }
  const policy = allowed_tools => ({ allowed_tools, max_steps: 8, max_tool_calls: 16, max_tokens: 65536, reasoning_effort: 'high' });
  assert.equal((await call('/configure', { session_id: 'gentactix-first', policy: policy(['get_afsim_observation']) })).code, 200);
  const first = create('gentactix-first');
  assert.deepEqual(first.visible(), ['get_afsim_observation']); // BEFORE pre-step or request.
  const other = create('gentactix-unit-new');
  assert.deepEqual(other.visible(), []);
  assert.equal((await call('/configure', { session_id: other.session.id, policy: policy(['get_scenario_basis']) })).code, 200);
  assert.deepEqual(other.visible(), ['get_scenario_basis']);
  assert.deepEqual(first.visible(), ['get_afsim_observation']);
  assert.equal((await call('/configure', { session_id: first.session.id, policy: policy([]) })).code, 200);
  assert.deepEqual(first.visible(), []);
  const unitTool = definitions.get('submit_unit_order');
  assert.deepEqual(unitTool.parameters.required, ['order', 'rationale', 'expected_effect']);
  assert.equal(unitTool.parameters.additionalProperties, false);
  assert.equal(unitTool.parameters.properties.order.additionalProperties, false);
  assert.equal(unitTool.parameters.properties.rationale.maxLength, 1000);
  const plannerTool = definitions.get('submit_planner_orders');
  assert.deepEqual(plannerTool.parameters.required, ['orders']);
  assert.equal(plannerTool.parameters.additionalProperties, false);
  assert.equal(plannerTool.parameters.properties.orders.maxItems, undefined);
  assert.deepEqual(plannerTool.parameters.properties.orders.items.required,
    ['unit_id', 'action', 'rationale', 'expected_effect']);
  assert.equal(plannerTool.parameters.properties.orders.items.properties.end_turn, undefined);
  await call('/configure', { session_id: first.session.id, policy: policy(['submit_planner_orders']) });
  assert.deepEqual(first.visible(), ['submit_planner_orders']);
  assert(!other.visible().includes('submit_planner_orders'));
  const plannerFetch = globalThis.fetch;
  const plannerArgs = {orders:Array.from({length:20},(_,i)=>({unit_id:`unit-${i}`,action:'hold',
    rationale:'离线原生工具流程测试',expected_effect:'尚未执行'}))};
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ok:false,readonly:true,error:'名单不完整'}));
    assert.equal((await plannerTool.execute(plannerArgs,{agent:first})).ok, false);
    assert.deepEqual(first.visible(), ['submit_planner_orders']);
    globalThis.fetch = async (_url,options) => {
      assert.deepEqual(JSON.parse(options.body).args,plannerArgs);
      return new Response(JSON.stringify({ok:true,readonly:true,version:'planner-order-proposal-1',
        operation_id:'qa-operation',world_version:'qa-world',command_revision:3,order_count:20,
        proposal_digest:'b'.repeat(64),required_units_digest:'c'.repeat(64)}));
    };
    const accepted = await plannerTool.execute(plannerArgs,{agent:first});
    assert.equal(accepted.next_action,'final_response');
    assert.deepEqual(first.visible(), []);
  } finally { globalThis.fetch = plannerFetch; }
  assert.equal((await call('/configure', { session_id: other.session.id, policy: policy(['submit_unit_order']) })).code, 200);
  assert.deepEqual(other.visible(), ['submit_unit_order']);
  assert(!first.visible().includes('submit_unit_order'));
  assert.equal((await call('/configure', { session_id: other.session.id, policy: policy(['get_scenario_basis']) })).code, 200);
  assert.equal((await call('/configure', { session_id: first.session.id, policy: policy(['mcp__afsim__run_mission']) })).code, 400);
  assert.deepEqual(first.visible(), []);
  const unowned = create('other-application');
  assert.equal(unowned.visible().length, definitions.size);
  const health = (await call('/health', {})).data;
  assert(health.capabilities.includes('agent-tool-visibility'));
  assert(health.capabilities.includes('turn-preview-paging'));
  assert.equal(health.mode, 'native');
  assert.equal(health.ptc, false);
  // Disposing a scope releases only its own mask, then a resume reapplies
  // the pending role policy before its first request.
  emit('agent/disposed', { agent: other }); registry.delete(other.session.id);
  assert.equal(other.visible().length, definitions.size);
  const resumed = create(other.session.id);
  assert.deepEqual(resumed.visible(), ['get_scenario_basis']);
  const requestHook = [...listeners.get('agent/request')][0];
  const config = await requestHook({ agent: resumed }, async () => ({ model: 'unchanged' }));
  assert.equal(config.maxTokens, 65536); assert.equal(config.reasoningEffort, 'high');
  await assert.rejects(() => definitions.get('update_scenario_configuration').execute({}, { agent: resumed }), /未启用/);
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ error: '翻页必须沿用view_version，参数未提交' }), { status: 400 });
    await assert.rejects(() => definitions.get('get_scenario_basis').execute({}, { agent: resumed }), /view_version/);
    globalThis.fetch = async () => new Response('<html>unavailable</html>', { status: 502 });
    await assert.rejects(() => definitions.get('get_scenario_basis').execute({}, { agent: resumed }), /HTTP 502/);
  } finally { globalThis.fetch = originalFetch; }
  const pageTool = definitions.get('get_turn_preview');
  assert.deepEqual(pageTool.parameters.anyOf, [
    {required:['preview_hash']}, {required:['candidate_ref']},
  ]);
  assert.equal(pageTool.parameters.required, undefined, 'failed candidates must not require a successful preview');
  assert.deepEqual(pageTool.parameters.properties.kind.enum, ['units','goals','constraints']);
  assert.equal(pageTool.parameters.properties.limit.maximum, 16);
  assert.equal(pageTool.parameters.additionalProperties, false);
  await call('/configure', { session_id: resumed.session.id, policy: policy(['get_turn_preview']) });
  const digest = 'a'.repeat(64);
  const pair = [
    {type:'tool/call',seq:1,data:{name:'preview_turn_effects',callId:'p',arguments:{candidate:{orders:[]}}}},
    {type:'tool/result',seq:2,data:{message:{toolCallId:'p',content:[{type:'text',text:JSON.stringify({ok:true,readonly:true,version:'turn-effects-preview-1',digest})}]}}},
  ];
  resumed.session.snapshotEvents = () => [...pair,{type:'assistant/message',seq:3,data:{content:'unrelated text must not be forwarded'}}];
  try {
    globalThis.fetch = async (_url, options) => {
      const value = JSON.parse(options.body);
      assert.equal(value.session_id, resumed.session.id);
      assert.equal(value.tool, 'get_turn_preview');
      assert.deepEqual(value.args, {preview_hash:digest,kind:'units',offset:16,limit:16});
      assert.deepEqual(value.preview_events, pair);
      return new Response(JSON.stringify({ok:true,readonly:true,total:22,items:[],next_args:null}));
    };
    assert((await pageTool.execute({preview_hash:digest,kind:'units',offset:16,limit:16},{agent:resumed})).ok);
  } finally { globalThis.fetch = originalFetch; }
  const candidateRef = 'e'.repeat(64);
  const failedPair = [
    {type:'tool/call',seq:4,data:{name:'preview_turn_effects',callId:'failed',arguments:{candidate:{orders:[]}}}},
    {type:'tool/result',seq:5,data:{message:{toolCallId:'failed',content:[{type:'text',text:JSON.stringify({ok:false,readonly:true,version:'turn-effects-preview-1',candidate_ref:candidateRef})}]}}},
  ];
  resumed.session.snapshotEvents = () => [...pair, ...failedPair,
    {type:'assistant/message',seq:6,data:{content:'unrelated text must not be forwarded'}}];
  try {
    globalThis.fetch = async (_url, options) => {
      const value = JSON.parse(options.body);
      assert.deepEqual(value.args, {candidate_ref:candidateRef,kind:'constraints',offset:16,limit:16});
      assert.deepEqual(value.candidate_events, failedPair, 'constraint pages use the linked failed candidate only');
      assert.equal(value.preview_events, undefined, 'failed candidates must not borrow successful preview evidence');
      return new Response(JSON.stringify({ok:true,readonly:true,total:20,items:[],next_args:null}));
    };
    assert((await pageTool.execute({candidate_ref:candidateRef,kind:'constraints',offset:16,limit:16},{agent:resumed})).ok);
  } finally { globalThis.fetch = originalFetch; }
  const guard = [...listeners.get('tools/pre-execute')][0];
  await assert.rejects(() => guard({ agent: resumed, name: 'mcp__afsim__run_mission' }, async () => 'wrong'), /控制端/);
  assert.equal(await guard({ name: 'mcp__afsim__run_mission' }, async () => 'controller'), 'controller');
  // Accepted reports end only this operation's tool authoring phase. This
  // fixture exercises the real plugin bridge; host proof/commit checks live in
  // verify_native_report_submission.py and must not be relaxed by this gate.
  const authorTools = ['get_observation', 'preview_turn_effects', 'amend_turn_effects', 'submit_turn_report', 'get_turn_preview'];
  await call('/configure', { session_id: first.session.id, policy: policy(authorTools) });
  first.session.snapshotEvents = () => pair;
  const reportTool = definitions.get('submit_turn_report');
  const reportArgs = { preview_hash: digest, report: '各军原地待命，按本轮结算消耗粮食。' };
  const accepted = { ok: true, readonly: true, version: 'turn-report-proposal-1',
    preview_hash: digest, report_digest: 'b'.repeat(64), before_hash: 'c'.repeat(64), operation_id: 'current-operation' };
  const failReply = { ok: false, readonly: true, version: accepted.version, issues: [{ code: 'inventory_claim' }] };
  const bridgeCalls = [];
  const peerBefore = resumed.visible();
  const stepHook = [...listeners.get('agent/pre-step')][0];
  await assert.rejects(() => stepHook({ agent: first, step: 9 }, async () => 'wrong'), /步骤预算/);
  assert.equal(await stepHook({ agent: first, step: 8 }, async () => 'last authoring step'), 'last authoring step');
  try {
    let reply = failReply;
    let reconfigureDuringReport = false;
    globalThis.fetch = async (_url, options) => {
      if (!String(_url).startsWith(process.env.GENTACTIX_TOOL_BRIDGE + '/tool')) return originalFetch(_url, options);
      bridgeCalls.push(JSON.parse(options.body));
      if (reconfigureDuringReport) {
        reconfigureDuringReport = false;
        await call('/configure', { session_id: first.session.id, policy: policy(authorTools) });
      }
      return new Response(JSON.stringify(reply));
    };
    assert.deepEqual(await reportTool.execute(reportArgs, { agent: first }), failReply);
    assert.deepEqual(new Set(first.visible()), new Set(authorTools), 'rejected report retains revision tools');
    for (const malformed of [{ ...accepted, readonly: false }, { ...accepted, version: 'other-proposal' },
      { ...accepted, preview_hash: 'd'.repeat(64) }]) {
      reply = malformed;
      await reportTool.execute(reportArgs, { agent: first });
      assert.deepEqual(new Set(first.visible()), new Set(authorTools), 'unmatched response does not complete this report');
    }
    reply = accepted;
    const returned = await reportTool.execute(reportArgs, { agent: first });
    assert.equal(returned.report_digest, accepted.report_digest);
    assert.equal(returned.next_action, 'final_response');
    assert.deepEqual(first.visible(), [], 'next native request has no redundant authoring tools');
    assert.equal(await stepHook({ agent: first, step: 9 }, async () => 'normal acknowledgement'), 'normal acknowledgement');
    await assert.rejects(() => stepHook({ agent: first, step: 10 }, async () => 'wrong'), /结束|确认|步骤预算/);
    assert.deepEqual(resumed.visible(), peerBefore, 'another role retains its own tool scope');
    const callsAfterReport = bridgeCalls.length;
    for (const name of authorTools) {
      await assert.rejects(() => definitions.get(name).execute({}, { agent: first }), /已完成|未启用/);
    }
    assert.equal(bridgeCalls.length, callsAfterReport, 'already assembled stale calls never reach the host');
    assert.equal(unowned.visible().length, definitions.size, 'unowned global controller stays unmasked');
    assert.equal(await guard({ name: 'mcp__afsim__run_mission' }, async () => 'controller'), 'controller');
    const endingConfig = await requestHook({ agent: first }, async () => ({ model: 'unchanged' }));
    assert.equal(endingConfig.reasoningEffort, 'high');
    assert.equal(endingConfig.maxTokens, 65536);
    // A new normal operation restores the original role surface even after
    // disposal/resume; completion is not written into world or session state.
    emit('agent/disposed', { agent: first }); registry.delete(first.session.id);
    const afterReportResume = create(first.session.id);
    assert.deepEqual(afterReportResume.visible(), []);
    afterReportResume.session.snapshotEvents = () => pair;
    await call('/configure', { session_id: first.session.id, policy: policy(authorTools) });
    assert.deepEqual(new Set(afterReportResume.visible()), new Set(authorTools));
    reply = failReply;
    assert.deepEqual(await reportTool.execute(reportArgs, { agent: afterReportResume }), failReply);
    assert.deepEqual(new Set(afterReportResume.visible()), new Set(authorTools));
    reply = accepted; reconfigureDuringReport = true;
    await assert.rejects(() => reportTool.execute(reportArgs, { agent: afterReportResume }), /操作策略已更新/);
    assert.deepEqual(new Set(afterReportResume.visible()), new Set(authorTools), 'old in-flight report cannot mask a new operation');
    // A valid unit proposal uses the same Native completion phase; it remains
    // a proposal and still requires a normal SDK acknowledgement and host proof.
    const unitTools=['get_afsim_observation','submit_unit_order'];
    await call('/configure',{session_id:first.session.id,policy:policy(unitTools)});
    const unitArgs={order:{action:'hold',duration:'next'},rationale:'本单位休整',expected_effect:'保持阵位'};
    const unitAccepted={ok:true,readonly:true,version:'unit-order-proposal-1',
      unit_id:'unit-one',operation_id:'unit-operation',world_version:'c'.repeat(64),proposal_digest:'d'.repeat(64)};
    for(const malformed of [{...unitAccepted,ok:false},{...unitAccepted,readonly:false},
      {...unitAccepted,version:'other-proposal'},{...unitAccepted,proposal_digest:''},
      {...unitAccepted,unit_id:''},{...unitAccepted,operation_id:''},{...unitAccepted,world_version:''}]){
      reply=malformed;await unitTool.execute(unitArgs,{agent:afterReportResume});
      assert.deepEqual(new Set(afterReportResume.visible()),new Set(unitTools),'rejected/unbound unit reply leaves correction tools available');
    }
    reply=unitAccepted;
    const unitResult=await unitTool.execute(unitArgs,{agent:afterReportResume});
    assert.equal(unitResult.proposal_digest,unitAccepted.proposal_digest);
    assert.equal(unitResult.next_action,'final_response');
    assert.deepEqual(afterReportResume.visible(),[],'first valid unit proposal ends redundant authoring');
    assert.deepEqual(resumed.visible(),peerBefore,'unit completion cannot hide another role');
    const unitCalls=bridgeCalls.length;
    await assert.rejects(()=>unitTool.execute(unitArgs,{agent:afterReportResume}),/已完成|未启用/);
    assert.equal(bridgeCalls.length,unitCalls,'stale unit calls never reach the host');
    assert.equal(await stepHook({agent:afterReportResume,step:9},async()=>'unit acknowledgement'),'unit acknowledgement');
    await assert.rejects(()=>stepHook({agent:afterReportResume,step:10},async()=>'wrong'),/结束|确认|步骤预算/);
    emit('agent/disposed',{agent:afterReportResume});registry.delete(first.session.id);
    const unitResume=create(first.session.id);
    assert.deepEqual(unitResume.visible(),[],'same SDK session retains its ending mask until a new operation');
    await call('/configure',{session_id:first.session.id,policy:policy(unitTools)});
    assert.deepEqual(new Set(unitResume.visible()),new Set(unitTools),'next operation restores unit tools on the same SDK session');
    const unitConfig=await requestHook({agent:unitResume},async()=>({model:'unchanged'}));
    assert.equal(unitConfig.reasoningEffort,'high');assert.equal(unitConfig.maxTokens,65536);
    reply=unitAccepted;reconfigureDuringReport=true;
    await assert.rejects(()=>unitTool.execute(unitArgs,{agent:unitResume}),/操作策略已更新/);
    assert.deepEqual(new Set(unitResume.visible()),new Set(authorTools),'old unit response cannot mask a newly configured operation');
    // A report-shaped reply is not valid proof for unit/scenario completion.
    for (const name of ['submit_unit_order', 'update_scenario_configuration']) {
      await call('/configure', { session_id: resumed.session.id, policy: policy([name]) });
      reply = accepted;
      await definitions.get(name).execute({}, { agent: resumed });
      assert.deepEqual(resumed.visible(), [name]);
    }
  } finally { globalThis.fetch = originalFetch; }
  assert((await call('/health', {})).data.capabilities.includes('turn-report-completion'));
  assert((await call('/health', {})).data.capabilities.includes('unit-order-completion'));
  console.log('PASS plugin lifecycle: first request, live changes, resume, execution gates, high/64K and host controller');
  console.log('PASS native report phase: rejection, accepted final response, stale calls, per-operation reset and role isolation');
} finally {
  for (const dispose of listeners.get('dispose') ?? []) await dispose();
  await rm(dir, { recursive: true, force: true });
}
