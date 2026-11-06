async page => {
 const build=page.__fixedBuild;if(build.status!=='finished'||build.http!==200)throw Error('Actual generation not finished');
 const checks=[];const check=(v,label)=>{if(!v)throw Error(label);checks.push(label);};
 const root='.cache/qa/fixed-parameters-2026-11-01/browser';
 const editor=page.getByTestId('fixed-parameter-inputs');
 const path=['actors','ww2.cn.division31','personnel'];
 const row=editor.locator('li').filter({has:page.locator('input[aria-label="红方 · 第31师 · 人员数量固定值"]')});
 const personnel=page.getByLabel('第31师人员',{exact:true});
 check(await personnel.inputValue()==='6000','generated-unit-preserves-fixed-personnel');
 await personnel.fill('5000');
 check(await row.getByText('下方编辑值与固定值不同；请修改或移除固定值后重验。',{exact:false}).isVisible(),'manual-conflict-visible');
 const invalidWait=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/validate')&&r.request().method()==='POST');
 await page.getByTestId('validate-historical-scenario').click();const invalid=await invalidWait;const failed=await invalid.json();
 check(invalid.status()===422&&String(failed.detail).includes('已固定参数冲突'),'manual-conflict-rejected-by-host');
 await row.getByRole('button',{name:'应用此固定值',exact:true}).click();
 check(await personnel.inputValue()==='6000','explicit-apply-restores-fixed-value');
 page.__fixedCurrent=build.body;
 const validate=async()=>{
  const button=page.getByTestId('validate-historical-scenario');
  if(await button.isDisabled()){
   check((await page.getByTestId('historical-validation').innerText()).includes('已通过'),'exact-restoration-reuses-existing-validation');
   return page.__fixedCurrent;
  }
  const response=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/validate')&&r.request().method()==='POST',{timeout:120000});
  await button.click();const r=await response;const b=await r.json();if(!r.ok())throw Error('Real revalidation failed '+r.status());page.__fixedCurrent=b;return b;
 };
 const restored=await validate();check(restored.construction.fixed_parameters.values.length===23,'restored-contract-revalidated');
 await row.getByRole('button',{name:'移除红方 · 第31师 · 人员数量',exact:true}).click();
 await personnel.fill('5000');const unlocked=await validate();
 check(unlocked.parameters.actors['ww2.cn.division31'].personnel===5000,'explicit-unlock-allows-manual-change');
 check(unlocked.construction.fixed_parameters.values.length===22&&unlocked.construction.manual_revision===true,'manual-provenance-and-current-locks');
 const field=build.request.fixed_parameters.find(r=>JSON.stringify(r.path)===JSON.stringify(path));
 await page.getByLabel('固定参数配置对象',{exact:true}).selectOption('红方 · 第31师');
 await page.getByLabel('固定参数数值项目',{exact:true}).selectOption(JSON.stringify(path));
 await page.getByLabel('固定参数指定数值',{exact:true}).fill(String(field.value));await page.getByTestId('add-fixed-parameter').click();
 check(await personnel.inputValue()==='6000','adding-lock-applies-explicit-user-input');
 const final=await validate();page.__fixedValidated=final;
 check(final.construction.fixed_parameters.values.length===23&&final.parameters.actors['ww2.cn.division31'].personnel===6000,'fixed-values-survive-revalidation');
 await row.scrollIntoViewIfNeeded();await page.screenshot({path:root+'/fixed-final-wide.png'});
 await page.setViewportSize({width:900,height:900});await row.scrollIntoViewIfNeeded();
 const bounds=await row.locator('input').boundingBox();check(!!bounds&&bounds.x>=0&&bounds.x+bounds.width<=900,'900px-fixed-field-inside-viewport');
 await page.screenshot({path:root+'/fixed-final-900.png'});await page.setViewportSize({width:1440,height:1000});
 const init=page.waitForResponse(r=>r.url().endsWith('/init')&&r.request().method()==='POST',{timeout:120000});
 await page.getByTestId('launch-start').click();const initialized=await init;const snapshot=await initialized.json();page.__fixedSnapshot=snapshot;
 check(initialized.ok()&&snapshot.turn_count===0,'actual-initialization-turn-zero');
 await page.getByTestId('map-workbench').waitFor({timeout:60000});
 check(await page.locator('.nato-marker').count()===3,'three-historical-unit-map-markers');
 await page.screenshot({path:root+'/fixed-initial-map.png'});
 page.__fixedEditReview={passed:true,checks,manual_revalidation_real_afsim:true,session_id:snapshot.session_id,
  generated_draft_id:build.body.id,unlocked_draft_id:unlocked.id,final_draft_id:final.id,fixed_fields:23};
 return page.__fixedEditReview;
}
