async page => {
  if (await page.locator('.nato-marker').count() !== 22) throw Error('Expected real22unit QA map');
  const collapse=page.getByRole('button',{name:'收起指挥面板',exact:true});
  if(await collapse.isVisible())await collapse.click();
  const candidates = await page.locator('.nato-marker').evaluateAll(nodes => nodes.map(node => {
    const r=node.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;
    const hit=document.elementFromPoint(x,y)?.closest('.nato-marker');
    return {x,y,name:node.getAttribute('aria-label'),visible:hit===node};
  }).filter(p=>p.visible));
  let found=null;
  for (const p of candidates) {
    await page.mouse.click(p.x,p.y);
    const buttons=page.locator('.leaflet-popup-content button');
    if(await buttons.count()>1){found={clicked:p.name,choices:await buttons.allTextContents()};break;}
    const close=page.getByRole('button',{name:'收起指挥面板',exact:true});
    if(await close.isVisible())await close.click();
  }
  if(!found)throw Error('No existing nearby-unit picker reached through visible marker');
  const last=page.locator('.leaflet-popup-content button').last();
  const chosen=(await last.innerText()).replace(/^选择[红蓝]方 /,'');
  await last.click();
  const selected=page.locator('.command-panel select').first();
  if(!(await selected.locator('option:checked').innerText()).includes(chosen))throw Error('Chooser selected wrong unit');
  await page.screenshot({path:'.cache/qa/fixed-parameters-2026-11-01/browser/map-existing-picker.png'});
  await page.getByRole('button',{name:'收起指挥面板',exact:true}).click();
  return {passed:true,existing_nearby_picker:found,selected:chosen,orders_submitted:false,
    scope:'Existing24pixel nearby picker reachable for one visible cluster; not all22markers accessibility or no overlap claim'};
}
