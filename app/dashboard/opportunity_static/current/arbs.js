import {el,venues,markets,periods,quoteText,age} from './board.js';
const $=id=>document.getElementById(id);let data,busy=false,again=false;
function pairCard(p,card){
  card ||= el('section',undefined,'arb-card');card.dataset.id=p.id;
  const header=el('div',undefined,'arb-header');header.append(el('h2',p.title),el('p',p.league+' · '+(periods[p.period]||p.period)+' · '+(markets[p.market]||p.market)+(p.line?' · '+p.line:'')+' · '+new Date(p.start_at).toLocaleString('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' ET'));
  const legs=el('div',undefined,'arb-legs');
  for(const leg of p.legs){const q=leg.quote,node=el('div');node.append(el('h3',leg.selection),el('p',venues[q.venue]),el('strong',quoteText(q)),el('p',q.state.replaceAll('_',' ')+(q.stale?' · stale':'')+' · '+age(q)+(q.source.provider==='the_odds_api'?' · Delayed · Freshness unqualified':'')),el('p','EV %: '+(p.ev[p.legs.indexOf(leg)].eligible?p.ev[p.legs.indexOf(leg)].display_value:p.ev[p.legs.indexOf(leg)].reason),'arb-ev'));if(p.legs[0].quote.rule_note!==p.legs[1].quote.rule_note)node.append(el('p','Rule notes differ','rules'));legs.append(node);}
  const result=el('div',undefined,'arb-result');result.append(el('h3','Arb %'),el('strong',p.arbitrage.display_value),el('p','Gross · conditional'));
  let basis=card.querySelector('details');
  if(!basis){basis=el('details');basis.append(el('summary','Calculation basis and venue rules'));}
  const body=el('div');body.append(el('p','100 × (1 − combined entry price) / combined entry price. Each winning leg pays one normalized unit.'),el('p','Net return: '+(p.net.eligible?(p.net.display_value||p.net.value+' '+(p.net.unit||'')):p.net.reason||'Required inputs unavailable')));
  for(const leg of p.legs){const q=leg.quote;body.append(el('h3',leg.selection+' · '+venues[q.venue]),el('p','Original: '+q.original.value+' '+q.original.units+' · revision '+q.revision),el('p','Source timestamp: '+(q.times.source_at||'Unknown')),el('p',q.rule_note));}
  const b=p.arbitrage.basis;if(b?.denominator)body.append(el('p','Combined entry price: '+b.denominator+' per normalized normal-win payout.'),el('p',b.exceptions));const raw=el('pre',JSON.stringify(b,null,2));raw.style.whiteSpace='pre-wrap';raw.style.overflowWrap='anywhere';body.append(raw);
  if(basis.children[1])basis.children[1].replaceWith(body);else basis.append(body);
  // Keep the disclosure and its focus in place while live prices change.
  for(const [i,node] of [header,legs,result].entries()){if(card.children[i]&&card.children[i]!==basis)card.children[i].replaceWith(node);else card.insertBefore(node,basis.parentNode===card?basis:null);}
  if(basis.parentNode!==card)card.append(basis);return card;
}
function draw(){if(!data)return;const search=$('search').value.toLowerCase(),market=$('market').value;
  const pairs=data.pairs.filter(p=>(!market||p.market===market)&&[p.title,...p.legs.map(l=>l.selection)].join(' ').toLowerCase().includes(search));$('flow').textContent=pairs.length+' opposing pairs';$('test-notice').hidden=data.mode!=='synthetic';
  const cards=new Map([...$('pairs').querySelectorAll('.arb-card')].map(n=>[n.dataset.id,n]));const retained=new Set(pairs.map(p=>p.id));
  for(const [id,card] of cards)if(!retained.has(id)){if(card.contains(document.activeElement))$('search').focus({preventScroll:true});card.remove();}
  $('pairs').querySelector('.empty')?.remove();
  pairs.forEach((p,i)=>{const card=pairCard(p,cards.get(p.id));if($('pairs').children[i]!==card)$('pairs').insertBefore(card,$('pairs').children[i]||null);});
  if(!pairs.length){const empty=el('div',undefined,'empty');empty.append(el('h2','No matching opposing pairs'),el('p','Try another game or market. Both legs need verified matching event and market coverage.'));$('pairs').append(empty);}
}
async function pull(){if(busy){again=true;return;}busy=true;try{const r=await fetch('/api/arbs?'+new URLSearchParams({market:$('market').value,search:$('search').value}));if(!r.ok)throw Error('Arbs unavailable');data=await r.json();draw();}catch(e){$('flow').textContent=e.message;}finally{busy=false;if(again){again=false;pull();}}}
$('filters').addEventListener('submit',e=>e.preventDefault());$('search').addEventListener('input',pull);$('market').addEventListener('change',pull);const stream=new EventSource('/api/current/updates');stream.onmessage=pull;stream.onopen=pull;stream.onerror=()=>{$('flow').textContent='Reconnecting';};window.addEventListener('pagehide',()=>stream.close());pull();
