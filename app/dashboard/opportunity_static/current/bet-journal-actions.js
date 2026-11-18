// A pending save keeps its inspected quote; redraws may supply a newer one.
export function journalAction(kind, snapshot, label, existing) {
  if(existing?.updateQuote){existing.updateQuote(snapshot,label);return existing;}
  const section=document.createElement('section');section.className='journal-action';
  const button=document.createElement('button');button.type='button';
  const status=document.createElement('span');status.setAttribute('role','status');
  let current=structuredClone(snapshot),currentLabel=label||'Save to My Bets',pending=false,saved;
  const sameSaved=()=>saved?.fingerprint===JSON.stringify(current);
  const render=()=>{
    button.disabled=pending||sameSaved();
    button.textContent=pending?'Saving…':sameSaved()?'Saved to My Bets':button.dataset.shortLabel||currentLabel;
    if(saved){
      const link=document.createElement('a');link.href='/my-bets?'+new URLSearchParams({entry:saved.id});link.textContent='Enter actual odds & stake →';
      status.replaceChildren(document.createTextNode(sameSaved()?'Saved. ':'Earlier quote saved. '),link);
    }
  };
  section.updateQuote=(value,text)=>{current=structuredClone(value);currentLabel=text||currentLabel;render();};
  button.onclick=async()=>{
    const frozen=structuredClone(current),fingerprint=JSON.stringify(frozen);
    pending=true;saved=null;render();status.textContent='Saving…';
    try{
      const response=await fetch('/api/bet-journal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,snapshot:frozen})});
      const data=await response.json();
      if(!response.ok)throw Error(data.message||data.error||'Save failed');
      saved={id:(data.entry||data).id,fingerprint};
    }catch(e){status.textContent=fingerprint===JSON.stringify(current)?'Could not save. Retry to keep this quote.':'Could not save the earlier quote. Retry to save the displayed quote.';}
    finally{pending=false;render();}
  };
  section.append(button,status);render();return section;
}
