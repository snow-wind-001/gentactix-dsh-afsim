/** AFSIM domain protocol; execution goes through DSH's existing MCP registry. */
import { randomUUID } from 'node:crypto';

export const definitions = [
  ['get_afsim_observation', '按单位ID分页读取已提交战局；默认紧凑数值态势，不重复来源长文。participation为宿主当前参与状态；后方/返场中保留伤损库存与实际位置、仍可被攻击，不等于失能或消失。需核对估计依据或完整单位字段时用返回的detail_query（ids+detail=true）；省略字段不代表缺载。完整态势留在程序端。只读。', {
    ids: { type: 'array', items: { type: 'string' }, maxItems: 16 },
    limit: { type: 'integer', minimum: 1, maximum: 16 },
    offset: { type: 'integer', minimum: 0 },
    detail: { type: 'boolean', description: '默认false；true保留所选单位的完整人员、装备、formation和来源字段。优先按ids定点读取。' },
  }],
  ['get_afsim_changes', '只读变化；aggregate默认汇总从首轮至当前，changes默认仅最近一轮。since_turn排除、through_turn包含；全局累计用since_turn=0或省略，不是1；第M至N轮用M-1与N。next_args是下一次完整参数对象，不要嵌套为next_args字段；翻页保留view_version。window.full_session=false不得称为全局累计。版本变更从offset=0重读，不传完整快照。', {
    mode: { type: 'string', enum: ['changes', 'aggregate'] },
    since_turn: { type: 'integer', minimum: 0, description: '排除下界（exclusive）：不包含这一轮。全局累计填0或在aggregate模式省略；填1会漏掉第1轮。' },
    through_turn: { type: 'integer', minimum: 0, description: '包含上界（inclusive），省略为当前已完成轮次。' },
    limit: { type: 'integer', minimum: 1, maximum: 16 },
    offset: { type: 'integer', minimum: 0 },
    view_version: { type: 'string', pattern: '^[a-f0-9]{64}$' },
  }],
];

const applicationTools = new Set(['run_mission', 'afsim_types', 'afsim_command', 'analyze_run']);

export function status(ctx) {
  const tools = ctx.tools.schemas().map(tool => tool.name).filter(name => name.startsWith('mcp__afsim__'));
  return { connected: tools.includes('mcp__afsim__run_mission'), tools, transport: 'dsh-native-mcp' };
}

export async function execute(ctx, body) {
  if (!applicationTools.has(body.tool)) throw new Error('AFSIM控制端仅接受已登记的领域工具');
  if (!body.args || typeof body.args !== 'object' || Array.isArray(body.args)) throw new Error('AFSIM参数须为对象');
  const name = 'mcp__afsim__' + body.tool;
  if (!ctx.tools.get(name)) throw new Error('DSH尚未连接AFSIM MCP服务');
  const dispatchId = randomUUID();
  const result = await ctx.tools.execute({ callId: dispatchId, name, arguments: body.args,
    signal: AbortSignal.timeout(130000) });
  if (result.isError) throw new Error('DSH/AFSIM工具执行失败：' + (result.error?.message ?? '见运行证据'));
  const content = result.value?.content ?? result.content ?? [];
  const block = content.find(item => item.type === 'text');
  if (!block) throw new Error('AFSIM MCP未返回结构化结果');
  let payload;
  try { payload = JSON.parse(block.text); } catch { throw new Error('AFSIM MCP结果不是合法JSON'); }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('AFSIM MCP结果形状不合法');
  return { dispatch_id: dispatchId, tool: name, transport: 'dsh-native-mcp', payload };
}
