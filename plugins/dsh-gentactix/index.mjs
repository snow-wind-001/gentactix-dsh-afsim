/** Cordis plugin: native domain tools, per-run policy, live cancellation and forks.
 * No dependencies on DSH internals: uses the injected public runtime services.
 */
import http from 'node:http';
import { writeFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import * as afsim from '../dsh-afsim/protocol.mjs';
import { definitions as plotting } from '../dsh-military-plotting/definitions.mjs';
import { configurationPatchSchema } from '../dsh-afsim/scenario-schema.mjs';
import { AgentToolVisibility } from './tool-visibility.mjs';
import { previewEvidence, candidateEvidence } from './report-evidence.mjs';
import { unitOrderProperties, plannerOrderProperties } from './unit-order-schema.mjs';
import { effectSchema } from './effect-schema.mjs';

export const name = 'gentactix-runtime';
export const inject = ['tools', 'agents', 'sessions'];

const object = { type: 'object', additionalProperties: true };
const definitions = [
  ['submit_planner_orders', '只读提交本次required_units完整批量行动与公开依据。严格校验全部且仅剩余单位，排除人工、单位Agent和已准备任务；核对当前操作、世界及命令版本。无16项试算分页上限，不执行、不改世界或消费队列。失败按精确名单修正；成功后简短确认，不重抄长JSON。', plannerOrderProperties],
  ['submit_unit_order', '为当前原生单位会话结构化提交一项行动及公开依据、预期。单位身份、观察版本与操作由宿主绑定；校验成功仍只是候选，不执行、不消费队列、不写世界。成功后最终简短确认，无须重复长JSON。', unitOrderProperties],
  ['preview_turn_effects', '只读校验完整候选效果；按参数合同提供unit_updates和orders，行选择字段为unit，不用name/unit_name，更新行不要附team。数值和物理仍完整校验，不写世界。失败先读issues及calculation_diagnostics.mismatches，按当前候选的精确path/expected一并核对粮耗、库存、时间保障回执及对应状态、装填倒计时、疲劳、位置和公开决策；这些是依赖当前候选的计算事实，不是通过或自动修订。用candidate_ref调用amend_turn_effects显式修订，无须重发完整候选；成功用digest提交战报。', {candidate:effectSchema}],
  ['amend_turn_effects', '按本操作candidate_ref显式修订候选效果。运行时仅传公开调用/结果链，逐条重放edits后重新完整校验，无候选缓存、自动纠正或世界提交。失败读issues及calculation_diagnostics.mismatches，按精确path/expected一次核对所有不一致；改变行动、到货或位置后旧计算事实失效，须重新预览。失败若有新candidate_ref可继续修订；成功用digest提交战报。JSON Pointer路径，remove无value，add/replace带完整value。', {
    base_ref:{type:'string',pattern:'^[a-f0-9]{64}$'},
    edits:{type:'array',minItems:1,maxItems:128,items:{oneOf:[
      {type:'object',additionalProperties:false,required:['op','path','value'],properties:{op:{type:'string',enum:['add','replace']},path:{type:'string',minLength:1,maxLength:512},value:{}}},
      {type:'object',additionalProperties:false,required:['op','path'],properties:{op:{type:'string',enum:['remove']},path:{type:'string',minLength:1,maxLength:512}}}
    ]}}
  }],
  ['get_turn_preview', '只读分页：成功preview_hash配kind=units/goals读取候选轮末结算；失败candidate_ref配kind=constraints读取候选条件／上限，沿next_args读完。上限不是必须到货量，不选择分配。运行时从当前DSH公开轨迹重建对应候选并核对指纹，无候选缓存。不替代轮初观察，不执行或提交。', {preview_hash:{type:'string',pattern:'^[a-f0-9]{64}$'},candidate_ref:{type:'string',pattern:'^[a-f0-9]{64}$'},kind:{type:'string',enum:['units','goals','constraints']},offset:{type:'integer',minimum:0},limit:{type:'integer',minimum:1,maximum:16}}],
  ['submit_turn_report', '根据本操作成功预览，以结构化参数提交完整中文战报候选。运行时自动提供对应公开预览证据，宿主校验指纹；不提交世界、不执行动作或消费命令。成功后最终简短确认即可，不重复长报告JSON。若修改效果，先重新预览再提交报告。', {preview_hash:{type:'string',pattern:'^[a-f0-9]{64}$'},report:{type:'string',minLength:1,maxLength:32768}}],
  ['get_campaign_lifecycle', '只读分页查询同一世界的会战阶段。读取当前阶段、完成时点与目标关联，沿next_args读完；view_version绑定当前观察。阶段不新建世界、不自动下令、补员或改编，不是已考证完整历史过程。未来阶段目标尚未评分。', {offset:{type:'integer',minimum:0},limit:{type:'integer',minimum:1,maximum:16},view_version:{type:'string'}}],
  ['get_campaign_objectives', '只读分页查询宿主会战目标图；kind=nodes读取方向、依赖和实际进度，沿next_args读完。member_args分页读取承担单位；view_version绑定本轮观察，plan_hash只是固定配置摘要，二者不可混用。里程碑已达成不等于当前仍控制；保持时长按回合端点采样。目标图只评分，不自动下令，不是史实战果。', {kind:{type:'string',enum:['nodes','members']},node_id:{type:'string'},offset:{type:'integer',minimum:0},limit:{type:'integer',minimum:1,maximum:16},view_version:{type:'string'}}],
  ['read_scenario_skill', '读取历史基础AFSIM想定配置skill与上游模板约束。', {}],
  ['get_scenario_basis', '读取本次想定的史料部队、来源、缺载项及派生配置种子。', {}],
  ['update_scenario_configuration', '仅填写本次分配的想定配置草稿；校验通过后保存草稿分片，不修改已有战局或运行AFSIM。', {revision:{type:'integer',minimum:0},patch:configurationPatchSchema}],
  ['validate_scenario_configuration', '校验派生配置与AFSIM封闭模板，不执行或提交已有战局。', {configuration:object}],
  ['get_observation', '读取本次决策前单位状态；只读。', { names: { type: 'array', items: { type: 'string' } } }],
  ['get_force_organization', '只读分页查询。hierarchy=command列当前指挥成员，historical列行政参考。items每项是成员；command_chain是该成员最高上级到直接上级的ID序列，不是成员ID列表；command_path给对应上级名称与依据，administrative_path不授予指挥权。available不代表已到场，须看operational_status和arrival_wait_seconds。沿next_args读完。', {offset:{type:'integer',minimum:0},limit:{type:'integer',minimum:1,maximum:32},revision:{type:'integer',minimum:0},node_id:{type:'string'},team:{type:'string',enum:['red','blue']},kind:{type:'string',enum:['nodes','groups','members']},hierarchy:{type:'string',enum:['historical','command']}}],
  ['get_force_tasks', '只读分页查询已确认持续任务。kind=tasks列任务、前置与实际进展，沿next_args读完；member_args读实际承担者，event_args读状态事件。后续页必须保留view_version，过期重查。应用已接受不等于部队实际收令；目标依赖不等于动作已经执行。人工改令、失权、等待和未交付各有原因。', {kind:{type:'string',enum:['tasks','members','events']},task_id:{type:'string'},offset:{type:'integer',minimum:0},limit:{type:'integer',minimum:1,maximum:16},view_version:{type:'string'}}],
  ['preview_force_task', '只读分页分解兵团任务，逐单位说明机动/火力/工程/预备或补给动作及人工命令冲突；可携带execution草稿声明持续任务前置/完成判据。沿next_args读完，不执行、不写队列或战局。', {group_id:{type:'string'},task:object,execution:object,replace_existing:{type:'boolean'},offset:{type:'integer',minimum:0},limit:{type:'integer',minimum:1,maximum:16},preview_hash:{type:'string'}}],
  ['preview_force_conversion', '只读核对当前实态的分合兵分配提案，不执行、不写世界或队列；runtime_admitted=false不能称已分兵。kind=split选一个命令unit_id，allocations每项{id,committed}并在合成模式填label，在历史模式填historical_unit_id（余部填null）。committed合计为原投入基数，不是current；可用/伤损与库存按当前实态守恒分配。历史下级须本阶段已核在场，覆盖不全保留余部。kind=merge选多个同地同源分队，不填写allocations。offset/limit分页，沿next_args保留view_version。', {kind:{type:'string',enum:['split','merge']},unit_ids:{type:'array',minItems:1,maxItems:32,items:{type:'string'}},allocations:{type:'array',minItems:2,maxItems:32,items:object},assumption:{type:'string',minLength:1,maxLength:2000},offset:{type:'integer',minimum:0},limit:{type:'integer',minimum:1,maximum:8},view_version:{type:'string'}}],
  ['retrieve_history', '检索当前战役史料与战报。kind=operations/relations/measurements分页读取冻结的阶段事件/配属/数值资料。数值须按statistic、population及quantity解读，补充基数、每师选拔人数或撤退群体不是当前全建制人数、战死或运输车辆；不自动写状态。完整阶段读取应省略query并沿next_args读完；query是文字子串，不是语义检索或通配符，禁止用*代替全量。空筛选不等于无资料，可用unfiltered_args重新读取；保留未知坐标，不代表实时态势。只读。', {query:{type:'string'},kind:{type:'string',enum:['operations','relations','measurements']},phase_id:{type:'string'},unit_id:{type:'string'},offset:{type:'integer',minimum:0},limit:{type:'integer',minimum:1,maximum:8},definition_hash:{type:'string'}}],
  ['evaluate_action', '只读核验AFSIM候选orders的单位ID、动作、资源及目标约束；moves仅作旧几何试算，均不执行或提交。', { moves: { type: 'array', items: object }, orders: { type: 'array', maxItems: 16, items: object } }],
  ['inspect_trajectory', '核对已提交决策的轨迹、状态变化与证据编号。', { turn: { type: 'integer', minimum: 0 } }],
  ['evaluate_counterfactual', '撤销已提交位移，固定其他终态，运行单步几何归因试算。', { turn: { type: 'integer', minimum: 1 }, undo: { type: 'array', items: object } }],
  ...afsim.definitions,
  ...plotting,
];

export function apply(ctx) {
  const token = process.env.GENTACTIX_CONTROL_TOKEN;
  const bridge = process.env.GENTACTIX_TOOL_BRIDGE;
  const readyFile = process.env.GENTACTIX_CONTROL_FILE;
  if (!token || !bridge || !readyFile) throw new Error('GenTactix runtime bridge is not configured');
  const policies = new Map();
  const visibility = new AgentToolVisibility(definitions.map(x => x[0]));
  const children = new Map();
  const counters = { events: 0, calls: 0, cancellations: 0, forks: 0 };
  const disposers = [];

  function setPolicy(id, policy) {
    visibility.validate(policy);
    const agent = ctx.agents.get(id);
    if (agent) visibility.apply(agent, policy);
    policies.set(id, { ...policy, calls: 0, phase: 'authoring' });
  }

  // The application executes validated scenarios. Model tools only observe or
  // propose; raw MCP execution cannot bypass the authoritative commit boundary.
  disposers.push(ctx.on('tools/pre-execute', async (exec, next) => {
    if (exec.agent && exec.name.startsWith('mcp__afsim__'))
      throw new Error('战局AFSIM运行由控制端确认命令后执行；模型请提交结构化命令或读取观察工具。');
    return next();
  }));

  for (const [toolName, description, properties] of definitions) {
    disposers.push(ctx.tools.register({
      name: toolName, description,
      parameters: { type: 'object', properties, additionalProperties: false,
        ...(toolName==='submit_planner_orders'?{required:['orders']}:toolName==='submit_unit_order'?{required:['order','rationale','expected_effect']}:toolName==='update_scenario_configuration'?{required:['revision','patch']}:toolName==='preview_turn_effects'?{required:['candidate']}:toolName==='amend_turn_effects'?{required:['base_ref','edits']}:toolName==='submit_turn_report'?{required:['preview_hash','report']}:toolName==='get_turn_preview'?{anyOf:[{required:['preview_hash']},{required:['candidate_ref']}]}:toolName==='preview_force_conversion'?{required:['kind','unit_ids','assumption']}:{}) },
      output: { schema: object, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
      async execute(args, exec) {
        const sessionId = String(exec.agent?.session?.id ?? '');
        const policy = policies.get(sessionId);
        if (!policy?.allowed_tools?.includes(toolName)) throw new Error('本次操作未启用该领域工具');
        policy.calls = (policy.calls ?? 0) + 1;
        if (policy.calls > policy.max_tool_calls) throw new Error('本次操作的领域工具预算已用尽');
        counters.calls++;
        const response = await fetch(bridge + '/tool', {
          method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ session_id: sessionId, tool: toolName, args,
            ...(toolName==='amend_turn_effects'||toolName==='get_turn_preview'&&args.kind==='constraints' ? { candidate_events: candidateEvidence(exec.agent.session.snapshotEvents(), args.base_ref??args.candidate_ref) } : {}),
            ...(['submit_turn_report','get_turn_preview'].includes(toolName)&&args.kind!=='constraints' ? { preview_events: previewEvidence(exec.agent.session.snapshotEvents(), args.preview_hash) } : {}) }), signal: exec.signal,
        });
        if (!response.ok) {
          const failure = await response.json().catch(() => null);
          const detail = typeof failure?.error === 'string' ? failure.error.slice(0, 200) : '';
          throw new Error(`领域工具桥接失败：HTTP ${response.status}${detail ? '；' + detail : ''}`);
        }
        const value = await response.json();
        const reportAccepted = toolName === 'submit_turn_report' && value?.ok === true && value.readonly === true
          && value.version === 'turn-report-proposal-1' && value.preview_hash === args.preview_hash;
        const unitAccepted = toolName === 'submit_unit_order' && value?.ok === true && value.readonly === true
          && value.version === 'unit-order-proposal-1' && /^[a-f0-9]{64}$/.test(value.proposal_digest ?? '')
          && ['unit_id', 'operation_id', 'world_version'].every(key => typeof value[key] === 'string' && value[key].trim());
        const plannerAccepted = toolName === 'submit_planner_orders' && value?.ok === true && value.readonly === true
          && value.version === 'planner-order-proposal-1'
          && ['proposal_digest', 'required_units_digest'].every(key => /^[a-f0-9]{64}$/.test(value[key] ?? ''))
          && ['operation_id', 'world_version'].every(key => typeof value[key] === 'string' && value[key].trim())
          && Number.isInteger(value.command_revision) && value.command_revision >= 0
          && Array.isArray(args.orders) && value.order_count === args.orders.length && value.order_count > 0;
        if (reportAccepted || unitAccepted || plannerAccepted) {
          // The host has accepted a proposal, not committed a world. End this
          // Agent's authoring surface before the NEXT native prompt assembly;
          // the SDK must still finish normally and the host rechecks its proof.
          if (policies.get(sessionId) !== policy) throw new Error('操作策略已更新，旧候选不能结束新操作');
          visibility.apply(exec.agent, { allowed_tools: [] });
          policy.allowed_tools = [];
          policy.phase = 'final_response';
          return { ...value, next_action: 'final_response' };
        }
        return value;
      },
    }));
  }

  // Creation is synchronous and precedes the FIRST prompt assembly. The
  // pre-step/request hooks run after assembly and cannot filter its schemas.
  disposers.push(ctx.on('agent/created', ({ agent }) => {
    if (String(agent.session.id).startsWith('gentactix-'))
      visibility.apply(agent, policies.get(String(agent.session.id)));
  }));
  disposers.push(ctx.on('agent/disposed', ({ agent }) => visibility.release(agent)));

  // Policy belongs in the runtime request waterfall, not in prompt wording.
  disposers.push(ctx.on('agent/request', async ({ agent }, next) => {
    const config = await next();
    const policy = policies.get(String(agent.session.id));
    if (!policy) return config;
    return { ...config, maxTokens: policy.max_tokens,
      ...(policy.reasoning_effort ? { reasoningEffort: policy.reasoning_effort } : {}) };
  }));
  disposers.push(ctx.on('agent/pre-step', async ({ agent, step }, next) => {
    const policy = policies.get(String(agent.session.id));
    if (policy?.phase === 'final_response') {
      // A proposal accepted on the last authoring step still gets one normal,
      // tool-free acknowledgement. This does not widen authoring/call budgets
      // or turn an SDK error/cancellation into a successful completion.
      if (policy.completion_step !== undefined && step !== policy.completion_step)
        throw new Error('候选已接受，结束确认步骤预算已用尽');
      policy.completion_step = step;
    } else if (policy && step > policy.max_steps) throw new Error('GenTactix 模型步骤预算已用尽');
    return next();
  }));
  disposers.push(ctx.on('session/event', () => { counters.events++; }));

  async function readBody(req) {
    let raw = '';
    for await (const chunk of req) {
      raw += chunk;
      if (raw.length > 4_000_000) throw new Error('control request too large');
    }
    return raw ? JSON.parse(raw) : {};
  }
  const server = http.createServer(async (req, res) => {
    const send = (code, value) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(value)); };
    if (req.headers.authorization !== `Bearer ${token}`) return send(401, { error: 'unauthorized' });
    try {
      const body = await readBody(req);
      if (req.url === '/afsim/status') return send(200, afsim.status(ctx));
      if (req.url === '/afsim/execute') return send(200, await afsim.execute(ctx, body));
      if (req.url === '/health') return send(200, { plugin: name, mode: 'native', ptc: false,
        tools: definitions.map(x => x[0]), capabilities: ['cancel', 'fork', 'request-policy', 'events', 'unit-sessions', 'scoped-scenario-drafts', 'agent-tool-visibility', 'turn-preview-paging', 'turn-report-completion', 'unit-order-completion'], counters });
      if (req.url === '/configure') {
        if (typeof body.session_id !== 'string') throw new Error('session_id is required');
        if (!body.session_id.startsWith('gentactix-')) throw new Error('invalid application session id');
        setPolicy(body.session_id, body.policy);
        return send(200, { ok: true });
      }
      if (req.url === '/session-state') {
        if (typeof body.session_id !== 'string' || !body.session_id.startsWith('gentactix-')) throw new Error('invalid application session id');
        return send(200, { session_id: body.session_id, live: Boolean(ctx.agents.get(body.session_id)) });
      }
      if (req.url === '/cancel') {
        const agent = ctx.agents.get(body.session_id);
        if (!agent) return send(404, { error: 'active runtime session not found' });
        agent.cancel({ kind: 'user' });
        counters.cancellations++;
        return send(200, { ok: true, mode: 'native-agent-cancel', session_id: body.session_id });
      }
      if (req.url === '/unit-session') {
        const id = body.session_id;
        if (typeof id !== 'string' || !/^gentactix-unit-[a-zA-Z0-9-]+$/.test(id)) throw new Error('invalid unit Agent id');
        const operation = body.operation ?? 'inspect';
        let agent = ctx.agents.get(id);
        if (operation === 'dispose') {
          const handle = children.get(id);
          if (!handle) throw new Error('unit Agent is not owned by this plugin');
          await handle.dispose(); children.delete(id); policies.delete(id);
          return send(200, { session_id: id, disposed: true });
        }
        if (operation === 'create' || operation === 'resume') {
          if (agent) throw new Error('unit Agent already live');
          const parent = body.parent_session_id ? ctx.agents.get(body.parent_session_id) : undefined;
          if (body.parent_session_id && !parent) throw new Error('parent Agent is not live');
          const route = body.agent_options ?? {};
          if (Object.keys(route).some(k => !['provider', 'model', 'reasoningEffort', 'maxTokens'].includes(k))) throw new Error('invalid unit route');
          const options = parent ? { ...parent.options } : route;
          const handle = operation === 'resume'
            ? await ctx.agents.resume({ resumeSessionId: id, agentOptions: options })
            : await ctx.agents.create({ sessionId: id,
              meta: { cwd: body.cwd, ...(parent ? { parentSession: parent.session.id } : {}) },
              agentOptions: options });
          children.set(id, handle); agent = handle.agent;
          if (body.policy) setPolicy(id, body.policy);
        } else if (operation !== 'inspect') throw new Error('unsupported unit lifecycle operation');
        if (!agent) return send(404, { error: 'unit Agent not live' });
        return send(200, { session_id: id, parent_session_id: agent.session.header.parentSession ?? null,
          event_count: agent.session.snapshotEvents().length,
          factory: 'DSH.AgentRegistry', persistence: agent.session.snapshotEvents().length ? 'session_journal' : 'pending_first_turn' });
      }
      if (req.url === '/unit-run') {
        const id = body.session_id;
        if (typeof id !== 'string' || !id.startsWith('gentactix-unit-') || !children.has(id)) throw new Error('unit Agent is not owned by this plugin');
        const agent = ctx.agents.get(id);
        if (!agent || typeof body.prompt !== 'string') throw new Error('invalid unit run');
        const offset = agent.session.snapshotEvents().length;
        setPolicy(id, body.policy);
        agent.followup({ id: randomUUID(), role: 'user', content: [{ type: 'text', text: body.prompt }], source: { kind: 'user' } });
        await agent.whenIdle();
        const events = agent.session.snapshotEvents(offset);
        const end = [...events].reverse().find(x => x.type === 'turn/end');
        const message = [...events].reverse().find(x => x.type === 'assistant/message');
        const blocks = message?.data?.message?.content ?? message?.data?.content ?? [];
        const reason = end?.data?.reason;
        return send(200, { session_id: id, finish_reason: typeof reason === 'string' ? reason : reason?.kind,
          final_response: blocks.filter(x => x.type === 'text').map(x => x.text ?? '').join('\n'), events });
      }
      if (req.url === '/fork-run') {
        const parent = ctx.agents.get(body.parent_session_id);
        if (!parent) return send(404, { error: 'fork parent is not live; resume it first' });
        const all = parent.session.snapshotEvents();
        const boundary = body.boundary;
        if (!Number.isInteger(boundary) || boundary < 0 || boundary >= all.length) throw new Error('invalid exact fork boundary');
        const prefix = all.slice(0, boundary + 1);
        let open = false;
        for (const event of prefix) { if (event.type === 'turn/start') open = true; if (event.type === 'turn/end') open = false; }
        if (open) throw new Error('fork boundary must be outside an open turn');
        const id = body.session_id;
        if (typeof id !== 'string' || !id.startsWith('gentactix-')) throw new Error('invalid branch id');
        // Public AgentRegistry factory seed contract: exact inherited prefix plus native marker.
        const seed = [...prefix, { type: 'session/end-seed', seq: prefix.length, time: Date.now(), data: { inherited: true } }];
        const handle = await ctx.agents.create({ sessionId: id, parentAgent: parent,
          meta: { cwd: parent.session.header.cwd, parentSession: parent.session.id, isSeeded: true },
          inheritedEventCount: prefix.length, seed, agentOptions: { ...parent.options } });
        children.set(id, handle);
        setPolicy(id, body.policy);
        counters.forks++;
        const agent = handle.agent;
        agent.followup({ id: randomUUID(), role: 'user', content: [{ type: 'text', text: body.prompt }], source: { kind: 'user' } });
        await agent.whenIdle();
        const events = agent.session.snapshotEvents(prefix.length + 1);
        const end = [...events].reverse().find(x => x.type === 'turn/end');
        const message = [...events].reverse().find(x => x.type === 'assistant/message');
        const blocks = message?.data?.message?.content ?? message?.data?.content ?? [];
        const final_response = blocks.filter(x => x.type === 'text').map(x => x.text ?? '').join('\n');
        const reason = end?.data?.reason;
        return send(200, { session_id: id, parent_session_id: body.parent_session_id, boundary,
          finish_reason: typeof reason === 'string' ? reason : reason?.kind, final_response, events });
      }
      return send(404, { error: 'unknown control operation' });
    } catch (error) { return send(400, { error: String(error?.message ?? error) }); }
  });
  server.listen(0, '127.0.0.1', () => {
    writeFileSync(readyFile, JSON.stringify({ port: server.address().port, plugin: name }), { mode: 0o600 });
  });
  ctx.on('dispose', async () => {
    visibility.close();
    for (const dispose of disposers) dispose();
    for (const handle of children.values()) await handle.dispose?.();
    server.close();
  });
}
