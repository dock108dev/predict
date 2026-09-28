/* Keep ordinary Stop available while inspecting a frozen game-detail snapshot. */
(function(root){
 'use strict';
 function attach(button,status,request,schedule){
  let busy=false,active=false;
  async function refresh(){
   try{
    const response=await request('/api/status');
    const state=await response.json();if(!response.ok)throw Error(state.error||'Status unavailable');
    active=state.active;button.disabled=busy||!active;
    status.textContent=active?(state.state==='stopping'?'Stopping feeds and saving observations…':'Scan running · Stop remains available here'):(state.cleanup_complete&&state.session?'Scan stopped · observations saved':'No scan running');
    if(state.error)status.textContent+=' · '+state.error;
   }catch(error){status.textContent='Scan status unavailable. Return to All games or use Stop if the scan may still be running.';button.disabled=busy||!active;}
  }
  button.onclick=async()=>{
   busy=true;button.disabled=true;status.textContent='Stopping feeds and saving observations…';
   try{
    const response=await request('/api/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const state=await response.json();if(!response.ok)throw Error(state.error||'Stop unavailable');
   }catch(error){status.textContent='Stop could not be confirmed. Return to All games and check the scan. '+error.message;busy=false;button.disabled=!active;return;}
   busy=false;await refresh();
  };
  async function poll(){await refresh();schedule(poll,1000);}
  poll();return {refresh};
 }
 if(typeof module==='object'&&module.exports)module.exports={attach};
 else attach(document.getElementById('session-stop'),document.getElementById('session-control-status'),(...args)=>fetch(...args),setTimeout);
})(typeof globalThis==='object'?globalThis:this);
