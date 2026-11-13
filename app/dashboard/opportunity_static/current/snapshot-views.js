// Pure view builders. Callers own navigation and immutable result selection.
const SnapshotViews = (() => {
  const {el,fmt,num,name,odd,link,button}=UI;
  const titles={gross_return_percent:'Before-fee estimate',conditional_return_percent:'After reviewed trade fees',conservative_return_percent:'Conservative public-fee estimate',net_return_percent:'Assumed net EV',price_difference_cents:'Price difference',minimum_return_percent:'Scenario minimum'};
  const metricLabel=(metric,a)=>metric==='net_return_percent'&&a.scenario==='decisive_only'?'Conditional net EV':titles[metric];
  function position(q,games){
    const s=q.selection||{},g=games?.find(g=>g.game_key===q.game_key);
    const participant=q.participant_label||g?.participants?.find(p=>p.id===s.participant)?.name||s.label||'Outcome not identified';
    const line=s.signed_line??q.market?.line, n=num(line);
    const signed=line==null?'':`${n>0?'+':''}${n}`;
    // Selection is already normalized by the source adapter. Short is not a
    // second negation, and a native NO never becomes the other team's win.
    if(s.predicate==='win')return participant+' to win';
    if(s.predicate==='not_win')return participant+' not to win';
    if(s.predicate==='cover')return participant+' to cover '+signed;
    if(s.predicate==='not_cover')return participant+' not to cover '+signed;
    if(['over','under'].includes(s.predicate))return `${s.predicate==='over'?'Over':'Under'} ${line==null?'':num(line)}`.trim();
    return [participant,({not_over:'Not over',not_under:'Not under'})[s.predicate]||s.predicate?.replaceAll('_',' '),signed].filter(Boolean).join(' · ');
  }
  function clock(at){return at?new Date(at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'Time unknown';}
  function state(q){
    const at=q.book_confirmation?.confirmed_at||q.times?.source_at||q.times?.received_at;
    const basis=q.book_confirmation?.confirmed_at?'Confirmed':q.times?.source_at?'Source':'Received';
    const mode=q.source_state==='budget_delayed'?'15-min collection':({paused:'Paused',stopped:'Stopped',error:'Source error',unavailable:'Source unavailable',stale:'Stale source'})[q.source_state];
    return `${basis} ${clock(at)}${mode?' · '+mode:''}`;
  }
  const pct=v=>v==null?'—':`${num(v)>0?'+':''}${fmt(v)}%`;
  function missing(q,metric){
    const reasons=q.current_reasons||[];
    if(reasons.includes('source_expired'))return q.price_current?'Reference expired':'Source price expired';
    if(reasons.includes('settings_replaced'))return 'Settings recalculating';
    if(reasons.includes('input_replaced_or_removed'))return q.price_current?'Reference inputs changed':'Source inputs changed';
    if(reasons.length)return q.price_current?'Current calculation unavailable':'Source currently unavailable';
    if(q.probability_missing==='finance_pending')return 'Calculation pending';
    if(metric==='conservative_return_percent')return 'Public-fee estimate unavailable';
    if(metric==='conditional_return_percent')return ({prophetx_account_fee_model_and_rate_unbound:'Account fee unknown',kalshi_instrument_fee_schedule_unbound:'Contract fee unknown',conditional_fee_review_expired_or_not_effective:'Fee review expired',conditional_pregame_ended:'Pregame fee only',supported_decisive_benchmark_required:'Reference unavailable'})[q.conditional_trade_benchmark?.reason]||(!q.probability?'Reference unavailable':'Fee estimate unavailable');
    if(metric==='gross_return_percent')return q.probability==null?'Reference unavailable':'Estimate unavailable';
    if(metric==='net_return_percent')return 'Assumptions needed';
    if(metric==='minimum_return_percent')return 'Fees / settlement / size needed';
    return 'Unavailable';
  }
  function metricCell(q,metric){const cell=el('td',null,'compare-number');cell.append(el('strong',pct(q[metric]),num(q[metric])>0?'positive':num(q[metric])<0?'negative':''));if(q[metric]==null)cell.append(el('small',missing(q,metric),'compare-note'));return cell;}
  function referenceStrip(quotes,result){
    const wrap=el('div',null,'compare-references'),refs=new Map();
    for(const q of quotes){
      const ref=q.reference_calculation, pair=ref?.pair||[];
      const key=JSON.stringify([ref?.venue||q.display?.benchmark_venue,pair.map(p=>[p.id,p.original,p.selection]),ref?.selected,ref?.selected_predicate,q.display?.benchmark,ref?.basis_sha256]);
      if(!pair.length&&!q.display?.benchmark?.length&&!ref?.contributors?.length)continue;
      if(!refs.has(key))refs.set(key,{q,venues:new Set(),retained:new Set()});refs.get(key).venues.add(name(q.venue));if(ref?.available===false)refs.get(key).retained.add(name(q.venue));
    }
    for(const {q,venues,retained} of refs.values()){
      const ref=q.reference_calculation, line=el('div',null,'compare-reference');
      line.append(el('strong',name(ref?.venue||q.display?.benchmark_venue||result.assumptions.benchmark_venue)+' quoted odds'),el('span',' · '+[...venues].join(', '),'compare-note'));
      const values=el('div',null,'compare-ref-values');
      if(ref?.contributors?.length){values.append(el('span','Contributing books: '+ref.contributors.map(c=>name(c.venue)).join(', ')));}
      else if(ref?.pair?.length)for(const [i,r] of ref.pair.entries()){
        const item=el('span',position({...r,market:q.market},result.games)+': ');item.append(odd(q.display?.benchmark?.[i],''));values.append(item);
      }else for(const [i,o] of (q.display?.benchmark||[]).entries()){
        const item=el('span','Reference outcome '+(i+1)+' (name unavailable): ');item.append(odd(o,''));values.append(item);
      }
      line.append(values);if(retained.size)line.append(el('small','Retained reference for '+[...retained].join(', '),'compare-note'));wrap.append(line);
    }
    if(!refs.size)wrap.append(el('p','Sportsbook comparison unavailable for these exact outcomes.','compare-note'));
    return wrap;
  }
  function comparison(group,result,metric,actions){
    const pair=group.kind==='pair_group',quotes=group.quotes,first=quotes[0],article=el('article',null,'compare-group');article.dataset.group=group.id;
    const header=el('header',null,'compare-heading');
    header.append(link(first.game_title,actions.game(first),'p-game'),el('span',`${first.league} · ${name(first.market.market)} · ${clock(first.start_at)}`,'p-meta'));
    header.append(el('h2',pair?(first.display.positions||[]).map(q=>position(q,result.games)).join(' / '):position(first,result.games)));
    if(group.score_source)header.append(el('p',`${name(group.score_source.venue)} sets rank · ${pct(group.score)}`,'compare-note'));
    else header.append(el('p','Unranked · '+metricLabel(metric,result.assumptions)+' unavailable','compare-note'));
    article.append(header);if(!pair)article.append(referenceStrip(quotes,result));
    const table=el('table',null,'compare-table'+(pair?' pair-table':''));table.setAttribute('aria-label',pair?'Compare both sides':position(first,result.games)+' by source');
    const head=el('thead'),tr=el('tr');
    const extra=!pair&&['conservative_return_percent','net_return_percent','price_difference_cents'].includes(metric)?metric:null;
    const headings=pair?['First outcome','Other outcome','Minimum return','Details']:['Source','Odds','EV before fees','EV after trade fees',...(extra?[metricLabel(extra,result.assumptions)]:[])];
    for(const text of headings){const th=el('th',text);th.setAttribute('scope','col');tr.append(th);}head.append(tr);table.append(head);const body=el('tbody');
    for(const q of quotes){
      const row=el('tr');row.dataset.row=q.id;row.dataset.quote=q.id;row.dataset.ranking=q.ranking?.eligible?'eligible':'unranked';if(group.score_source?.id===q.id)row.classList.add('sets-rank');
      if(pair){for(const leg of q.display.positions||[]){const c=el('td');c.append(el('strong',position(leg,result.games)),el('div',name(leg.venue),'compare-note'),odd(leg.display?.offered),el('small',state(leg),'compare-note'));row.append(c);}row.append(metricCell(q,'minimum_return_percent'));}
      else{
        const source=el('td');source.append(el('strong',name(q.venue)));if(q.price_current===false)source.append(el('small','Retained price','compare-note'));if(group.score_source?.id===q.id)source.append(el('small','Sets rank','compare-note'));row.append(source);
        const price=el('td',null,'compare-number');price.append(odd(q.display?.offered));row.append(price,metricCell(q,'gross_return_percent'),metricCell(q,'conditional_return_percent'));
        if(extra==='price_difference_cents'){const c=el('td',q[extra]==null?'—':fmt(q[extra])+'¢','compare-number');row.append(c);}else if(extra)row.append(metricCell(q,extra));
      }
      const cell=el('td'),b=button('Math & fees',()=>{
        if(actions.openInspection){actions.openInspection(q,result,pair?'minimum_return_percent':metric);return;}
        const open=article.querySelector('.p-why-panel'),same=open?.dataset.selection===q.id;open?.remove();for(const x of article.querySelectorAll('.p-why-button'))x.setAttribute('aria-expanded','false');
        if(same){actions.selected(null);return;}const panel=why(q,result,pair?'minimum_return_percent':metric,actions.inspect(q,pair?'minimum_return_percent':metric));panel.dataset.selection=q.id;article.append(panel);b.setAttribute('aria-expanded','true');actions.selected(q.id);
      },'p-why-button');b.setAttribute('aria-expanded','false');b.setAttribute('aria-label',`Why ${pair?'this pair':name(q.venue)+' '+position(q,result.games)}`);b.setAttribute('aria-haspopup','dialog');b.setAttribute('aria-controls','math-inspection');if(pair){cell.append(b);row.append(cell);}else{b.textContent=name(q.venue);row.firstChild.querySelector('strong').replaceWith(b);b.title='Math & fees';}[...row.children].forEach((td,i)=>td.dataset.label=headings[i]);body.append(row);
    }
    table.append(body);const scroll=el('div',null,'compare-scroll');scroll.append(table);article.append(scroll);
    if(pair)article.append(el('p','Minimum return uses both purchases and the settlement, fees, size and buffer in Admin. A dash means inputs are missing; it does not mean zero or guaranteed profit.','compare-footnote'));

    return article;
  }
  function why(row,result,metric,inspect){
    const box=el('section',null,'p-why-panel');box.setAttribute('aria-label','Why this estimate');
    const title=el('div',null,'p-why-title');title.append(el('strong',metricLabel(metric,result.assumptions)),link('Inspect exact inputs in Admin',inspect));box.append(title,el('p',row.kind==='pair'?row.game_title:position(row,result.games)+' · '+row.game_title,'p-meta'));
    const conservative=metric==='conservative_return_percent',conditional=metric==='conditional_return_percent'||conservative,fee=(conservative?row.conservative_trade_benchmark:row.conditional_trade_benchmark)||{};
    if(conservative)box.append(el('p','Conservative public-schedule estimate. Account terms are unverified; this does not enter the reviewed-fee ranking.'));
    const d=row.display||{},grid=el('div',null,'p-why-grid');
    function fact(label,value,caption){const item=el('div');item.append(el('small',label),value,el('span',caption));grid.append(item);}
    if(row.kind!=='pair'){
      fact('Offered odds',odd(d.offered,'p-odds'),name(row.venue));
      fact('Estimated fair odds',odd(d.fair,'p-odds'),row.probability==null?'Benchmark unavailable':`${fmt(num(row.probability)*100)}% win chance, excluding pushes`);
    }else for(const leg of d.positions||[])fact(position(leg,result.games),odd(leg.display?.offered,'p-odds'),name(leg.venue));
    const value=row[metric];const dollars=metric==='price_difference_cents'?null:value;
    fact(metric==='price_difference_cents'?'Difference per claim':'Per $100 deployed',el('strong',value==null?'Unavailable':metric==='price_difference_cents'?fmt(value)+'¢':(num(value)<0?'−$':'$')+fmt(Math.abs(num(dollars)))),metric==='gross_return_percent'?'Expected profit before fees':conditional?'Expected profit in the trade-fee scenario':metric==='minimum_return_percent'?'Buffered minimum in assumed states':metric==='net_return_percent'?'Expected profit after assumed fees and buffer':'Not an expected-value estimate');
    box.append(grid);
    if(metric==='net_return_percent'||metric==='minimum_return_percent')box.append(el('p',result.assumptions.scenario==='decisive_only'?'This scenario includes decisive wins and losses only.':result.assumptions.scenario==='refund_other'?'This scenario assumes other outcomes return the purchase cost, with fees retained.':'Choose settlement, fee and size assumptions in Admin to calculate this estimate.'));
    if(metric==='gross_return_percent')box.append(el('p','The offered odds pay more or less than our reference-based estimate of a fair price. The $100 example averages decisive wins and losses; it excludes fees, pushes and other settlement outcomes. Fair odds are an estimate, not a known chance.'));
    else if(conditional&&fee.available)box.append(el('p',row.venue==='polymarket_us'?'Based on one contract bought as a taker in one fill, before rebates. The $100 figure scales that example; it is not the fee for a $100 order. Only decisive wins and losses are included; no buffer or other costs are deducted.':'Based on a pregame straight trade under the reviewed fee schedule. Only decisive wins and losses are included; no buffer or other costs are deducted.'));
    else if(conditional)box.append(el('p','A trade-fee estimate needs a supported reference probability and an applicable reviewed fee schedule.'))
    else if(metric==='price_difference_cents')box.append(el('p','Difference from another comparable instrument’s price, in cents per normal claim. This is not expected profit or a two-position minimum.'));
    else box.append(el('p','Uses the fees, fractional size and buffer entered in Admin. Available depth and actual fills are not established. Unknown inputs remain unavailable.'));
    if(d.benchmark?.length)box.append(referenceStrip([row],result));
    if(value==null)box.append(el('p','Needed: '+(metric==='gross_return_percent'?row.probability_missing||'supported price and decisive benchmark':conditional?({prophetx_account_fee_model_and_rate_unbound:'the account fee model and rate',kalshi_instrument_fee_schedule_unbound:'the fee schedule for this exact contract',conditional_fee_review_expired_or_not_effective:'a fee review applicable to this capture',conditional_pregame_ended:'a capture taken before the game starts',supported_decisive_benchmark_required:'supported offered odds and a reference probability'}[fee.reason]||'a supported reference and reviewed fee scenario for this saved position'):row.math?.missing?.join('; ')||'comparable supported inputs')));
    if(metric==='gross_return_percent'&&value!=null){const details=el('details');details.append(el('summary','How the $100 example works'));const dl=el('dl',null,'p-example');for(const [k,v] of [['Profit on a decisive win','$'+fmt(d.win_profit_per_100)],['Loss on a decisive loss','−$100.00'],['Estimated win chance',fmt(num(row.probability)*100)+'%'],['Expected profit before fees','$'+fmt(d.gross_profit_per_100)]])dl.append(el('dt',k),el('dd',v));details.append(dl,el('p','Expected profit = win chance × win profit − loss chance × $100. Full-precision captured inputs are used.'));box.append(details);}
    box.append(el('p','The $100 illustration does not change your calculation settings.','p-meta'));
    return box;
  }
  function card(row,result,metric,actions){
    const article=el('article',null,'p-opportunity');article.dataset.row=row.id;
    const line=el('div',null,'p-row'),game=link('',actions.game(row),'p-match');game.append(el('div',null,'p-match-text'));game.firstChild.append(el('div',row.game_title,'p-game'),el('small',`${row.league} · ${name(row.market.market)} · Full game`,'p-meta'));
    game.onclick=()=>actions.remember(row.id);
    const pos=el('div',null,'p-position'),price=el('div',null,'p-price');
    for(const q of row.kind==='pair'?row.display.positions:[row]){const p=el('div',position(q,result.games),'p-selection');p.append(el('small',name(q.venue),'p-meta'));pos.append(p);price.append(odd(q.display?.offered));}
    const edge=el('div',null,'p-edge'+(num(row[metric])<0?' negative':''));edge.append(el('strong',row[metric]==null?'—':`${num(row[metric])>0?'+':''}${fmt(row[metric])}${metric==='price_difference_cents'?'¢':'%'}`),el('small',metricLabel(metric,result.assumptions)),el('div',state(row),'p-age'));
    const whyButton=button('Why',()=>{const open=article.querySelector('.p-why-panel');if(open){open.remove();whyButton.setAttribute('aria-expanded','false');actions.selected(null);}else{article.append(why(row,result,metric,actions.inspect(row)));whyButton.setAttribute('aria-expanded','true');actions.selected(row.id);}},'p-why-button');whyButton.setAttribute('aria-expanded','false');
    line.append(game,pos,price,edge,whyButton);article.append(line);return article;
  }
  function markets(group,result,actions){
    const card=el('article',null,'p-market-card'),q=group.quotes[0];card.append(el('h2',`${name(q.market.market)} · ${position(q,result.games)}`));
    if(!actions.inGame)card.prepend(link(q.game_title,actions.game(q),'p-game'));
    if(!group.comparable)card.append(el('p','Native position · settlement equivalence unverified','p-meta'));
    const prices=el('div',null,'venue-prices');
    for(const quote of group.quotes){const c=el('div',null,'venue-price');c.dataset.quote=quote.id;c.append(el('strong',name(quote.venue)),odd(quote.display?.offered),el('div',position(quote,result.games),'p-meta'));const m=quote.gross_return_percent;c.append(el('div',m==null?'Estimate unavailable':`${fmt(m)}% before-fee estimate`,'p-meta'));c.append(button('Why',()=>{card.querySelector('.p-why-panel')?.remove();card.append(why(quote,result,'gross_return_percent',actions.inspect(quote,'gross_return_percent')));actions.selected(quote.id);},'p-why-button'));prices.append(c);}
    const ref=group.quotes.find(q=>q.display?.benchmark?.length);if(ref){const c=el('div',null,'venue-price');c.append(el('strong',name(ref.display.benchmark_venue)+' · reference'));const idx=(ref.snapshot_benchmark||ref.reference).selected;c.append(odd(ref.display.benchmark[idx]),el('small','Reference only','p-meta'));prices.append(c);}
    card.append(prices);return card;
  }
  function inspection(value,result,metric){
    const box=el('article',null,'inspection'),r=value.row;box.append(el('h2',r.game_title),el('p',r.kind==='pair'?'Both captured positions':position(r,result.games)));
    for(const q of r.kind==='pair'?r.display.positions:[r]){const p=el('p',name(q.venue)+' · '+position(q,result.games)+' · ');p.append(odd(q.display?.offered));box.append(p);}
    const explanation=why(r,result,r.kind==='pair'?'minimum_return_percent':metric||'gross_return_percent',location.href);explanation.querySelector('a')?.remove();box.append(explanation);
    const clocks=el('dl');for(const [label,v] of [['Captured',value.captured_at],['Calculated',result.calculated_at]])clocks.append(el('dt',label),el('dd',v||'Not established'));box.append(el('h3','Quote timing'),clocks);
    for(const q of value.originals){const dl=el('dl');for(const [label,v] of [['Venue',name(q.venue)],['Provider update',q.times?.source_at],['Successful confirmation',q.book_confirmation?.confirmed_at],['Local receipt',q.times?.received_at],['Last price change',q.last_price_change_at]])dl.append(el('dt',label),el('dd',v||'Not established by this capture'));box.append(dl);}
    box.append(el('p','A provider update is not a successful confirmation or last price-change clock. A newer capture does not make a quote current.'));
    box.append(el('h3','Calculation basis'),el('p',`Configured funding: $${fmt(result.assumptions.amount)} · ${fmt(num(result.assumptions.buffer)*100)}% buffer; applied once only to the assumed-net and scenario-minimum metrics.`));
    if(r.conditional_trade_benchmark?.formula)box.append(el('p',r.conditional_trade_benchmark.formula),el('p',r.conditional_trade_benchmark.condition));
    if(r.math?.formula)box.append(el('h3','Formula'),el('p',r.math.formula));
    const exact=el('details');exact.append(el('summary','Exact calculation records · literal values, units and identifiers'),el('pre',JSON.stringify({result_id:value.result_id,snapshot_id:value.snapshot_id,row:r,assumptions:value.assumptions},null,2)));
    const originals=el('details');originals.append(el('summary','Original records · literal units and precision'),el('pre',JSON.stringify({originals:value.originals,references:value.references},null,2)));box.append(exact,originals);return box;
  }
  return {card,markets,comparison,why,inspection,position,metricLabel,state,referenceStrip,missing,pct};
})();
