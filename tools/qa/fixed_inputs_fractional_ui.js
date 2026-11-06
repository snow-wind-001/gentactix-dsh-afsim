async page => {
 const generated=page.__campaignFixed;if(generated?.http!==200)throw Error('Retained actual campaign result required');
 page.removeAllListeners('response');
 await page.route('**/api/historical-scenarios/build',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(generated.body)}));
 await page.goto('http://127.0.0.1:19089/');
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('万家岭');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();await page.locator('#draft-mode').selectOption('historical');
 await page.locator('#draft-executor').selectOption('afsim');await page.locator('#draft-step').selectOption('1小时');
 await page.getByLabel('编制范围',{exact:true}).selectOption('campaign');
 const picker=page.getByLabel('会战窗口',{exact:true});await picker.locator('option[value="WJL-oct6-10@1.3.0"]').waitFor({state:'attached'});await picker.selectOption('WJL-oct6-10@1.3.0');
 await page.getByTestId('campaign-window-scope').waitFor();await page.getByTestId('generate-historical-scenario').click();
 const editor=page.getByTestId('fixed-parameter-inputs');await editor.locator('summary').click();
 await page.getByLabel('固定参数配置对象',{exact:true}).selectOption('作战规则');
 await page.getByLabel('固定参数数值项目',{exact:true}).selectOption(JSON.stringify(['rules','cargo_mass_tons','fuel_liters']));
 if(await page.getByLabel('固定参数指定数值',{exact:true}).getAttribute('step')!=='any')throw Error('Continuous weight mislabeled as integer stock count');
 await page.getByLabel('固定参数指定数值',{exact:true}).fill('0.0012');
 if(!await page.getByTestId('add-fixed-parameter').isEnabled())throw Error('Valid fractional mass blocked');
 const url='http://127.0.0.1:19131/api/sessions/a11f180342cf';const before=await (await page.request.get(url)).json();
 await page.getByTestId('add-fixed-parameter').click();
 const checked=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/validate')&&r.request().method()==='POST',{timeout:120000});
 await page.getByTestId('validate-historical-scenario').click();const response=await checked;const draft=await response.json();
 if(!response.ok()||draft.parameters.rules.cargo_mass_tons.fuel_liters!==.0012)throw Error('Fractional input did not pass actual validation');
 if(draft.construction.fixed_parameters.values.length!==23||draft.afsim.entity_count!==22)throw Error('Wrong numerical contract/entity count');
 const after=await (await page.request.get(url)).json();if(JSON.stringify(before.war_state)!==JSON.stringify(after.war_state))throw Error('Draft edit altered live QA world');
 await page.screenshot({path:'.cache/qa/fixed-parameters-2026-11-01/browser/fractional-mass-final.png'});
 await page.unroute('**/api/historical-scenarios/build');await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 await page.getByTestId('map-workbench').waitFor();
 page.__fractionalReview={passed:true,generation_replayed:true,new_model_generation:false,actual_afsim_validation:true,
  actors:22,fixed_fields:23,fractional_value:.0012,canonical_live_world_unchanged:true,draft_id:draft.id};
 return page.__fractionalReview;
}
