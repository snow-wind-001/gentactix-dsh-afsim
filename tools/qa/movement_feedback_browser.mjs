/** Real UI/Native configuration with complete22, no routes, injected data or state writes. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));
const {chromium}=require('playwright-core');
const root='.cache/qa/movement-feedback-2026-11-02/live22';
fs.mkdirSync(root,{recursive:true});
const save=(name,value)=>{const p=root+'/'+name;if(fs.existsSync(p))throw Error('Preserve '+p);fs.writeFileSync(p,JSON.stringify(value,null,2));};
if(fs.existsSync(root+'/build-response.json'))throw Error('Preserve prior build; do not submit twice');
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const faults=[];let timer;
page.on('pageerror',e=>faults.push(e.message));page.on('crash',()=>faults.push('page_crash'));
await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19227'});
try{
 await page.goto('http://127.0.0.1:19228');
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('万家岭');
 await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('historical');
 await page.locator('#draft-executor').selectOption('afsim');
 await page.locator('#draft-step').selectOption('1小时');
 await page.getByLabel('编制范围',{exact:true}).selectOption('campaign');
 const picker=page.getByLabel('会战窗口',{exact:true});
 await picker.locator('option[value="WJL-oct6-10@1.5.0"]').waitFor({state:'attached'});
 // An additional version must not silently select itself or enable a model.
 const movement=page.getByRole('checkbox',{name:'生成时必须校验运动与疲劳反馈',exact:true});
 if(await movement.isChecked())throw Error('Motion requirement changed existing default');
 const oldSelection=await picker.inputValue();
 if(oldSelection==='WJL-oct6-10@1.5.0')throw Error('New version silently became default');
 await picker.selectOption('WJL-oct6-10@1.5.0');await movement.check();
 const evidence=page.getByTestId('campaign-window-evidence');await evidence.locator('summary').click();
 if(await page.locator('[data-estimate-actor]').count()!==22)throw Error('Incomplete22 displayed priors');
 await page.screenshot({path:root+'/motion-option-1440.png'});
 await page.setViewportSize({width:900,height:1000});await page.screenshot({path:root+'/motion-option-900.png'});
 await page.setViewportSize({width:1440,height:1000});await evidence.locator('summary').click();
 const lifecycle=JSON.parse(fs.readFileSync('.cache/qa/wjl22-continuous-2026-11-02/lifecycle.json','utf8'));
 const instruction='完整22单位公开1.5.0运动约束验收，保留所有39历史身份处理、22候选、双边6目标和数值先验。'
  +'来源仍为1.4.0史料；人数装备位置库存是计算先验，非已核历史数值。movement_feedback必须原样保留，通信延迟及疲劳按原生偶数舍入。'
  +'公共片只patch assumptions与以下campaign_lifecycle，不重写其他条件：'+JSON.stringify(lifecycle)
  +'。单位片patch覆盖本片全部actor ID，各自只更新assumption说明复核原先验，保留全部已有数值。'
  +'不生成新增部队、不改变1小时与按目标结束，不按未来史实自动执行；末片调用真实全量validate有效后结束。';
 await page.getByRole('textbox',{name:'计算参数与推演目标需求',exact:true}).fill(instruction);
 let request;
 const completed=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/build')&&r.request().method()==='POST',{timeout:3600000});
 page.on('request',r=>{if(r.url().endsWith('/api/historical-scenarios/build'))request=r.postDataJSON();});
 const started=Date.now();await page.getByTestId('generate-historical-scenario').click();
 console.log('REAL_NATIVE_MOTION_BUILD_STARTED');
 timer=setInterval(()=>console.log('WAIT_BUILD',Math.round((Date.now()-started)/1000)),15000);
 const response=await completed;clearInterval(timer);const draft=await response.json();
 save('build-response.json',{http:response.status(),seconds:(Date.now()-started)/1000,request,body:draft});
 if(!response.ok())throw Error('Build rejected '+JSON.stringify(draft).slice(0,800));
 if(draft.construction.source!=='dsh_native_skill'||draft.parameters.movement_feedback?.version!=='movement-feedback-1')throw Error('Native model/contract absent');
 if(!request.required_models.includes('movement-feedback-1'))throw Error('UI dropped required model');
 const creation=page.waitForResponse(r=>r.url().endsWith('/api/sessions')&&r.request().method()==='POST',{timeout:120000});
 const initialization=page.waitForResponse(r=>r.url().endsWith('/init')&&r.request().method()==='POST',{timeout:180000});
 await page.getByTestId('launch-start').click();
 const cr=await creation,ir=await initialization,snap=await ir.json();
 save('creation.json',{http:cr.status(),body:await cr.json()});save('initial.json',{http:ir.status(),body:snap});
 if(!cr.ok()||!ir.ok())throw Error('Create/init failed');
 await page.getByTestId('map-workbench').waitFor({timeout:60000});
 if(await page.locator('.nato-marker').count()!==22||snap.war_state.afsim.entity_count!==22)throw Error('Incomplete22 world/markers/AFSIM');
 await page.screenshot({path:root+'/initial-1440.png'});
 if(faults.length)throw Error(faults.join(';'));
 save('builder-result.json',{passed:true,session_id:snap.session_id,actors:22,markers:22,default_window_before_selection:oldSelection,
  movement_version:'movement-feedback-1',source_version:draft.initial.version,window_version:'1.5.0',faults,
  scope:'Real UI->Native configuration tools->actual AFSIM22; unchanged explicit priors, not historical calibration'});
 console.log('REAL_NATIVE_MOTION_BUILD_COMPLETE',snap.session_id);
}catch(e){clearInterval(timer);save('builder-failure.json',{passed:false,error:String(e),faults});await page.screenshot({path:root+'/builder-failure.png'}).catch(()=>{});console.log('FAILED',String(e));process.exitCode=1;}
finally{clearInterval(timer);await browser.close();}
