// A pending save keeps its inspected quote; redraws may supply a newer one.
export function recordAction(snapshot,existing){
 if(existing?.updateQuote){existing.updateQuote(snapshot);return existing;}
 const button=document.createElement('button');button.type='button';button.className='record-bet';button.textContent='Record bet';button.dataset.focusKey='record-'+snapshot.id;
 button.recordStatus=document.createElement('span');button.recordStatus.setAttribute('role','status');
 let current=structuredClone(snapshot);
 button.updateQuote=value=>{current=structuredClone(value);};
 button.onclick=async()=>{
  if(button.disabled)return;
  const frozen=structuredClone(current);button.disabled=true;button.textContent='Saving quote…';button.recordStatus.textContent='Saving a research quote first. Actual stake and odds are entered on My Bets.';
  try{
   const response=await fetch('/api/bet-journal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'ev',snapshot:frozen})});
   if(!response.ok){const error=Error();error.rejected=[400,403,413,415,422].includes(response.status);throw error;}const data=await response.json();const id=(data.entry||data).id;if(!id)throw Error();
   button.recordStatus.textContent='Quote saved. No bet has been recorded.';
   if(button.isConnected&&button.closest('dialog')?.open)location.assign('/my-bets?'+new URLSearchParams({entry:id,record:'1'}));
  }catch(error){button.textContent='Retry record bet';button.recordStatus.textContent=error.rejected?'Quote rejected; nothing saved by this request. No bet recorded.':'Quote save unconfirmed; it may have persisted. Check My Bets or retry the same quote safely. No bet was recorded.';}
  finally{button.disabled=false;}
 };
 return button;
}
export function journalAction(kind, snapshot, label, existing) {
  if(existing?.updateQuote){existing.updateQuote(snapshot,label);return existing;}
  const section=document.createElement('section');section.className='journal-action';
  const button=document.createElement('button');button.type='button';
  const status=document.createElement('span');status.setAttribute('role','status');
  let current=structuredClone(snapshot),currentLabel=label||'Save to My Bets',pending=false,saved,failed=false;
  const sameSaved=()=>saved?.fingerprint===JSON.stringify(current);
  const render=()=>{
    button.disabled=pending||sameSaved();
    section.dataset.state=pending?'saving':sameSaved()?'saved':failed?'error':'idle';
    if(button.dataset.compact){
      const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS(svg.namespaceURI,'path');
      svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
      path.setAttribute('d',sameSaved()?'M6 3h12v18l-6-4-6 4V3Z M9 9l2 2 4-4':'M6 3h12v18l-6-4-6 4V3Z');svg.append(path);button.replaceChildren(svg);
      button.setAttribute('aria-label',pending?'Saving to research':sameSaved()?'Saved to research':currentLabel);
      button.title=pending?'Saving…':sameSaved()?'Saved to research':failed?'Retry saving to research':'Save to research';
    }else button.textContent=pending?'Saving…':sameSaved()?'Saved to My Bets':button.dataset.shortLabel||currentLabel;
    if(saved&&button.dataset.compact){status.textContent=sameSaved()?'Saved':'Earlier quote saved';}
    else if(saved){
      const link=document.createElement('a');link.href='/my-bets?'+new URLSearchParams({entry:saved.id});link.textContent='Enter actual odds & stake →';
      status.replaceChildren(document.createTextNode(sameSaved()?'Saved. ':'Earlier quote saved. '),link);
    }
  };
  section.setCompact=()=>{button.dataset.compact='true';render();};
  section.updateQuote=(value,text)=>{current=structuredClone(value);currentLabel=text||currentLabel;render();};
  button.onclick=async event=>{
    // Rendering a new SVG detaches the hit path before a card's click handler runs.
    event.stopPropagation();
    const frozen=structuredClone(current),fingerprint=JSON.stringify(frozen);
    pending=true;saved=null;failed=false;render();status.textContent='Saving…';
    try{
      const response=await fetch('/api/bet-journal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,snapshot:frozen})});
      const data=await response.json();
      if(!response.ok){const error=Error(data.message||data.error||'Save failed');error.rejected=[400,403,413,415,422].includes(response.status);throw error;}
      const id=(data.entry||data).id;if(!id)throw Error();saved={id,fingerprint};
    }catch(e){failed=true;status.textContent=e.rejected?'Could not save: quote rejected. No record saved by this request.':'Could not confirm save; the quote may have persisted. Check My Bets or retry the same quote safely.';}
    finally{pending=false;render();}
  };
  section.append(button,status);render();return section;
}
