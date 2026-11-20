// Recover only editable values; the server-owned quote snapshot never lives in a draft.
export function createDraftGuard({dialog,form,busy,onRestore}){
 let key,baseline='',returnFocus;
 const values=()=>Object.fromEntries([...form.elements].filter(e=>e.name&&(!['radio','checkbox'].includes(e.type)||e.checked)).map(e=>[e.name,e.type==='checkbox'?true:e.value]));
 const serial=()=>JSON.stringify(values());
 const notice=document.createElement('section');notice.className='journal-discard';notice.hidden=true;notice.setAttribute('aria-label','Unsaved changes');
 const message=document.createElement('p'),keep=document.createElement('button'),discard=document.createElement('button');keep.type=discard.type='button';notice.append(message,keep,discard);dialog.querySelector('.dialog-heading').after(notice);
 const clear=()=>{try{localStorage.removeItem(key);}catch{}};
 const close=()=>{clear();notice.hidden=true;dialog.close();};
 const resetNotice=()=>{notice.hidden=true;(returnFocus?.isConnected?returnFocus:form.querySelector('input'))?.focus({preventScroll:true});};
 function requestClose(){if(serial()===baseline){dialog.close();return;}
  returnFocus=document.activeElement;notice.hidden=false;message.textContent=busy()?'A save is in progress and may still complete. Close this form?':'Discard these changes? Your edited values have not been saved.';keep.textContent='Keep editing';discard.textContent=busy()?'Close form':'Discard changes';keep.onclick=resetNotice;discard.onclick=close;keep.focus({preventScroll:true});
 }
 dialog.addEventListener('cancel',event=>{event.preventDefault();requestClose();});
 form.addEventListener('input',()=>{if(!key)return;try{if(serial()===baseline)clear();else localStorage.setItem(key,serial());}catch{}});
 window.addEventListener('beforeunload',event=>{if(dialog.open&&serial()!==baseline){event.preventDefault();event.returnValue='';}});
 return {
  requestClose,
  saved(){clear();baseline=serial();notice.hidden=true;},
  start(id){key='predict-journal-draft-v1:'+id;baseline=serial();notice.hidden=true;let draft;try{draft=JSON.parse(localStorage.getItem(key));}catch{}
   if(!draft||JSON.stringify(draft)===baseline)return;
   notice.hidden=false;message.textContent='An unsaved draft is available for this bet.';keep.textContent='Restore draft';discard.textContent='Dismiss draft';
   keep.onclick=()=>{for(const e of form.elements){if(!e.name)continue;if(e.type==='radio')e.checked=draft[e.name]===e.value;else if(e.type==='checkbox')e.checked=draft[e.name]===true;else if(Object.hasOwn(draft,e.name))e.value=draft[e.name];}notice.hidden=true;onRestore();};
   discard.onclick=()=>{clear();notice.hidden=true;};
  }
 };
}
