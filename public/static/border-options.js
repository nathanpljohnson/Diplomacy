
const options=[
 ['clean','Clean expanding outlines','One thin dark country edge replaces the pale seam. Internal province lines stay finer.','Expands with control','Most direct replacement'],
 ['tinted','Color-matched expanding outlines','Dark shades of each country’s own color define its outer edge. Softer than black, with the same expansion.','Expands with control','A softer atlas look'],
 ['colors','Colors only','Every province gets the same thin border. Country colors expand, with no separate thick country outline.','Only colors expand','Quietest map'],
 ['fixed','Fixed original outlines','Original country outlines remain in place even when territory changes hands. Ownership is shown by fill color.','Outlines stay fixed','Stable historical reference'],
 ['frontiers','Land-frontier accents','Dark accents appear only between differently controlled land. Coastlines and sea boundaries stay thin.','Land frontiers expand','Less coastal clutter']
];
let state='expanded',view='detail';
const grid=document.querySelector('#grid');
grid.innerHTML=options.map(([key,title,description,tag,summary],i)=>`<article class="card" data-key="${key}"><div class="card-top"><span class="number">OPTION ${i+1} / 05</span><h2>${title}</h2><p>${description}</p></div><a class="preview" target="_blank" rel="noopener" title="Open full-size map"><img alt="${title}" width="710" height="570"></a><div class="error" role="alert">This preview could not load.<br><button type="button">Retry</button></div><div class="card-bottom"><span class="tag">${tag}</span><span>${summary} ↗</span></div></article>`).join('');
function update(){
 document.querySelector('#state-note').textContent=state==='start'?'1901 starting control: all five options show the same initial territories. Switch to the captured-territory example to see which outlines move.':'Example: Belgium (BEL) and Holland (HOL) are French. Compare whether the outline moves with the colors.';
 document.querySelectorAll('.card').forEach(card=>{const key=card.dataset.key;card.classList.remove('failed');card.classList.toggle('full',view==='full');const img=card.querySelector('img');img.src=`/static/border-options/${state}-${key}-${view}.svg`;img.alt=`${card.querySelector('h2').textContent} — ${state==='start'?'1901 starting control':'France owns Belgium and Holland'} — ${view==='full'?'full map':'Central Europe detail'}`;card.querySelector('.preview').href=`/static/border-options/${state}-${key}-full.svg`;});
}
document.querySelectorAll('[name=state]').forEach(input=>input.onchange=()=>{state=input.value;update();});
document.querySelector('#view').onchange=event=>{view=event.target.value;update();};
document.querySelectorAll('.card').forEach(card=>{const img=card.querySelector('img');img.onerror=()=>card.classList.add('failed');card.querySelector('.error button').onclick=()=>{card.classList.remove('failed');img.src=img.src.split('?')[0]+'?retry='+Date.now();};});
update();
