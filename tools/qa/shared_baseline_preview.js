async page=>{
 const checks=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 await page.waitForFunction(()=>document.querySelector('[data-testid=historical-validation]')?.textContent?.includes('AFSIM实际装载'),{},{timeout:360000});
 const copying=page.waitForResponse(r=>r.url().endsWith('/api/scenarios/from-historical'));
 await page.locator('#draft-mode').selectOption('synthetic');const response=await copying,copy=await response.json();check(response.status()===200,'fresh current bundle derives the real source draft');
 await page.waitForFunction(()=>document.querySelector('[data-testid=scenario-validation]')?.textContent?.includes('AFSIM已装载'));
 await page.getByTestId('synthetic-blue').getByRole('button',{name:'添加编组',exact:true}).click();
 await page.getByRole('button',{name:'返回配置',exact:true}).click();
 const added=page.getByTestId('synthetic-blue').locator('details.formation').nth(1);if(!await added.evaluate(e=>e.open))await added.locator('summary').click();
 const name=await page.getByLabel('blue-1-名称',{exact:true}).inputValue();
 await page.waitForFunction(()=>document.querySelectorAll('.nato-marker').length===3);
 const marker=page.locator('.nato-marker').filter({has:page.locator('svg')});
 const before=await page.getByLabel('蓝方 '+name,{exact:true}).innerHTML();
 await page.getByLabel('blue-1-装甲车辆',{exact:true}).fill('4');await page.getByLabel('blue-1-燃油（升）',{exact:true}).fill('2000');
 await page.waitForFunction(({name,before})=>document.querySelector('[aria-label="蓝方 '+name+'"]')?.innerHTML!==before,{name,before});
 check(await page.getByLabel('蓝方 '+name,{exact:true}).innerHTML()!==before,'draft military glyph changes when the added infantry formation receives armor');
 check(!(await page.getByTestId('scenario-validation').innerText()).includes('已装载核验'),'equipment edits require revalidation');
 const validating=page.waitForResponse(r=>r.url().endsWith('/api/scenarios/validate'));
 await page.getByTestId('validate-scenario').click();const validated=await validating,draft=await validated.json();
 check(validated.status()===200&&draft.preview_world.blue_units[1].type==='装甲兵'&&draft.preview_world.blue_units[1].formation.motorized,'native configuration agrees with the draft armor glyph and fuel mode');
 check(draft.afsim.entity_count===3&&await marker.count()===3,'all derived actors remain visible');
 await page.getByTestId('synthetic-setup').scrollIntoViewIfNeeded();await page.screenshot({path:'.cache/qa/shared-baseline/preview-current.png'});
 return {passed:true,checks,base_draft_id:draft.construction.base_draft_id??copy.draft.construction.base_draft_id,draft_id:draft.id,route_mocks:false};
}
