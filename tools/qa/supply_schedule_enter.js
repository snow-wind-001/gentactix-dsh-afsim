async page => {
 const generated=page.__scheduleBuild;
 if(generated?.http!==200||generated.body.construction.source!=='dsh_native_skill')throw Error('Need completed actual native generation');
 const root='.cache/qa/supply-schedule-2026-11-01/browser';
 const editor=page.getByTestId('supply-schedule-editor');await editor.locator('summary').click();
 if(!await page.getByLabel('按固定时点配送补给',{exact:true}).isChecked())throw Error('Generated timing configuration missing');
 // Exact inputs are set through typed editor fields, not inferred from prose.
 const fields=[['补给周期（秒）','1800'],['普通保障上限（工作量/小时）','4'],['主动补给上限（工作量/小时）','16'],
  ['运输周转速度（公里/小时）','15'],['每次装卸周转时间（小时）','0.25'],['red-historical-supply装卸能力','100'],['blue-historical-supply装卸能力','100']];
 for(const [name,value] of fields)await page.getByLabel(name,{exact:true}).fill(value);
 const revalidate=page.getByTestId('validate-historical-scenario');
 if(!await revalidate.isEnabled())throw Error('Editing did not invalidate verification');
 const response=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/validate')&&r.request().method()==='POST',{timeout:120000});
 await revalidate.click();const checked=await response;const revised=await checked.json();page.__scheduleValidated=revised;
 if(!checked.ok()||revised.parameters.supply_schedule.period_seconds!==1800)throw Error('Typed schedule changes were not accepted');
 if(!await page.getByTestId('launch-start').isEnabled())throw Error('Validated inputs cannot launch');
 const init=page.waitForResponse(r=>r.url().endsWith('/init')&&r.request().method()==='POST',{timeout:120000});
 await page.getByTestId('launch-start').click();const initialized=await init;if(!initialized.ok())throw Error('Initialization failed');
 const snap=await initialized.json();page.__scheduleSnap=snap;
 await page.getByTestId('map-workbench').waitFor({timeout:60000});
 if(await page.locator('.nato-marker').count()!==3)throw Error('Missing historical identities on map');
 if(snap.war_state.mission.definition.supply_schedule.period_seconds!==1800||snap.war_state.mission.turn!==0)throw Error('Wrong configuration or initialization advanced time');
 await page.screenshot({path:root+'/initial.png'});
 return {passed:true,session_id:snap.session_id,units:3,actual_model_generation:true,typed_edit_revalidated:true,
  actual_afsim_load:true,init_turn:0,scope:'Generated estimates manually reviewed/edited; not exact NLP parameter copying or historical calibration'};
}
