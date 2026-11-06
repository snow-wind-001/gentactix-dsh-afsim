/** Normal app, actual saved reports. No response mocks or game writes. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require = createRequire(fs.realpathSync(process.argv[2]));
const {chromium} = require('playwright-core');
const root = '.cache/qa/report-supported-claims-2026-11-02';
const api = 'http://127.0.0.1:19136/api';
const browser = await chromium.launch({channel:'chrome',headless:true});
const page = await browser.newPage();
const checks = [], errors = [], writes = [];
const check = (value,label) => {if(!value)throw Error(label);checks.push(label);};
const get = async path => {const r=await fetch(api+path);if(!r.ok)throw Error(await r.text());return r.json();};
page.on('pageerror', e=>errors.push(String(e)));
page.on('request', r=>{if(r.url().startsWith(api)&&r.method()!=='GET')writes.push({url:r.url(),method:r.method()});});
try {
  await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19136'});
  for(const engine of ['afsim','narrative']) for(const width of [1440,900]) {
    const evidence=engine==='narrative'&&process.argv[3]?`${root}/${process.argv[3]}`:root;
    const result=JSON.parse(fs.readFileSync(`${evidence}/${engine}/result.json`));
    check(result.passed,`${engine} actual combat test passed before browser`);
    const sid=result.session_id, before=await get('/sessions/'+sid);
    await page.setViewportSize({width,height:1000});
    await page.goto('http://127.0.0.1:19089/');
    await page.getByRole('tab',{name:/已保存战局/}).click();
    await page.locator(`[data-session-id="${sid}"] .open-battle`).click();
    await page.getByTestId('map-unit-locator').waitFor();
    check(await page.locator('.nato-marker').count()===6,`${engine}/${width} all6unit markers`);
    await page.getByTestId('analysis-tab-reports').click();
    const article=page.locator('.reports .report').first();await article.waitFor();
    const report=await article.innerText();
    check(report.includes('随队库存（模型工作量）'),`${engine}/${width} inventory balance visible`);
    check(report.includes('第159师')&&report.includes('日军第106师团')&&report.includes('弹药0'),`${engine}/${width} exact named zero stocks`);
    check(report.includes('DSH过程估计，非AFSIM遥测')===(engine==='narrative'),`${engine}/${width} estimate provenance correct`);
    if(engine==='narrative')check(/末发\d+秒/.test(report),`${engine}/${width} shot offset visible`);
    const drawer=await page.getByTestId('analysis-panel').boundingBox();
    check(drawer&&drawer.x>=0&&drawer.x+drawer.width<=width+1,`${engine}/${width} report drawer within viewport`);
    await page.screenshot({path:`${root}/report-${engine}-${width}.png`});
    await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
    await page.getByTestId('map-unit-locator').waitFor();
    const after=await get('/sessions/'+sid);
    check(JSON.stringify(before.war_state)===JSON.stringify(after.war_state),`${engine}/${width} refresh preserves entire world`);
    check(JSON.stringify(before.history)===JSON.stringify(after.history),`${engine}/${width} immutable report history`);
  }
  check(!errors.length,'no application exceptions');check(!writes.length,'no API writes');
  fs.writeFileSync(root+'/browser-review.json',JSON.stringify({passed:true,checks,count:checks.length,errors,writes,
    scope:'Actual two-backend combat reports and existing normal app1440/900; no frontend code changes, not full-history acceptance'},null,2));
  console.log('PASS',checks.length,'actual normal app report checks');
} catch(error) {
  fs.writeFileSync(root+'/browser-failure.json',JSON.stringify({error:String(error),checks,errors,writes},null,2));
  await page.screenshot({path:root+'/browser-failure.png'});throw error;
} finally {await browser.close();}
