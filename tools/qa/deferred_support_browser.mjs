/** Normal UI observes an earned deferred load and optionally confirms one merge. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json');
const {chromium}=require('playwright-core');
const [engine,mode,tag]=process.argv.slice(2),root='.cache/qa/deferred-support-2026-11-03';
if(!['afsim','narrative'].includes(engine)||!['preview','merge'].includes(mode)||!tag||!/^[a-z0-9-]+$/.test(tag))throw Error('Explicit QA case/mode/tag required');
const out=`${root}/${engine}/${tag}`;if(fs.existsSync(out))throw Error('Preserve prior evidence');fs.mkdirSync(out);
const info=JSON.parse(fs.readFileSync(`${root}/${engine}/${mode==='merge'?'browser-case':'case'}.json`));
const host='http://127.0.0.1:19378',ui=process.env.DEFERRED_UI_URL??'http://127.0.0.1:19379';
const get=async suffix=>{const r=await fetch(`${host}/api/sessions/${info.session_id}${suffix}`);if(!r.ok)throw Error(`HTTP ${r.status}: ${await r.text()}`);return r.json();};
const save=(name,v)=>fs.writeFileSync(`${out}/${name}.json`,JSON.stringify(v,null,2));
const checks=[],errors=[],writes=[];const check=(v,m)=>{if(!v)throw Error(m);checks.push(m);};
const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}});
page.on('pageerror',e=>errors.push(e.message));
page.on('request',r=>{if(!['GET','HEAD','OPTIONS'].includes(r.method()))writes.push({method:r.method(),url:r.url()});});
await page.addInitScript(({host,sid})=>{window.gentactix={backendUrl:host};localStorage.setItem('gentactix-session',sid);},{host,sid:info.session_id});
try{
 const before=(await get('/export')).session;save('before',before);
 check(!(await get('/progress')).active,'authoritative case is idle');
 check(before.turn_count===3,'actual exposure checkpoint is T3');
 await page.goto(ui,{waitUntil:'domcontentloaded'});
 const workbench=page.getByTestId('map-workbench'),saved=page.getByRole('tab',{name:/已保存战局/});
 await Promise.race([workbench.waitFor(),saved.waitFor()]);
 if(!await workbench.isVisible()){await saved.click();await page.locator(`[data-session-id="${info.session_id}"] .open-battle`).click();}
 await workbench.waitFor();await page.getByRole('button',{name:'推进一轮',exact:true}).waitFor();
 await page.waitForFunction(()=>{const b=document.querySelector('button[aria-label="推进一轮"]');return b&&!b.disabled;});
 await page.getByTestId('analysis-tab-forces').click();const panel=page.getByTestId('formation-conversion');await panel.waitFor();
 await panel.getByLabel('实体转换方式',{exact:true}).selectOption(mode==='merge'?'merge':'split');
 await panel.getByLabel('实体转换单位',{exact:true}).selectOption(info.members);
 await panel.getByLabel('实体转换依据',{exact:true}).fill('实际保障形成余量后的前端验收，保留账目与时钟；非历史战损或改编命令。');
 const previewResponse=page.waitForResponse(r=>r.url().includes('/force-organization/conversion-preview')&&r.request().method()==='POST');
 await panel.getByTestId('formation-preview').click();const preview=await(await previewResponse).json();save('preview',preview);
 await panel.getByTestId('formation-preview-result').waitFor();
 check(preview.totals_before.fractional_debts.noncombat_remainder===1.2&&preview.totals_after.fractional_debts.noncombat_remainder===1.2,'preview preserves earned total 1.2');
 check(JSON.stringify((await get('/export')).session)===JSON.stringify(before),'preview is whole-session readonly');
 const row=panel.getByTestId('formation-support-load');
 check(await row.count()===1,'UI explicitly shows deferred noncombat load');
 check((await row.innerText()).includes('1.2'),'displayed load matches authoritative 1.2');
 const policy=panel.getByTestId('formation-fraction-policy');
 check((await policy.innerText()).includes('有效暴露'),'UI explains when pending load settles');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await row.scrollIntoViewIfNeeded();
  const box=await panel.boundingBox();check(!!box&&box.x>=0&&box.x+box.width<=width+1,`${width}px conversion remains inside viewport`);
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${width}px document has no horizontal overflow`);
  await page.screenshot({path:`${out}/pending-${width}.png`});
 }
 if(mode==='merge'){
  const responsePromise=page.waitForResponse(r=>r.url().endsWith('/force-organization/conversion-commit')&&r.request().method()==='POST');
  await panel.getByTestId('formation-confirm').click();const response=await responsePromise;
  check(response.ok(),'normal UI merge commit is accepted');const result=await response.json();save('conversion-response',result);
  await panel.getByTestId('formation-saved').waitFor();
  const after=(await get('/export')).session;save('after',after);
  for(const field of ['history','trajectory'])check(JSON.stringify(before[field])===JSON.stringify(after[field]),`merge preserves complete ${field}`);
  for(const field of ['simulation_clock','campaign_lifecycle'])check(JSON.stringify(before.war_state[field])===JSON.stringify(after.war_state[field]),`merge preserves ${field}`);
  const members=[...new Set(Object.values(result.conversion_result.command_map).flat())];check(members.length===1,'UI receipt resolves one current identity');
  const view=await get('/commands'),entry=view.units.find(u=>u.id===members[0]&&u.present&&!u.retired);
  const unit=after.war_state.red_units.find(u=>u.name===entry?.name);check(!!unit,'merged entity is current and selectable');
  check(unit.personnel.current===10000&&unit.personnel.noncombat_losses===0&&unit.sustainment.noncombat_remainder===1.2,'zero-time merge creates no whole-person loss');
  check(unit.runtime_allocation.support_remainder_policy==='deferred-support-exposure-1','formal merge records the registered settlement policy');
  const next={...info,members};
  for(const [name,value]of [['case',next],['expected-pending-cold',after]]){
   const path=`${root}/${engine}/${name}.json`;if(fs.existsSync(path))throw Error('Preserve '+path);fs.writeFileSync(path,JSON.stringify(value,null,2));
  }
 }
 check(writes.every(r=>r.url.includes('/force-organization/conversion-')),'UI makes no model, advance or unrelated write requests');
 check(writes.length===(mode==='merge'?2:1),'one preview and at most one explicit confirmation');
 check(errors.length===0,'no application exceptions');
 save('result',{passed:true,mode,engine,count:checks.length,checks,errors,writes,scope:'Normal UI observation/confirmation of load earned by real runtime, not full historical campaign acceptance.'});
 console.log('PASS deferred-support UI',engine,mode,checks.length);
}catch(error){save('result',{passed:false,error:String(error),checks,errors,writes});await page.screenshot({path:`${out}/failure.png`}).catch(()=>{});throw error;}
finally{await browser.close();}
