async page=>{
 const checks=[],errors=[];const check=(v,s)=>{if(!v)throw Error(s);checks.push(s)};
 page.on('pageerror',e=>errors.push(e.message));await page.setViewportSize({width:900,height:1000});
 await page.goto('http://127.0.0.1:18995/split-editor.html');
 const editor=page.getByTestId('split-supply-editor');await editor.locator('summary').click();
 check(await page.evaluate(()=>window.qa.value===undefined),'old configuration remains absent');
 const toggle=editor.getByRole('checkbox');await toggle.check();
 check(await page.evaluate(()=>window.qa.value.version==='split-stocks-1'),'explicit enable emits split model');
 await editor.getByLabel('粮食质量份额',{exact:true}).fill('0.35');
 await editor.getByLabel('运力不足时优先配送',{exact:true}).selectOption('ammo');
 check(await page.evaluate(()=>window.qa.value.food_mass_share===.35&&window.qa.value.priority==='ammo'),'share and priority independently editable');
 check((await editor.innerText()).includes('不是历史实测')||(await editor.getByRole('textbox').inputValue()).includes('不是历史实测'),'assumptions disclosed');
 check((await editor.innerText()).includes('需重新验证'),'changes require validation');
 for(const width of [900,420]){
  await page.setViewportSize({width,height:1000});check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'fits '+width);
  await page.screenshot({path:`.cache/qa/split-supply-ui/editor-${width}.png`});
 }
 await page.evaluate(()=>window.qa.disabled=true);check(await toggle.isDisabled(),'busy toggle disabled');
 check(await editor.getByLabel('粮食质量份额',{exact:true}).isDisabled(),'busy numeric input disabled');
 check(await editor.getByLabel('运力不足时优先配送',{exact:true}).isDisabled(),'busy priority disabled');
 await page.evaluate(()=>window.qa.disabled=false);await toggle.uncheck();
 check(await page.evaluate(()=>window.qa.value===undefined),'disable restores absent field');
 check(!errors.length,'no component exceptions');return{passed:true,checks,scope:'actual Vue component, isolated props; no API mocks'};
}
