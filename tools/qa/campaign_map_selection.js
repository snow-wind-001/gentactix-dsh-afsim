// UI regression. Supply page.__historicalMapFixture from a retained, successful
// Native build; replaying that response tests editing, not another model run.
async page => {
 const fixture=page.__historicalMapFixture;
 if(!fixture?.parameters?.campaign_plan)throw Error('A retained bilateral campaign draft is required');
 await page.route('**/api/historical-scenarios/build',r=>r.fulfill({json:fixture}));
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19125'});
 await page.setViewportSize({width:1440,height:1000});
 await page.goto('http://127.0.0.1:19089');
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('万家岭');
 await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-executor').selectOption('afsim');
 await page.locator('#draft-step').selectOption('1小时');
 await page.getByLabel('编制范围',{exact:true}).selectOption('campaign');
 const picker=page.getByLabel('会战窗口',{exact:true});
 await picker.locator('option[value="WJL-oct6-10@1.2.0"]').waitFor({state:'attached'});
 await picker.selectOption('WJL-oct6-10@1.2.0');
 await page.getByTestId('generate-historical-scenario').click();
 const node=fixture.parameters.campaign_plan.nodes.find(n=>n.condition.region);
 const details=page.locator(`[data-goal-input="${node.id}"]`);
 await details.locator('summary').click();
 const lat=page.getByLabel(`${node.label}纬度`,{exact:true});
 const before=await lat.inputValue();
 await details.getByRole('button',{name:'地图设置'+node.label,exact:true}).click();
 if(!await page.locator('.launch-map .command-picking').count())
  throw Error('Target region selection did not enable map clicks');
 const prompt=page.locator('.draft-map-prompt');
 if(!(await prompt.innerText()).includes(node.label))throw Error('Map prompt lost the selected target label');
 const bounds=await page.locator('.launch-map .leaflet-container').boundingBox();
 await page.mouse.click(bounds.x+bounds.width*.54,bounds.y+bounds.height*.44);
 await lat.waitFor({state:'visible'});
 if(await lat.inputValue()===before)throw Error('Physical map click did not update the selected target');
 if(await page.locator('.launch-map .command-picking').count())throw Error('Map picking remained active after placement');
 if(!(await page.getByTestId('historical-validation').innerText()).includes('需要重新验证'))
  throw Error('Editing a target did not invalidate the previous validation');
 await details.getByRole('button',{name:'地图设置'+node.label,exact:true}).click();
 await page.getByRole('button',{name:'返回配置',exact:true}).click();
 if(await page.locator('.launch-map .command-picking').count())throw Error('Returning to configuration did not cancel map picking');
 await page.unroute('**/api/historical-scenarios/build');
 return {passed:true,source:'replayed successful Native draft; physical browser clicks',goal:node.id,originalLatitude:before,editedLatitude:await lat.inputValue()};
}
