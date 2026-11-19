import {bindDialogClose} from './dialog-close.js';

const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
const ownerSession='predict-owner-mode-controls-v1',activityThrottle=15000;
const durations=[
 ['monitor_interval_seconds','Monitor refresh','minutes',60,1,120,1],
 ['live_interval_seconds','Live refresh','seconds',1,15,300,15],
 ['live_window_seconds','Live games start within','minutes',60,5,180,5],
 ['inactivity_seconds','Turn Live off after inactivity','minutes',60,1,60,1],
];
const minutes=seconds=>Number.isFinite(seconds)?Number((seconds/60).toFixed(2))+'m':'—';
const valid=value=>value&&['monitor','live'].includes(value.mode)&&value.settings;
function ownerOptIn(){try{return sessionStorage.getItem(ownerSession)==='1';}catch{return false;}}
function rememberOwner(enabled){try{if(enabled)sessionStorage.setItem(ownerSession,'1');else sessionStorage.removeItem(ownerSession);}catch{}}
async function request(url,options={}){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),5000);
 try{
  const response=await fetch(url,{cache:'no-store',credentials:'same-origin',...options,signal:controller.signal});
  if(response.status===401)return {unauthorized:true};
  if(!response.ok)throw Error('HTTP '+response.status);
  const packet=await response.json(),value=packet.activity_mode||packet;if(!valid(value))throw Error('Mode status is unavailable');return value;
 }finally{clearTimeout(timer);}
}
export function createModeSettings(onModeChange=()=>{}){
 let state=null,owner=false,pollTimer,refreshing=false,lastActivity=0,activityPending=false,dialogReturn,formDirty=false;
 const controls=node('div',undefined,'mode-controls'),open=node('button','Mode settings','mode-badge');open.type='button';open.id='mode-settings-open';controls.append(open);
 document.querySelector('.board-info')?.prepend(controls);
 const dialog=node('dialog',undefined,'mode-settings-dialog');dialog.id='mode-settings';dialog.setAttribute('aria-labelledby','mode-settings-title');
 const heading=node('div',undefined,'dialog-heading'),title=node('h2','Collection settings'),close=node('button','×');title.id='mode-settings-title';close.type='button';close.setAttribute('aria-label','Close collection settings');heading.append(title,close);
 const body=node('div',undefined,'mode-settings-body'),summary=node('p','Loading collection settings…','mode-summary'),access=node('p',undefined,'mode-access'),message=node('p',undefined,'mode-message');message.setAttribute('role','status');
 const signIn=node('a','Sign in through Admin →');signIn.href='/admin?section=settings';access.append(signIn);
 const choices=node('div',undefined,'mode-choices'),switchLabel=node('label',undefined,'mode-switch'),live=node('input'),track=node('span',undefined,'mode-switch-track'),runSummary=node('p',undefined,'mode-run-summary');live.type='checkbox';live.setAttribute('role','switch');live.setAttribute('aria-label','Live mode');live.disabled=true;track.setAttribute('aria-hidden','true');switchLabel.append(live,track,node('span','Live mode'));choices.append(switchLabel);
 const form=node('form',undefined,'mode-settings-form'),fields=new Map();
 for(const [key,label,unit,multiplier,min,max,step]of durations){
  const field=node('label',undefined,'mode-setting'),text=node('span',label),value=node('input'),range=node('input'),inputs=node('div',undefined,'mode-setting-inputs');
  value.type='number';value.min=String(1/multiplier);value.max=String(31536000/multiplier);value.step=unit==='seconds'?'1':'any';value.required=true;value.setAttribute('aria-label',label+' ('+unit+')');
  range.type='range';range.min=String(min);range.max=String(max);range.step=String(step);range.setAttribute('aria-label',label+' slider');
  range.oninput=()=>{value.value=range.value;};value.oninput=()=>{range.value=value.value;};
  inputs.append(range,value,node('small',unit));field.append(text,inputs);form.append(field);fields.set(key,{value,range,multiplier});
 }
 const horizonLabel=node('label',undefined,'mode-setting'),horizon=node('select'),hours=node('input');horizon.setAttribute('aria-label','Monitor games start within');
 for(const [value,label]of [['86400','24 hours'],['259200','72 hours'],['all','All future games'],['custom','Custom hours']]){const option=node('option',label);option.value=value;horizon.append(option);}
 hours.type='number';hours.min=String(1/3600);hours.max='8760';hours.step='any';hours.setAttribute('aria-label','Custom monitor horizon hours');hours.hidden=true;horizon.onchange=()=>{hours.hidden=horizon.value!=='custom';};
 horizonLabel.append(node('span','Monitor games start within'),horizon,hours);form.append(horizonLabel);
 form.addEventListener('input',()=>{formDirty=true;});
 const save=node('button','Save settings');save.type='submit';save.disabled=true;form.append(save);
 const note=node('p','Monitor continues in the background. Live targets pregame games in its selected window while you are active, then returns to Monitor after inactivity. Existing source Stop and pause choices stay in effect.','mode-explanation');
 body.append(summary,choices,runSummary,access,form,note,message);dialog.append(heading,body);document.body.append(dialog);bindDialogClose(close,dialog);
 function permissions(){
  for(const control of [...form.querySelectorAll('input,select,button'),live])control.disabled=!owner;
  access.hidden=owner;
 }
 function render(){
  if(!state){open.textContent='Collection settings';return;}
  open.textContent=(state.mode==='live'?'Live':'Monitor')+' · '+minutes(state.mode==='live'?state.settings.live_interval_seconds:state.settings.monitor_interval_seconds);
  open.dataset.mode=state.mode;open.setAttribute('aria-label',open.textContent+'. Open collection settings');
  summary.textContent=state.mode==='live'?'Live · pregame games starting within '+minutes(state.settings.live_window_seconds)+' · target every '+minutes(state.settings.live_interval_seconds):'Monitor · target every '+minutes(state.settings.monitor_interval_seconds);
  if(state.reason==='inactivity')summary.textContent+=' · Live ended after inactivity';
  live.checked=state.mode==='live';
  const runLabels={budget_delayed:'waiting for budget',partial:'partial update',running:'updating',complete:'complete',failed:'update failed'};runSummary.textContent=Object.entries(state.runs||{}).map(([kind,run])=>(kind==='live'?'Live':'Monitor')+': '+(runLabels[run.state]||'update pending')+(run.completed_at?' · '+new Date(run.completed_at).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'}):'')).join(' · ');runSummary.hidden=!runSummary.textContent;
  if(!formDirty){
   for(const [key,field]of fields){field.value.value=String(state.settings[key]/field.multiplier);field.range.value=field.value.value;}
   const seconds=state.settings.monitor_horizon_seconds;
   horizon.value=seconds===null?'all':[86400,259200].includes(seconds)?String(seconds):'custom';hours.hidden=horizon.value!=='custom';hours.value=seconds===null?'':String(seconds/3600);
  }
  permissions();
 }
 function update(value,refresh=false){
  if(!valid(value)||state&&Number(value.revision)<Number(state.revision))return;const changed=state&&(state.mode!==value.mode||state.settings.live_window_seconds!==value.settings.live_window_seconds||state.settings.monitor_horizon_seconds!==value.settings.monitor_horizon_seconds);state=value;render();
  if(!pollTimer)pollTimer=setInterval(async()=>{if(document.hidden||refreshing)return;refreshing=true;try{update(await request('/api/pregame?mode_status=1'),true);}catch{}finally{refreshing=false;}},15000);
  if(refresh&&changed)onModeChange(state);
 }
 async function authorize(){
  try{const value=await request('/api/admin/activity-mode');owner=!value.unauthorized;if(owner){rememberOwner(true);update(value,true);}else rememberOwner(false);permissions();return owner;}
  catch{owner=false;permissions();message.textContent='Owner controls could not be verified. Reopen collection settings to retry.';return false;}
 }
 async function change(body){
  if(!owner)return;message.textContent='Saving…';
  try{
   const value=await request('/api/admin/activity-mode',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   if(value.unauthorized){owner=false;rememberOwner(false);permissions();render();message.textContent='Sign in through Admin to change collection settings.';return;}
   formDirty=false;update(value,true);message.textContent='Collection settings saved.';
  }catch{render();message.textContent='Collection settings could not be saved. Your previous settings remain in effect.';}
 }
 live.onchange=()=>change({mode:live.checked?'live':'monitor'});
 form.onsubmit=event=>{
  event.preventDefault();if(!owner||!form.reportValidity())return;const settings={};
  for(const [key,field]of fields)settings[key]=Math.round(Number(field.value.value)*field.multiplier);
  settings.monitor_horizon_seconds=horizon.value==='all'?null:horizon.value==='custom'?Math.round(Number(hours.value)*3600):Number(horizon.value);
  if(Object.values(settings).some(value=>value!==null&&(!Number.isInteger(value)||value<=0||value>31536000))){message.textContent='Choose a positive duration within one year.';return;}
  change({settings});
 };
 open.onclick=async event=>{
  dialogReturn={trigger:event.currentTarget,x:scrollX,y:scrollY,style:['position','top','left','width'].map(name=>[name,document.body.style.getPropertyValue(name),document.body.style.getPropertyPriority(name)])};
  Object.assign(document.body.style,{position:'fixed',top:-scrollY+'px',left:-scrollX+'px',width:'100%'});formDirty=false;render();dialog.showModal();message.textContent='';
  const results=await Promise.allSettled([request('/api/pregame?mode_status=1'),authorize()]);if(results[0].status==='fulfilled')update(results[0].value,true);else if(!state)summary.textContent='Collection status could not be loaded.';
 };
 dialog.addEventListener('close',()=>{if(!dialogReturn)return;const saved=dialogReturn;dialogReturn=null;for(const [name,value,priority]of saved.style){if(value)document.body.style.setProperty(name,value,priority);else document.body.style.removeProperty(name);}scrollTo(saved.x,saved.y);saved.trigger?.focus({preventScroll:true});});
 async function activity(event){
  const throttle=Math.min(activityThrottle,(state?.settings.inactivity_seconds||45)*1000/3);
  if(!event.isTrusted||document.hidden||!owner||state?.mode!=='live'||activityPending||Date.now()-lastActivity<throttle||!Number.isFinite(Date.parse(state.live_until))||Date.parse(state.live_until)<=Date.now())return;
  lastActivity=Date.now();activityPending=true;
  try{const value=await request('/api/admin/activity-mode/activity',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(value.unauthorized){owner=false;rememberOwner(false);permissions();}else update(value,true);}catch{}finally{activityPending=false;}
 }
 for(const type of ['pointerdown','pointermove','keydown','touchstart','wheel'])document.addEventListener(type,activity,{passive:true,capture:true});
 if(ownerOptIn())authorize();
 permissions();return {update};
}
export function collectionBadge(row){
 const kind=row.collection?.kind;if(!['monitor','live'].includes(kind))return null;
 const badge=node('span',kind==='live'?'Live':'Monitor','collection-badge');badge.dataset.kind=kind;
 badge.title=row.collection.origin==='legacy_retained'?'Retained baseline adopted '+(row.collection.observed_at||'at an unknown time')+'; original source clocks shown with quote':'Collected '+(row.collection.observed_at||'at an unknown time');return badge;
}
