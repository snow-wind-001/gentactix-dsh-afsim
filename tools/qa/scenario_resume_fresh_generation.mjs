/** Independent real full34generation through the current frontend, no replay. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root='.cache/qa/scenario-resume-2026-11-01',base='http://127.0.0.1:19132';
const browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
let basis=null,response=null,request=null;
page.on('response',async r=>{
 if(r.url().includes('/api/historical-scenarios/basis?')&&r.ok())basis=await r.json();
 if(r.url().endsWith('/api/historical-scenarios/build')&&r.request().method()==='POST')response={status:'finished',http:r.status(),request:r.request().postDataJSON(),body:await r.json()};
});
page.on('request',r=>{if(r.url().endsWith('/api/historical-scenarios/build')&&r.method()==='POST')request=r.postDataJSON();});
try{
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19132'});await page.goto('http://127.0.0.1:19089/');
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('冀中');await page.locator('.battle-option').filter({hasText:'冀中五一反扫荡'}).click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-executor').selectOption('afsim');await page.locator('[data-admission-choice="1.0.0:campaign"]').click();await page.getByTestId('generate-historical-scenario').waitFor();
 if(Object.keys(basis.configuration_template.actors).length!==34)throw Error('34identitybasisrequired');
 await page.locator('#draft-step').selectOption('6小时');await page.getByTestId('fixed-parameter-inputs').locator('summary').click();
 for(const [key,value] of [['committed',4],['ordnance',8],['fuel',16]]){
  const path=['aviation','ww2.jp.flight29','initial',key],field=basis.fixed_parameter_fields.find(f=>JSON.stringify(f.path)===JSON.stringify(path));
  await page.getByLabel('固定参数配置对象',{exact:true}).selectOption(field.group);await page.getByLabel('固定参数数值项目',{exact:true}).selectOption(JSON.stringify(path));await page.getByLabel('固定参数指定数值',{exact:true}).fill(String(value));await page.getByTestId('add-fixed-parameter').click();
 }
 await page.getByLabel('计算参数与推演目标需求',{exact:true}).fill('独立34身份QA完整生成，不读取或复用旧分片参数。保留全部34个不重叠地面历史番号及第29独立飞行队。缺载人数、装备、部署和到场均说明为未标定估计，不编成史实。各部队分散部署符合层级与地名参考，区分待到场与已入场。按目标完成，6小时一轮，1942年5月1日起，规划至6月21日。采用红方防御迟滞目标delay，goal和rules一致，并明确campaign.objective_policy为defensive-delay-1；按已入场编组存续、人员保持比例与出口未被突破结算，不要求反扫荡部队进攻占点。合理填写目标方存续编组门槛及连续保持回合，不将未到场部队计数。航空4架、8弹药和16燃油为QA固定数值，不是史实库存；航空可用时间start明确估计在开局之后，end可为null。按时间消耗粮秣，分队和总部来源不得虚构，未知余部保持未投入。campaign_scope.remainders若模板为空就保持空对象。严格使用可见原生函数名称，不加前缀，不用普通回复模拟调用。按工具返回revision修改并取得有效回执，最终全量核验与AFSIM装载交给宿主。');
 await page.getByTestId('generate-historical-scenario').click();
 if(!request)throw Error('Actual build request missing');fs.writeFileSync(root+'/fresh-generation-request.json',JSON.stringify(request));console.log('START',request.operation_id,flush());
 const until=Date.now()+3600000;let previous='';
 while(!response&&Date.now()<until){
  try{const r=await fetch(base+'/api/scenarios/operations/'+request.operation_id+'/progress');const d=await r.json();const p=d.progress??{};const key=JSON.stringify({active:d.active,stage:p.configuration_stage,done:p.completed_actors,phase:p.phase});if(key!==previous){console.log('PROGRESS',key);previous=key;}}catch(e){console.log('PROGRESS_UNAVAILABLE',e.name);}
  await new Promise(r=>setTimeout(r,3000));
 }
 fs.writeFileSync(root+'/fresh-generation-response.json',JSON.stringify(response));
 if(!response||response.http!==200)throw Error('Independent generation did not pass: '+JSON.stringify(response?.body?.detail));
 console.log('COMPLETE',JSON.stringify({http:response.http,actors:Object.keys(response.body.parameters.actors).length,entities:response.body.afsim.entity_count,id:response.body.id}));
 await page.screenshot({path:root+'/browser-fresh-generation.png'});
}finally{await browser.close();}
function flush(){return 'real_model; all34fromscratch; no_replay';}
