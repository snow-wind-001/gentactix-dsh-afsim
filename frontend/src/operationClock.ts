import type { RuntimeProgress } from './types';

/** Interpolate server duration samples using this browser's monotonic clock. */
export class OperationClock {
  source: 'client_pending' | 'server' | 'unknown' = 'client_pending';
  private identity: string | undefined;
  private anchor = 0;
  private milliseconds: number | null = 0;
  private running = false;

  start(now: number) {
    this.identity = undefined; this.anchor = now; this.milliseconds = 0;
    this.source = 'client_pending'; this.running = true;
  }

  observe(sample: RuntimeProgress, now: number) {
    if (sample.operation_id && sample.operation_id !== this.identity) {
      this.identity = sample.operation_id; this.anchor = now;
      this.milliseconds = null; this.source = 'unknown';
    }
    if (typeof sample.wall_elapsed_ms !== 'number' || !Number.isFinite(sample.wall_elapsed_ms) || sample.wall_elapsed_ms < 0) return;
    const previous = this.elapsed(now);
    this.milliseconds = Math.max(previous ?? 0, sample.wall_elapsed_ms);
    this.anchor = now; this.source = 'server';
  }

  finish(sample: RuntimeProgress, now: number) {
    this.observe(sample, now);
    const supplied = sample.wall_elapsed_ms;
    this.milliseconds = typeof supplied === 'number' && Number.isFinite(supplied) && supplied >= 0
      ? supplied : this.elapsed(now);
    this.anchor = now; this.running = false;
  }

  elapsed(now: number): number | null {
    if (this.milliseconds === null) return null;
    return this.milliseconds + (this.running ? Math.max(0, now - this.anchor) : 0);
  }
}
