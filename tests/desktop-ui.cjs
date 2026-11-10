// npm install playwright-core in a scratch directory; set PLAYWRIGHT_MODULE to it.
// Run desktop with --debug-port 9228, then: node tests/desktop-ui.cjs
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const output=process.env.OSUNEU_TEST_OUTPUT;
(async()=>{
  const browser=await chromium.connectOverCDP('http://127.0.0.1:9228',{noDefaults:true});
  const page=browser.contexts()[0].pages().find(p=>p.url().includes('desktop=1'));
  assert(page,'desktop page not found');
  await page.reload();
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.click('#demo');
  assert.equal(await page.locator('html').getAttribute('data-desktop'),'true');
  const box=await page.locator('#timeline').boundingBox();
  async function drag(from,to,button='right',target=box){
    await page.mouse.move(target.x+target.width*from,target.y+target.height*.4);
    await page.mouse.down({button});
    await page.mouse.move(target.x+target.width*to,target.y+target.height*.4,{steps:8});
    await page.mouse.up({button});
  }
  const bounds=async()=>[await page.locator('#start').inputValue(),await page.locator('#end').inputValue()];
  await drag(.2,.4);assert.deepEqual(await bounds(),['00:04.500','00:09.000']);
  await drag(.7,.5);assert.deepEqual(await bounds(),['00:11.250','00:15.750']);
  await page.mouse.click(box.x+box.width*.1,box.y+box.height*.4);
  assert.deepEqual(await bounds(),['00:11.250','00:15.750']);
  assert.equal(await page.locator('#time').inputValue(),'00:02.250');
  await drag(.1,.3,'left');
  assert.deepEqual(await bounds(),['00:11.250','00:15.750']);
  assert.equal(await page.locator('#time').inputValue(),'00:06.750');
  await drag(.5,.45,'left');
  assert.deepEqual(await bounds(),['00:10.125','00:15.750']);
  await page.click('#zoomIn');
  await drag(.4,.6);assert.deepEqual(await bounds(),['00:10.125','00:12.375']);
  await drag(.5,.3,'middle');
  assert.deepEqual(await bounds(),['00:10.125','00:12.375']);
  await drag(.4,.6);assert.deepEqual(await bounds(),['00:12.375','00:14.625']);
  const pan=await page.locator('#pan').boundingBox();
  await drag(.5,.4,'middle',pan);
  await drag(.4,.6);assert.deepEqual(await bounds(),['00:13.500','00:15.750']);
  await page.mouse.move(box.x+box.width*.5,box.y+box.height*.4);
  await page.mouse.wheel(0,-100);await page.waitForTimeout(100);
  await drag(.4,.6);
  const zoomBounds=(await bounds()).map(v=>Number(v.slice(3))*1000);
  // CDP rounds the wheel anchor to device pixels; allow the resulting few ms offset.
  assert(Math.abs(zoomBounds[0]-13687.5)<=3&&Math.abs(zoomBounds[1]-15562.5)<=3,JSON.stringify(zoomBounds));
  await page.locator('#tags button').first().click();
  await page.locator('#note').fill('Desktop mouse interaction check');
  const initial=Number(await page.locator('#count').textContent());
  await page.locator('#note').press('Control+Enter');
  assert.equal(Number(await page.locator('#count').textContent()),initial+1);
  assert((await page.locator('#saveStatus').textContent()).includes('桌面应用'));
  await page.reload();await page.click('#demo');
  assert.equal(Number(await page.locator('#count').textContent()),initial+1);
  assert.deepEqual(errors,[]);
  if(output){await page.screenshot({path:output+'/desktop.png',fullPage:true});fs.writeFileSync(output+'/desktop-check.json',JSON.stringify({passed:true,checks:['real Qt desktop window','right drag selection','reverse selection','left click and drag seek preserve selection','left boundary drag','middle drag on timeline','middle drag on scrollbar','wheel zoom at pointer','desktop autosave','reload restore'],errors},null,2));}
  await browser.close();console.log('Desktop interaction checks passed');
})().catch(e=>{console.error(e);process.exit(1)});
