/** Public DSH per-Agent capability masks. The global controller stays unmasked. */
export class AgentToolVisibility {
  constructor(toolNames) {
    this.toolNames = new Set(toolNames);
    this.masks = new Map();
  }

  validate(policy) {
    const allowed = policy?.allowed_tools ?? [];
    if (!Array.isArray(allowed)) throw new Error('allowed_tools 必须是领域工具名称数组');
    if (allowed.some(name => !this.toolNames.has(name))) throw new Error('可见工具仅限已注册的 GenTactix 领域工具');
    return [...new Set(allowed)].sort();
  }

  apply(agent, policy) {
    const allowed = this.validate(policy);
    const signature = JSON.stringify(allowed);
    const prior = this.masks.get(agent);
    if (prior?.signature === signature) return;
    if (typeof agent.ctx?.tools?.restrict !== 'function')
      throw new Error('当前 DSH runtime 缺少 agent.ctx.tools.restrict；无法隔离角色工具，请升级项目使用的 DSH runtime。');
    // Install first, then lift exactly our old mask. A rejected replacement
    // keeps the previous restriction; never mask ctx.tools globally.
    const release = agent.ctx.tools.restrict({ allow: allowed });
    this.masks.set(agent, { signature, release });
    prior?.release();
  }

  release(agent) {
    const mask = this.masks.get(agent);
    this.masks.delete(agent);
    mask?.release();
  }

  close() {
    for (const agent of this.masks.keys()) this.release(agent);
  }
}
