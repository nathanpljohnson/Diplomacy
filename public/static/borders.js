'use strict';
const form=document.querySelector('.study-controls');
function updateStudy(){
 const area=document.querySelector('#study-area').value;
 const level=form.querySelector('[name=treatment]:checked').value;
 document.querySelector('#original-map').src=`/static/border-study/${area}-0.svg`;
 document.querySelector('#angular-map').src=`/static/border-study/${area}-${level}.svg`;
 document.querySelector('#original-map').alt=`Current curved province outlines in ${area==='central'?'central Europe':'Europe'}`;
 document.querySelector('#angular-map').alt=`${level==='1'?'Faceted':'Geometric'} concept province outlines in ${area==='central'?'central Europe':'Europe'}`;
 document.querySelector('#angular-title').textContent=level==='1'?'Faceted atlas':'Geometric atlas';
 document.querySelector('#angular-description').textContent=level==='1'?'Crisper corners, with the geographic silhouette retained.':'Stronger angles and a more schematic silhouette.';
 document.querySelector('#study-status').textContent=`Showing ${area==='central'?'central Europe':'all of Europe'} with ${level==='1'?'faceted':'geometric'} borders.`;
 for(const img of document.querySelectorAll('.study-map img'))img.height=area==='central'?940:850;
}
form.addEventListener('change',updateStudy);
