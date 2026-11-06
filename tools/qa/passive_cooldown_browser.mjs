/** Read-only normal app review of actual source/branch cooldown clocks. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root='.cache/qa/passive-cooldown-2026-11-02',mode=process.argv[3]??'final';
const out=`${root}/browser-${mode}.json`;
if(fs.existsSync(out))throw Error('Preserve prior browser evidence');
const api='http://127.0.0.1:19211/api',host=mode==='before'?'http://127.0.0.1:19212':'http://127.0.0.1:19213';
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),checks=[],errors=[],writes=[];
const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
const get=async path=>{const response=await fetch(api+path);if(!response.ok)throw Error(await response.text());return response.json();};
page.on('pageerror',error=>errors.push(String(error)));
page.on('request',r=>{if(r.url().startsWith(api)&&r.method()!=='GET')writes.push({url:r.url(),method:r.method()});});
try{
    await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19211'});
    const ids=JSON.parse(fs.readFileSync(`${root}/live-case.json`));
    const cases=mode==='before'?[['source',ids.source_session,60]]:[['source',ids.source_session,60],['branch',ids.session_id,0]];
    for(const [label,sid,expected] of cases)for(const width of (mode==='before'?[1440]:[1440,900])){
        await page.setViewportSize({width,height:1000});
        const before=await get('/sessions/'+sid),q=await get('/sessions/'+sid+'/commands');
        const unit=q.units.find(u=>u.name==='日军第106师团');
        check(unit.formation.reload_remaining_s===expected,`${label} actual API clock ${expected}s`);
        await page.goto(host);await page.getByRole('tab',{name:/已保存战局/}).click();
        await page.locator(`[data-session-id="${sid}"] .open-battle`).click();
        await page.getByTestId('map-unit-locator').waitFor();await page.getByTestId('command-toggle').click();
        await page.getByLabel('单位名单（含无坐标单位）').selectOption(unit.id);
        const text=await page.getByTestId('command-panel').innerText();
        const clock=text.match(/冷却\s+([^·\n]+)/)?.[1]?.trim();
        if(mode==='before'){
            check(clock==='60 轮','reproduced legacy field incorrectly displayed as 60 turns');
        }else{
            check(clock===`${expected} 秒`,`${label} command clock must show canonical ${expected} seconds; got ${clock}`);
        }
        const box=await page.getByTestId('command-panel').boundingBox();
        check(box&&box.x>=0&&box.x+box.width<=width+1,`${label}/${width} command panel within viewport`);
        await page.screenshot({path:`${root}/browser-${mode}-${label}-${width}.png`});
        const after=await get('/sessions/'+sid);check(JSON.stringify(before.war_state)===JSON.stringify(after.war_state),`${label} whole world unchanged`);
        check(JSON.stringify(before.history)===JSON.stringify(after.history),`${label} history unchanged`);
    }
    check(!errors.length,'no application exceptions');check(!writes.length,'no API writes');
    fs.writeFileSync(out,JSON.stringify({passed:true,mode,checks,count:checks.length,errors,writes,
        scope:'Canonical cooldown display only; not complete command-center or history acceptance'},null,2));
    console.log('PASS browser',mode,checks.length,'checks');
}catch(error){
    fs.writeFileSync(out,JSON.stringify({passed:false,mode,error:String(error),checks,errors,writes},null,2));throw error;
}finally{await browser.close();}
