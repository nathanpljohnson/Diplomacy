async page=>{
 page.on('dialog',d=>d.accept().catch(()=>{}));
 const base='http://127.0.0.1:8006',name='poll_'+Date.now().toString(36);
 const auth=await(await page.request.post(base+'/api/register',{data:{name,password:'local fixture password only'}})).json();
 const h={'X-CSRF-Token':auth.csrf};const create=async title=>(await(await page.request.post(base+'/api/games',{headers:h,data:{title,power:'FRANCE'}})).json()).id;
 const a=await create('Stale poll A'),b=await create('Stale poll B');
 await page.goto('about:blank');await page.goto(base+'/#game='+a,{waitUntil:'domcontentloaded'});await page.waitForSelector('#unit-select');
 let release,captured;const gate=new Promise(r=>release=r),started=new Promise(r=>captured=r);let first=true;
 await page.route(base+'/api/games/'+a,async route=>{if(!first){await route.continue();return;}first=false;const response=await route.fetch();captured();await gate;await route.fulfill({response});});
 const old=page.evaluate(id=>loadGame(id,true),a);await started;
 const before=await(await page.request.get(base+'/api/games/'+a)).json();
 const resolved=await page.request.post(base+'/api/games/'+a+'/adjudicate',{headers:h,data:{phase:before.phase,revision:before.revision,force:true}});if(!resolved.ok())throw Error('Fixture adjudication failed');
 await page.evaluate(id=>loadGame(id,true),a);release();await old;
 if(!(await page.locator('#quick-phase').innerText()).includes('Fall 1901'))throw Error('Stale response rolled board back');
 await page.unroute(base+'/api/games/'+a);
 let release2,captured2;const gate2=new Promise(r=>release2=r),started2=new Promise(r=>captured2=r);first=true;
 await page.route(base+'/api/games/'+a,async route=>{if(!first){await route.continue();return;}first=false;const response=await route.fetch();captured2();await gate2;await route.fulfill({response});});
 const old2=page.evaluate(id=>loadGame(id,true),a);await started2;
 await page.evaluate(id=>loadGame(id),b);release2();await old2;
 if(await page.evaluate(()=>location.hash)!=='#game='+b)throw Error('Old game response replaced chosen game');
 await page.unroute(base+'/api/games/'+a);
 let release3,captured3;const gate3=new Promise(r=>release3=r),started3=new Promise(r=>captured3=r);first=true;
 await page.route(base+'/api/games/'+b,async route=>{if(!first){await route.continue();return;}first=false;const response=await route.fetch();captured3();await gate3;await route.fulfill({response});});
 const old3=page.evaluate(id=>loadGame(id,true),b);await started3;
 await page.getByRole('button',{name:'My games',exact:true}).click();await page.locator('#logout-button').click();
 await page.waitForFunction(()=>document.querySelector('#notice')?.textContent==='Signed out.');
 release3();await old3;
 if(await page.evaluate(()=>location.hash)!==''||!await page.locator('#quick-actions').evaluate(e=>e.hidden))throw Error('A stale response restored the signed-out game');

}
