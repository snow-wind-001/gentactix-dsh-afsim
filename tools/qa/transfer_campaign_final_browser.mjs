/** Read-only completed-case UI after cold restoration. */
import fs from 'node:fs';import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json'),{chromium}=require('playwright-core');
const base='.cache/qa/transfer-window-2026-11-03/live-final',root=base+'/completed-cold-browser';if(fs.existsSync(root))throw Error('Preserve evidence');fs.mkdirSync(root);
const info=JSON.parse(fs.readFileSync(base+'/live-case.json','utf8')),browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}});
const checks=[],errors=[],writes=[];function check(v,m){if(!v)throw Error(m);checks.push(m);}
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(['POST','PUT','DELETE'].includes(r.method()))writes.push(r.url());});
await page.addInitScript(i=>{window.gentactix={backendUrl:i.api};localStorage.setItem('gentactix-session',i.session_id);},info);
try{
 const api=info.api+'/api/sessions/'+info.session_id;
 const before=(await(await fetch(api+'/export')).json()).session;
 await page.goto(info.ui,{waitUntil:'domcontentloaded'});await page.getByRole('tab',{name:/已保存战局/}).click();
 await page.locator(`[data-session-id="${info.session_id}"] .open-battle`).click();await page.getByTestId('map-workbench').waitFor();
 check(await page.getByRole('button',{name:'推进一轮',exact:true}).isDisabled(),'completed case prevents an extra physical turn');
 await page.getByRole('button',{name:/^目标与运行/}).click();await page.getByTestId('single-team-goals').waitFor();
 for(const goal of before.war_state.mission.definition.campaign_plan.nodes){
  const row=page.locator(`[data-goal-id="${goal.id}"]`);await row.scrollIntoViewIfNeeded();
  check((await row.innerText()).includes('已达成'),'completed goal remains reachable by scrolling '+goal.id);
 }
 check(await page.getByRole('combobox',{name:'目标阵营'}).locator('option').count()===2,'only all-participants and red goal filters shown');
 await page.screenshot({path:root+'/all-goals-1440.png'});
 await page.getByTestId('command-toggle').click();const panel=page.getByTestId('command-panel'),menu=panel.getByLabel('单位名单（含无坐标单位）');
 for(const unit of before.command_state.registry){
  await menu.selectOption(unit.id);await panel.getByRole('button',{name:'本单位决策／执行回执',exact:true}).click();
  await panel.getByRole('region',{name:'单位决策记录',exact:true}).waitFor();
  check((await panel.getByRole('region',{name:'单位决策记录',exact:true}).innerText()).includes('T+4'),'retained command receipts readable for '+unit.name);
 }
 await panel.getByRole('button',{name:'收起指挥面板'}).click();
 await page.setViewportSize({width:900,height:1000});
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'completed layout has no document overflow at900px');
 await page.screenshot({path:root+'/completed-900.png'});
 const after=(await(await fetch(api+'/export')).json()).session;
 check(JSON.stringify(after)===JSON.stringify(before),'completed UI inspection preserves the whole API session');
 check(!writes.length,'goal scrolling and receipt review issue no writes or model calls');check(!errors.length,'no browser application exceptions');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,checks,count:checks.length,errors,writes,scope:'Read-only completed T4 after cold restore, all goals and four unit receipts; no extra model/physical turn.'},null,2));console.log('PASS',checks.length,'completed UI checks');
}catch(error){fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,errors,writes},null,2));await page.screenshot({path:root+'/failure.png'});throw error;}
finally{await browser.close();}
