import {referenceOnly,tradingContext} from './workspace-scope.js';
// Compatibility inspection for immutable saved captures. Reads only existing
// evidence APIs; never invokes snapshot refresh/recalculation controls.
const node=(tag,text)=>{const element=document.createElement(tag);if(text!==undefined)element.textContent=text;return element;};
const known=value=>value==null||value===''?'Unavailable':String(value);
const text=value=>known(value).replaceAll('_',' ');
const price=row=>row.display?.offered?.american??row.odds?.american??row.display?.price??row.offered_price??row.original?.value;
const json=value=>JSON.stringify(value,null,2);
async function get(url){const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(20000)}),value=await response.json();if(!response.ok)throw Error(value.error||value.reason||`Saved evidence unavailable (${response.status})`);return value;}
function evidence(root,label,value){const details=node('details');details.append(node('summary',label),node('pre',json(value)));root.append(details);}
function facts(root,values){const dl=node('dl');dl.className='research-detail-grid';for(const [name,value]of Object.entries(values))dl.append(node('dt',name),node('dd',known(value)));root.append(dl);}
function download(root,label,value){const link=node('a',label),url=URL.createObjectURL(new Blob([json(value)+'\n'],{type:'application/json'}));link.className='research-button';link.href=url;link.download='predict-saved-capture-evidence.json';root.append(link);return ()=>URL.revokeObjectURL(url);}
function position(row){const market=row.market||{};return row.selection_label||row.position||[text(market.market||row.family),text(row.side||row.outcome),row.line??market.line].filter(value=>value!=null).join(' · ');}
export async function renderSavedCapture(root,query,{inspectRoot,inspectTitle,dialog,onSelect=()=>{},isCurrent=()=>true}){
 const resultId=query.get('game_capture')||query.get('result_id'),game=query.get('game_key')||query.get('game'),dataset=query.get('dataset')||(query.get('game_capture')?'retained':null),replay=!!dataset;
 const params=new URLSearchParams({limit:'50',offset:query.get('record_offset')||'0',view:'odds',group:'offer'});
 if(resultId)params.set('result_id',resultId);if(game)params.set(replay?'game_key':'game',game);if(dataset)params.set('dataset',dataset);
 for(const [from,to]of [['search','search'],['sport','league'],['league','league'],['family','family']])if(query.get(from))params.set(to,query.get(from));
 root.replaceChildren(node('p','Reading the saved capture…'));
 const value=await get((replay?'/api/odds-replay':'/api/comparison-snapshot')+'?'+params);
 if(!isCurrent())return ()=>{};
 root.replaceChildren(node('h3','Saved capture evidence'),node('p',`Captured ${known(value.replay?.captured_at||value.captured_at)}. Historical prices and calculations retain their original clocks.`));
 if(value.synthetic===true||value.replay?.synthetic===true)root.append(node('p','Synthetic fixture; this is not received market data.'));
 const groups=value.rows||[],rows=groups.flatMap(row=>row.quotes||[row]);
 const cleanups=[download(root,'Export this captured page',value)];
 let detailGeneration=0;
 async function inspect(rowId,update=true){
  const generation=++detailGeneration;inspectTitle.textContent='Exact saved observation';inspectRoot.replaceChildren(node('p','Reading exact source and calculation evidence…'));if(!dialog.open)dialog.showModal();if(update)onSelect(rowId);
  const exact=new URLSearchParams({result_id:resultId||value.replay?.id||value.id||value.result_id,id:rowId});if(dataset)exact.set('dataset',dataset);if(game)exact.set('game_key',game);
  try{const result=await get((replay?'/api/odds-replay/details':'/api/comparison-snapshot/details')+'?'+exact);if(!isCurrent()||generation!==detailGeneration||!dialog.open)return;inspectRoot.replaceChildren();const row=result.row||{},reference=referenceOnly(row),context=tradingContext(row);inspectTitle.textContent=row.game_title||'Exact saved observation';
   facts(inspectRoot,{Capture:result.captured_at,Book:row.venue,'Exact bet':position(row),'Source price':price(row),'Source time':row.times?.source_at,'Receipt time':row.times?.received_at,'Calculation status':reference?'Reference only':context?'Trading market · calculation unavailable':row.calculation_status||row.reason,'Quoted EV':reference?'Reference only':context?'Unavailable':row.conditional_return_percent??row.net_return_percent??row.gross_return_percent});
   inspectRoot.append(node('p',reference?'Reference only. This sportsbook observation is retained as price evidence for prediction market calculations.':context?'This retained exchange observation is trading-side context. Numeric calculation support for this market is unavailable.':'This saved prediction market calculation uses its recorded assumptions. Missing reference, fee and settlement inputs remain unavailable.'));
   cleanups.push(download(inspectRoot,'Export this exact saved observation',result));
   evidence(inspectRoot,reference?'Retained source and calculation history · reference only':context?'Retained source history · unsupported trading market':'Probability, fees, cashflows and calculation',result.inspection||row);
   evidence(inspectRoot,'Underlying received source evidence',result.originals||result);
   evidence(inspectRoot,'Complete captured result',result);
  }catch(error){if(isCurrent()&&generation===detailGeneration)inspectRoot.replaceChildren(node('p',error.message+' No latest observation has been substituted.'));}
 }
 const table=node('table'),thead=node('thead'),head=node('tr'),tbody=node('tbody');table.className='catalog-table';for(const name of ['Game / exact bet','Book','Price / calculation','Clocks','Inspect'])head.append(node('th',name));thead.append(head);
 for(const row of rows){const tr=node('tr');const values=[`${row.game_title||row.game||'Saved game'} · ${position(row)}`,row.venue,`${known(price(row))} · ${referenceOnly(row)?'Reference only':tradingContext(row)?'Trading market · calculation unavailable':'EV '+known(row.conditional_return_percent??row.net_return_percent??row.gross_return_percent)}`,`Source ${known(row.times?.source_at)} · received ${known(row.times?.received_at)}`];for(const [index,value]of values.entries()){const td=node('td',known(value));td.dataset.label=head.children[index].textContent;tr.append(td);}const td=node('td'),button=node('button','Inspect exact saved observation');td.dataset.label='Inspect';button.onclick=()=>inspect(row.id);td.append(button);tr.append(td);tbody.append(tr);}table.append(thead,tbody);const scroll=node('div');scroll.className='catalog-scroll';scroll.append(table);root.append(scroll);
 if(!rows.length)root.append(node('p','This saved capture is no longer retained or contains no matching observations. Its selection has not been replaced with current data.'));
 const offset=Number(params.get('offset')),total=value.total??rows.length,pages=node('nav');pages.className='catalog-pagination';for(const [label,target,disabled]of [['Previous saved observations',Math.max(0,offset-50),offset===0],['Next saved observations',offset+50,offset+groups.length>=total]]){const a=node('a',label),q=new URLSearchParams(query);q.set('record_offset',String(target));for(const key of ['saved_bet','selection','id','bet_id','quote_key','line'])q.delete(key);a.href='/data?'+q;a.className='research-button';if(disabled){a.removeAttribute('href');a.setAttribute('aria-disabled','true');}pages.append(a);}root.append(node('p',`${offset+Math.min(groups.length,1)}–${offset+groups.length} of ${total} captured groups`),pages);
 const selected=query.get('saved_bet')||query.get('selection')||query.get('id')||query.get('bet_id')||query.get('quote_key')||query.get('line');if(selected)await inspect(selected,false);
 return ()=>{detailGeneration++;for(const cleanup of cleanups)cleanup();};
}
