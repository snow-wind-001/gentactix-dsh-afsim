/** Retry a retained full-roster round through real UI, preserving old failures. */
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(fs.realpathSync(process.argv[2]));
const { chromium } = require('playwright-core');
const sid = process.argv[3], turn = Number(process.argv[4]);
const root = process.argv[5];
if (!/^[a-f0-9]{12}$/.test(sid) || !Number.isInteger(turn) || turn < 1 || !root) throw Error('Explicit retained session, next turn and fresh output required');
fs.mkdirSync(root, { recursive: true });
const save = (name, value) => {
  const path = `${root}/${name}`;
  if (fs.existsSync(path)) throw Error('Preserve evidence ' + path);
  fs.writeFileSync(path, JSON.stringify(value, null, 2));
};
const apiRoot=process.env.GENTACTIX_QA_API_URL??'http://127.0.0.1:19217';
const uiRoot=process.env.GENTACTIX_QA_UI_URL??'http://127.0.0.1:19218';
if(![apiRoot,uiRoot].every(url=>/^http:\/\/127\.0\.0\.1:\d+$/.test(url)))throw Error('Owned local QA URLs required');
const api = `${apiRoot}/api/sessions/${sid}`;
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const faults = []; let timer; let before; let started;
page.on('pageerror', error => faults.push(error.message));
page.on('crash', () => faults.push('page_crash'));
await page.addInitScript(url => { window.gentactix = { backendUrl: url }; },apiRoot);
const snapshot = async () => {
  const response = await page.request.get(api + '/export');
  if (!response.ok()) throw Error('Snapshot HTTP ' + response.status());
  return (await response.json()).session;
};
try {
  before = await snapshot(); save('before.json', before);
  if (before.turn_count !== turn-1) throw Error('Wrong retained turn; refuse duplicate advance');
  const progress = await (await page.request.get(api + '/progress')).json();
  if (progress.active) throw Error('Original operation still active; do not duplicate');
  await page.goto(uiRoot);
  await page.getByRole('tab', { name: /已保存战局/ }).click();
  await page.locator(`[data-session-id="${sid}"] .open-battle`).click();
  await page.getByTestId('map-workbench').waitFor({ timeout: 60000 });
  if (await page.locator('.nato-marker').count() !== 22) throw Error('Expected complete22 markers');
  await page.screenshot({ path: `${root}/before-1440.png` });
  const completed = page.waitForResponse(r => r.url() === api+'/next' && r.request().method() === 'POST', { timeout: 3600000 });
  started = Date.now();
  await page.getByRole('button', { name: '推进一轮', exact: true }).click();
  console.log('REAL_UI_RETRY_STARTED', sid, turn);
  let polling = false;
  timer = setInterval(async () => {
    if (polling) return; polling = true;
    try {
      const p = await (await page.request.get(api+'/progress')).json();
      const row = { seconds: (Date.now()-started)/1000, active: p.active, markers: await page.locator('.nato-marker').count() };
      fs.appendFileSync(`${root}/progress.jsonl`, JSON.stringify(row)+'\n');
      console.log('WAIT', Math.round(row.seconds), row.active, row.markers);
    } catch (error) { console.log('POLL_ERROR', error.message.slice(0, 120)); }
    finally { polling = false; }
  }, 15000);
  const response = await completed, body = await response.json();
  clearInterval(timer);
  save('response.json', { status: response.status(), seconds: (Date.now()-started)/1000, body });
  const after = await snapshot(); save('after.json', after);
  if (!response.ok()) throw Error('Round rejected: '+JSON.stringify(body).slice(0, 900));
  if (after.turn_count !== turn) throw Error('Turn did not commit exactly once');
  const oldUnits = [...before.war_state.red_units, ...before.war_state.blue_units];
  const newUnits = [...after.war_state.red_units, ...after.war_state.blue_units];
  if (newUnits.length !== 22 || newUnits.some(u => !oldUnits.find(v => v.historical_unit_id === u.historical_unit_id))) throw Error('Actor identity loss');
  for (const [id, binding] of Object.entries(before.command_state.agent_sessions??{})) {
    if (after.command_state.agent_sessions[id]?.session_id !== binding.session_id) throw Error('Native session identity changed');
  }
  const trace = after.trajectory.at(-1);
  const decisions = trace.decisions.filter(d => d.source === 'native_unit_agent');
  if (decisions.length !== before.command_state.unit_agents.length || decisions.some(d => d.proposal?.source !== 'dsh_native_unit_order_tool')) throw Error('Structured Native unit receipt missing');
  const motionVersion=before.war_state.mission.definition.movement_feedback?.version;
  if(motionVersion){
    const receipt=after.war_state.dsh_execution?.movement??after.war_state.combined_arms?.movement_feedback;
    if(receipt?.version!==motionVersion||receipt.units?.length!==22)throw Error('Versioned22 movement admission absent');
  }
  await page.screenshot({ path: `${root}/after-1440.png` });
  await page.setViewportSize({ width: 900, height: 1000 });
  await page.screenshot({ path: `${root}/after-900.png` });
  if (await page.locator('.nato-marker').count() !== 22 || faults.length) throw Error('UI marker/error regression '+JSON.stringify(faults));
  save('result.json', { passed: true, session_id: sid, turn, seconds: (Date.now()-started)/1000, markers: 22,
    native_proposals: decisions.map(d => d.proposal), faults, mission_status: after.war_state.mission.status,
    winner: after.war_state.mission.winner, motion_version:motionVersion??null,
    scope: 'Retained22 actors, real UI/DSH/native structured candidates. Explicit motion admission checked when configured; full campaigns and historical calibration remain unaccepted.' });
  console.log('REAL_UI_RETRY_COMMITTED', sid, turn, after.war_state.mission.status);
} catch (error) {
  clearInterval(timer);
  const after = await snapshot().catch(() => null);
  if (after && !fs.existsSync(`${root}/after.json`)) save('after.json', after);
  if (!fs.existsSync(`${root}/result.json`)) save('result.json', { passed: false, error: error.message, faults,
    session_id: sid, expected_turn: turn, actual_turn: after?.turn_count, seconds: started ? (Date.now()-started)/1000 : 0 });
  await page.screenshot({ path: `${root}/failure.png` }).catch(() => {});
  console.log('FAILED', error.message); process.exitCode = 1;
} finally { clearInterval(timer); await browser.close(); }
