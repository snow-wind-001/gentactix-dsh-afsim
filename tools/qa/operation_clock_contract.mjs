/** Server elapsed samples, refresh, skew, identity and terminal freeze. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const ts = require('typescript');
const root = await mkdtemp(join(tmpdir(), 'gentactix-clock-'));
try {
  const source = await readFile(new URL('../../frontend/src/operationClock.ts',import.meta.url),'utf8');
  const code = ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
  const path = join(root,'clock.mjs');await writeFile(path,code);
  const { OperationClock } = await import(pathToFileURL(path));
  const clock = new OperationClock();
  clock.start(100);clock.observe({operation_id:'a',started_at_ms:1,wall_elapsed_ms:750000},101);
  assert.equal(clock.elapsed(1101),751000);assert.equal(clock.source,'server');
  clock.observe({operation_id:'a',started_at_ms:99999999999999,wall_elapsed_ms:749000},1201);
  assert.equal(clock.elapsed(1201),751100); // Neither server wall skew nor stale sample rewinds it.
  clock.finish({operation_id:'a',wall_elapsed_ms:751600},6000);
  assert.equal(clock.elapsed(999999),751600);
  clock.start(0);clock.finish({operation_id:'fast-completion',wall_elapsed_ms:4200},10);
  assert.equal(clock.source,'server');assert.equal(clock.elapsed(900000),4200);
  clock.start(20000);assert.equal(clock.elapsed(21000),1000);assert.equal(clock.source,'client_pending');
  clock.observe({operation_id:'b',wall_elapsed_ms:8000},21000);
  assert.equal(clock.elapsed(21000),8000);
  clock.observe({operation_id:'c',wall_elapsed_ms:100},22000);
  assert.equal(clock.elapsed(22000),100); // A new operation may restart at zero.
  clock.start(0);clock.observe({operation_id:'legacy'},1);
  assert.equal(clock.elapsed(500000),null);assert.equal(clock.source,'unknown');
  for(const value of [null,-1,NaN,Infinity,'12000']) {
    clock.start(0);clock.observe({operation_id:'invalid',wall_elapsed_ms:value},1);
    assert.equal(clock.elapsed(900000),null);
  }
  console.log('PASS clock recovery, stale samples, skew, identity, terminal freeze and unknown legacy time');
} finally { await rm(root,{recursive:true,force:true}); }
