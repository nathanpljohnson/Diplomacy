'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const powers = ['AUSTRIA','ENGLAND','FRANCE','GERMANY','ITALY','RUSSIA','TURKEY'];
const names = {AUSTRIA:'Austria-Hungary',ENGLAND:'England',FRANCE:'France',GERMANY:'Germany',ITALY:'Italy',RUSSIA:'Russia',TURKEY:'Turkey'};
const colors = ['#c85c4e','#8c5ab5','#3d85b5','#85542e','#548c4c','#57545f','#d77726'];
let user = null, csrf = '', game = null, activeTab = 'orders', selectedPower = '', selectedLocation = '', orderType = 'H', draft = [], dirty = false, zoom = 1, clean = false, historicalPhase = '', pendingAction = null, register = false, provinces = [], mapRequest = 0;
let noticeTimer, gameTarget = '';
let retreatPlan={},retreatPhase='',retreatPrompted='',retreatSaving=false;
let buildPlannerOpen=false;
let buildPlan={},buildPlanPhase='',buildPrompted='',buildSaving=false;
let showLastResults=false;
let mapOrigin='', mapAssist=null, mapActions=Promise.resolve();
let inspectedProvince='', clockOffset=0, clockRefreshing=false;
function notice(message) { $('#notice').textContent = message; $('#notice').classList.add('visible'); clearTimeout(noticeTimer); noticeTimer = setTimeout(() => $('#notice').classList.remove('visible'), 6500); }
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: {'Content-Type':'application/json','X-CSRF-Token':csrf,...options.headers} });
  const data = await response.json().catch(() => ({error:'The server returned an unexpected response. Try again.'}));
  if (!response.ok) { const error = new Error(data.error || 'Something went wrong. Try again.'); error.status = response.status; throw error; }
  return data;
}
const send = (path, data, method = 'POST') => api(path, {method,body:JSON.stringify(data)});
function openDialog(id) { $$('dialog[open]').forEach(d => d.close()); $(id).showModal(); }
function phaseName(phase) { if (phase === 'COMPLETED') return 'Game complete'; return `${({S:'Spring',F:'Fall',W:'Winter'})[phase?.[0]] || ''} ${phase?.slice(1,5) || ''}`; }
function phaseType(phase) { return ({M:'Movement',R:'Retreats',A:'Adjustments'})[phase?.slice(-1)] || 'Completed'; }
function auth(action) { pendingAction = action; openDialog('#auth-dialog'); }
function authenticated(action) { if (!user) return auth(action); action(); }
function draftKey() { return game ? `entente:${user.id}:${game.id}:${game.phase}:${selectedPower}` : ''; }
function rememberDraft() { try { localStorage.setItem(draftKey(), JSON.stringify(draft)); } catch {} }
function loadDraft() {
  draft = [...(game.orders[selectedPower] || [])]; dirty = false;
  try { const local = JSON.parse(localStorage.getItem(draftKey())); if (Array.isArray(local) && local.every(o => typeof o === 'string') && JSON.stringify(local) !== JSON.stringify(draft)) { draft = local; dirty = true; } } catch {}
  selectedLocation = game.orderable[selectedPower]?.[0] || ''; orderType = game.phase.endsWith('R') ? 'R' : game.phase.endsWith('A') ? 'B' : 'H';
}
async function loadGame(id, silent = false) {
  if(silent&&gameTarget&&gameTarget!==id)return;
  if(!silent||!gameTarget)gameTarget=id;
  const requestedUser=user?.id;
  const next = await api(`/api/games/${encodeURIComponent(id)}`);
  if(!user||user.id!==requestedUser||gameTarget!==id)return;
  if(game?.id===next.id&&next.revision<game.revision)return;
  const same = game?.id === next.id && game?.phase === next.phase;
  const changed = !same || game?.revision !== next.revision;
  if (!same) { buildPlannerOpen=false;mapOrigin='';mapAssist=null; if (dirty) notice('The phase changed. The board now shows the current position.'); historicalPhase = ''; selectedPower = next.controlled.includes(selectedPower) ? selectedPower : next.controlled[0] || ''; }
  if(!same)showLastResults=next.history.length>0&&!Object.values(next.orders).some(sheet=>sheet.length);
  if(!next.controlled.includes(selectedPower)){selectedPower=next.controlled[0]||'';dirty=false;}
  game = next;
  clockOffset=Date.now()/1000-next.server_time;
  if (!same || !dirty && changed) {const location=selectedLocation,type=orderType;loadDraft();if(same&&mapOrigin&&game.orderable[selectedPower]?.includes(location)){selectedLocation=location;orderType=type;}}
  if (changed || !silent) { render(); if (!dirty || !same) await loadMap(); }
  location.hash = `game=${game.id}`;
  maybeBuildPrompt();maybeRetreatPrompt();
}
async function loadMap() {
  const current = ++mapRequest;
  const endpoint = game ? `/api/games/${encodeURIComponent(game.id)}/map${historicalPhase ? `?phase=${historicalPhase}` : showLastResults?'?results=1':''}` : '/api/map';
  $('#map').setAttribute('aria-busy','true');
  try {
    const response = await fetch(game && dirty && !historicalPhase && !showLastResults ? `/api/games/${game.id}/preview` : endpoint, game && dirty && !historicalPhase && !showLastResults ? {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({power:selectedPower,orders:draft,phase:game.phase})} : {});
    if (!response.ok) throw new Error('Could not load the board. Refresh to try again.');
    const svg = await response.text();
    if (current !== mapRequest) return;
    $('#map').innerHTML = svg;
    $('#map svg').classList.toggle('clean',clean);
    highlightLocation();
  } catch(error) { notice(error.message); }
  finally { if (current === mapRequest) $('#map').setAttribute('aria-busy','false'); }
}
function renderQuickActions(){
 const active=game&&!game.completed;
 $('#quick-actions').hidden=!active;
 if(!active)return;
 $('#quick-phase').textContent=`${phaseName(game.phase)} · ${phaseType(game.phase)}`;
 $('#quick-adjudicate').hidden=!game.host;
 $('#quick-submit').hidden=!game.controlled.length||!!game.draws[selectedPower]||game.phase.endsWith('R')&&!retreatEntries().length;
 $('#quick-submit').textContent=historicalPhase?'Current orders':game.phase.endsWith('A')?'Build choices':game.phase.endsWith('R')?'Retreat choices':selectedPower===game.drunk_power?`Submit ${names[selectedPower]} proposal`:'Submit sheet';
}
$('#quick-submit').onclick=async()=>{
 const button=$('#quick-submit');button.disabled=true;
 try{
  if(historicalPhase){historicalPhase='';activeTab='orders';render();await loadMap();return;}
  if(game.phase.endsWith('A'))return showBuildPlanner();
  if(game.phase.endsWith('R'))return showRetreatPlanner();
  await mapActions;await saveOrders(true);
 }catch(error){notice(error.message);}finally{button.disabled=false;}
};
$('#quick-adjudicate').onclick=async()=>{
 const button=$('#quick-adjudicate');button.disabled=true;
 try{await adjudicate();}catch(error){notice(error.message);}finally{button.disabled=false;}
};

function renderArrowLegend(){
 const last=game?.history.at(-1);
 $('#arrow-legend').hidden=!game;
 $('#result-view').hidden=!last||!!historicalPhase;
 $('#result-view').textContent=showLastResults?'Enter new orders':'Show last results';
 $('#result-view').setAttribute('aria-pressed',String(showLastResults));
 $('#arrow-context').textContent=historicalPhase?`${phaseName(historicalPhase)} results · starting position`:showLastResults&&last?`${phaseName(last.phase)} results · resulting position`:'Current orders';
 $('#arrow-red-key').hidden=!historicalPhase&&!showLastResults;
}
$('#result-view').onclick=()=>{showLastResults=!showLastResults;clean=false;$('#clean-map').setAttribute('aria-pressed','false');renderArrowLegend();loadMap();};

function render() {
  $('#account-nav').innerHTML = user ? `${esc(user.name)} <span aria-hidden="true">↗</span>` : 'Sign in <span aria-hidden="true">↗</span>';
  $('#game-title').textContent = game?.title || 'Europe, on the brink.';
  $('#game-kind').textContent = game ? (game.sandbox ? 'PRIVATE SANDBOX · ALL SEVEN POWERS' : 'PRIVATE GAME · HOST-PACED ADJUDICATION') : 'THE CLASSIC BOARD · SEVEN GREAT POWERS';
  $('#game-description').textContent = game ? (game.completed ? 'The final balance of power. Explore the results in History.' : game.sandbox ? 'Test an alliance. Find the flaw. Rewrite the plan.' : 'Negotiate together. Submit in secret. Let the host resolve the rest.') : 'A beautiful place to make very questionable alliances.';
  const phase = historicalPhase || game?.phase || 'S1901M';
  $('#phase-title').textContent = phaseName(phase);
  $('#phase-type').textContent = `${phaseType(phase).toUpperCase()} · ${historicalPhase ? 'HISTORICAL POSITION' : 'STANDARD EUROPE'}`;
  $('#export-button').hidden = !game;
  $('#power-strip').innerHTML = powers.map((p,i) => { const count = game ? game.state.centers[p].length : p === 'RUSSIA' ? 4 : 3; return `<div class="power-chip" style="--power:${colors[i]}"><span><i class="power-dot" aria-hidden="true"></i>${p === 'AUSTRIA' ? 'Austria' : names[p]}</span><small><b>${count}</b> centers</small></div>`; }).join('');
  renderArrowLegend();
  $('#scenario-button').hidden=!game;
  renderClock();
  renderProvince();
  renderPanel();
}
function renderPanel() {
  const buildForm=$('#build-form');if(buildForm.closest('#tab-content'))$('#build-dialog').append(buildForm);
  $('.game-shell').classList.toggle('build-mode',!!(buildPlannerOpen&&game?.phase.endsWith('A')&&activeTab==='orders'&&!historicalPhase));
  renderQuickActions();
  $$('.panel-tabs button').forEach(b => { b.setAttribute('aria-selected', String(b.dataset.tab === activeTab)); b.tabIndex = b.dataset.tab === activeTab ? 0 : -1; });
  $('#tab-content').setAttribute('aria-labelledby',`tab-${activeTab}`);
  if (activeTab === 'guide') return renderGuide();
  if (activeTab === 'powers') return renderPowers();
  if (activeTab === 'history') return renderHistory();
  if (!game) return renderWelcome();
  if (historicalPhase) { $('#tab-content').innerHTML = `<div class="current-phase-banner">Viewing ${esc(phaseName(historicalPhase))} ${esc(phaseType(historicalPhase))}.</div><h3>A page from the past.</h3><p class="intro-copy">Resolved orders are visible on the map. Return to the current phase to enter orders.</p><button class="button dark full" data-action="current">Return to current phase</button>`; return; }
  if (game.completed) { $('#tab-content').innerHTML = `<div class="eyebrow">THE FINAL ACCORD</div><h2>${game.ended_reason==='draw'?'A draw is agreed.':'The game is complete.'}</h2><p>${esc(game.outcome?.join(' · ') || 'The final position has been recorded.')}</p><button class="button full" data-action="history">Explore the history</button>`; return; }
  if (!game.controlled.length) { $('#tab-content').innerHTML=`<div class="eyebrow">GAME HOST</div><h2>Set the stage.</h2><p class="host-only-note">You are hosting without playing a power. Invite friends to claim the seven countries, set the pace, and follow the shared board. Each player's current order sheet stays private.</p>${hostBlock()}`;return; }
  if(game.draws[selectedPower]) return renderDrawSheet();
  if(game.phase.endsWith('R'))return renderRetreatPanel();
  if(game.phase.endsWith('A')&&buildPlannerOpen){$('#tab-content').innerHTML='<div id="inline-build-planner"></div>';$('#inline-build-planner').append(buildForm);renderBuildPlanner();return;}
  const locations = game.orderable[selectedPower] || [];
  const status = dirty ? 'Unsaved changes on this device' : game.ready[selectedPower] ? 'Submitted · editable until adjudication' : 'Not submitted';
  $('#tab-content').innerHTML = `<div class="panel-kicker"><span><i class="status-dot"></i>${game.sandbox ? 'SANDBOX ORDER SHEET' : 'YOUR PRIVATE ORDER SHEET'}</span></div>
  ${game.sandbox ? `<div class="panel-heading"><span class="power-badge" style="--power:${colors[powers.indexOf(selectedPower)]}" aria-hidden="true">${selectedPower[0]}</span><h3>All powers · ${names[selectedPower]}</h3></div>` : game.controlled.length > 1 ? `<label>Order sheet<select id="power-control">${game.controlled.map(p=>`<option value="${p}" ${p===selectedPower?'selected':''}>${names[p]}${p===game.drunk_power?' · your drunk proposal':''}${game.ready[p]?' · submitted':''}</option>`).join('')}</select></label>` : `<div class="panel-heading"><span class="power-badge" style="--power:${colors[powers.indexOf(selectedPower)]}" aria-hidden="true">${selectedPower[0]}</span><h3>${names[selectedPower] || 'Observer'}</h3></div>`}
  ${selectedPower===game.drunk_power?'<div class="panel-note"><strong>Your private drunk-country proposal</strong><br>Submit this sheet separately from your own country. One submitted, nonempty player sheet is chosen at random when the phase resolves. Other proposals stay private.</div>':''}<p class="fineprint">${phaseInstructions()}${game.drunk_power&&game.phase.endsWith('A')?` Drunk ${names[game.drunk_power]} adjusts automatically.`:''}</p>${game.phase.endsWith('A')?'<button class="button dark full" data-action="build-planner">Open builds & removals</button>':''}
  ${locations.length ? `<label>${game.phase.endsWith('A') ? 'Home center or unit' : 'Select a unit'}<select id="unit-select">${locations.map(loc=>`<option ${loc===selectedLocation?'selected':''} value="${esc(loc)}">${esc(unitLabel(loc))}</option>`).join('')}</select></label><div class="order-types" aria-label="Order type">${availableTypes().map(t=>`<button data-type="${t}" aria-pressed="${t===orderType}">${typeLabel(t)}</button>`).join('')}</div>${convoyHelp()}<label id="order-label">Complete order<select id="order-select"></select></label><button class="button full" style="margin-top:12px" id="add-order">Add to order sheet <span aria-hidden="true">＋</span></button>` : `<div class="panel-note">No orders are required for ${names[selectedPower]} in this phase. You can still mark your sheet submitted.</div>`}
  <div class="sheet-heading"><strong>Order sheet</strong><span>${draft.length} ${draft.length===1?'order':'orders'}</span></div><ul class="order-list">${draft.length ? draft.map((o,i)=>`<li><div><code>${esc(o)}</code>${['C','V'].includes(classify(o))?`<small class="convoy-summary">${esc(orderDescription(o))}</small>`:''}</div><button class="remove-order" data-remove="${i}" aria-label="Remove ${esc(o)}">×</button></li>`).join('') : '<li class="muted">No orders entered yet.</li>'}</ul><div class="save-actions"><button class="button" id="save-draft">Save draft</button><button class="button dark" id="submit-orders">${selectedPower===game.drunk_power?'Submit proposal':'Submit orders'}</button></div><div class="ready-status" role="status">${status}</div>
  <p class="fineprint">Unordered units use the default for this phase. Saving a draft marks your sheet not ready.</p>${drawControls()}${game.source?`<a class="scenario-source" href="/#game=${esc(game.source.game_id)}" target="_blank" rel="noopener">Real game · ${esc(game.source.title)} ↗</a>`:''}${game.host ? hostBlock() : '<hr class="rule"><p class="fineprint">Your host resolves the phase. Other players cannot see these orders until then.</p>'}`;
  renderOrderOptions();
}
function phaseInstructions() {
  if (game.phase.endsWith('R')) return game.retreat_options?.[selectedPower]?.length?'Only displaced units need to retreat.':'None of your units needs to retreat.';
  if (game.phase.endsWith('A')) { const n = game.state.builds[selectedPower]?.count || 0; return n>0 ? `You may build ${n} ${n===1?'unit':'units'} in vacant, owned home centers. Unused builds are waived.` : n<0 ? `You must remove ${-n} ${n===-1?'unit':'units'}. Missing removals use civil disorder rules.` : 'Your unit count matches your supply centers. No adjustments are needed.'; }
  return game.sandbox?'Click any country’s unit, then its destination. Moves save automatically and arrows stay visible. Click the same unit twice to hold. Use Support or Convoy for other orders.':'Click your unit, then its destination to add a move and show its arrow. Save or submit your sheet before resolution.';
}
function hostBlock() {
 const needed=game.required,ready=needed.filter(p=>game.ready[p]).length;
 return `<div class="host-block"><div class="panel-kicker"><span>HOST CONTROLS</span><span>${ready}/${needed.length} submitted</span></div><button class="button dark" id="adjudicate">Adjudicate phase <span aria-hidden="true">→</span></button>${!game.sandbox?'<button class="button full" style="margin-top:8px" data-action="clock">Manage phase clock</button>':''}<p class="fineprint">${game.sandbox?'This is a private study. Your experiments cannot change the real game.':'The clock resolves saved sheets automatically when running. You can pause it or resolve manually.'}</p>${game.timer?.error?`<p class="fineprint clock-error">${esc(game.timer.error)}</p>`:''}${!game.sandbox?'<button class="text-button" data-action="invite">Copy invitation code ↗</button>':''}</div>`;
}
function unitLabel(loc) { const unit = game.state.units[selectedPower]?.find(u=>u.replace('*','').split(' ')[1].slice(0,3) === loc.slice(0,3)); const name = provinces.find(p=>p.id===loc.slice(0,3))?.name || loc; return `${unit || loc} · ${name}`; }
function classify(order) { if(order==='WAIVE') return 'B'; const parts=order.split(' '); return parts[2]==='-'&&parts.at(-1)==='VIA'?'V':parts[2] || 'H'; }
function typeLabel(type) { return ({H:'Hold','-':'Move',S:'Support',C:'Convoy an army',V:'Move via convoy',R:'Retreat',D:'Disband',B:'Build'})[type] || type; }
function availableTypes() { const types = [...new Set((game.possible[selectedLocation] || []).map(classify))]; if (!types.includes(orderType)) orderType = types[0] || 'H'; return types; }
function renderOrderOptions(filterProvince = '') {
  const select = $('#order-select'); if(!select) return;
  const options = (game.possible[selectedLocation] || []).filter(o=>classify(o)===orderType).sort();
  select.innerHTML = options.map(o=>`<option value="${esc(o)}">${esc(orderDescription(o))}</option>`).join('');
  const existing = draft.find(o=>o.split(' ')[1]?.slice(0,3)===selectedLocation.slice(0,3)); if(options.includes(existing)) select.value=existing;
  if (filterProvince) { const matching = options.filter(o=>o.split(' ').slice(3).some(x=>x.slice(0,3)===filterProvince)); if (matching.length) { select.value=matching[0]; if(matching.length>1) notice('Check the complete order, including its coast and supported unit.'); } else notice('That destination is not legal for this order. Choose from the list.'); }
  $('#add-order').disabled = !options.length;
}
function renderWelcome() {
  $('#tab-content').innerHTML = `<div class="panel-kicker"><span><i class="status-dot"></i>${user?'READY WHEN YOU ARE':'THE ART OF DIPLOMACY'}</span><span>01 / 07</span></div><h2 class="panel-intro">Every alliance<br>starts somewhere.</h2><p class="intro-copy">An old world. A fresh table.<br>Bring your friends, choose a power, and let the negotiations begin.</p><button class="button dark full" data-action="create">Create a private game <span aria-hidden="true">↗</span></button><button class="text-button full" data-action="join">Have an invitation? Join a game</button><hr class="rule"><ul class="feature-list"><li><i aria-hidden="true">♜</i><span>Seven powers. One shared board.</span></li><li><i aria-hidden="true">✉</i><span>Secret orders, submitted individually.</span></li><li><i aria-hidden="true">⌁</i><span>Your host decides when the world moves.</span></li></ul><div class="panel-note"><strong>A little rehearsal?</strong><br>Try a private sandbox. Control every power, test orders, and see what happens.<button class="text-button" style="display:block;font-size:11px" data-action="sandbox">Open a sandbox →</button></div>`;
}
function renderPowers() {
  $('#tab-content').innerHTML = `<div class="eyebrow">THE BALANCE OF POWER</div><h2>Seven seats.<br>Countless agendas.</h2><ul class="standings">${powers.map((p,i)=>`<li><strong><i class="power-dot" style="--power:${colors[i]}" aria-hidden="true"></i>${names[p]}</strong><small>${game ? game.state.centers[p].length : p==='RUSSIA'?4:3} centers</small><small>${game ? esc(game.seats[p]?.name || (p===game.drunk_power?'Drunk country · shared':game.sandbox?'Sandbox control':'Unclaimed seat')) : 'Available in a new game'}</small><small class="${game?.ready[p]?'ready':''}">${game ? p===game.drunk_power?'Random selection':game.ready[p]?'✓ Submitted':'Not submitted':''}</small></li>`).join('')}</ul>${game?.host && !game.sandbox ? `<hr class="rule"><div class="eyebrow">INVITE YOUR FRIENDS</div><p class="fineprint">Share this code privately. Each friend signs in and chooses an unclaimed power.</p><code class="invite-code">${esc(game.invite)}</code><button class="button full" data-action="invite">Copy invitation code</button>` : ''}${drunkSetup()}`;
}
function drunkSetup() {
 if(!game)return '';
 const info=game.drunk_power?`<div class="panel-note"><strong>Drunk ${names[game.drunk_power]}</strong><p>Movement: each player submits a private proposal. A random submitted sheet is used as a whole. No proposals means hold.</p><p>Retreats choose legal destinations automatically. Winter builds fill available home centers at random; removals happen only when required. Centers remain capturable.</p>${game.drunk_players.map(p=>`<div>Player ${p.number}: ${esc(p.name)} · ${names[p.power]}</div>`).join('')}</div>`:'';
 if(!game.host||game.sandbox||game.history.length||game.timer?.enabled)return info;
 return info+`<hr class="rule"><label>Shared drunk country<select id="drunk-setup"><option value="">None · standard game</option>${powers.filter(p=>!game.seats[p]).map(p=>`<option value="${p}" ${p===game.drunk_power?'selected':''}>${names[p]}</option>`).join('')}</select></label><button class="button full" data-action="set-drunk">Save drunk-country setting</button><p class="fineprint">Choose an unclaimed country before the first adjudication and before starting the clock.</p>`;
}
function drunkHistory(s){return s.mode==='player'?`Drunk ${names[s.power]} used Player ${s.player_number}: ${s.player_name} (${names[s.player_power]}).`:s.mode==='automatic'?`Drunk ${names[s.power]}: automatic retreats / adjustments.`:`Drunk ${names[s.power]}: no submitted proposals; default holds.`;}
function renderHistory() {
  $('#tab-content').innerHTML = `<div class="eyebrow">THE ARCHIVE</div><h2>History remembers.</h2>${game?.history.length ? `<p class="fineprint">Select a resolved phase to see its board and orders. Results use the adjudicator’s labels; an empty result means no failure was reported.</p><button class="button full" data-action="current">Current phase · ${phaseName(game.phase)}</button>${[...game.history].reverse().map(h=>`<div class="history-item"><button data-history="${h.phase}">${phaseName(h.phase)} <small>${phaseType(h.phase)} ↗</small></button><p class="fineprint">${h.drunk_selection?esc(drunkHistory(h.drunk_selection))+' ':''}${h.automatic?'Resolved by phase clock. ':''}${h.draw_offers?.length?'Draw offers: '+h.draw_offers.map(p=>names[p]).join(', ')+'.':''}</p><details><summary>Orders & results</summary><pre>${esc(powers.map(p=>`${names[p]}\n${(h.orders[p]||[]).map(o=>{const loc=o.split(' ')[1]; const result=h.results[o.split(' ').slice(0,2).join(' ')]||[];return `  ${o}${result.length?' · '+result.join(', '):''}`;}).join('\n') || '  Default orders'}`).join('\n\n'))}</pre></details></div>`).join('')}` : `<p class="intro-copy">No orders have been resolved yet. Each adjudicated phase will become a page in your game’s history.</p><div class="panel-note">Current orders remain private. The archive reveals them only after the host adjudicates.</div>`}`;
}
function renderGuide() {
  $('#tab-content').innerHTML = `<div class="eyebrow">A FIELD GUIDE</div><h2>Words first.<br>Orders second.</h2><div class="guide"><ol><li><strong>Gather your table.</strong> Create a private game, share the invitation code, and have each friend claim a different power.</li><li><strong>Negotiate.</strong> Talk in person or in your favorite group chat. Promises are entirely your responsibility.</li><li><strong>Write your orders.</strong> Select a unit on the board or in the order builder. Move, hold, support, or convoy, then submit your sheet.</li><li><strong>Resolve together.</strong> The host can set a phase clock or resolve manually. Saved sheets adjudicate together. Retreat and winter adjustment phases appear when required.</li></ol><hr class="rule"><h3>Clock, draws & private studies</h3><p>The host sets and pauses the phase clock. Save your sheet before the deadline; unsaved browser edits are not sent automatically. A draw offer replaces your moves for that phase: all surviving powers must offer a draw to end the game, otherwise your units receive the missing-order defaults while others play.</p><p>Try a scenario opens a private copy of the current or selected historical board in a new tab. You control all powers without affecting the live table or seeing secret enemy orders.</p><h3>Reading the atlas</h3><p>Double diamonds mark home supply centers; single diamonds mark other supply centers. Home centers remain tied to their original power after capture. Filled circles are armies; filled triangles are fleets. Armies travel by land; fleets use seas and coasts. Russia starts with four units; the other powers start with three. Own 18 supply centers to win.</p><p>Spain, Bulgaria, and St Petersburg have multiple coasts. Select the explicit coast offered in the order builder. A support order identifies the supported unit and its destination; a convoy requires both the army’s move via convoy and the fleet convoy order.</p><p>Use the + and − map buttons to inspect small provinces. Every order can also be entered using the keyboard and the selects beside the map.</p><p><a href="/rules" target="_blank" rel="noopener">Open the Entente rulebook ↗</a></p><p><a href="/static/borders.html" target="_blank" rel="noopener">Compare map border styles ↗</a></p><p><a href="https://www.backstabbr.com/how-to-play" target="_blank" rel="noopener">Read the Diplomacy rules ↗</a></p>${game ? '<p><button class="button full" data-action="dbn-export">Download DBN game JSON ↗</button></p>' : ''}<p class="fineprint">Independent project. Not affiliated with Backstabbr or the Diplomacy trademark owners. Rules adjudicated by the open-source Diplomacy engine.</p></div>`;
}
function highlightLocation() { $$('#map [data-province]').forEach(p=>p.classList.toggle('selected',p.dataset.province===(inspectedProvince||selectedLocation))); }
function renderProvince(){
 const code=inspectedProvince||selectedLocation?.slice(0,3);
 const province=provinces.find(p=>p.id===code);
 if(!province){$('#province-detail').innerHTML='<strong>Select a territory</strong><span>See its full name, units, and ownership.</span>';return;}
 const position=historicalPhase?game.history.find(h=>h.phase===historicalPhase)?.state:game?.state;
 const centerOwner=position?powers.find(p=>position.centers[p].includes(code)):province.starting_owner;
 const influence=position?powers.find(p=>(position.influence[p]||[]).includes(code)):null;
 const owner=province.supply_center?centerOwner:(influence||province.starting_owner);
 const occupants=position?powers.flatMap(p=>position.units[p].filter(u=>u.replace('*','').split(' ')[1].slice(0,3)===code).map(u=>`${names[p]} ${u.includes('A ')?'army':'fleet'}${u.startsWith('*')?' (dislodged)':''}`)):[];
 const facts=[...(province.coasts?.length?[`Fleet coasts: ${province.coasts.map(c=>coastName(c.split('/')[1])).join(' / ')}`]:[]),province.terrain==='WATER'?'Sea':province.terrain==='COAST'?'Coastal province':'Inland province',province.supply_center?`${province.home_power?'Home supply center of '+names[province.home_power]:'Non-home supply center'} · Current owner: ${owner?names[owner]:'neutral'} · ${province.home_power?'Only '+names[province.home_power]+' can build here, when owned and vacant':'Counts toward units and victory; no builds here'}`:owner?`Territory · ${names[owner]}`:'Neutral territory',...occupants];
 $('#province-detail').innerHTML=`<strong>${esc(province.name)}</strong><code>${esc(code)}</code><span class="territory-facts">${facts.map(esc).join(' · ')}</span>`;
}
function drawControls(){
 if(selectedPower===game.drunk_power)return '';
 if(!(game.state.units[selectedPower]?.length||game.state.centers[selectedPower]?.length))return '';
 return '<div class="draw-choice"><button class="button" data-action="draw">Submit a draw offer instead</button><p class="fineprint">Choose moves or draw. If the draw is not unanimous, this power issues no orders for the phase.</p></div>';
}
function renderDrawSheet(){
 $('#tab-content').innerHTML=`<div class="eyebrow">PRIVATE ORDER SHEET</div>${game.controlled.length>1?`<label>Order sheet<select id="power-control">${game.controlled.map(p=>`<option value="${p}" ${p===selectedPower?'selected':''}>${names[p]}</option>`).join('')}</select></label>`:`<h2>${names[selectedPower]}</h2>`}<div class="draw-sheet"><h3>Draw offer submitted.</h3><p class="fineprint">This replaces your moves for the phase. If every surviving power also submits a draw, the game ends. Otherwise, your power issues no orders and the others' moves resolve.</p></div><button class="button full" data-action="withdraw-draw">Withdraw draw and enter moves</button><p class="fineprint">You can change this choice until the phase closes.</p>${game.host?hostBlock():''}`;
}
function confirmChoice(title,copy,accept){
 return new Promise(resolve=>{const dialog=$('#choice-dialog');$('#choice-title').textContent=title;$('#choice-copy').textContent=copy;$('#choice-accept').textContent=accept;dialog.returnValue='';dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true});dialog.showModal();});
}
async function submitDraw(){
 await mapActions;
 if(!await confirmChoice('Draw instead of moves?','This replaces your whole order sheet. If the draw is not unanimous, your power issues no orders in this phase.','Submit draw offer'))return;
 await send(`/api/games/${game.id}/orders`,{power:selectedPower,orders:[],ready:true,draw:true,phase:game.phase},'PUT');
 dirty=false;try{localStorage.removeItem(draftKey());}catch{}draft=[];await loadGame(game.id);notice('Draw offer submitted instead of moves.');
}
async function withdrawDraw(){
 await send(`/api/games/${game.id}/orders`,{power:selectedPower,orders:[],ready:false,draw:false,phase:game.phase},'PUT');
 dirty=false;await loadGame(game.id);notice('Draw offer withdrawn. Enter and submit your moves.');
}
function renderClock(){
 $('#phase-clock-row').hidden=!game;
 $('#clock-settings').hidden=!game?.host||game?.sandbox||game?.completed;
 updateCountdown();
}
function updateCountdown(){
 if(!game)return;
 const timer=game.timer||{};
 let title='Manual',description='Host controls the turn';
 if(game.completed){title='Finished';description='No further orders or clock actions';}
 else if(game.sandbox){title='Private study';description=game.source?`Copied from ${phaseName(game.source.phase)}`:'No live game clock';}
 else if(timer.enabled){
  const seconds=timer.paused?timer.remaining:Math.max(0,Math.ceil(timer.deadline-(Date.now()/1000-clockOffset)));
  title=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
  description=timer.paused?'Paused by host':'Automatic adjudication at zero';
  if(seconds===0&&!timer.paused&&!clockRefreshing){clockRefreshing=true;loadGame(game.id,true).catch(error=>notice(error.message)).finally(()=>setTimeout(()=>{clockRefreshing=false;},3000));}
 }
 $('#clock-countdown').textContent=title;$('#clock-status').textContent=description;
}
function showClock(){
 const durations=game.timer?.durations||game.suggested_durations;
 for(const [key,value] of Object.entries(durations))$('#timer-form [name='+key+']').value=value/60;
 $('#timer-error').textContent=game.timer_available?'':'The scheduler is not connected yet. Manual turns remain available.';
 $('#start-clock').disabled=!game.timer_available;
 $('[data-clock=pause]').disabled=!game.timer?.enabled||game.timer.paused;
 $('[data-clock=resume]').disabled=!game.timer?.enabled||!game.timer.paused;
 $('[data-clock=stop]').disabled=!game.timer?.enabled;
 openDialog('#timer-dialog');
}
async function changeClock(action,durations){
 try{await send(`/api/games/${game.id}/timer`,{action,durations,phase:game.phase});$('#timer-dialog').close();await loadGame(game.id);notice(action==='pause'?'Phase clock paused.':action==='stop'?'Manual turns restored.':'Phase clock running.');}catch(error){$('#timer-error').textContent=error.message;}
}
async function createScenario(){
 const button=$('#scenario-button');button.disabled=true;
 const popup=window.open('about:blank','_blank');if(popup)popup.opener=null;
 try{
  const payload={phase:historicalPhase||game.phase};
  if(!historicalPhase&&game.controlled.includes(selectedPower))payload.draft={power:selectedPower,orders:game.draws[selectedPower]?[]:draft};
  const result=await send(`/api/games/${game.id}/scenarios`,payload);
  const url=location.origin+'/#game='+result.id;
  if(popup)popup.location.href=url;
  else{const link=document.createElement('a');link.href=url;link.target='_blank';link.rel='noopener';link.className='button';link.textContent='Open your new scenario ↗';$('.heading-actions').append(link);notice('Scenario ready. Use the new link above to open it.');}
 }catch(error){if(popup)popup.close();notice(error.message);}finally{button.disabled=false;}
}
function retreatEntries(){return Object.entries(game?.retreat_options||{}).flatMap(([power,units])=>units.map(unit=>({...unit,power})));}
function retreatDescription(order){const p=order.split(' ');return p[2]==='D'?'Disband this unit (remove it)':`Retreat to ${fullLocation(p[3])}`;}
function renderRetreatPanel(){
 const units=retreatEntries();
 $('#tab-content').innerHTML=`<div class="eyebrow">RETREAT PHASE</div><h2>${units.length?'Choose a safe destination.':'No retreats for your units.'}</h2><p>${units.length?`${units.length} displaced ${units.length===1?'unit needs':'units need'} a retreat or disband order. Your other units do not move in this phase.`:'None of your units was displaced. Only powers with displaced units enter orders; wait for the host or phase clock.'}</p>${game.drunk_power?`<p class="panel-note">Drunk ${names[game.drunk_power]} retreats automatically when the phase resolves.</p>`:''}${units.length?'<button class="button dark full" data-action="retreat-planner">Choose retreats / disbands</button>':''}${units.map(u=>{const order=(game.orders[u.power]||[]).find(o=>o.startsWith(u.unit+' '));return `<div class="panel-note"><strong>${esc(names[u.power])} ${u.unit[0]==='A'?'army':'fleet'} · ${esc(fullLocation(u.province))}</strong><p>${order?esc(retreatDescription(order)):'No retreat order submitted yet.'}</p></div>`;}).join('')}${drawControls()}${game.host?hostBlock():''}`;
}
function maybeRetreatPrompt(){
 if(!game||historicalPhase||!game.phase.endsWith('R')||!retreatEntries().length||$('dialog[open]'))return;
 const key=game.id+':'+game.phase;if(retreatPrompted===key)return;retreatPrompted=key;showRetreatPlanner();
}
function showRetreatPlanner(){
 if(!game?.phase.endsWith('R')||!retreatEntries().length)return;
 retreatPhase=game.phase;retreatPrompted=game.id+':'+game.phase;
 retreatPlan=Object.fromEntries(retreatEntries().map(u=>[u.power+':'+u.unit,(game.orders[u.power]||[]).find(o=>o.startsWith(u.unit+' '))||'']));
 $('#retreat-title').textContent=`${retreatEntries().length} displaced ${retreatEntries().length===1?'unit needs':'units need'} a decision.`;
 $('#retreat-options').innerHTML=retreatEntries().map((u,i)=>`<section class="retreat-unit"><h3>${esc(names[u.power])} ${u.unit[0]==='A'?'army':'fleet'}</h3><p>Displaced from <strong>${esc(fullLocation(u.province))}</strong>. ${u.orders.some(o=>o.split(' ')[2]==='R')?'Where should this unit retreat?':'No legal retreat destinations remain. This unit must disband.'}</p>${game.draws[u.power]?'<p class="form-error">This power offered a draw instead of orders. Withdraw the offer to enter a retreat.</p>':''}<label for="retreat-unit-${i}">Retreat destination or disband<select id="retreat-unit-${i}" data-retreat-key="${esc(u.power+':'+u.unit)}" required ${game.draws[u.power]?'disabled':''}><option value="">Choose a destination…</option>${u.orders.map(o=>`<option value="${esc(o)}" ${retreatPlan[u.power+':'+u.unit]===o?'selected':''}>${esc(retreatDescription(o))}</option>`).join('')}</select></label></section>`).join('');
 $('#retreat-error').textContent='';$('#submit-retreats').disabled=!retreatEntries().some(u=>!game.draws[u.power]);openDialog('#retreat-dialog');
}
$('#retreat-options').onchange=event=>{if(event.target.dataset.retreatKey&&!retreatSaving)retreatPlan[event.target.dataset.retreatKey]=event.target.value;};
$('#retreat-form').onsubmit=async event=>{
 event.preventDefault();retreatSaving=true;$$('#retreat-options select').forEach(s=>s.disabled=true);$('#submit-retreats').disabled=true;$('#retreat-error').textContent='';
 try{
  await mapActions;
  if(game.phase!==retreatPhase||!game.phase.endsWith('R'))throw new Error('This retreat phase has ended. Close this window to see the current position.');
  for(const [power,units] of Object.entries(game.retreat_options)){
   if(!units.length||game.draws[power])continue;
   const orders=units.map(u=>retreatPlan[power+':'+u.unit]);if(orders.some(o=>!o))throw new Error('Choose a destination or disband for every displaced unit.');
   await send(`/api/games/${game.id}/orders`,{phase:retreatPhase,power,orders,ready:true},'PUT');
   try{localStorage.removeItem(`entente:${user.id}:${game.id}:${retreatPhase}:${power}`);}catch{}
  }
  dirty=false;$('#retreat-dialog').close();await loadGame(game.id);notice('Retreat choices submitted. They resolve with the rest of this phase.');
 }catch(error){$('#retreat-error').textContent=error.message;}finally{retreatSaving=false;$$('#retreat-options select').forEach(s=>s.disabled=!!game.draws[s.dataset.retreatKey.split(':')[0]]);$('#submit-retreats').disabled=false;}
};

function maybeBuildPrompt(){
 if(!game||historicalPhase||!game.phase.endsWith('A')||!Object.values(game.construction||{}).some(c=>c.count!==0||c.potential>0)||$('dialog[open]'))return;
 const key=game.id+':'+game.phase;
 if(buildPrompted===key)return;
 buildPrompted=key;showBuildPlanner();
}
function closeBuildPlanner(){buildPlannerOpen=false;renderPanel();}
function showBuildPlanner(){
 if(!game?.phase.endsWith('A'))return;
 const opening=!buildPlannerOpen;
 if(!buildPlannerOpen||buildPlanPhase!==game.phase){
  buildPlanPhase=game.phase;
  buildPlan=Object.fromEntries(game.controlled.map(p=>[p,[...(p===selectedPower?draft:game.orders[p]||[])].filter(o=>o!=='WAIVE')]));
 }
 buildPrompted=game.id+':'+game.phase;buildPlannerOpen=true;activeTab='orders';
 $('#build-error').textContent='';renderPanel();if(opening)$('.game-shell').scrollIntoView({block:'start'});
}

function renderBuildPlanner(){
 const groups=Object.entries(game.construction||{}).filter(([,c])=>c.count!==0||c.potential>0);
 const total=groups.reduce((n,[,c])=>n+Math.max(0,c.count),0);
 $('#submit-builds').textContent=groups.some(([,c])=>c.count<0)?'Submit adjustments':'Submit builds';
 $('#submit-builds').disabled=!groups.some(([p,c])=>c.count&&!game.draws[p]);
 $('#build-title').textContent=total?`You can build ${total} ${total===1?'unit':'units'}.`:'Winter adjustments';
 $('#build-options').innerHTML=(game.drunk_power?`<p class="panel-note">Drunk ${names[game.drunk_power]} builds and required removals are chosen automatically when this phase resolves.</p>`:'')+groups.map(([power,c])=>{
  const sheet=buildPlan[power]||[],blocked=game.draws[power];
  const selected=sheet.length,remaining=Math.max(0,Math.abs(c.count)-selected);
  const summary=c.count>0?`Build up to ${c.count} · ${selected} chosen · ${remaining} remaining`:c.count<0?`Remove ${-c.count} · ${selected} chosen · ${remaining} remaining`:'No builds or removals';
  const cards=c.count<0?c.removals.map(order=>`<button type="button" class="button build-choice ${sheet.includes(order)?'chosen':''}" data-build-power="${power}" data-build-order="${esc(order)}" aria-pressed="${sheet.includes(order)}" ${blocked||remaining===0&&!sheet.includes(order)?'disabled':''}>Remove ${esc(order.split(' ')[0]==='A'?'army':'fleet')} in ${esc(fullLocation(order.split(' ')[1]))}</button>`).join(''):c.centers.filter(center=>center.orders.length).map(center=>{
   const existing=sheet.find(o=>o.split(' ')[1].slice(0,3)===center.province);
   return `<div class="build-territory" role="group" aria-label="Build in ${esc(placeName(center.province))}"><strong>${esc(placeName(center.province))}</strong><div class="build-choices">${center.orders.map(order=>`<button type="button" class="button build-choice ${sheet.includes(order)?'chosen':''}" data-build-power="${power}" data-build-order="${esc(order)}" aria-pressed="${sheet.includes(order)}" ${blocked||remaining===0&&!existing?'disabled':''}>${order.startsWith('A ')?'● Army':'▲ Fleet'}${order.includes('/')?' — '+esc(coastName(order.split(' ')[1].split('/')[1])):''}</button>`).join('')}</div></div>`;
  }).join('');
  const unavailable=c.centers.filter(center=>!center.orders.length).map(center=>`<li>${esc(placeName(center.province))} — ${!center.home?'captured center; not a home center':center.occupied?'occupied by a unit':'no build available this Winter'}</li>`).join('');
  return `<section class="build-power"><h3>${esc(names[power])}</h3><p class="build-count" role="status">${summary}</p>${blocked?'<p class="form-error">This power offered a draw instead of orders. Withdraw the offer to build or remove units.</p>':''}${c.potential>c.count&&c.count>=0?`<p class="fineprint">${c.potential} more centers than units, but only ${c.count} vacant, owned home ${c.count===1?'center is':'centers are'} available.</p>`:''}${cards||'<p class="fineprint">No units can be built here this Winter.</p>'}${unavailable?`<details><summary>Why not the other controlled centers?</summary><ul class="fineprint">${unavailable}</ul></details>`:''}</section>`;
 }).join('')||'<p>No builds or removals are needed. Your unit count matches your supply centers, or you are observing this game.</p>';
}
$('#build-options').onclick=event=>{
 const button=event.target.closest('[data-build-order]');if(!button||button.disabled||buildSaving)return;
 const power=button.dataset.buildPower,order=button.dataset.buildOrder,sheet=buildPlan[power],index=sheet.indexOf(order);
 if(index>=0)sheet.splice(index,1);
 else{const loc=order.split(' ')[1].slice(0,3),previous=sheet.findIndex(o=>o.split(' ')[1].slice(0,3)===loc);if(previous>=0)sheet.splice(previous,1);sheet.push(order);}
 renderBuildPlanner();$$('[data-build-order]').find(b=>b.dataset.buildPower===power&&b.dataset.buildOrder===order)?.focus();
};
$('#build-form').onsubmit=async event=>{
 event.preventDefault();const button=$('#submit-builds');button.disabled=true;buildSaving=true;$('#build-error').textContent='';
 try{
  await mapActions;
  if(game.phase!==buildPlanPhase||!game.phase.endsWith('A'))throw new Error('This build phase has ended. Close the planner to see the current position.');
  for(const [power,c] of Object.entries(game.construction||{})){
   if(!c.count||game.draws[power])continue;
   await send(`/api/games/${game.id}/orders`,{phase:buildPlanPhase,power,orders:buildPlan[power],ready:true},'PUT');
   try{localStorage.removeItem(`entente:${user.id}:${game.id}:${buildPlanPhase}:${power}`);}catch{}
  }
  dirty=false;await loadGame(game.id);notice('Winter choices submitted. Units change when the phase resolves.');
 }catch(error){$('#build-error').textContent=error.message;}finally{buildSaving=false;button.disabled=false;}
};

function syncCreateRole(){
 const sandbox=$('#create-form [name=sandbox]').checked;
 $('#drunk-create-label').hidden=sandbox;
 $('#drunk-create').disabled=sandbox;
 $('#host-only-label').hidden=sandbox;
 $('#create-form [name=power]').disabled=!sandbox&&$('#create-form [name=host_only]').checked;
}
function enqueueMapAction(task){
  mapActions=mapActions.then(task).catch(error=>notice(error.message));
  return mapActions;
}
async function putOrder(order){
  if(game.draws[selectedPower]){notice('Withdraw this power’s draw offer before entering moves.');return;}
  const province=order==='WAIVE'?'WAIVE':order.split(' ')[1].slice(0,3);
  const index=draft.findIndex(o=>o!=='WAIVE'&&o.split(' ')[1].slice(0,3)===province);
  if(index>=0)draft[index]=order;else draft.push(order);
  showLastResults=false;renderArrowLegend();dirty=true;rememberDraft();clean=false;$('#clean-map').setAttribute('aria-pressed','false');
  renderPanel();
  const preview=loadMap();
  if(game.sandbox){
    await send(`/api/games/${game.id}/orders`,{power:selectedPower,orders:[...draft],ready:true,phase:game.phase},'PUT');
    game.orders[selectedPower]=[...draft];game.ready[selectedPower]=true;dirty=false;
    try{localStorage.removeItem(draftKey());}catch{}
    renderPanel();
  }
  await preview;
  notice(`${orderDescription(order)} · ${game.sandbox?'saved in this sandbox':'added to your sheet'}`);
}
function coastName(code){return ({NC:'North coast (top)',SC:'South coast (bottom)',EC:'East coast (right)'})[code]||code;}
function fullLocation(loc){const [base,coast]=loc.split('/');return placeName(base)+(coast?' — '+coastName(coast):'');}
function placeName(code){return provinces.find(p=>p.id===code?.slice(0,3))?.name||code;}
function orderDescription(order){
 const t=order.split(' ');
 if(t[2]==='B')return `Build ${t[0]==='A'?'army':'fleet'} in ${fullLocation(t[1])}`;
 if(t.some(part=>part.includes('/')))return `${order} · ${t.filter(part=>part.includes('/')).map(fullLocation).join(' → ')}`;
 if(t[2]==='C')return `Convoy army from ${placeName(t[4])} to ${placeName(t[6])} · fleet in ${placeName(t[1])}`;
 if(classify(order)==='V')return `Move army from ${placeName(t[1])} to ${placeName(t[3])} via convoy`;
 return order;
}
function convoyHelp(){
 if(orderType==='C')return '<div class="panel-note convoy-help"><strong>Convoy an army</strong><p>Click the army’s starting province, then its destination. This fleet will carry that army between those places. The army must also order a move via convoy; every fleet in the route needs a matching convoy order.</p></div>';
 if(orderType==='V')return '<div class="panel-note convoy-help"><strong>Army move via convoy</strong><p>Choose the army’s destination. Fleets in the connecting seas must each order “Convoy an army” with the same origin and destination. A coastal fleet cannot convoy until it is at sea.</p></div>';
 return '';
}
function chooseMapOrder(options){
 return new Promise(resolve=>{
  const dialog=document.createElement('dialog');
  const convoy=options.some(o=>classify(o)==='V');
  const direct=options.some(o=>classify(o)==='-');
  const coastChoice=options.some(o=>o.includes('/'));
  const heading=coastChoice&&!convoy?'Which coast for this fleet?':convoy&&direct?'Move directly or use a convoy?':convoy?'Move this army via convoy?':'Choose the complete order';
  const copy=convoy?(direct?'A direct move uses the land border. A convoy uses fleets at sea, which must each enter a matching convoy order.':'This army needs a convoy to reach that destination. Each fleet in the sea route must enter a matching “Convoy an army” order.'):coastChoice?'North coast means the top coastline; South coast means the bottom coastline. These are separate fleet locations. A fleet cannot switch coasts by holding.':'Choose the complete order.';
  dialog.setAttribute('aria-labelledby','route-choice-title');
  dialog.innerHTML=`<h2 id="route-choice-title">${heading}</h2><p>${copy}</p><div class="map-order-choices">${options.map((o,i)=>`<button class="button full" data-index="${i}"><span>${esc(classify(o)==='-'&&convoy?`Move directly from ${placeName(o.split(' ')[1])} to ${placeName(o.split(' ')[3])}`:orderDescription(o))}<small>${esc(o)}</small></span></button>`).join('')}</div><form method="dialog"><button class="button full">Cancel</button></form>`;
  document.body.append(dialog);let choice=null;
  dialog.onclick=event=>{const button=event.target.closest('[data-index]');if(button){choice=options[Number(button.dataset.index)];dialog.close();}};
  dialog.onclose=()=>{dialog.remove();resolve(choice);};dialog.showModal();
 });
}

async function chooseProvince(province) {
  inspectedProvince=province;renderProvince();highlightLocation();
  $('#map-hint').textContent=`${provinces.find(p=>p.id===province)?.name||province} · ${province}`;
  if(!game||historicalPhase||game.completed)return;
  const phase=game.phase;
  if(phase.endsWith('R')){if(retreatEntries().some(u=>u.province.slice(0,3)===province))showRetreatPlanner();return;}
  if(phase.endsWith('A')){
   const eligible=Object.values(game.construction||{}).some(c=>c.centers.some(center=>center.province===province&&center.orders.length));
   if(eligible){showBuildPlanner();const card=$$('.build-territory').find(c=>c.getAttribute('aria-label')==='Build in '+placeName(province));card?.scrollIntoView({block:'center'});$('button',card||$('#build-form'))?.focus();return;}
  }
  if(mapOrigin&&['S','C'].includes(orderType)){
    const choices=(game.possible[selectedLocation]||[]).filter(o=>classify(o)===orderType);
    if(!mapAssist){
      const matching=choices.filter(o=>(o.split(' ')[4]||'').slice(0,3)===province);
      if(!matching.length){notice('Choose a unit that this unit can support or convoy.');return;}
      mapAssist=province;$('#map-hint').textContent=`${orderType==='C'?'Convoy army from':'Support'} ${placeName(province)} · click its destination${orderType==='S'?' (or click it again to support a hold)':''}`;return;
    }
    const matching=choices.filter(o=>{const parts=o.split(' ');return parts[4]?.slice(0,3)===mapAssist&&(parts[6]?.slice(0,3)===province||orderType==='S'&&parts.length===5&&province===mapAssist);});
    if(!matching.length){notice('That destination does not match a legal support or convoy.');return;}
    const order=matching.length===1?matching[0]:await chooseMapOrder(matching);
    if(order&&game.phase===phase){await putOrder(order);mapOrigin='';mapAssist=null;}return;
  }
  const nextType=orderType==='H'?(phase.endsWith('R')?'R':'-'):orderType;
  const options=mapOrigin?(game.possible[selectedLocation]||[]).filter(o=>(classify(o)===nextType||nextType==='-'&&classify(o)==='V')&&(o.split(' ')[3]||'').slice(0,3)===province):[];
  if(mapOrigin&&province===selectedLocation.slice(0,3)&&phase.endsWith('M')){
    await putOrder((game.possible[selectedLocation]||[]).find(o=>classify(o)==='H'));mapOrigin='';return;
  }
  if(options.length){
    const order=options.length===1&&classify(options[0])!=='V'?options[0]:await chooseMapOrder(options);
    if(order&&game.phase===phase){await putOrder(order);mapOrigin='';}return;
  }
  const power=game.controlled.find(p=>(game.orderable[p]||[]).some(loc=>loc.slice(0,3)===province));
  if(power){
    if(power!==selectedPower){
      if(dirty&&game.sandbox)await saveOrders(false);
      if(dirty&&game.sandbox)throw new Error('Save the current sheet before switching units.');
      rememberDraft();selectedPower=power;loadDraft();
    }
    selectedLocation=game.orderable[power].find(loc=>loc.slice(0,3)===province);
    mapOrigin=selectedLocation;mapAssist=null;orderType=phase.endsWith('R')?'R':phase.endsWith('A')?'B':'-';activeTab='orders';
    renderPanel();highlightLocation();
    $('#map-hint').textContent=`${unitLabel(selectedLocation)} · click its destination`;
  }
}

async function showGames() {
  openDialog('#games-dialog'); $('#games-list').textContent='Finding your tables…';
  try { const data=await api('/api/games'); $('#games-list').innerHTML = data.games.length ? data.games.map(g=>`<button class="game-card" data-game="${esc(g.id)}"><span><strong>${esc(g.title)}</strong><small>${g.sandbox?'Private sandbox':`${g.seats}/7 powers claimed`} · ${esc(phaseName(g.phase))}</small></span><span aria-hidden="true">↗</span></button>`).join('') : '<div class="empty-state">Your first game is waiting to be written. Create a table or join a friend’s.</div>'; } catch(error) { $('#games-list').textContent=error.message; }
}
function showCreate(sandbox=false) { openDialog('#create-dialog'); $('#create-form [name=host_only]').checked=!sandbox; $('#host-only-label').hidden=sandbox; $('#create-form [name=sandbox]').checked=sandbox; $('#create-form [name=title]').value=sandbox?'The rehearsal room':''; $('#create-error').textContent=''; syncCreateRole(); }
async function saveOrders(ready) {
  const buttons=$$('.save-actions button',$('#tab-content')); buttons.forEach(b=>b.disabled=true);
  const saved={id:game.id,phase:game.phase,power:selectedPower,key:draftKey(),orders:[...draft]};
  const current=()=>game?.id===saved.id&&game.phase===saved.phase&&selectedPower===saved.power;
  try {
    await send(`/api/games/${saved.id}/orders`,{power:saved.power,orders:saved.orders,ready,phase:saved.phase},'PUT');
    // Edits made while the request was in flight belong to the next save.
    if(current())dirty=JSON.stringify(draft)!==JSON.stringify(saved.orders);
    try{const local=localStorage.getItem(saved.key);if(local&&JSON.stringify(JSON.parse(local))===JSON.stringify(saved.orders))localStorage.removeItem(saved.key);}catch{}
    if(game?.id===saved.id&&gameTarget===saved.id)await loadGame(saved.id);
    notice(current()&&dirty?'Earlier orders saved. Your newer edits are still unsaved.':ready?'Orders submitted. You may still revise them until adjudication.':'Draft saved. Your sheet is marked not ready.');
  }catch(error){notice(error.message);buttons.forEach(b=>b.disabled=false);}
}
async function adjudicate() {
  await mapActions;
  if(dirty) { notice('Save or submit your current order sheet before adjudicating.'); return; }
  const button=$('#adjudicate')||$('#quick-adjudicate'); button.disabled=true;
  try {
    await loadGame(game.id,true);
    const ready=game.required.filter(p=>game.ready[p]);
    $('#confirm-copy').textContent=`${ready.length} of ${game.required.length} required powers have submitted. Resolve ${phaseName(game.phase)} ${phaseType(game.phase).toLowerCase()} with the saved order sheets? Any missing orders use the defaults below.`;
    const dialog=$('#confirm-dialog'); dialog.returnValue=''; dialog.showModal();
    dialog.addEventListener('close', async()=>{if(dialog.returnValue!=='confirm'){const b=$('#adjudicate');if(b)b.disabled=false;return;} try{await send(`/api/games/${game.id}/adjudicate`,{phase:game.phase,revision:game.revision,force:true}); await loadGame(game.id); notice('Phase resolved. The next chapter is ready.');}catch(error){notice(error.message);await loadGame(game.id).catch(()=>{});} },{once:true});
  }catch(error){notice(error.message);button.disabled=false;}
}
async function action(name) {
  if(name==='retreat-planner')return showRetreatPlanner();
  if(name==='build-planner')return showBuildPlanner();
  if(name==='clock') return showClock();
  if(name==='draw') return submitDraw();
  if(name==='withdraw-draw') return withdrawDraw();
  if(name==='dbn-export') return downloadGame(true);
  if(name==='create') return authenticated(()=>showCreate(false));
  if(name==='sandbox') return authenticated(()=>showCreate(true));
  if(name==='join') return authenticated(()=>openDialog('#join-dialog'));
  if(name==='history'){activeTab='history';return renderPanel();}
  if(name==='current'){historicalPhase='';render();return loadMap();}
  if(name==='invite'){try{await navigator.clipboard.writeText(game.invite);notice('Invitation code copied. Share it privately with your friends.');}catch{activeTab='powers';renderPanel();notice('Copy the invitation code from the Powers panel.');}}
}
$$('[data-close]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog')?button.closest('dialog').close():closeBuildPlanner()));
$$('.power-select').forEach(select=>select.innerHTML=powers.map(p=>`<option value="${p}" ${p==='FRANCE'?'selected':''}>${names[p]}</option>`).join(''));
$('#scenario-button').onclick=createScenario;
$('#clock-settings').onclick=showClock;
$('#drunk-create').innerHTML += powers.map(p=>`<option value="${p}">${names[p]}</option>`).join('');
$('#create-form [name=sandbox]').onchange=syncCreateRole;
$('#create-form [name=host_only]').onchange=syncCreateRole;
$('#timer-form').onsubmit=async event=>{event.preventDefault();const durations=Object.fromEntries([...new FormData(event.target)].map(([key,value])=>[key,Number(value)*60]));if(game.timer?.enabled&&!await confirmChoice('Restart this phase clock?','The current phase will receive its full configured duration from now.','Restart clock'))return;const button=$('#start-clock');button.disabled=true;await changeClock('start',durations);button.disabled=false;};
$$('[data-clock]').forEach(button=>button.onclick=()=>changeClock(button.dataset.clock));
setInterval(updateCountdown,1000);
$('#games-nav').onclick=()=>authenticated(showGames);
$('#account-nav').onclick=()=>user?showGames():auth(showGames);
$('#sandbox-nav').onclick=()=>action('sandbox');
$('#create-nav').onclick=()=>action('create');
$('#new-game').onclick=()=>showCreate(false);
$('#join-game').onclick=()=>openDialog('#join-dialog');
$('#auth-switch').onclick=()=>{register=!register;$('#auth-title').textContent=register?'Take your seat.':'Welcome back.';$('#auth-copy').textContent=register?'Create an account to play privately with friends.':'Sign in to your games and private order sheets.';$('#auth-submit').textContent=register?'Create account':'Sign in';$('#auth-switch').textContent=register?'Already playing? Sign in':'New here? Create an account';$('#auth-form [name=password]').autocomplete=register?'new-password':'current-password';$('#auth-error').textContent='';};
$('#auth-form').onsubmit=async event=>{event.preventDefault();const button=$('#auth-submit');button.disabled=true;$('#auth-error').textContent='';try{const data=await send(register?'/api/register':'/api/login',Object.fromEntries(new FormData(event.target)));user=data.user;csrf=data.csrf;$('#auth-dialog').close();event.target.reset();render();const next=pendingAction;pendingAction=null;if(next)await next();}catch(error){$('#auth-error').textContent=error.message;}finally{button.disabled=false;}};
$('#create-form').onsubmit=async event=>{event.preventDefault();const button=$('button[type=submit]',event.target)||event.submitter;button.disabled=true;const data=Object.fromEntries(new FormData(event.target));data.sandbox=$('[name=sandbox]',event.target).checked;data.host_only=$('[name=host_only]',event.target).checked&&!data.sandbox;try{const result=await send('/api/games',data);$('#create-dialog').close();selectedPower=data.power;activeTab='orders';await loadGame(result.id);notice(data.sandbox?'Your private sandbox is ready.':'Your table is ready. Invite friends from the Powers panel.');}catch(error){$('#create-error').textContent=error.message;}finally{button.disabled=false;}};
$('#join-form').onsubmit=async event=>{event.preventDefault();event.submitter.disabled=true;try{const result=await send('/api/join',Object.fromEntries(new FormData(event.target)));$('#join-dialog').close();activeTab='orders';await loadGame(result.id);notice('You have taken your seat. Let the negotiations begin.');}catch(error){$('#join-error').textContent=error.message;}finally{event.submitter.disabled=false;}};
$('#logout-button').onclick=async()=>{try{await send('/api/logout',{});user=null;csrf='';game=null;gameTarget='';dirty=false;location.hash='';$('#games-dialog').close();render();await loadMap();notice('Signed out.');}catch(error){notice(error.message);}};
$('#games-list').onclick=async event=>{const button=event.target.closest('[data-game]');if(!button)return;try{$('#games-dialog').close();activeTab='orders';await loadGame(button.dataset.game);}catch(error){notice(error.message);}};
$$('.panel-tabs button').forEach(button=>{button.onclick=()=>{activeTab=button.dataset.tab;renderPanel();};button.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const tabs=$$('.panel-tabs button');let index=tabs.indexOf(button);index=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[index].click();tabs[index].focus();};});
$('#tab-content').addEventListener('click',async event=>{
  const target=event.target.closest('button');if(!target)return;
  if(target.dataset.action==='set-drunk'){try{await send(`/api/games/${game.id}/drunk-power`,{power:$('#drunk-setup').value},'PUT');await loadGame(game.id);notice('Drunk-country setting saved.');}catch(error){notice(error.message);}return;}
  if(target.dataset.action)return action(target.dataset.action).catch(error=>notice(error.message));
  if(target.dataset.type){orderType=target.dataset.type;mapOrigin=selectedLocation;mapAssist=null;renderPanel();if(['S','C'].includes(orderType))$('#map-hint').textContent=orderType==='C'?'Convoy an army: click its starting province, then its destination.':'Click the unit to support, then its destination';if(orderType==='H'){const order=$('#order-select')?.value;if(order)await enqueueMapAction(()=>putOrder(order));}else $('#order-select')?.focus();return;}
  if(target.dataset.remove!==undefined){const index=Number(target.dataset.remove);await enqueueMapAction(async()=>{draft.splice(index,1);dirty=true;rememberDraft();renderPanel();if(game.sandbox)await saveOrders(true);else await loadMap();});return;}
  if(target.dataset.history){historicalPhase=target.dataset.history;render();await loadMap();return;}
  if(target.id==='add-order'){const order=$('#order-select').value;if(order)await enqueueMapAction(()=>putOrder(order));}
  if(target.id==='save-draft'){await mapActions;await saveOrders(false);}
  if(target.id==='submit-orders'){await mapActions;await saveOrders(true);}
  if(target.id==='adjudicate')await adjudicate();
});
$('#tab-content').addEventListener('change',async event=>{if(event.target.id==='power-control'){const nextPower=event.target.value;await mapActions;rememberDraft();selectedPower=nextPower;loadDraft();renderPanel();highlightLocation();loadMap();}if(event.target.id==='order-select'){const order=event.target.value;enqueueMapAction(()=>putOrder(order));}if(event.target.id==='unit-select'){selectedLocation=event.target.value;mapOrigin=selectedLocation;inspectedProvince=selectedLocation.slice(0,3);renderProvince();renderPanel();highlightLocation();}});
$('#map').addEventListener('click',event=>{const region=event.target.closest('[data-province]');if(region)enqueueMapAction(()=>chooseProvince(region.dataset.province));});
$('#map').addEventListener('keydown',event=>{if(event.key==='Escape'){mapOrigin='';mapAssist=null;$('#map-hint').textContent='Order selection cancelled. Click any unit to begin.';return;}if(event.key==='Enter'||event.key===' '){const region=event.target.closest('[data-province]');if(region){event.preventDefault();enqueueMapAction(()=>chooseProvince(region.dataset.province));}}});
function setZoom(value){zoom=Math.min(2.5,Math.max(1,value));$('#map').style.width=`${zoom*100}%`;$('#zoom-label').textContent=`${Math.round(zoom*100)}%`;$('#zoom-out').disabled=zoom===1;$('#zoom-in').disabled=zoom===2.5;$('.map-cartouche').hidden=zoom>1;}
$('#zoom-in').onclick=()=>setZoom(zoom+.25);$('#zoom-out').onclick=()=>setZoom(zoom-.25);
$('#clean-map').onclick=()=>{clean=!clean;$('#map svg')?.classList.toggle('clean',clean);$('#clean-map').setAttribute('aria-pressed',String(clean));};
async function downloadGame(dbn=false){try{const data=await api(`/api/games/${game.id}/export${dbn?'/dbn':''}`);const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`entente-${game.id}-${game.phase}${dbn?'-dbn':''}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){notice(error.message);}}
$('#export-button').onclick=()=>downloadGame();
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
async function init(){render();setZoom(1);try{const results=await Promise.all([api('/api/me'),api('/api/provinces')]);user=results[0].user;csrf=results[0].csrf;provinces=results[1].regions;const match=location.hash.match(/^#game=([\w-]+)$/);if(user&&match)await loadGame(match[1]);else{render();await loadMap();}}catch(error){notice(error.message);await loadMap();}}
setInterval(()=>{if(game&&user&&!document.hidden&&!$('dialog[open]'))loadGame(game.id,true).catch(error=>{if(error.status===401)notice('Your session expired. Sign in again to continue.');});},15000);
init();
