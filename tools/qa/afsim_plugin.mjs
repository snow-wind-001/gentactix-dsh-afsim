import assert from 'node:assert/strict';
import { execute, status } from '../../plugins/dsh-afsim/protocol.mjs';

const calls = [];
const ctx = { tools: {
  schemas: () => [{ name: 'mcp__afsim__run_mission' }],
  get: name => name === 'mcp__afsim__run_mission' ? {} : undefined,
  execute: async value => { calls.push(value); return { isError: false,
    value: { content: [{ type: 'text', text: JSON.stringify({ process_id: 'process', status: 'running' }) }] } }; },
} };
assert.equal(status(ctx).connected, true);
const args = { scenario: 'case.afsim', background: true };
const result = await execute(ctx, { tool: 'run_mission', args });
assert.equal(result.payload.process_id, 'process');
assert.equal(result.transport, 'dsh-native-mcp');
assert.deepEqual(calls[0].arguments, args);
assert.equal(calls[0].agent, undefined); // Domain controller, not an invented model decision.
await assert.rejects(() => execute(ctx, { tool: 'launch_afsim_tool', args: {} }), /已登记/);
await assert.rejects(() => execute(ctx, { tool: 'run_mission', args: [] }), /参数/);
ctx.tools.execute = async () => ({ isError: true, error: { message: 'offline' } });
await assert.rejects(() => execute(ctx, { tool: 'run_mission', args: {} }), /offline/);
ctx.tools.execute = async () => ({ isError: false, content: [{ type: 'text', text: 'not json' }] });
await assert.rejects(() => execute(ctx, { tool: 'run_mission', args: {} }), /合法JSON/);
console.log('AFSIM native-registry adapter checks passed');
