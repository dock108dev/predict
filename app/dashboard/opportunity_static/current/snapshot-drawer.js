// Drawer presentation only. SnapshotLive owns all retention and adoption.
const SnapshotDrawer = (() => {
  const {el,fmt,num,name,odd,link}=UI;
  const {position,pct,missing,referenceStrip}=SnapshotViews;
  const human=v=>String(v??'Not established').replaceAll('_',' ');
  function facts(entries){const dl=el('dl',null,'math-facts');for(const [k,v] of entries)dl.append(el('dt',k),el('dd',v==null?'Not established':String(v)));return dl;}
  function section(title){const s=el('section',null,'math-section');s.append(el('h3',title));return s;}
  function disclosure(title,child){const d=el('details');d.append(el('summary',title),child);return d;}
  function content({row,result,metric,details},inspect){
    // Current displayed economics may be null even when this member retains math.
    // Never replace row with details.row or borrow result.assumptions for it.
    const box=el('div',null,'math-content'),a=details.assumptions||{};
    box.append(el('p',row.game_title,'p-meta'),el('h3',row.kind==='pair'?'Both outcomes':position(row,result.games)));
    if(row.kind==='pair'){
      box.append(SnapshotViews.why(row,{...result,assumptions:a},metric,inspect));
    }else{
      const price=el('div',null,'math-price');price.append(el('span',name(row.venue)+' · selected odds'),odd(row.display?.offered));box.append(price);
      const values=el('div',null,'math-values');
      for(const [key,label] of [['gross_return_percent','EV before trade fees'],['conditional_return_percent','EV after reviewed trade fees'],...(metric==='conservative_return_percent'?[['conservative_return_percent','Conservative public-fee estimate']]:[])]){
        const item=el('div');item.append(el('small',label),el('strong',pct(row[key]),num(row[key])>0?'positive':num(row[key])<0?'negative':''));
        if(row[key]==null)item.append(el('span',missing(row,key),'compare-note'));values.append(item);
      }
      if(['net_return_percent','price_difference_cents'].includes(metric))box.append(SnapshotViews.why(row,{...result,assumptions:a},metric,inspect));
      box.append(values,el('p','EV is estimated profit per $100 of modeled risk, conditional on a decisive win or loss. Pushes and exceptional outcomes are excluded.','p-meta'));
      if(row.current_reasons?.length||row.probability_missing==='finance_pending')box.append(el('p','Pinned availability: '+(row.current_reasons?.map(human).join('; ')||'Calculation pending')+'. Retained arithmetic below has no current ranking authority.','math-state'));
      const r=row.reference_calculation||{};
      const ref=section('Sportsbook prices and estimated fair odds');
      ref.append(referenceStrip([row],result));
      if(r.available!==false&&row.probability!=null){
        const multi=r.method==='sgo-book-median-proportional-1';
        const derivation=el('p',multi?'Remove the margin from each eligible two-sided book pair, then take the median of their decisive probabilities.':'Remove the margin proportionally: (1 ÷ selected decimal price) ÷ the sum of both implied probabilities.');
        ref.append(derivation,facts([...(multi?[]:[['Margin (overround)',r.overround==null?null:pct(num(r.overround)*100)]]),['Decisive win probability',fmt(num(row.probability)*100)+'%'],['Estimated fair odds',odd(row.display?.fair||{decimal:r.fair_decimal_odds})]]));
      }else ref.append(el('p','Fair price unavailable in the pinned display. Retained reference prices do not restore current probability.'));
      box.append(ref);
      const fair=row.sgo_fair_comparison;
      if(fair){const v=section('Provider fair-odds estimate');v.append(facts([['Availability',fair.available?'Available':'Unavailable'],['Fair American odds',fair.price_american],['Fair line',fair.line],['Original source time','Unknown'],['Received',fair.received_at]]),el('p',!fair.available?'This baseline is unavailable or incomplete. It is not used as the reference probability.':fair.same_line===false?'Context at a different line; not the fair price for this offer. Contributors and original update time are unknown.':'Third-party baseline; contributors and original update time are unknown. It is not used as the reference probability.','p-meta'));box.append(v);}
      const calc=section('Before / after trade fees');
      calc.append(el('p','Before fees: expected profit = win probability × win profit − loss probability × acquisition cost. EV % divides expected profit by acquisition cost.'));
      const fee=metric==='conservative_return_percent'?row.conservative_trade_benchmark:row.conditional_trade_benchmark;
      calc.append(el('p',fee?.formula||'After-fee calculation unavailable for these displayed inputs.'));
      if(fee?.available){calc.append(facts([['Acquisition per normal claim',row.cost_per_normal_claim==null?null:'$'+fmt(row.cost_per_normal_claim,6)],['Modeled trade fee','$'+fmt(fee.trade_fee_usd,6)],['Risk denominator','$'+fmt(fee.normalization_risk_usd,6)],['Expected profit in scenario',fee.scenario_net_usd==null?null:'$'+fmt(fee.scenario_net_usd,6)],['Fee payment',human(fee.fee_payment||fee.percentage_denominator)]]));}
      box.append(calc);
      const fees=section(metric==='conservative_return_percent'?'Conservative fee assumptions':'Reviewed fee assumptions');
      if(metric==='conservative_return_percent')fees.append(el('p','Public-schedule estimate; account terms unverified. This is a separate basis and never enters reviewed-fee ranking.','math-state'));
      fees.append(el('p',fee?.condition||human(fee?.reason||'Applicable reviewed fee schedule unavailable')));
      if(fee?.available){
        const evidence=fee.evidence||{};
        const authority=[['Terms verified',evidence.reviewed_at]];
        if(evidence.review_before)authority.push(['Applicable through',evidence.review_before]);
        if(evidence.standing_public_terms)authority.push(['Terms',evidence.verification_scope==='market_terms_only'?'Standing public terms · market evidence verified':'Standing public terms'],['Recheck due',evidence.recheck_due_at]);
        fees.append(facts([['Quantity',`${fee.quantity??'Unknown'} ${fee.quantity_unit||''}`],['Order',`${human(fee.liquidity_role)} · ${fee.fill_count??'Unknown'} fill(s)`],...authority]));
      }
      const fullFee=details.row[metric==='conservative_return_percent'?'conservative_trade_benchmark':'conditional_trade_benchmark'];
      if(fullFee?.rounding_trace)fees.append(disclosure('Exact fee rounding',el('pre',JSON.stringify(fullFee.rounding_trace,null,2))));
      if(fee?.assumptions)fees.append(el('p',Array.isArray(fee.assumptions)?fee.assumptions.join(' · '):JSON.stringify(fee.assumptions)));
      fees.append(el('p','The $100 illustration scales the modeled trade and excludes the buffer and other costs.','p-meta'));box.append(fees);
    }
    const clocks=section('Detailed clocks'),original=(details.originals||[]).find(q=>q.id===row.id)||{};
    clocks.append(facts([['Source capture',row.captured_at||details.captured_at],['Provider update',row.times?.source_at],['Successful confirmation',row.book_confirmation?.confirmed_at||original.book_confirmation?.confirmed_at],['Local receipt',row.times?.received_at],['Last price change',row.last_price_change_at||original.last_price_change_at],['Price authority ends',row.current_authority?.price?.current_until]]));
    for(const ref of row.reference_calculation?.pair||[])clocks.append(el('h4',position({...ref,market:row.market},result.games)),facts([['Reference provider update',ref.times?.source_at],['Reference receipt',ref.times?.received_at]]));
    for(const book of row.reference_calculation?.contributors||[])for(const side of book.inputs||[])clocks.append(el('h4',name(book.venue)+' · '+human(side.side)),facts([['Original American odds',side.price_american],['Line',side.line],['Jurisdiction',side.jurisdiction],['Reviewed rule source',side.rule_source],['Reference provider update',side.source_at],['Reference receipt',side.received_at],['Shared frame receipt',side.frame_received_at]]));
    clocks.append(el('p','Capture, receipt and publication do not renew source evidence.','p-meta'));box.append(disclosure('Source details & clocks',clocks));
    const provider=row.source?.provider||original.source?.provider;
    const providerKind=['the_odds_api','sportsgameodds'].includes(provider)?'Aggregate':(['kalshi','polymarket_us','novig'].includes(provider)?'Direct':null);
    const native=section('Original source');native.append(facts([['Source type',providerKind],['Venue',row.venue?name(row.venue):null],['Original side',row.native_side||row.source?.native_side],['Original price',row.original?.value],['Price units',human(row.original?.units)],['Native price',row.original?.native_value],['Transformation',human(row.original?.transformation)]]));box.append(disclosure('Source price & interpretation',native));
    const retained=section('Retained historical arithmetic');retained.append(el('p','Exact member evidence, separate from the pinned displayed availability. These values cannot restore a withdrawn estimate.'),facts([['Before-fee EV',pct(details.row.gross_return_percent)],['After reviewed-fee EV',pct(details.row.conditional_return_percent)],['Member funding',a.amount==null?null:'$'+fmt(a.amount)],['Member buffer',a.buffer==null?null:pct(num(a.buffer)*100)],['Member scenario',human(a.scenario)],['Member sizing',human(a.sizing)]]));
    retained.append(disclosure('Literal inputs, formulas and fee records',el('pre',JSON.stringify({displayed:row,evidence:details},null,2))));box.append(disclosure('Retained arithmetic & exact inputs',retained),link('Inspect exact inputs in Admin',inspect,'math-admin'));
    return box;
  }
  function changes(notice){
    const box=el('div',null,'math-changes'),old=notice.old||{},next=notice.latest||{};
    function change(label,a,b){if(JSON.stringify(a)!==JSON.stringify(b))box.append(el('p',`${label}: ${a??'Unavailable'} → ${b??'Unavailable'}`));}
    if(old.original?.value!==next.original?.value&&old.offered&&next.offered){const line=el('p','Offered odds: ');line.append(odd(old.offered,''),document.createTextNode(' → '),odd(next.offered,''));box.append(line);}
    change('Original price',old.original?.value,next.original?.value);
    change('EV before trade fees',pct(old.before_trade_fee),pct(next.before_trade_fee));
    if(old.original?.value!==next.original?.value)box.append(el('small',human(next.original?.units||old.original?.units),'compare-note'));
    change('EV after trade fees',pct(old.after_trade_fee),pct(next.after_trade_fee));
    change('Conservative estimate',pct(old.conservative_estimate),pct(next.conservative_estimate));
    change('Fair win probability',old.probability==null?'Unavailable':fmt(num(old.probability)*100)+'%',next.probability==null?'Unavailable':fmt(num(next.probability)*100)+'%');
    change('Reference book',name(old.reference_venue),name(next.reference_venue));
    if(JSON.stringify(old.reference_pair)!==JSON.stringify(next.reference_pair)){
      const label=old.reference_venue&&old.reference_venue===next.reference_venue?name(old.reference_venue)+' reference':'Reference pair';
      const prices=v=>(v.reference_pair||[]).map(r=>`${position(r)} ${r.original?.value??'Unavailable'}`).join(' / ')||'Unavailable';change(label,prices(old),prices(next));
      if(prices(old)===prices(next))box.append(el('p',label+' binding changed.'));
    }
    for(const [key,label] of [['fee_basis','Reviewed fees'],['conservative_fee_basis','Conservative fees']])if(JSON.stringify(old[key])!==JSON.stringify(next[key])){
      const summarize=f=>f?`${f.trade_fee_usd==null?'Unavailable':'$'+fmt(f.trade_fee_usd,6)} · ${human(f.reason||f.evidence?.version||f.ranking_basis)}`:'Unavailable';
      if(summarize(old[key])!==summarize(next[key]))change(label,summarize(old[key]),summarize(next[key]));else box.append(el('p',label+' assumptions or applicability changed.'));
    }
    const availability=v=>v.price_current===false?'Price unavailable':v.reasons?.length?v.reasons.map(human).join('; '):v.after_trade_fee==null?'After-fee EV unavailable':'Price and after-fee EV available';
    change('Availability',availability(old),notice.state==='removed'?'Offer removed':availability(next));
    if(!box.childNodes.length)box.append(el('p','Calculation inputs or authority changed; use latest to adopt the complete revision.'));
    return box;
  }
  return {content,changes};
})();
