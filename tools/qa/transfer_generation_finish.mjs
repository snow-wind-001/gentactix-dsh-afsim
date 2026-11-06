/** Recover the already generated draft after a QA provenance-label typo. */
import fs from 'node:fs';import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json'),{chromium}=require('playwright-core');
const base='.cache/qa/transfer-generation-2026-11-03',attempt=process.argv[2]??'finish-browser';if(!/^[a-z0-9-]+$/.test(attempt))throw Error('Invalid attempt');const root=base+'/'+attempt;if(fs.existsSync(root))throw Error('Preserve evidence');fs.mkdirSync(root);
const generated=JSON.parse(fs.readFileSync(base+'/browser/build-response.txt','utf8')),api='http://127.0.0.1:19338',ui='http://127.0.0.1:19339';
if(generated.construction?.source!=='dsh_native_skill'||generated.construction?.workflow!=='native_agent_registry_scoped_drafts')throw Error('No actual validated staged model configuration');
const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}}),checks=[],errors=[],posts=[];
function check(v,m){if(!v)throw Error(m);checks.push(m);}page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);});
await page.addInitScript(api=>window.gentactix={backendUrl:api},api);
try{
 await page.goto(ui,{waitUntil:'domcontentloaded'});await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('雪山草地');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-executor').selectOption('narrative');
 await page.locator('#draft-step').selectOption('30分钟');await page.getByLabel('编制范围',{exact:true}).selectOption('campaign');
 await page.getByLabel('会战窗口',{exact:true}).selectOption('LM06-right-column-aug21-27@1.0.0');await page.getByTestId('campaign-window-scope').waitFor();
 await page.getByLabel('生成时必须按时间计算粮秣',{exact:true}).check();await page.getByLabel('生成时必须校验运动与疲劳反馈',{exact:true}).check();
 const loader=page.locator(`[data-open-configuration="${generated.id}"]`);await loader.waitFor({state:'attached'});
 await page.getByTestId('completed-historical-configurations').locator('summary').click();
 await loader.waitFor();check(await loader.isEnabled(),'saved real model draft is available for the matching source and model requirements');
 await loader.click();await page.getByTestId('historical-validation').waitFor();
 check((await page.getByTestId('historical-validation').innerText()).includes('未启动AFSIM'),'loaded narrative configuration does not claim AFSIM execution');
 check(generated.preview_world.red_units.length===4&&!generated.preview_world.blue_units.length,'model generated four sourced armies with no invented opponent');
 check(generated.parameters.support_dynamics?.version==='time-sustainment-1'&&generated.parameters.movement_feedback?.version==='movement-feedback-1','both requested feedback models retained');
 check(Object.values(generated.parameters.actors).every(u=>u.formation.role==='infantry'),'each generated army has an explicit infantry role');
 await page.screenshot({path:root+'/generated-1440.png'});
 const initialized=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/init'),{timeout:0});
 await page.getByTestId('launch-start').click();const response=await initialized;check(response.ok(),'actual generated draft initializes through normal frontend');
 const snap=await response.json();check(snap.turn_count===0&&snap.war_state.simulation_clock.elapsed_seconds===0,'no physical turn hidden in configuration or initialization');
 await page.getByTestId('map-workbench').waitFor();await page.screenshot({path:root+'/initialized-1440.png'});await page.setViewportSize({width:900,height:1000});await page.screenshot({path:root+'/initialized-900.png'});
 fs.writeFileSync(base+'/live-case.json',JSON.stringify({session_id:snap.session_id,api,ui,turn:1,actor_count:4,step_seconds:1800,draft_id:generated.id},null,2));
 check(posts.filter(p=>p.endsWith('/historical-scenarios/build')).length===0,'reopening saved draft never regenerates model output');
 check(errors.length===0,'no application exceptions');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,checks,count:checks.length,posts,errors,actual_initial_model_generation:true,model_regenerated:false,scope:'Reuse the original actual generated draft after a QA string mismatch; no response or parameter replacement.'},null,2));console.log('PASS',checks.length,'real draft and initialization checks',snap.session_id);
}catch(error){fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,posts,errors},null,2));await page.screenshot({path:root+'/failure.png'}).catch(()=>{});throw error;}
finally{await browser.close();}
