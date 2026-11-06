/** Normal application, current isolated Native world and actual queued route/turn. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root='.cache/qa/operation-boundary-2026-11-02';
const fixture=JSON.parse(fs.readFileSync(root+'/afsim/case.json'));const sid=fixture.session_id;
const url='http://127.0.0.1:19136/api/sessions/'+sid;
const before=await(await fetch(url)).json();const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});const checks=[],errors=[];
const check=(v,label)=>{if(!v)throw Error(label);checks.push(label);};page.on('pageerror',e=>errors.push(String(e)));
try{
 check(JSON.stringify(before.war_state)===JSON.stringify(JSON.parse(fs.readFileSync(root+'/afsim/turn-12.json')).war_state),'fresh backend cold restores exact12turn world');
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19136'});await page.goto('http://127.0.0.1:19089/');
 await page.getByRole('tab',{name:/已保存战局/}).click();await page.locator(`[data-session-id="${sid}"] .open-battle`).click();
 await page.getByTestId('map-unit-locator').waitFor();check(await page.locator('.nato-marker').count()===6,'all6physical units retained');
 check(await page.locator('.operation-boundary').count()===1,'explicit operation circle rendered');check(await page.locator('.operation-route').count()===1,'registered actual route rendered');
 await page.getByTestId('map-unit-locator').locator('.locator-trigger').click();await page.getByRole('searchbox',{name:'地图单位搜索'}).fill('第159师');await page.locator('[data-locate-unit]').click();
 check((await page.getByTestId('unit-participation-status').innerText()).includes('作战区内'),'initial command panel shows operation inside');
 await page.getByTestId('unit-action').selectOption('move');await page.getByTestId('unit-participation').selectOption('withdraw');
 await page.getByRole('combobox',{name:'选择已登记出入通路'}).selectOption('red-north');
 check((await page.getByTestId('map-destination').innerText()).includes(fixture.route.outside.lat.toFixed(5)),'fixed route sets intended outside coordinate');
 await page.getByRole('button',{name:'校验并加入队列',exact:true}).click();
 const queued=await(await fetch(url)).json();check(JSON.stringify(queued.war_state)===JSON.stringify(before.war_state),'queue confirmation has no physical world effect');
 await page.getByRole('button',{name:'收起指挥面板',exact:true}).click();
 const response=page.waitForResponse(r=>r.url().endsWith('/sessions/'+sid+'/next')&&r.request().method()==='POST',{timeout:300000});
 await page.getByRole('button',{name:/^推进一轮/}).click();const result=await response;check(result.status()===200,'actual frontend Native turn succeeds');
 const after=await result.json();fs.writeFileSync(root+'/frontend-post-turn.json',JSON.stringify(after));
 const member=after.war_state.red_units.find(u=>u.historical_unit_id==='ww2.cn.division159');const state=Object.values(after.war_state.unit_participation.actors).find(u=>u.name===member.name);
 check(state.status==='offmap','actual physical exit yields offmap');check(after.war_state.simulation_clock.elapsed_seconds-before.war_state.simulation_clock.elapsed_seconds===21600,'actual frontend advances precisely6hours');
 check(after.afsim.returncode===0&&after.afsim.model_skipped,'allmanual Native turn uses no model simulation');
 check(JSON.stringify(member.personnel)===JSON.stringify(before.war_state.red_units.find(u=>u.name===member.name).personnel),'frontend exit retains actual prior casualty account');
 await page.getByTestId('map-unit-locator').locator('.locator-trigger').click();await page.getByRole('searchbox',{name:'地图单位搜索'}).fill('第159师');
 check((await page.locator('[data-locate-unit]').innerText()).includes('场外待命'),'locator identifies offmap without removing unit');await page.locator('[data-locate-unit]').click();
 check((await page.getByTestId('unit-participation-status').innerText()).includes('作战区外'),'command panel shows actual outside state');
 await page.screenshot({path:root+'/app-offmap-1440.png'});await page.setViewportSize({width:900,height:900});await page.screenshot({path:root+'/app-offmap-900.png'});
 check(!errors.length,'no application browser errors');
 fs.writeFileSync(root+'/app-browser-review.json',JSON.stringify({passed:true,checks,count:checks.length,errors,session_id:sid,scope:'Actual source app, normal queued route and one real Native6h turn; no full historical acceptance'},null,2));console.log('PASS',checks.length,'actual app checks');
}catch(e){fs.writeFileSync(root+'/app-browser-failure.json',JSON.stringify({error:String(e),checks,errors},null,2));await page.screenshot({path:root+'/app-browser-failure.png'});throw e;}finally{await browser.close();}
