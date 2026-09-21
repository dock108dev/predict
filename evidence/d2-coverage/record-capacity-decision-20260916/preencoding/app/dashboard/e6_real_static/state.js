/* Identity-bound selection; never choose a nearby observation for an invalid link. */
(function(root){
 const state={
  restore(data,search){
   const q=new URLSearchParams(search),allowed=['session','hash','at','venue'];
   for(const key of q.keys())if(!allowed.includes(key)||q.getAll(key).length!==1)throw Error('Invalid saved selection parameters.');
   if(q.size && (!q.has('session')||!q.has('hash')||!q.has('at')||!q.has('venue')))throw Error('Saved selection is incomplete.');
   if(q.size && (q.get('session')!==data.session||q.get('hash')!==data.hash))throw Error('Saved session identity is unavailable or changed.');
   const at=q.size?q.get('at'):data.timeline.at(-1)?.id,venue=q.size?q.get('venue'):'both';
   if(!['both','kalshi','polymarket_us'].includes(venue))throw Error('Saved venue is unavailable.');
   const point=root.E5State.select(data.timeline,at);
   if(!point)throw Error('Saved cutoff is unavailable. No replacement was opened.');
   return {at,venue};
  },
  move(data,selection,offset){const index=data.timeline.findIndex(p=>p.id===selection.at);if(index<0)throw Error('Unknown cutoff');return {...selection,at:data.timeline[Math.max(0,Math.min(data.timeline.length-1,index+offset))].id};},
  url(data,selection){return '/?'+new URLSearchParams({session:data.session,hash:data.hash,at:selection.at,venue:selection.venue}).toString();}
 };
 root.RealState=state;if(typeof module!=='undefined')module.exports=state;
})(globalThis);
