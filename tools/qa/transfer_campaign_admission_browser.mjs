/** Normal launch selection; no models, sessions, configuration or saved-game writes. */
import fs from 'node:fs';import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json');const {chromium}=require('playwright-core');
const base='.cache/qa/transfer-window-2026-11-03/live-final',root=base+'/admission';if(fs.existsSync(root))throw Error('Preserve evidence');fs.mkdirSync(root);
const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}}),checks=[],errors=[],writes=[],bases=[];
const check=(v,m)=>{if(!v)throw Error(m);checks.push(m);};page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(['PUT','POST','DELETE'].includes(r.method()))writes.push(new URL(r.url()).pathname);});
page.on('response',async r=>{if(r.ok()&&r.url().includes('/api/historical-scenarios/basis?'))bases.push(await r.json());});
await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19318'});
try{
 await page.goto('http://127.0.0.1:19329',{waitUntil:'domcontentloaded'});
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('雪山草地');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();await page.locator('#draft-mode').selectOption('historical');
 await page.locator('#draft-executor').selectOption('afsim');
 await page.getByTestId('generate-historical-scenario').waitFor();
 check(await page.getByLabel('史料档案版本',{exact:true}).inputValue()==='1.0.0','original default source version retained');
 await page.getByLabel('编制范围',{exact:true}).selectOption('campaign');
 await page.getByTestId('historical-configuration-gap').waitFor();
 check((await page.getByTestId('historical-configuration-gap').innerText()).includes('双方'),'cumulative campaign remains explicitly guarded');
 const selector=page.getByLabel('会战窗口',{exact:true});
 await selector.selectOption('LM06-right-column-aug21-27@1.0.0');
 await page.getByTestId('campaign-window-scope').waitFor();await page.getByTestId('generate-historical-scenario').waitFor();
 check(await page.getByTestId('generate-historical-scenario').isEnabled(),'explicit sourced noncontact window is configurable');
 check(await page.getByLabel('史料档案版本',{exact:true}).inputValue()==='1.1.0','window freezes its own additive source version');
 check(await page.getByLabel('史料档案版本',{exact:true}).isDisabled(),'window pin cannot silently drift source version');
 check((await page.getByTestId('historical-noncontact-scope').innerText()).includes('不生成'),'source scope discloses no invented enemy');
 const latest=bases.at(-1);check(latest?.ready&&latest.actors.length===4,'actual API basis admits four army actors');
 check(latest.configuration_template.campaign_plan.nodes.length===6,'actual API template includes all six transfer objectives');
 check(latest.configuration_template.campaign_plan.outcomes.blue.node_ids.length===0,'inactive side has no generated opposing goal');
 check(latest.configuration_template.campaign.objective.relief_regions.length===0&&!latest.configuration_template.campaign.surrender.enabled,'no fake blocking region or surrender');
 check(Object.values(latest.configuration_template.actors).every(a=>a.personnel===null),'unknown army strengths remain unfilled estimates');
 await page.screenshot({path:root+'/window-1440.png'});await page.setViewportSize({width:900,height:1000});
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'launch window fits 900px viewport');await page.screenshot({path:root+'/window-900.png'});
 check(!writes.length,'selection does not call models or write a session');check(!errors.length,'no application exceptions');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,checks,count:checks.length,writes,errors,actual_api:true,actual_model:false,scope:'Normal source/window selection only; staged contract tests and running-case tests are separate.'},null,2));console.log('PASS',checks.length,'normal admission checks');
}catch(error){fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,writes,errors},null,2));await page.screenshot({path:root+'/failure.png'});throw error;}
finally{await browser.close();}
