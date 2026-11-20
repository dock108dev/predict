// Session-only research context, restored before the first data request/chip render.
export function boardContext(form,{position=()=>({x:scrollX,y:scrollY}),extra=()=>({})}={}){
 const params=new URLSearchParams(location.search),identity=['game_key','bet_id','id','line','quote_key'].map(k=>params.get(k)||'').join(':');
 const key='predict-board-context-v1:'+location.pathname+':'+identity;let saved;
 try{saved=JSON.parse(sessionStorage.getItem(key)||'null');}catch{}
 function restore(){const fields={...saved?.fields};for(const [name,value]of params)if(form.elements.namedItem(name))fields[name]=value;for(const [name,value]of Object.entries(fields)){const control=form.elements.namedItem(name);if(control){if(control.type==='checkbox')control.checked=value;else{if(control.tagName==='SELECT'&&![...control.options].some(o=>o.value===value))control.add(new Option(value,value));control.value=value;}}}for(const e of form.querySelectorAll('details'))e.open=Boolean(saved?.expanded?.includes(e.id));}
 function save(){const fields={};for(const control of form.elements)if(control.name)fields[control.name]=control.type==='checkbox'?control.checked:control.value;try{sessionStorage.setItem(key,JSON.stringify({fields,expanded:[...form.querySelectorAll('details[open]')].map(e=>e.id),position:position(),...extra()}));}catch{}}
 restore();window.addEventListener('pagehide',save);form.addEventListener('input',save);form.addEventListener('change',save);
 let restored=false;
 return {saved,save,restore,afterRender(){if(restored)return;restored=true;if(saved?.position){const apply=()=>scrollTo(saved.position.x,saved.position.y);apply();requestAnimationFrame(()=>{if(!document.querySelector('dialog[open]'))apply();});}}};
}
