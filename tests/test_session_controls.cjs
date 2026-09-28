'use strict';
const assert=require('assert');const {attach}=require('../app/dashboard/opportunity_static/session_controls.js');
(async()=>{
 let active=true,fail=false,stopFail=false;const calls=[];const button={disabled:true},status={textContent:''};
 const request=async(url,options)=>{calls.push({url,options});if(fail)throw Error('offline');if(url==='/api/stop'){if(stopFail)return {ok:false,json:async()=>({error:'failed'})};active=false;}return {ok:true,json:async()=>({active,session:'fixture',cleanup_complete:!active})};};
 const control=attach(button,status,request,()=>{});await new Promise(setImmediate);
 assert.equal(button.disabled,false);assert(status.textContent.includes('Scan running'));
 fail=true;await control.refresh();assert(status.textContent.includes('unavailable'));assert.equal(button.disabled,false);
 fail=false;stopFail=true;await button.onclick();assert(status.textContent.includes('could not be confirmed'));assert.equal(button.disabled,false);
 stopFail=false;await button.onclick();assert(button.disabled);assert(status.textContent.includes('observations saved'));
 assert(calls.some(x=>x.url==='/api/stop'&&x.options.method==='POST'&&x.options.body==='{}'));
 console.log('Game Details Stop: active, unavailable status, failed Stop, ordinary Stop and saved state PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
