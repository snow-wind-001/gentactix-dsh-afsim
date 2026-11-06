/** Real from-zero Native configuration through normal launch controls. */
import fs from 'node:fs';import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json'),{chromium}=require('playwright-core');
const base=process.argv[2]??'.cache/qa/transfer-generation-2026-11-03';
const root=base+'/browser';if(fs.existsSync(root))throw Error('Preserve previous evidence');fs.mkdirSync(root,{recursive:true});
const api=process.argv[3]??'http://127.0.0.1:19338',ui=process.argv[4]??'http://127.0.0.1:19329';
const rationModel=process.argv[5]??'time-sustainment-1';
const scenarioCase=process.argv[6]?JSON.parse(fs.readFileSync(process.argv[6])):{};
if(!['time-sustainment-1','personnel-rations-1'].includes(rationModel))throw Error('Unknown ration model');
const personnelRations=rationModel==='personnel-rations-1',step=scenarioCase.time_step??(personnelRations?'6小时':'30分钟'),stepSeconds=scenarioCase.step_seconds??(personnelRations?21600:1800);
const actorCount=scenarioCase.actor_count??4;
const teamCounts=scenarioCase.team_counts??{red:actorCount,blue:0};
if(teamCounts.red+teamCounts.blue!==actorCount)throw Error('Team counts must match the whole requested roster');
const checks=[],errors=[],posts=[];
const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}});
function check(v,m){if(!v)throw Error(m);checks.push(m);}
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'){const path=new URL(r.url()).pathname;posts.push(path);if(path.endsWith('/historical-scenarios/build'))fs.writeFileSync(root+'/build-request.json',r.postData()??'');}});
await page.addInitScript(api=>window.gentactix={backendUrl:api},api);
try{
 await page.goto(ui,{waitUntil:'domcontentloaded'});await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill(scenarioCase.battle_query??'雪山草地');
 await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-executor').selectOption('narrative');
 await page.locator('#draft-step').selectOption(step);await page.getByLabel('编制范围',{exact:true}).selectOption('campaign');
 await page.getByLabel('会战窗口',{exact:true}).selectOption(scenarioCase.window??'LM06-right-column-aug21-27@1.0.0');
 await page.getByTestId('campaign-window-scope').waitFor();
 await page.getByLabel('生成时必须按时间计算粮秣',{exact:true}).check();await page.getByLabel('生成时必须校验运动与疲劳反馈',{exact:true}).check();
 if(personnelRations)await page.getByLabel('生成时采用的耗粮模型',{exact:true}).selectOption(rationModel);
 if(scenarioCase.fixed_parameters?.length){
  await page.getByTestId('fixed-parameter-inputs').locator('summary').click();
  for(const field of scenarioCase.fixed_parameters){
   await page.getByLabel('固定参数配置对象',{exact:true}).selectOption(field.group);
   await page.getByLabel('固定参数数值项目',{exact:true}).selectOption(JSON.stringify(field.path));
   await page.getByLabel('固定参数指定数值',{exact:true}).fill(String(field.value));
   await page.getByTestId('add-fixed-parameter').click();
  }
 }
 const defaultInstruction='从宿主未填写的模板生成本次新配置，不复用已有对局或QA夹具。当前是1935年右路军四军转移窗口，只有红方4个军计算身份；两个方面军和右路军指挥参考不生成步兵。按窗口绑定史料1.1.0与1935-08-21起点；保留全部4个军、6个目标及目标依赖。公开史料未载逐军人数装备部署，因此你给出的每项数值都必须标为探索性估计，不得将会师总人数平均摊给各军。按军级独立估计人数，可将每军4000—12000人作为本次探索范围，这不是史料区间；逐军说明假设，不能称满编。formation.role均为infantry，type步兵，motorized=false，步行速度和地形修正合理，不虚构装甲、航空、汽车或真实武器型号；分类运输装备不明确时可零投入，工兵作业组可独立估计并说明不是实测装备数。'
 +'空间只围绕毛儿盖—草地—巴西的来源方向，坐标是显式估计而非历史精确阵位；所有单位初始位置和各自到达地域都在来源160km地域范围内。到达目标与对应初始部署要有实际行军距离，不能直接放在目标圈内。不要强制8月27日自动到达，也不靠日期结束，选择目标完成制；各军到达、保存比例及随队资源共同约束。允许设置不同到达地域与最少人数；不得删除节点、改承担身份或依赖。填写所有全局目标数值再提交公共片，不能把null留到只读final。'
 +(personnelRations
 ? '必须从零生成personnel-rations-1与movement-feedback-1，不能改用旧time-sustainment-1。按skill严格schema：ration_kg_per_person_day=0.75、food_kg_per_work=125、carried_kg_per_committed_person=0.5，都是本次软件QA估计，不是历史口粮或生理标准；其余疲劳和缺粮阈值也标明估计。supply_distribution使用split-stocks-1、food_mass_share=0.5，rules.ton_per_supply_unit=0.25吨，保证0.25*1000*0.5=125kg/粮食工作量。按每军自己估计的人员和资源份额换算实际携行容量及需求，不把各军都装到100工作量；逐军初始正库存只够约0.3kg/人的估计干粮，不超0.5kg/人名义容量。库存仍仅用food/ammo工作量，不另存food_kg权威字段。support.red和support.blue库存全部0，无运输车辆就不编造后续送粮。按六小时步长设置deadline_turn=28仅作七日滚动需求参考；必须说明初始口粮不能独立支撑七日行军、需要后续来源或会受到缺粮约束，不能因仓库未知就凭空补满。不得强制历史减员。'
 : '必须使用time-sustainment-1与movement-feedback-1，使用小时耗粮和缺粮约束，粮食工作量不是按人数或重量标定的口粮。为7日左右转移计算提供可持续的初始粮食及明确的可能后勤边界，不编造历史固定补给站；没有运输装备或史实补给来源时可把节点库存设0，但需解释续航极限和无法持续接济。')
 +'红方food/ammo均为工作量，取值0至100；蓝方无人，support.blue所有库存必须0，不生成虚构仓库。不得为凑历史减员强行扣人。兼容goal.profile=breakout，team=red，required_survivors须在1至4且与rules一致，required_turns=2，deadline_turn只作规划参考。campaign.arrivals逐个估计not_before并注明不等于史实实到；campaign.objective.relief_regions=[]，surrender.enabled=false。facility只是无功能计算汇总点，progress/integrity/capacity/used均设0，bridge_enabled=false，无舟艇或桥梁，不声称施工。使用模板完整rules及已注册模型，不自建裁决器。只通过现有四个原生工具逐片保存并取得最终校验，结束回复只写工具回执和估计限制，不输出整场JSON。';
 const instruction=scenarioCase.instruction??defaultInstruction;
 await page.getByRole('textbox',{name:'计算参数与推演目标需求',exact:true}).fill(instruction);
 await page.screenshot({path:root+'/before-generation-1440.png'});
 check(posts.length===0,'no world or prefilled configuration created before model call');
 const responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/build')&&r.request().method()==='POST',{timeout:0});
 await page.getByTestId('generate-historical-scenario').click();console.log('REAL_FROM_ZERO_STARTED');
 const response=await responsePromise;const text=await response.text();fs.writeFileSync(root+'/build-response.txt',text);
 check(response.ok(),'real Native staged generation succeeds: HTTP '+response.status());
 const draft=JSON.parse(text);fs.writeFileSync(root+'/draft-id.json',JSON.stringify({id:draft.id,api,ui,execution_backend:'narrative'},null,2));
 check(draft.construction.source==='dsh_native_skill'&&draft.construction.workflow==='native_agent_registry_scoped_drafts','real Native staged construction provenance');
 check(draft.afsim===null&&draft.validation.scope==='configuration_contract_only','narrative configuration does not claim AFSIM load');
 check(['red','blue'].every(team=>draft.preview_world[team+'_units'].length===teamCounts[team]),`generated initial retains ${actorCount} actual formation identities across both requested teams`);
 check(draft.parameters.support_dynamics?.version===rationModel&&draft.parameters.movement_feedback?.version==='movement-feedback-1','requested temporal and movement models retained');
 if(personnelRations){
  const d=draft.parameters.support_dynamics;
  check(d.ration_kg_per_person_day===0.75&&d.food_kg_per_work===125&&d.carried_kg_per_committed_person===0.5,'generated explicit mass/person QA parameters');
  check(draft.construction.required_models.includes(rationModel)&&!draft.construction.required_models.includes('time-sustainment-1'),'saved requirements use requested personnel model');
  check(['red','blue'].filter(team=>teamCounts[team]>0).every(team=>draft.sustainment.teams[team].on_hand_food_kg>0&&draft.sustainment.teams[team].minimum_hold_food_kg>draft.sustainment.teams[team].on_hand_food_kg),'real generated budget exposes the configured planning-period shortage for each populated team instead of inventing supplies');
  fs.writeFileSync(root+'/draft.json',JSON.stringify(draft));
 }
 await page.getByTestId('historical-validation').waitFor();await page.screenshot({path:root+'/generated-1440.png'});
 const initPromise=page.waitForResponse(r=>r.url().endsWith('/init')&&r.request().method()==='POST',{timeout:0});
 await page.getByTestId('launch-start').click();const initialized=await initPromise;check(initialized.ok(),'generated draft initializes normally');
 const snapshot=await initialized.json();fs.writeFileSync(root+'/session-id.json',JSON.stringify({session_id:snapshot.session_id,api,ui,turn:0,actor_count:actorCount,step_seconds:stepSeconds},null,2));
 await page.getByTestId('map-workbench').waitFor();await page.screenshot({path:root+'/initialized-1440.png'});await page.setViewportSize({width:900,height:1000});await page.screenshot({path:root+'/initialized-900.png'});
 check(snapshot.turn_count===0&&snapshot.war_state.simulation_clock.elapsed_seconds===0,'generation and initialization execute no physical battle turn');
 if(personnelRations)check(['red','blue'].every(team=>snapshot.war_state[team+'_units'].every(u=>u.sustainment.version===rationModel)),'all initialized units on both teams retain newly generated personnel model');
 check(errors.length===0,'no application exceptions');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,checks,count:checks.length,errors,posts,source:'real model generation from unfilled globals and actors',scope:`Estimated ${actorCount}-formation configuration and ordinary initialization; not historical calibration or effect execution.`},null,2));console.log('PASS',checks.length,'real generation checks');
}catch(error){fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,errors,posts},null,2));await page.screenshot({path:root+'/failure.png'}).catch(()=>{});throw error;}
finally{await browser.close();}
