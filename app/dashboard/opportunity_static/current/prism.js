import {palettes,themeTokens,defaultAppearance,appearanceModes,validAppearance} from './prism-theme.js';

const root=document.documentElement,cacheKey='predict-personal-appearance-v1';
let saved=defaultAppearance,draft,pending=false;
try{const cached=JSON.parse(localStorage.getItem(cacheKey));if(validAppearance(cached))saved=cached;}catch{}
function apply(value){
 const {dark,tokens}=themeTokens(value,value.appearance);
 root.dataset.appearance=dark?'dark':'light';
 for(const [key,color]of Object.entries(tokens))root.style.setProperty('--'+key,color);
 root.style.colorScheme=dark?'dark':'light';
}
apply(saved);
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text)e.textContent=text;if(cls)e.className=cls;return e;};
const trigger=node('button','◉ Theme','theme-trigger');trigger.type='button';trigger.setAttribute('aria-haspopup','dialog');trigger.setAttribute('aria-controls','theme-dialog');
document.querySelector('.masthead')?.append(trigger);
const dialog=node('dialog',null,'theme-dialog');dialog.id='theme-dialog';dialog.setAttribute('aria-labelledby','theme-title');
const heading=node('h2','Appearance');heading.id='theme-title';
const form=node('form'),grid=node('fieldset',null,'theme-grid'),legend=node('legend','Color palette');grid.append(legend);
for(const palette of palettes){const label=node('label',null,'theme-palette'),input=node('input');input.type='radio';input.name='palette';input.value=palette.id;
 const swatch=node('span',null,'theme-swatches');swatch.setAttribute('aria-hidden','true');swatch.style.background=`linear-gradient(90deg,${palette.primary} 50%,${palette.secondary} 50%)`;
 label.append(input,swatch,node('span',palette.name));grid.append(label);
}
const custom=node('div',null,'theme-custom');
for(const key of ['primary','secondary']){const label=node('label','Custom '+key+' color'),input=node('input');input.type='color';input.name=key;label.append(input);custom.append(label);}
const label=node('label','Appearance'),appearance=node('select');appearance.name='appearance';
for(const value of appearanceModes)appearance.append(new Option(value[0].toUpperCase()+value.slice(1),value));label.append(appearance);
const status=node('p');status.setAttribute('role','status');
const actions=node('div',null,'theme-actions'),cancel=node('button','Cancel'),commit=node('button','Apply theme','primary-button');cancel.type='button';commit.type='submit';actions.append(cancel,commit);
form.append(grid,custom,label,status,actions);dialog.append(heading,form);document.body.append(dialog);
function preview(){apply(draft);}
trigger.onclick=()=>{draft=structuredClone(saved);for(const input of grid.querySelectorAll('input'))input.checked=input.value===draft.palette;
 form.elements.primary.value=draft.primary;form.elements.secondary.value=draft.secondary;appearance.value=draft.appearance;status.textContent='';dialog.showModal();};
form.oninput=event=>{const {name,value}=event.target;if(name==='palette'){const p=palettes.find(p=>p.id===value);draft={...draft,palette:p.id,primary:p.primary,secondary:p.secondary};form.elements.primary.value=p.primary;form.elements.secondary.value=p.secondary;}
 else if(name==='appearance')draft.appearance=value;
 else if(['primary','secondary'].includes(name)){draft[name]=value;draft.palette='custom';for(const input of grid.querySelectorAll('input'))input.checked=false;}preview();};
const close=()=>{if(pending)return;apply(saved);dialog.close();};cancel.onclick=close;
dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
dialog.addEventListener('close',()=>{apply(saved);trigger.focus({preventScroll:true});});
form.onsubmit=async event=>{event.preventDefault();if(pending)return;pending=true;for(const input of form.elements)input.disabled=true;status.textContent='Saving appearance…';
 try{const response=await fetch('/api/appearance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(draft)});if(!response.ok)throw Error();saved=await response.json();try{localStorage.setItem(cacheKey,JSON.stringify(saved));}catch{}dialog.close();}
 catch{status.textContent='Appearance could not be saved. Your preview is preserved; retry or Cancel.';}
 finally{pending=false;for(const input of form.elements)input.disabled=false;}
};
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>apply(dialog.open?draft:saved));
fetch('/api/appearance',{cache:'no-store'}).then(r=>r.ok?r.json():null).then(value=>{if(validAppearance(value)){saved=value;try{localStorage.setItem(cacheKey,JSON.stringify(saved));}catch{}if(!dialog.open)apply(saved);}}).catch(()=>{});

// Collapse secondary filters in the normal page flow; names and API queries stay intact.
const filters=document.getElementById('filters'),advanced=document.querySelector('.advanced-fields');
if(filters&&advanced){for(const field of [...filters.querySelectorAll(':scope > .filter-field')])advanced.prepend(field);
 document.querySelector('.advanced-filters>summary').textContent='Filters';
 const age=document.querySelector('label[for="max-age"]>span');if(age)age.textContent='Maximum source age (minutes)';
 const refresh=document.getElementById('refresh');document.querySelector('.board-info')?.append(refresh);
}
for(const link of document.querySelectorAll('.masthead nav a')){
 const path=location.pathname==='/'||location.pathname==='/ev'?'/':location.pathname;
 if(link.getAttribute('href')===path)link.setAttribute('aria-current','page');
}
