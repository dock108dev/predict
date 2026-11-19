// Filter controls remain in the page flow. Clearing a filter keeps the chosen rank.
export function bindBoardFilters(form,{dataType='' }={}){
 const chips=document.getElementById('active-filters'),reset=document.getElementById('reset-filters');
 const labels={search:'Search',league:'League',family:'Market',venue:'Venue',category:'Pair type',book:'Sportsbook',data_type:'Data',max_age_minutes:'Quote age'};
 const defaults={data_type:dataType};
 const buttons=new Map();
 const field=name=>form.elements.namedItem(name);
 const changed=()=>form.dispatchEvent(new Event('input',{bubbles:true}));
 function sync(){
  const keep=[];
  for(const [name,label]of Object.entries(labels)){
   const control=field(name),value=control?.value||'';
   if(!value||value===(defaults[name]||''))continue;
   let chip=buttons.get(name);
   if(!chip){
    chip=document.createElement('button');chip.type='button';chip.className='filter-chip';
    chip.setAttribute('aria-label','Remove '+label+' filter');
    chip.onclick=()=>{control.value=defaults[name]||'';changed();control.focus({preventScroll:true});};
    buttons.set(name,chip);
   }
   const text=control.tagName==='SELECT'?control.selectedOptions[0]?.textContent:value+(name==='max_age_minutes'?'m':'');
   const caption=label+': '+text+' ×';if(chip.textContent!==caption)chip.textContent=caption;
   keep.push(chip);
  }
  // A blur/change between pointerdown and click must not remove the pressed chip.
  for(const child of [...chips.children])if(!keep.includes(child))child.remove();
  let before=chips.firstElementChild;
  for(const chip of keep){if(chip!==before)chips.insertBefore(chip,before);before=chip.nextElementSibling;}
  chips.hidden=!chips.childElementCount;reset.disabled=chips.hidden;
 }
 reset.onclick=()=>{for(const name of Object.keys(labels)){const control=field(name);if(control)control.value=defaults[name]||'';}changed();};
 form.addEventListener('input',sync);form.addEventListener('change',sync);sync();
 document.getElementById('show-filters').onclick=()=>{form.scrollIntoView({block:'start'});field('search')?.focus({preventScroll:true});};
 return {sync};
}
