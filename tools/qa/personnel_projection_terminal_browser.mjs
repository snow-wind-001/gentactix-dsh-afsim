/** Inspect the fixed real T2 UI read-only; no chat, commands or extra advance. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));
const {chromium}=require('playwright-core');
const base='.cache/qa/personnel-projection-2026-11-02';
const root=process.argv[3]??base+'/fixed-terminal-browser';
if(fs.existsSync(root))throw Error('Preserve earlier terminal browser evidence');
const caseInfo=JSON.parse(fs.readFileSync(process.argv[4]??base+'/retry-case.json','utf8'));
const sid=caseInfo.session_id,expectedTurn=caseInfo.expected_turn??2;
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const api='http://127.0.0.1:19227/api/sessions/'+sid;
const errors=[],posts=[];
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
await page.addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:19227'};localStorage.setItem('gentactix-session',id);},sid);
fs.mkdirSync(root);
try{
 const before=(await(await page.request.get(api+'/export')).json()).session;
 const progress=await(await page.request.get(api+'/progress')).json();
 if(progress.active||before.turn_count!==expectedTurn)throw Error('Expected real round is not terminal');
 const view=await(await page.request.get(api+'/commands')).json();
 const selected=view.units.find(u=>u.name==='日军第106师团');
 if(!selected||!(selected.personnel_strength_pct<100))throw Error('Expected known current losses');
 await page.goto('http://127.0.0.1:19238');
 await page.getByRole('tab',{name:/已保存战局/}).click();
 await page.locator(`[data-session-id="${sid}"] .open-battle`).click();
 await page.getByTestId('map-workbench').waitFor({timeout:60000});
 if(!await page.getByTestId('command-panel').isVisible())await page.getByTestId('command-toggle').click();
 await page.getByLabel('单位名单（含无坐标单位）').selectOption(selected.id);
 const indicator=page.getByTestId('selected-unit-strength');await indicator.waitFor();
 const text=await indicator.innerText();
 if(!text.includes(String(selected.personnel_strength_pct)+'%')||!text.includes('非核定编制满员率'))throw Error('Terminal personnel display differs from actual command view: '+text);
 await page.screenshot({path:root+'/strength-1440.png'});await page.setViewportSize({width:900,height:1000});
 await page.screenshot({path:root+'/strength-900.png'});
 const after=(await(await page.request.get(api+'/export')).json()).session;
 if(JSON.stringify(before.war_state)!==JSON.stringify(after.war_state)||posts.length||errors.length||await page.locator('.nato-marker').count()!==22)throw Error('Readonly terminal UI regression');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,session_id:sid,turn:expectedTurn,unit:selected.name,
  personnel_strength_pct:selected.personnel_strength_pct,indicator:text,markers:22,viewports:[1440,900],errors,posts,
  world_unchanged:true,scope:`Actual real22 T${expectedTurn} rendered current personnel and readonly controls; not complete map/history certification`},null,2));
 console.log(`PASS actual T${expectedTurn} personnel UI1440/900,22markers,zeroPOST/errors`);
}catch(e){fs.writeFileSync(root+'/failure.json',JSON.stringify({passed:false,error:String(e),errors,posts},null,2));throw e;}
finally{await browser.close();}
