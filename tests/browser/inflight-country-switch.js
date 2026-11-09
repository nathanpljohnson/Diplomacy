async page=>{
 page.on('dialog',d=>d.accept());
 const base='http://127.0.0.1:8005';const name='edge_'+Date.now().toString(36);
 const auth=await(await page.request.post(base+'/api/register',{data:{name,password:'only local test passphrase'}})).json();
 const created=await(await page.request.post(base+'/api/games',{headers:{'X-CSRF-Token':auth.csrf},data:{title:'Inflight edit test',power:'FRANCE',drunk_power:'TURKEY'}})).json();
 await page.goto('about:blank');await page.goto(base+'/#game='+created.id,{waitUntil:'domcontentloaded'});await page.waitForSelector('#unit-select');
 async function move(loc,order){await page.locator('#unit-select').selectOption(loc);await page.locator('[data-type="-"]').click();await page.locator('#order-select').selectOption(order);await page.waitForFunction(o=>document.querySelector('.order-list')?.textContent.includes(o),order);}
 await move('PAR','A PAR - BUR');
 await page.route('**/orders',async route=>{const r=await route.fetch();await page.evaluate(()=>window.__savePending=true);await new Promise(r=>setTimeout(r,1500));await route.fulfill({response:r});});
 const saved=page.waitForResponse(r=>r.url().endsWith('/orders')&&r.request().method()==='PUT');
 await page.locator('#submit-orders').click();await page.waitForFunction(()=>window.__savePending);
 await page.locator('#power-control').selectOption('TURKEY');
 await move('CON','A CON - BUL');
 await saved;
 await page.waitForFunction(()=>document.querySelector('#notice')?.textContent.includes('Earlier orders saved')||document.querySelector('#notice')?.textContent.includes('Orders submitted.'));
 await page.waitForFunction(()=>document.querySelector('.order-list')?.textContent.includes('A CON - BUL')&&document.querySelector('.ready-status')?.textContent.includes('Unsaved'),null,{timeout:3000});
 const remote=await(await page.request.get(base+'/api/games/'+created.id)).json();
 if(remote.orders.FRANCE.length!==1)throw Error('Unexpected saved snapshot');
 await page.unroute('**/orders');await page.locator('#submit-orders').click();await page.waitForFunction(()=>document.querySelector('.ready-status')?.textContent.includes('Submitted'));
 const complete=await(await page.request.get(base+'/api/games/'+created.id)).json();if(complete.orders.FRANCE.length!==1||JSON.stringify(complete.orders.TURKEY)!==JSON.stringify(['A CON - BUL']))throw Error('Country switch mixed or lost sheets');
}
