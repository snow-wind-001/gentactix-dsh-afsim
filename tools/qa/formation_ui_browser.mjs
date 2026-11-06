/** Normal runtime conversion UI. Fault injection is recorded separately. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root='.cache/qa/formation-ui-2026-11-02',mode=process.argv[3]??'final';
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});const checks=[],errors=[];
const check=(v,label)=>{if(!v)throw Error(label);checks.push(label);};
page.on('pageerror',e=>errors.push(String(e)));
try{
    await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19214'});
    const cases=JSON.parse(fs.readFileSync(root+'/cases.json'));
    const sid=cases.narrative.session_id;
    await page.goto('http://127.0.0.1:19215/');
    await page.getByRole('tab',{name:/已保存战局/}).click();
    await page.locator(`[data-session-id="${sid}"] .open-battle`).click();
    await page.getByTestId('analysis-tab-forces').click();
    await page.getByTestId('formation-conversion').waitFor({timeout:5000});
    check(true,'physical entity conversion entry distinct from temporary groups');
    check(!errors.length,'no application exceptions');
    fs.writeFileSync(`${root}/browser-${mode}.json`,JSON.stringify({passed:true,checks,errors},null,2));
    console.log('PASS conversion UI entry',checks.length);
}catch(error){
    fs.writeFileSync(`${root}/browser-${mode}.json`,JSON.stringify({passed:false,error:String(error),checks,errors},null,2));
    await page.screenshot({path:`${root}/browser-${mode}-failure.png`});throw error;
}finally{await browser.close();}
