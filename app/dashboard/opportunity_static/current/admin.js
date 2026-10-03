const status=document.querySelector('#native-status');
const issues=document.querySelector('#native-issues');
async function refresh(){
  try{
    const response=await fetch('/api/admin/current');
    const state=await response.json();
    status.textContent=JSON.stringify(state,null,2);
    issues.textContent=(state.issues||[]).map(x=>`${x.provider}: ${x.category} / ${x.code}`).join('\n')||'No recorded native issues.';
  }catch(error){status.textContent='Native status unavailable.';}
}
for(const button of document.querySelectorAll('[data-action]')){
  button.addEventListener('click',async()=>{
    const body={action:button.dataset.action};
    if(button.dataset.source)body.source=button.dataset.source;
    button.disabled=true;
    try{
      const response=await fetch('/api/admin/current',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(!response.ok)throw new Error('Control unavailable');
      await refresh();
    }catch(error){issues.textContent='Native control failed. Inspect status before reopening.';}
    finally{button.disabled=false;}
  });
}
refresh();setInterval(refresh,5000);
