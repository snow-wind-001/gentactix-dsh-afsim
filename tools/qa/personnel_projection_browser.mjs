/** Current22 branch, normal rendered controls and actual Native readonly question. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const base='.cache/qa/personnel-projection-2026-11-02';
const root=process.argv[3]??base;
if(fs.existsSync(root+'/browser-result.json')||fs.existsSync(root+'/browser-failure.json'))throw Error('Preserve earlier browser evidence');
fs.mkdirSync(root,{recursive:true});
const c=JSON.parse(fs.readFileSync(base+'/case.json','utf8'));
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});const faults=[],posts=[];let timer;
page.on('pageerror',e=>faults.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19227'});
const api='http://127.0.0.1:19227/api/sessions/'+c.session_id;
try{
 const before=(await(await page.request.get(api+'/export')).json()).session;
 if(before.turn_count!==1||before.war_state.red_units.length+before.war_state.blue_units.length!==22)throw Error('Expected unchanged22 T1 branch');
 await page.goto('http://127.0.0.1:19238');
 await page.getByRole('tab',{name:/已保存战局/}).click();await page.locator(`[data-session-id="${c.session_id}"] .open-battle`).click();
 await page.getByTestId('map-workbench').waitFor({timeout:60000});
 if(await page.locator('.nato-marker').count()!==22)throw Error('Missing actors');
 if(!await page.getByTestId('command-panel').isVisible())await page.getByTestId('command-toggle').click();
 await page.getByLabel('单位名单（含无坐标单位）').selectOption(c.unit_id);
 const indicator=page.getByTestId('selected-unit-strength');await indicator.waitFor();
 if(!(await indicator.innerText()).includes('99.19%'))throw Error('Desktop control projection absent');
 await page.screenshot({path:root+'/strength-1440.png'});await page.setViewportSize({width:900,height:1000});
 await page.screenshot({path:root+'/strength-900.png'});await page.setViewportSize({width:1440,height:1000});
 await page.getByTestId('focus-map').click();await page.getByTestId('analysis-tab-chat').click();
 const question='请先调用get_afsim_observation，ids=["'+c.unit_id+'"],limit=1,detail=true，读取日军第106师团当前状态。'
  +'只依据本次工具回执，仅回答JSON，字段current、committed、personnel_strength_pct、legacy_hp、fatigue为数字，full_establishment_proven为布尔值。'
  +'最后一项表示现有资料是否证明核定编制满员。区分累计投入、人员保有率与旧HP；这些是本局计算值。不要修改战局，不根据旧战报代答。';
 await page.getByPlaceholder('向总参谋长璇玑提问（如：帮我评估当前优势在哪方？）').fill(question);
 const completed=page.waitForResponse(r=>r.url()===api+'/chat'&&r.request().method()==='POST',{timeout:1800000});
 const started=Date.now();await page.getByRole('button',{name:'发送',exact:true}).click();
 console.log('ACTUAL_NATIVE_PROJECTION_QUESTION_STARTED');timer=setInterval(()=>console.log('WAIT_NATIVE',Math.round((Date.now()-started)/1000)),15000);
 const response=await completed;clearInterval(timer);const body=await response.json();
 const messages=(body.chat_messages??[]).map(({role,content})=>({role,content}));
 fs.writeFileSync(root+'/question-response.json',JSON.stringify({http:response.status(),seconds:(Date.now()-started)/1000,messages,detail:body.detail},null,2));
 if(!response.ok())throw Error('Readonly question failed');
 const answerText=messages.findLast(m=>m.role==='assistant')?.content??'';
 const match=answerText.match(/\{[\s\S]*\}/);if(!match)throw Error('Missing requested structured public answer');const answer=JSON.parse(match[0]);
 if(answer.current!==7935||answer.committed!==8000||answer.personnel_strength_pct!==99.19||answer.legacy_hp!==100||answer.fatigue!==37||answer.full_establishment_proven!==false)throw Error('Native public answer inconsistent '+JSON.stringify(answer));
 const after=(await(await page.request.get(api+'/export')).json()).session;
 if(JSON.stringify(before.war_state)!==JSON.stringify(after.war_state)||before.turn_count!==after.turn_count)throw Error('Readonly Native question changed world');
 if(posts.length!==1||!posts[0].endsWith('/chat')||faults.length)throw Error('Unexpected requests or UI faults');
 await page.screenshot({path:root+'/native-answer-1440.png'});
 fs.writeFileSync(root+'/browser-result.json',JSON.stringify({passed:true,session_id:c.session_id,turn:1,markers:22,answer,faults,posts,
  world_unchanged:true,raw_hp_preserved:true,scope:'Real22 branch UI and actual Native observation question; not historical calibration or full campaign'},null,2));
 console.log('PASS actual22 UI and Native personnel projection');
}catch(e){clearInterval(timer);fs.writeFileSync(root+'/browser-failure.json',JSON.stringify({passed:false,error:String(e),faults,posts},null,2));await page.screenshot({path:root+'/browser-failure.png'}).catch(()=>{});console.log('FAILED',String(e));process.exitCode=1;}
finally{clearInterval(timer);await browser.close();}
