async page => {
  const assert=(value,text)=>{if(!value)throw new Error(text);};
  const results=[];
  for(const [width,height] of [[1440,1000],[820,900],[390,844],[1280,650]]){
    await page.setViewportSize({width,height});
    await page.getByTestId('focus-map').click();
    const map=page.getByRole('region',{name:'战场态势地图',exact:true});
    const box=await map.boundingBox();
    assert(box.height>=height-50&&box.width>=width-90,'map area regressed');
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal page overflow');
    const identity=await map.evaluate(el=>el._leaflet_id);
    await page.getByRole('tab',{name:'兵种与保障',exact:true}).click();
    let panel=await page.getByTestId('analysis-panel').boundingBox();
    assert(panel.x>=0&&panel.x+panel.width<=width+1&&panel.y+panel.height<=height,'analysis outside viewport');
    assert(await page.getByTestId('combined-unit').count()===6,'ledger unavailable');
    await page.screenshot({path:`.cache/qa/map-workbench/analysis-${width}.png`});
    await page.getByRole('tab',{name:'兵种与保障',exact:true}).press('End');
    assert(await page.getByRole('tab',{name:'运行摘要与数据质量',exact:true}).getAttribute('aria-selected')==='true','keyboard tab navigation failed');
    await page.getByTestId('left-toggle').click();
    if(width<1100)assert(!(await page.getByTestId('analysis-panel').isVisible()),'narrow side drawers overlap');
    panel=await page.getByTestId('left-panel').boundingBox();
    assert(panel.x>=0&&panel.x+panel.width<=width+1,'left panel outside viewport');
    await page.screenshot({path:`.cache/qa/map-workbench/left-${width}.png`});
    await page.getByTestId('top-controls').click();
    assert(!(await page.getByTestId('left-panel').isVisible()),'top overlaps left');
    panel=await page.getByTestId('top-panel').boundingBox();
    assert(panel.x>=0&&panel.x+panel.width<=width+1&&panel.y+panel.height<=height,'top panel outside viewport');
    await page.getByLabel('本轮决策意图').fill('折叠草稿不应丢失');
    await page.getByTestId('top-status').click();
    await page.getByTestId('afsim-status').waitFor({state:'visible'});
    await page.screenshot({path:`.cache/qa/map-workbench/status-${width}.png`});
    await page.getByTestId('top-controls').click();
    assert(await page.getByLabel('本轮决策意图').inputValue()==='折叠草稿不应丢失','draft disappeared across tabs');
    await page.getByTestId('focus-map').click();
    assert(await map.evaluate(el=>el._leaflet_id)===identity,'Leaflet instance replaced');
    await page.screenshot({path:`.cache/qa/map-workbench/map-${width}.png`});
    results.push({width,height,map:box,panels_in_viewport:true,keyboard:true,leaflet_preserved:true});
  }
  await page.setViewportSize({width:1440,height:1000});
  return {passed:true,viewports:results};
}
