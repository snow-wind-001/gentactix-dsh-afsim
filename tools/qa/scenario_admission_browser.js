async page => {
 page.removeAllListeners('request');page.removeAllListeners('response');
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19132'});
 const checks=[];const check=(v,label)=>{if(!v)throw Error(label);checks.push(label);};
 let sessions=0;page.on('request',r=>{if(r.method()==='POST'&&/\/api\/sessions(?:\/[^/]+\/init)?$/.test(r.url()))sessions++;});
 page.__admissionBases=[];
 page.on('response',async r=>{if(r.url().includes('/api/historical-scenarios/basis?')&&r.ok()){
   const body=await r.json();page.__admissionBases.push({url:r.url(),body});
 }});
 async function choose(term,label){
   await page.goto('http://127.0.0.1:19089/');
   await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill(term);
   await page.locator('.battle-option').filter({hasText:label}).click();
   await page.getByRole('button',{name:/继续配置/}).click();
   await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-executor').selectOption('afsim');
   await page.getByTestId('historical-configuration-alternatives').waitFor();
 }
 await choose('冀中','冀中五一反扫荡');
 check((await page.getByTestId('historical-configuration-gap').innerText()).includes('flight29'),'jizhong-default-keeps-unverified-phase-guard');
 check(await page.getByLabel('编制范围',{exact:true}).inputValue()==='phase','default-scope-not-silently-promoted');
 await page.locator('[data-admission-choice="1.0.0:campaign"]').click();
 await page.getByTestId('generate-historical-scenario').waitFor();
 check(await page.getByTestId('generate-historical-scenario').isEnabled(),'explicit-jizhong-campaign-is-configurable');
 check(await page.getByLabel('编制范围',{exact:true}).inputValue()==='campaign','explicit-choice-selects-campaign');
 const jz=page.__admissionBases.at(-1).body;
 check(Object.keys(jz.configuration_template.actors).length===34,'all34ground-identities-retained');
 check(jz.configuration_template.aviation['ww2.jp.flight29'].availability.start===null,'unknown-aviation-time-remains-an-unfilled-estimate');
 await choose('武汉','武汉会战');
 check(await page.getByLabel('史料档案版本',{exact:true}).inputValue()==='1.0.0','wuhan-default-version-is-preserved');
 check((await page.getByTestId('historical-configuration-gap').innerText()).includes('累计'),'wuhan-cumulative-at-opening-stays-blocked');
 const before=page.__admissionBases.length;
 await page.locator('[data-admission-choice="1.1.0:campaign"]').click();
 await page.getByTestId('generate-historical-scenario').waitFor();
 check(await page.getByLabel('史料档案版本',{exact:true}).inputValue()==='1.1.0','explicit-wuhan-version-switch');
 check(Object.keys(page.__admissionBases.at(-1).body.configuration_template.actors).length===79,'explicit-wuhan-keeps79source-identities');
 check(page.__admissionBases.length===before+1,'scope-and-version-choice-issues-one-basis-request');
 await page.setViewportSize({width:900,height:900});await page.screenshot({path:'.cache/qa/scenario-admission-2026-11-01/browser-wuhan-900.png'});
 await page.setViewportSize({width:1440,height:1000});
 await choose('冀中','冀中五一反扫荡');
 check(await page.getByLabel('编制范围',{exact:true}).inputValue()==='phase','new-selection-has-not-mutated-historical-default');
 await page.locator('[data-admission-choice="1.0.0:campaign"]').click();await page.getByTestId('generate-historical-scenario').waitFor();
 check(sessions===0,'admission-selection-never-creates-or-initializes-world');
 await page.screenshot({path:'.cache/qa/scenario-admission-2026-11-01/browser-jizhong-campaign.png'});
 page.__admissionUi={passed:true,checks,model_called:false,native_called:false,world_created:false};
 return page.__admissionUi;
}
