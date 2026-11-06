import assert from 'node:assert/strict';
import { AgentToolVisibility } from '../../plugins/dsh-gentactix/tool-visibility.mjs';

// A scope-local restriction fixture, not a model or runtime execution substitute.
const globalNames = ['observe', 'draft', 'mcp__afsim__run_mission'];
function agent(id) {
  const masks = new Set();
  const value = { session: { id }, changes: 0, releases: 0, masks };
  value.ctx = { tools: { restrict({ allow }) {
    assert(allow.every(name => globalNames.includes(name)));
    const mask = new Set(allow); masks.add(mask); value.changes++;
    return () => { masks.delete(mask); value.releases++; };
  } } };
  value.visible = () => globalNames.filter(name => [...masks].every(mask => mask.has(name)));
  return value;
}
const visibility = new AgentToolVisibility(['observe', 'draft']);
const observer = agent('gentactix-observer');
const builder = agent('gentactix-unit-builder');
visibility.apply(observer, { allowed_tools: ['observe'] });
visibility.apply(builder, { allowed_tools: ['draft'] });
assert.deepEqual(observer.visible(), ['observe']);
assert.deepEqual(builder.visible(), ['draft']);
assert.deepEqual(globalNames, ['observe', 'draft', 'mcp__afsim__run_mission']);
assert.equal(observer.changes, 1);
visibility.apply(observer, { allowed_tools: ['observe', 'observe'] });
assert.equal(observer.changes, 1); // Per-step rechecks do not leak masks.
visibility.apply(observer, { allowed_tools: ['draft'] });
assert.deepEqual(observer.visible(), ['draft']);
assert.equal(observer.releases, 1);
assert.equal(observer.masks.size, 1);
visibility.apply(observer, { allowed_tools: [] });
assert.deepEqual(observer.visible(), []);
visibility.apply(observer); // Unconfigured fresh/resumed application Agents fail closed.
assert.deepEqual(observer.visible(), []);
assert.throws(() => visibility.apply(observer, { allowed_tools: ['mcp__afsim__run_mission'] }), /领域工具/);
assert.throws(() => visibility.validate({ allowed_tools: 'observe' }), /数组/);
assert.deepEqual(observer.visible(), []);
const oldRestrict = observer.ctx.tools.restrict;
observer.ctx.tools.restrict = () => { throw new Error('native failure'); };
assert.throws(() => visibility.apply(observer, { allowed_tools: ['observe'] }), /native failure/);
assert.deepEqual(observer.visible(), []); // A failed policy change preserves the old restriction.
observer.ctx.tools.restrict = oldRestrict;
assert.throws(() => visibility.apply({ session: { id: 'gentactix-old-runtime' }, ctx: { tools: {} } }), /restrict/);
visibility.release(observer);
visibility.release(observer);
assert.equal(observer.masks.size, 0);
assert.deepEqual(builder.visible(), ['draft']);
const resumed = agent('gentactix-observer');
visibility.apply(resumed, { allowed_tools: ['observe'] });
assert.deepEqual(resumed.visible(), ['observe']);
visibility.close();
assert.equal(resumed.masks.size, 0);
assert.equal(builder.masks.size, 0);
console.log('PASS scoped visibility: role isolation, native controller independence, empty policies, changes, failures, resume and cleanup');
