/** Explicit six-hour variant via ordinary saved-draft editing, no regeneration. */
import fs from 'node:fs';import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json'),{chromium}=require('playwright-core');
const base='.cache/qa/transfer-generation-2026-11-03',root=base+'/longstep-browser';if(fs.existsSync(root))throw Error('Preserve evidence');fs.mkdirSync(root);
const draft=JSON.parse(fs.readFileSync(base+'/authoritative-draft.json','utf8')),api='http://127.0.0.1:19338',ui='http://127.0.0.1:19339';
const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}}),checks=[],errors=[],posts=[];
const check=(v,m)=>{if(!v)throw Error(m);checks.push(m);};page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);});
await page.addInitScript(api=>window.gentactix={backendUrl:api},api);
try{
 await page.goto(ui,{waitUntil:'domcontentloaded'});await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('雪山草地');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-executor').selectOption('narrative');
 await page.locator('#draft-step').selectOption('30分钟');await page.getByLabel('编制范围',{exact:true}).selectOption('campaign');
 await page.getByLabel('会战窗口',{exact:true}).selectOption('LM06-right-column-aug21-27@1.0.0');await page.getByTestId('campaign-window-scope').waitFor();
 await page.getByLabel('生成时必须按时间计算粮秣',{exact:true}).check();await page.getByLabel('生成时必须校验运动与疲劳反馈',{exact:true}).check();
 await page.getByTestId('completed-historical-configurations').locator('summary').click();await page.locator(`[data-open-configuration="${draft.id}"]`).click();
 await page.waitForFunction(()=>document.querySelector('[data-testid="historical-validation"]')?.textContent?.includes('未启动AFSIM'));
 await page.locator('#draft-step').selectOption('6小时');
 check(!(await page.getByTestId('historical-validation').innerText()).includes('可创建'),'explicit step change invalidates prior validation');
 const validated=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/historical-scenarios/validate'),{timeout:0});
 await page.getByTestId('validate-historical-scenario').click();const response=await validated;check(response.ok(),'edited six-hour draft validates normally');
 const variant=await response.json();fs.writeFileSync(root+'/variant-id.json',JSON.stringify({id:variant.id,parent:draft.id},null,2));
 check(variant.parameters.clock.time_step==='6小时','six-hour choice is explicit in authoritative parameters');
 check(variant.parent_id===draft.id,'model-generated source draft retained as parent');
 check(variant.preview_world.red_units.length===4&&!variant.preview_world.blue_units.length,'same four source armies and empty opposing side');
 check(JSON.stringify(variant.parameters.actors)===JSON.stringify(draft.parameters.actors),'step variant does not alter units, stocks or initial deployments');
 check(variant.validation.scope==='configuration_contract_only'&&variant.afsim===null,'edited draft still does not claim AFSIM execution');
 await page.screenshot({path:root+'/six-hour-validated.png'});
 const initialized=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/init'),{timeout:0});
 await page.getByTestId('launch-start').click();const init=await initialized;check(init.ok(),'six-hour variant initializes through ordinary frontend');const snap=await init.json();
 await page.getByTestId('map-workbench').waitFor();
 const folder=base+'/longstep';fs.mkdirSync(folder);
 fs.writeFileSync(folder+'/live-case.json',JSON.stringify({api,ui,session_id:snap.session_id,turn:1,actor_count:4,step_seconds:21600,native_decision_count:0,draft_id:variant.id,parent_draft_id:draft.id},null,2));
 check(posts.filter(p=>p.endsWith('/historical-scenarios/build')).length===0,'step variant never calls model generation again');
 check(errors.length===0,'no application exceptions');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,checks,count:checks.length,posts,errors,scope:'Explicit independent six-hour initial variant; original 30-minute session and model draft unchanged.'},null,2));console.log('PASS',checks.length,'six-hour variant checks',snap.session_id);
}catch(error){fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,posts,errors},null,2));await page.screenshot({path:root+'/failure.png'}).catch(()=>{});throw error;}
finally{await browser.close();}
