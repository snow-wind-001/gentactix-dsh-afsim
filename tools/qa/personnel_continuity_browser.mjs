/** Read-only completed three-stage case, resources, decisions and responsive UI. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json');
const {chromium}=require('playwright-core');
const engine=process.argv[2],attempt=process.argv[3]??'completed-browser';
if(!['afsim','narrative','dsh-supply'].includes(engine)||!/^[a-z0-9-]+$/.test(attempt))throw Error('Invalid QA case');
const base=process.argv[4]??'.cache/qa/personnel-continuity-2026-11-03',root=`${base}/${engine}/${attempt}`;
if(fs.existsSync(root))throw Error('Preserve existing evidence');fs.mkdirSync(root);
const info=JSON.parse(fs.readFileSync(`${base}/${engine}/case.json`)),api=info.api??'http://127.0.0.1:19368',ui=info.ui??'http://127.0.0.1:19369';
const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}});
const checks=[],errors=[],writes=[];const check=(v,m)=>{if(!v)throw Error(m);checks.push(m);};
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!['GET','HEAD','OPTIONS'].includes(r.method()))writes.push(r.url());});
await page.addInitScript(({api,sid})=>{window.gentactix={backendUrl:api};localStorage.setItem('gentactix-session',sid);},{api,sid:info.session_id});
const get=async suffix=>{const r=await fetch(`${api}/api/sessions/${info.session_id}${suffix}`);if(!r.ok)throw Error(`HTTP ${r.status}`);return r;};
try{
 const raw=await(await get('/export')).text(),before=JSON.parse(raw).session,snap=await(await get('')).json();
 check(!(await(await get('/progress')).json()).active,'completed source is idle');
 const completed=before.war_state.mission.status==='completed';
 if(engine==='dsh-supply')check(!completed&&before.turn_count===3,'three-round scheduled-supply case remains an active local scenario');
 else check(completed&&before.war_state.mission.winner==='red','program settled the two-axis goal with red winner');
 const response=await page.goto(ui,{waitUntil:'domcontentloaded'});check(response?.ok(),'QA frontend HTTP success');
 const workbench=page.getByTestId('map-workbench'),saved=page.getByRole('tab',{name:/已保存战局/});
 await Promise.race([workbench.waitFor(),saved.waitFor()]);
 if(!await workbench.isVisible()){await saved.click();await page.locator(`[data-session-id="${info.session_id}"] .open-battle`).click();}
 await workbench.waitFor();
 // The workbench renders before the normal restore request clears its local
 // loading state. Observe the settled control, not that transient disabled UI.
 await page.waitForFunction(done=>{const b=document.querySelector('button[aria-label="推进一轮"]');return b&&b.disabled===done;},completed);
 check(await page.getByRole('button',{name:'推进一轮',exact:true}).isDisabled()===completed,'advance availability matches actual settlement status');
 await page.getByTestId('top-status').click();
 if(info.goal_count){
  const rows=page.getByTestId('mission-panel').locator('[data-goal-id]');
  check(await rows.count()===info.goal_count,'all generated window goals retained');
  if(completed)for(const row of await rows.all())check((await row.innerText()).includes('已达成'),'program-completed goal shown achieved');
 }
 if(before.war_state.mission.definition.campaign_lifecycle){
 check((await page.getByTestId('lifecycle-current').innerText()).includes('全部阶段已完成'),'all-stage completion shown');
 for(const phase of before.war_state.mission.definition.campaign_lifecycle.phases){
  const row=page.locator(`[data-phase-id="${phase.id}"]`);await row.scrollIntoViewIfNeeded();
  check((await row.innerText()).includes('已完成'),`completed stage ${phase.id} readable`);
 }
 for(const id of ['north','south']){
  const row=page.locator(`[data-goal-id="${id}"]`);await row.scrollIntoViewIfNeeded();
  check((await row.innerText()).includes('已达成'),`actual ${id} goal shown achieved`);
 }
 }else{
  const details=page.getByTestId('mission-panel').locator('details').filter({has:page.getByTestId('mission-resource-table')});
  await details.locator('summary').click();
  const sourceText=await page.getByTestId('mission-resource-source').innerText();fs.writeFileSync(root+'/resource-source.txt',sourceText);
  check(engine==='afsim'?sourceText.includes('AFSIM'):sourceText.includes('DSH')&&sourceText.includes('估计'),'resource source matches the actual execution backend');
  check(await page.getByTestId('mission-resource-table').locator('tbody tr').count()===before.war_state.mission.ledger.length,'all scheduled resource rows retained');
 }
 await page.getByTestId('resource-readiness').locator('summary').click();
 const massRows=page.getByTestId('resource-readiness').locator('tbody tr');
 check(await massRows.count()===snap.resource_readiness.units.length,'all current actors have ration rows after split/merge');
 for(const expected of snap.resource_readiness.units){
  const row=massRows.filter({has:page.locator('td').first().filter({hasText:expected.unit})});
  const cell=row.getByTestId('unit-ration-mass');await cell.scrollIntoViewIfNeeded();const text=await cell.innerText();
  check(text.includes(`随队${expected.food_on_hand_kg.toFixed(1)}`)&&text.includes(`携行容量${expected.food_capacity_kg.toFixed(1)}`),`authoritative mass/capacity for ${expected.unit}`);
 }
 await page.screenshot({path:root+'/'+(completed?'completed':'runtime')+'-mass-1440.png'});
 await page.getByTestId('focus-map').click();await page.getByTestId('command-toggle').click();
 const panel=page.getByTestId('command-panel'),menu=panel.getByLabel('单位名单（含无坐标单位）');
 const view=await(await get('/commands')).json();
 const current=view.units.filter(u=>u.present&&!u.retired);
 check(current.length===before.war_state.red_units.length+before.war_state.blue_units.length,'current identities distinguished from same-label retired split generations');
 for(const entry of current){
  await menu.selectOption(entry.id);await panel.getByRole('button',{name:'本单位决策／执行回执',exact:true}).click();
  const receipt=panel.getByRole('region',{name:'单位决策记录',exact:true});await receipt.waitFor();
  check((await receipt.innerText()).includes('T+'+before.turn_count),`latest retained receipt for ${entry.name}`);
 }
 await panel.getByRole('button',{name:'收起指挥面板'}).click();await page.setViewportSize({width:900,height:1000});
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'no document overflow at900px');
 await page.screenshot({path:root+'/'+(completed?'completed':'runtime')+'-map-900.png'});
 check(await(await get('/export')).text()===raw,'whole exported session bytes unchanged by UI inspection');
 check(writes.length===0,'inspection issues no writes or model calls');check(errors.length===0,'no browser application exceptions');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,engine,session_id:info.session_id,turn:before.turn_count,count:checks.length,checks,errors,writes,
  scope:'Read-only normal UI '+(completed?'completion/stages/goals':'active scheduled-supply resource rows')+', current rations and per-unit receipts; not another physical or historical campaign run.'},null,2));
 console.log('PASS',engine,checks.length,'completed continuity UI checks');
}catch(error){fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,errors,writes},null,2));await page.screenshot({path:root+'/failure.png'}).catch(()=>{});throw error;}
finally{await browser.close();}
