import {bookName} from './pregame-labels.js';

// Keep the quote that the person inspected, even if the board refreshes.
export function journalAction(kind, snapshot, label) {
  const section=document.createElement('section');section.className='journal-action';
  const button=document.createElement('button');button.type='button';
  button.textContent=label||'Save to My Bets';
  const status=document.createElement('span');status.setAttribute('role','status');
  const frozen=structuredClone(snapshot);
  button.onclick=async()=>{
    button.disabled=true;status.textContent='Saving…';
    try{
      const response=await fetch('/api/bet-journal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,snapshot:frozen})});
      const data=await response.json();
      if(!response.ok)throw Error(data.message||data.error||'Save failed');
      const entry=data.entry||data;
      const link=document.createElement('a');link.href='/my-bets?'+new URLSearchParams({entry:entry.id});link.textContent='Enter actual odds & stake →';
      status.replaceChildren(document.createTextNode('Saved. '),link);button.textContent='Saved to My Bets';
    }catch(e){status.textContent='Could not save. Retry to keep this quote.';button.disabled=false;}
  };
  section.append(button,status);return section;
}

export function journalVenueActions(rows) {
  const section=document.createElement('section');section.className='journal-venue-actions';
  const heading=document.createElement('h3');heading.textContent='Track this bet';
  const note=document.createElement('p');note.className='comparison-context';note.textContent='Save the quote, then record the odds and stake you actually got in My Bets.';
  section.append(heading,note,...rows.map(row=>journalAction('ev',row,'Save '+bookName(row.venue)+' to My Bets')));return section;
}
