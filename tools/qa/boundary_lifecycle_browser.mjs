/** Same normal UI for committed outside checkpoints and resumed original tasks. */
import fs from 'node:fs';import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const stage=process.argv[3];if(!['offmap','deployed'].includes(stage))throw Error('Expected offmap or deployed');
const root='.cache/qa/boundary-lifecycle-2026-11-02',api='http://127.0.0.1:19140/api';
const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage();
const checks=[],errors=[],writes=[];const check=(v,label)=>{if(!v)throw Error(label);checks.push(label);};
const get=async p=>{const r=await fetch(api+p);if(!r.ok)throw Error(await r.text());return r.json();};
page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{if(r.url().startsWith(api)&&r.method()!=='GET')writes.push(r.url());});
try{
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19140'});
 for(const engine of ['afsim','narrative'])for(const width of [1440,900]){
  const c=JSON.parse(fs.readFileSync(`${root}/controlled/${engine}/case.json`)),base='/sessions/'+c.session_id;
  check(!(await get(base+'/progress')).active,engine+' idle checkpoint');
  const before=await get(base),tasks=await get(base+'/force-organization/tasks?kind=members&task_id='+c.task_id);
  check(before.war_state.campaign_lifecycle.phase_index===2,engine+' same-world third stage');
  check(tasks.rows[0].executions===(stage==='offmap'?0:1),engine+' expected original-task execution count');
  await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:19089/');
  await page.getByRole('tab',{name:/已保存战局/}).click();await page.locator(`[data-session-id="${c.session_id}"] .open-battle`).click();
  await page.getByTestId('map-unit-locator').waitFor();check(await page.locator('.nato-marker').count()===6,engine+width+' six markers');
  await page.getByTestId('top-status').click();
  const phase=page.getByTestId('lifecycle-current');await phase.scrollIntoViewIfNeeded();
  check((await phase.innerText()).includes('QA阶段三'),engine+width+' correct phase panel');
  await page.getByRole('button',{name:'向上收起工具面板'}).click();
  await page.getByTestId('map-unit-locator').locator('.locator-trigger').click();
  await page.getByRole('searchbox',{name:'地图单位搜索'}).fill('第159师');await page.locator('[data-locate-unit]').click();
  const status=await page.getByTestId('unit-participation-status').innerText();
  check(status.includes(stage==='offmap'?'场外待命':'在场作战'),engine+width+' actual participation label');
  check(status.includes(stage==='offmap'?'暂不承担作战目标':'可承担作战目标'),engine+width+' eligibility label');
  const actions=await page.getByTestId('unit-action').locator('option').evaluateAll(options=>options.map(o=>o.value));
  check(actions.includes('fire')===(stage==='deployed'),engine+width+' fire action follows return state');
  await page.screenshot({path:`${root}/${stage}-${engine}-${width}.png`});
  const after=await get(base);check(JSON.stringify(after.war_state)===JSON.stringify(before.war_state),engine+width+' full world unchanged');
  check(JSON.stringify(after.history)===JSON.stringify(before.history),engine+width+' history unchanged');
  check(JSON.stringify(await get(base+'/force-organization/tasks?kind=members&task_id='+c.task_id))===JSON.stringify(tasks),engine+width+' task identity/count unchanged');
 }
 check(!errors.length,'no application exceptions');check(!writes.length,'no API writes');
 fs.writeFileSync(`${root}/${stage}-browser-review.json`,JSON.stringify({passed:true,checks,count:checks.length,errors,writes,
   scope:'Two backends actual committed third-stage worlds1440/900; original task retained; read-only browser checks'},null,2));
 console.log('PASS',stage,checks.length,'normal-app phase/participation/task checks');
}catch(error){fs.writeFileSync(`${root}/${stage}-browser-failure.json`,JSON.stringify({error:String(error),checks,errors,writes},null,2));await page.screenshot({path:`${root}/${stage}-browser-failure.png`});throw error;}
finally{await browser.close();}
