/** Owned Chromium, normal rendered UI and real Native builder. No fixtures/routes. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));
const {chromium}=require('playwright-core');
const root='.cache/qa/wjl22-continuous-2026-11-02';
const mode=process.argv[3]??'build';
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const faults=[];
page.on('crash',()=>{faults.push('page_crash');console.log('PAGE_CRASH');});
page.on('pageerror',e=>{faults.push(String(e));console.log('PAGE_ERROR',String(e).slice(0,300));});
await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19217'});
const save=(name,value)=>{
 const path=root+'/'+name;if(fs.existsSync(path))throw Error('Preserve evidence '+path);
 fs.mkdirSync(path.slice(0,path.lastIndexOf('/')),{recursive:true});
 fs.writeFileSync(path,JSON.stringify(value,null,2));
};
try{
 if(mode==='build'){
  await page.goto('http://127.0.0.1:19218');
  await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('万家岭');
  await page.locator('.battle-option').first().click();
  await page.getByRole('button',{name:/继续配置/}).click();
  await page.locator('#draft-mode').selectOption('historical');
  await page.locator('#draft-executor').selectOption('afsim');
  await page.locator('#draft-step').selectOption('1小时');
  await page.getByLabel('编制范围',{exact:true}).selectOption('campaign');
  const picker=page.getByLabel('会战窗口',{exact:true});
  await picker.locator('option[value="WJL-oct6-10@1.4.0"]').waitFor({state:'attached'});
  await picker.selectOption('WJL-oct6-10@1.4.0');
  const evidence=page.getByTestId('campaign-window-evidence');await evidence.locator('summary').click();
  if(await page.locator('[data-estimate-actor]').count()!==22)throw Error('Expected22 prior actors');
  await page.screenshot({path:root+'/builder-22-priors.png'});
  await evidence.locator('summary').click();
  const lifecycle=JSON.parse(fs.readFileSync(root+'/lifecycle.json','utf8'));
  const instruction='本次完整22单位开放会战功能验收，数值和位置是公开1.4.0窗口中的显式计算先验，不是历史标定。'
   +'先读skill、公共/单位片工具观察，保留39身份处理、22候选及双边六目标的身份、依赖、承担者。'
   +'只增补连续阶段配置campaign_lifecycle，不改其他已有效数值、clock、目标或时间保障。'
   +'公共片patch必须加入如下campaign_lifecycle并更新assumptions说明为估计阶段、不自动复制史实结果；'
   +'阶段来源只作为参照，蓝方仍可提前完成合法目标。公共片不要重写整个配置：'+JSON.stringify(lifecycle)
   +'。单位片patch覆盖本片全部actor ID，各自仅更新assumption（原数值保留）并取得有效update回执。'
   +'历史缺载人数、装备、到场、位置及库存仍为估计；2700补充基数不能替换宇贺支队2900先验，不把接敌人数或马匹当伤亡、车辆。'
   +'保持1小时、按目标结束，不作分队扩编，不投未核余部，不强制未来史实命令。末片必须真实全量validate有效后结束。';
  await page.getByRole('textbox',{name:'计算参数与推演目标需求',exact:true}).fill(instruction);
  const built=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/build')&&r.request().method()==='POST',{timeout:850000});
  await page.getByTestId('generate-historical-scenario').click();
  console.log('REAL_NATIVE_BUILD_STARTED');
  const response=await built;const draft=await response.json();save('build-response.json',{http:response.status(),body:draft});
  if(!response.ok())throw Error('Native build failed: '+JSON.stringify(draft).slice(0,800));
  if(draft.construction.source!=='dsh_native_skill')throw Error('Native construction source absent');
  console.log('REAL_NATIVE_BUILD_COMPLETE',draft.id);
  const created=page.waitForResponse(r=>/\/api\/sessions$/.test(r.url())&&r.request().method()==='POST',{timeout:120000});
  const initialized=page.waitForResponse(r=>r.url().endsWith('/init')&&r.request().method()==='POST',{timeout:180000});
  await page.getByTestId('launch-start').click();
  const cr=await created;const ir=await initialized;const snap=await ir.json();
  save('creation.json',{http:cr.status(),body:await cr.json()});save('initial.json',{http:ir.status(),body:snap});
  if(!cr.ok()||!ir.ok())throw Error('Normal create/init failed');
  await page.getByTestId('map-workbench').waitFor({timeout:60000});
  const world=snap.war_state,units=[...world.red_units,...world.blue_units];
  if(units.length!==22||await page.locator('.nato-marker').count()!==22||world.afsim.entity_count!==22)throw Error('22 actor/marker/entity mismatch');
  if(world.mission.definition.campaign_lifecycle?.phases.length!==4)throw Error('Lifecycle was not actually built');
  await page.screenshot({path:root+'/initial-1440.png'});
  save('builder-result.json',{passed:true,session_id:snap.session_id,actors:22,markers:22,lifecycle_phases:4,faults,scope:'Real UI->DSH Native staged configuration->AFSIM22; numerical priors, not historical calibration'});
 }else if(mode==='advance'){
  const sid=process.argv[4],turn=Number(process.argv[5]);
  const base='http://127.0.0.1:19217/api/sessions/'+sid;
  await page.addInitScript(id=>localStorage.setItem('gentactix-session',id),sid);
  await page.goto('http://127.0.0.1:19218');
  await page.getByRole('tab',{name:/已保存战局/}).click();
  await page.locator('[data-session-id="'+sid+'"] .open-battle').click();
  await page.getByTestId('map-workbench').waitFor({timeout:60000});
  const before=await(await page.request.get(base)).json();
  if(before.turn_count!==turn-1)throw Error('Wrong retained turn');
  const started=Date.now();
  const advanced=page.waitForResponse(r=>r.url()===base+'/next'&&r.request().method()==='POST',{timeout:3600000});
  await page.getByRole('button',{name:'推进一轮',exact:true}).click();
  console.log('FRONTEND_ADVANCE_STARTED',sid,turn);
  const response=await advanced,snap=await response.json();
  save(sid+'/turn-'+turn+'-response.json',{http:response.status(),seconds:(Date.now()-started)/1000,body:snap});
  if(!response.ok())throw Error(JSON.stringify(snap).slice(0,1200));
  if(snap.turn_count!==turn)throw Error('Advance response did not commit');
  await page.screenshot({path:root+'/'+sid+'/turn-'+turn+'-1440.png'});
  save(sid+'/browser-'+turn+'.json',{passed:true,session_id:sid,turn,markers:await page.locator('.nato-marker').count(),faults,seconds:(Date.now()-started)/1000});
  console.log('FRONTEND_ADVANCE_COMPLETE',sid,turn);
 }else throw Error('Unknown browser phase');
}catch(e){
 console.log('FAILED',String(e));
 await page.screenshot({path:root+'/failure-'+mode+'-'+Date.now()+'.png'}).catch(()=>{});
 process.exitCode=1;
}
finally{await browser.close();}
