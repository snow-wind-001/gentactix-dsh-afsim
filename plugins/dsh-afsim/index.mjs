/** Loadable Cordis plugin. Reuses GenTactix's existing controlled runtime host. */
import * as runtime from '../dsh-gentactix/index.mjs';

export const name = 'gentactix-afsim';
export const inject = ['tools', 'agents', 'sessions'];
export function apply(ctx) {
  ctx.plugin(runtime);
}
