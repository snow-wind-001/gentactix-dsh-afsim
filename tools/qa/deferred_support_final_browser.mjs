/** Read-only normal UI after repeated real settlement and final cold restore. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json');
const {chromium}=require('playwright-core');
const [engine,tag]=process.argv.slice(2),base='.cache/qa/deferred-support-2026-11-03';
if(!['afsim','narrative'].includes(engine)||!tag||!/^[a-z0-9-]+$/.test(tag))throw Error('Explicit case/tag required');
const root=`${base}/${engine}/${tag}`;if(fs.existsSync(root))throw Error('Preserve evidence');fs.mkdirSync(root);
const info=JSON.parse(fs.readFileSync(`${base}/${engine}/case.json`)),host='http://127.0.0.1:19378',ui='http://127.0.0.1:19379';
const get=async suffix=>{const r=await fetch(`${host}/api/sessions/${info.session_id}${suffix}`);if(!r.ok)throw Error(`HTTP ${r.status}`);return r;};
const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}});
const checks=[],errors=[],writes=[],check=(v,m)=>{if(!v)throw Error(m);checks.push(m);};
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!['GET','HEAD','OPTIONS'].includes(r.method()))writes.push(r.url());});
await page.addInitScript(({host,sid})=>{window.gentactix={backendUrl:host};localStorage.setItem('gentactix-session',sid);},{host,sid:info.session_id});
try{
 const raw=await(await get('/export')).text(),before=JSON.parse(raw).session,w=before.war_state;
 check(before.turn_count===6&&w.simulation_clock.elapsed_seconds===10800,'six real half-hour rounds retained');
 check(!(await(await get('/progress')).json()).active,'case is idle');
 check(w.mission.status==='active','QA scenario remains active, not a completed historical campaign');
 const rootUnit=w.red_units.find(u=>u.runtime_allocation?.support_remainder_policy==='deferred-support-exposure-1');
 check(rootUnit?.personnel.current===9996&&rootUnit.personnel.noncombat_losses===4&&Math.abs(rootUnit.sustainment.noncombat_remainder-.8)<1e-6,'final current/NC/pending account 9996/4/.8 within receipt tolerance');
 await page.goto(ui,{waitUntil:'domcontentloaded'});
 const workbench=page.getByTestId('map-workbench'),saved=page.getByRole('tab',{name:/已保存战局/});await Promise.race([workbench.waitFor(),saved.waitFor()]);
 if(!await workbench.isVisible()){await saved.click();await page.locator(`[data-session-id="${info.session_id}"] .open-battle`).click();}
 await workbench.waitFor();await page.waitForFunction(()=>{const b=document.querySelector('button[aria-label="推进一轮"]');return b&&!b.disabled;});
 await page.getByTestId('analysis-tab-battlefield').click();const panel=page.getByTestId('battlefield-panel');await panel.waitFor();
 const table=panel.locator('table').filter({has:page.getByRole('columnheader',{name:'非战斗减员',exact:true})});
 const expected=[...w.red_units,...w.blue_units];check(await table.locator('tbody tr').count()===expected.length,'every current entity has a personnel ledger row');
 for(const unit of expected){
  // Match exact first-cell text; retired same-name generations are not current rows.
  const rows=await table.locator('tbody tr').all();const target=[];
  for(const r of rows)if(await r.locator('td').first().innerText()===unit.name)target.push(r);
  check(target.length===1,`one current ledger row for ${unit.name}`);
  const cells=target[0].locator('td');
  check(Number((await cells.nth(3).innerText()).replaceAll(',',''))===unit.personnel.current&&Number((await cells.nth(5).innerText()).replaceAll(',',''))===unit.personnel.noncombat_losses,`current and noncombat loss for ${unit.name}`);
 }
 const last=table.locator('tbody tr').last();await last.scrollIntoViewIfNeeded();
 await page.screenshot({path:`${root}/personnel-1440.png`});
 await page.getByTestId('focus-map').click();await page.getByTestId('command-toggle').click();
 const view=await(await get('/commands')).json(),entry=view.units.find(u=>u.present&&!u.retired&&u.name===rootUnit.name);check(!!entry,'latest merged identity can be selected');
 const command=page.getByTestId('command-panel');await command.getByLabel('单位名单（含无坐标单位）').selectOption(entry.id);
 check((await command.getByTestId('selected-unit-resources').innerText()).includes('9996'),'command panel shows surviving persons');
 await command.getByRole('button',{name:'本单位决策／执行回执',exact:true}).click();
 check((await command.getByRole('region',{name:'单位决策记录',exact:true}).innerText()).includes('T+6'),'current merged identity retains its last actual receipt');
 await command.getByRole('button',{name:'收起指挥面板'}).click();await page.setViewportSize({width:900,height:1000});
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'900px map has no document overflow');await page.screenshot({path:`${root}/map-900.png`});
 check(await(await get('/export')).text()===raw,'whole session bytes unchanged');check(writes.length===0,'readonly review sends no writes or model calls');check(errors.length===0,'no application exceptions');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,engine,count:checks.length,checks,errors,writes,actual_pending_load:rootUnit.sustainment.noncombat_remainder,receipt_tolerance:1e-6,scope:'Read-only current personnel/NC/map/receipt UI after real settlement; not full historical campaign acceptance.'},null,2));
 console.log('PASS final deferred UI',engine,checks.length);
}catch(error){fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,errors,writes},null,2));await page.screenshot({path:root+'/failure.png'}).catch(()=>{});throw error;}
finally{await browser.close();}
