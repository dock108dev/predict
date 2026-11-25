import {card,count,label,link,node,pairs,pct,readJSON,table,time,usd} from './workspace-ui.js';
import {qualityComparison} from './research-quality.js';
import {number} from './workspace-format.js';
import {rational} from './comparison-board.js';

const API='/api/research/workspace/campaigns';
const titles={best_venue:'Best venue only',all_venues:'All qualifying venues'};
const allPortfolios=Object.keys(titles);
const modes={fixed_profit:'Win fixed profit',kelly:'Kelly'};
const defaultOddsEdges=['200','300','500','1000'];
const oddsEdgeList=edges=>edges.map(edge=>'+'+edge).join(', ');
export const campaignHref=(id,variant='best_venue',context={})=>'/research?'+new URLSearchParams({
  section:'experiments',campaign:id,variant,...Object.fromEntries(Object.entries(context).filter(([,value])=>value!=null)),
});
const href=campaignHref;
const money=value=>value==null?'—':usd(value);
const summaryRows=s=>[count(s.tickets),money(s.stake_usd),money(s.expected_profit_usd),money(s.return_usd),money(s.pnl_usd),pct(s.roi),`${count(s.wins)} / ${count(s.losses)} / ${count(s.unresolved)}`];
const headers=['Tickets','Staked','Expected profit','Returned','Modeled P/L','ROI on graded stake','Win / loss / unresolved'];
export const band=b=>`${percent(b.minimum)}%${b.maximum?'–<'+percent(b.maximum)+'%':'+'}`;
const rendered = new WeakMap();

export function workbenchPeriod(daily, weekly, active) {
  const nav=node('nav',undefined,'paper-workbench-period workspace-variant');
  nav.setAttribute('aria-label','Report period');
  for (const [name,title,destination] of [['daily','Daily',daily],['weekly','Weekly',weekly]]) {
    const tab=destination ? link(title,destination,'research-button') : node('span',title,'research-button');
    if (name===active) tab.setAttribute('aria-current','page');
    nav.append(tab);
  }
  return nav;
}

export function workbenchSizing(config, available, active, destination) {
  if (available.length<2 || !destination) return null;
  const nav=node('nav',undefined,'workspace-variant');
  nav.setAttribute('aria-label','Sizing mode');
  for (const mode of available) {
    const tab=link(sizingTitle(config,mode),destination(mode),'research-button');
    if (mode===active) tab.setAttribute('aria-current','page');
    nav.append(tab);
  }
  return nav;
}

export function sizingTitle(config, mode=config.sizing_mode || 'kelly') {
  if (mode!=='fixed_profit') return 'Kelly';
  const amount=number(config.target_profit_usd);
  return amount==null ? modes.fixed_profit : 'Win '+(Number.isInteger(amount) ? '$'+amount.toLocaleString('en-US') : exactMoney(config.target_profit_usd));
}

export function exactMoney(value) {
  if(value==null)return 'Unavailable';
  const [numerator,denominator]=rational(String(value).replace(/^(-?)\./,(_,sign)=>sign+'0.'));
  return 100n*numerator%denominator ? `${usd(value)} (${value} USD exact)` : usd(value);
}

export function fixedProfitFields(sizing) {
  return {
    'Target win profit':exactMoney(sizing.target_profit_usd),
    'Modeled net profit on a win':exactMoney(sizing.modeled_win_profit_usd),
    'Modeled profit minus target':exactMoney(sizing.profit_difference_usd),
  };
}

export function configuredModes(config) {
  return config.kelly_comparison ? ['fixed_profit','kelly'] : [config.sizing_mode || 'kelly'];
}

export function configuredPortfolio(config, requested) {
  const portfolios=config?.portfolios || allPortfolios;
  return portfolios.includes(requested) ? requested : portfolios[0];
}

function rescale(input, numerator, denominator) {
  const raw = String(input).trim();
  const decimal = /^(\d*)(?:\.(\d+))?$/.exec(raw);
  const fraction = /^(\d+)\/(\d+)$/.exec(raw);
  if (!raw || (!decimal && !fraction)) throw Error('Enter percentages as decimals or fractions.');
  const digits = decimal?.[2] || '';
  let a = numerator * BigInt(fraction ? fraction[1] : (decimal[1] || '0') + digits);
  let b = denominator * (fraction ? BigInt(fraction[2]) : 10n ** BigInt(digits.length));
  if (!b) throw Error('Use a nonzero fraction denominator.');
  const gcd = (a, b) => b === 0n ? a : gcd(b, a % b);
  const divisor = gcd(a, b);
  a /= divisor;
  b /= divisor;
  const whole = a / b;
  let remainder = a % b;
  if (!remainder) return String(whole);
  let tail = '';
  while (remainder && tail.length < 12) {
    remainder *= 10n;
    tail += String(remainder / b);
    remainder %= b;
  }
  return remainder ? `${a}/${b}` : `${whole}.${tail}`;
}

const percent=value=>rescale(value,100n,1n);
const decimalRate=value=>{
  if (String(value).trim().length > 32) throw Error('Enter percentages as decimals or fractions.');
  return rescale(value,1n,100n);
};

export function campaignList(values){
  const root=card('Daily & weekly experiments');
  root.append(link('Create experiment','/research?section=experiments&view=schedule','research-button'));
  const entries=node('ul',undefined,'campaign-list');
  for(const c of values||[]) {
    const item=node('li');
    item.append(link(c.name,href(c.id,configuredPortfolio(c,'best_venue'),{view:'daily'})),
      node('p',`${c.start_date}–${c.end_date} Eastern · ${configuredModes(c).map(mode=>sizingTitle(c,mode)).join(' + ')}`));
    entries.append(item);
  }
  if(entries.childElementCount)root.append(entries);
  return root;
}

const evidenceRules = {
  'Capture timing':'Final eligible retained observation at T−10 (ten minutes before the scheduled start)',
  'Reference prices':'Exact-line reference inputs and probability recorded with each capture',
  'Fee assumption':'Use the captured fee model. Retrospective reconstructions assume $0 fees.',
};

export function ruleSummary(config) {
  const fixed=config.sizing_mode==='fixed_profit';
  const kelly=config.kelly_multiplier!=null
    ? `${percent(config.kelly_multiplier)}% of full Kelly on a ${usd(config.reference_bankroll_usd)} reference bankroll` : null;
  return {
    'Game scope':'Men’s NCAA Division I vs. Division I',
    'Game dates':`${config.start_date} through ${config.end_date}, inclusive (Eastern)`,
    'Primary sizing':fixed ? `${sizingTitle(config)} per winning paper trade, using the nearest achievable positive net profit` : kelly,
    ...(fixed&&config.kelly_comparison ? {'Kelly comparison':kelly} : {}),
    'Minimum EV':`${percent(config.minimum_ev)}% unrounded, including after sizing`,
    'Minimum stake':config.minimum_stake_usd == null ? 'No minimum' : `${exactMoney(config.minimum_stake_usd)} per trade after sizing`,
    'EV buckets':config.bucket_edges.map((minimum,i,edges)=>band({minimum,maximum:edges[i+1]})).join(', '),
    'Posted odds bucket boundaries':oddsEdgeList(config.odds_bucket_edges || defaultOddsEdges),
    Portfolios:(config.portfolios || allPortfolios).map(portfolio=>titles[portfolio]).join(' and '),
    ...evidenceRules,
  };
}

export function campaignForm(root,config=null,revision=null,variant='best_venue',context={},options={}){
  const panel=card(config?'Revise experiment':'Create experiment');
  panel.append(node('p',config?'Saving changes creates a new version. Earlier reports remain available.':'Save a paper experiment to replay retained evidence and schedule upcoming game dates.'));
  const form=node('form',undefined,'campaign-form'), fields=node('div',undefined,'campaign-fields'), inputs={};
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const get=type=>parts.find(p=>p.type===type).value;
  const monday=new Date(`${get('year')}-${get('month')}-${get('day')}T12:00:00Z`);monday.setUTCDate(monday.getUTCDate()-(monday.getUTCDay()+6)%7);
  const sunday=new Date(monday);sunday.setUTCDate(sunday.getUTCDate()+6);
  const defaults={
    name:'', scope:'mens-d1', start_date:monday.toISOString().slice(0,10), end_date:sunday.toISOString().slice(0,10),
    minimum_ev:'4', minimum_stake_usd:'1.00', sizing_mode:'fixed_profit', target_profit_usd:'10', kelly_comparison:false,
    kelly_multiplier:'2.5', reference_bankroll_usd:'10000', bucket_edges:'4, 8, 15, 25', portfolios:allPortfolios,
    odds_bucket_edges:oddsEdgeList(defaultOddsEdges),
  };
  if(config)Object.assign(defaults,config,{
    sizing_mode:config.sizing_mode || 'kelly', minimum_ev:percent(config.minimum_ev),
    minimum_stake_usd:config.minimum_stake_usd == null ? '' : rescale(config.minimum_stake_usd,1n,1n),
    target_profit_usd:config.target_profit_usd==null ? defaults.target_profit_usd : rescale(config.target_profit_usd,1n,1n),
    kelly_multiplier:config.kelly_multiplier==null ? defaults.kelly_multiplier : percent(config.kelly_multiplier),
    reference_bankroll_usd:config.reference_bankroll_usd==null ? defaults.reference_bankroll_usd : rescale(config.reference_bankroll_usd,1n,1n),
    bucket_edges:config.bucket_edges.map(percent).join(', '),
    odds_bucket_edges:oddsEdgeList(config.odds_bucket_edges || defaultOddsEdges),
  });
  const handoff=options.dataFilters;
  if (handoff) {
    const date=handoff.get('date');
    const useDate=(keys,fallback)=>keys.map(key=>handoff.get(key)).find(value=>value && /^\d{4}-\d{2}-\d{2}$/.test(value)) || fallback;
    defaults.start_date=useDate(['start_date','date_from','date'], date || '');
    defaults.end_date=useDate(['end_date','date_to','date'], date || '');
    if (handoff.get('scope') !== 'mens-d1') defaults.scope='';
  }
  function field(parent,key,title,{type='text',options,required=true,maxLength=32}={}) {
    const lab=node('label'), caption=node('span',title), input=node(options ? 'select' : 'input');
    input.name=key;
    caption.id='campaign-field-'+key;
    input.setAttribute('aria-labelledby',caption.id);
    lab.append(caption);
    if(options) input.append(...Object.entries(options).map(([value,text])=>new Option(text,value)));
    else input.type=type;
    if(type==='checkbox') {
      lab.className='campaign-check';
      input.checked=Boolean(defaults[key]);
      lab.prepend(input);
    } else {
      input.value=defaults[key];
      input.required=required;
      lab.append(input);
      if(type==='text')input.maxLength=maxLength;
    }
    parent.append(lab);
    inputs[key]=input;
    return input;
  }
  field(fields,'name','Experiment name',{maxLength:120});
  field(fields,'scope','Game scope',{options:{'':'Choose game scope','mens-d1':'Men’s NCAA Division I vs. Division I'}});
  field(fields,'start_date','First game date (Eastern)',{type:'date'});
  field(fields,'end_date','Last game date (Eastern)',{type:'date'});
  const retained=node('fieldset',undefined,'campaign-fields campaign-evidence-rules');
  retained.append(node('legend','Captured data and assumptions'), pairs(evidenceRules));
  fields.append(retained);
  field(fields,'sizing_mode','Sizing method',{options:modes});
  const fixed=node('fieldset',undefined,'campaign-fields');
  fixed.append(node('legend','Fixed profit settings'));
  field(fixed,'target_profit_usd','Target win profit ($)');
  field(fixed,'kelly_comparison','Compare with Kelly',{type:'checkbox'});
  const kelly=node('fieldset',undefined,'campaign-fields');
  kelly.append(node('legend','Kelly settings'));
  field(kelly,'kelly_multiplier','Full Kelly used (%)');
  field(kelly,'reference_bankroll_usd','Reference bankroll ($)');
  fields.append(fixed,kelly);
  const minimumStake=field(fields,'minimum_stake_usd','Minimum stake ($)',{required:false});
  minimumStake.setAttribute('aria-describedby','campaign-minimum-stake-help');
  const stakeHelp=node('small','Applied after sizing and modeled fees. Leave blank for no minimum.');
  stakeHelp.id='campaign-minimum-stake-help';
  minimumStake.parentElement.append(stakeHelp);
  field(fields,'minimum_ev','Minimum EV (%)');
  const edges=field(fields,'bucket_edges','EV bucket boundaries (%)',{maxLength:420});
  edges.setAttribute('aria-describedby','campaign-ev-help');
  const edgeHelp=node('small','Separate boundaries with commas. Start with the minimum EV.');
  edgeHelp.id='campaign-ev-help';
  edges.parentElement.append(edgeHelp);
  const oddsEdges=field(fields,'odds_bucket_edges','Posted odds bucket boundaries (American odds)',{maxLength:144});
  oddsEdges.setAttribute('aria-describedby','campaign-odds-help');
  const oddsHelp=node('small','Enter increasing whole-number odds above +100, separated by commas. Favorites and even money have fixed buckets.');
  oddsHelp.id='campaign-odds-help';
  oddsEdges.parentElement.append(oddsHelp);
  const portfolios=node('fieldset',undefined,'campaign-portfolios'), picks=[];
  portfolios.append(node('legend','Portfolios'));
  for(const [id,title] of Object.entries(titles)) {
    const lab=node('label',title,'campaign-check'), input=node('input');
    input.type='checkbox';input.value=id;input.checked=defaults.portfolios.includes(id);
    lab.prepend(input);portfolios.append(lab);picks.push(input);
  }
  portfolios.append(node('p','Best venue keeps one qualifying venue per exact bet. Different lines stay separate.'));
  fields.append(portfolios);
  let acceptFilters;
  if (handoff) {
    const dataFilters={sport:'Sport',game:'Game',search:'Search',provider:'Source',source:'Source',venue:'Venue',
      book:'Venue',original_bookmaker_id:'Venue',market:'Market',family:'Market',calculation_status:'Calculation',
      pull:'Original pull',receipt:'Original raw response',event_id:'Source event',competition:'Competition',include_alternates:'Alternate lines',
      reference_scope:'Reference scope',max_age_minutes:'Maximum quote age'};
    if (handoff.has('scope') && handoff.get('scope') !== 'mens-d1') dataFilters.scope='Scope';
    const unsupported=Object.entries(dataFilters).filter(([key])=>handoff.get(key));
    if (unsupported.length) {
      const disclosure=node('fieldset',undefined,'campaign-fields campaign-handoff');
      disclosure.append(node('legend','Review filters from Data'),
        node('p','These Data filters limit what you were browsing. The paper engine evaluates every supported market and venue in the experiment’s game scope and dates.'),
        pairs(Object.fromEntries(unsupported.map(([key,title])=>[title,handoff.get(key)]))));
      const acceptance=node('label','Use the experiment’s game scope and dates','campaign-check');
      acceptFilters=node('input');acceptFilters.type='checkbox';acceptFilters.required=true;
      acceptance.prepend(acceptFilters);disclosure.append(acceptance);fields.prepend(disclosure);
    }
  }
  function updateFields(){
    const isFixed=inputs.sizing_mode.value==='fixed_profit';
    fixed.hidden=fixed.disabled=!isFixed;
    kelly.hidden=kelly.disabled=isFixed&&!inputs.kelly_comparison.checked;
  }
  inputs.sizing_mode.onchange=inputs.kelly_comparison.onchange=updateFields;
  updateFields();
  const review=node('section',undefined,'campaign-review'), feedback=node('p');
  const reviewHeading=node('h3','Review experiment');
  reviewHeading.tabIndex=-1;
  review.setAttribute('aria-label','Review experiment');
  review.hidden=true;
  feedback.setAttribute('role','status');
  const next=node('button','Review'), back=node('button','Edit settings'), save=node('button','Save and run');
  next.type=save.type='submit';back.type='button';
  const actions=node('div',undefined,'workspace-links');
  actions.append(back,save);
  function build(){
    const body=Object.fromEntries(Object.entries(inputs).filter(([,input])=>!input.closest('fieldset:disabled'))
      .map(([key,input])=>[key,input.type==='checkbox' ? input.checked : input.value.trim()]));
    if(!body.name)throw Error('Enter an experiment name.');
    if(acceptFilters && !acceptFilters.checked)throw Error('Review which Data filters the experiment supports.');
    if(body.end_date<body.start_date)throw Error('Choose a last game date on or after the first.');
    if((Date.parse(body.end_date)-Date.parse(body.start_date))/86400000>=366)throw Error('Choose an experiment period of up to one year.');
    for(const key of ['minimum_ev','kelly_multiplier'])if(body[key]!=null)body[key]=decimalRate(body[key]);
    body.bucket_edges=body.bucket_edges.split(',').map(decimalRate);
    const boundaryPairs=body.bucket_edges.map(rational);
    if(body.bucket_edges.length>12 || body.bucket_edges[0]!==body.minimum_ev ||
       boundaryPairs.some(([a,b],i,pairs)=>i>0&&a*pairs[i-1][1]<=b*pairs[i-1][0])) {
      throw Error('Enter up to twelve increasing EV boundaries, beginning at the minimum EV.');
    }
    const oddsInputs=body.odds_bucket_edges.split(',').map(value=>value.trim());
    const oddsBoundaries=oddsInputs.map(Number);
    if (oddsInputs.length>12 || oddsInputs.some(value=>!/^\+?\d{1,9}$/.test(value)) ||
        oddsBoundaries.some((value,i)=>value<=(oddsBoundaries[i-1] ?? 100))) {
      throw Error('Enter one to twelve increasing whole-number odds boundaries above +100.');
    }
    const normalizedOdds=oddsBoundaries.map(String);
    if (normalizedOdds.join(',')===defaultOddsEdges.join(','))delete body.odds_bucket_edges;
    else body.odds_bucket_edges=normalizedOdds;
    if(number(body.minimum_ev)<=0)throw Error('Enter a positive minimum EV.');
    if(body.kelly_multiplier!=null&&!(number(body.kelly_multiplier)>0&&number(body.kelly_multiplier)<=1)) {
      throw Error('Enter a Kelly fraction greater than 0% and at most 100%.');
    }
    if(body.minimum_stake_usd==='')delete body.minimum_stake_usd;
    for(const [key,title] of [['target_profit_usd','win profit target'],['reference_bankroll_usd','reference bankroll'],
      ['minimum_stake_usd','minimum stake']]) {
      if(body[key]!=null && (!(number(body[key])>0) || !/^(\d+(\.\d+)?|\.\d+|\d+\/\d+)$/.test(body[key]))) {
        throw Error(`Enter a positive ${title}.`);
      }
    }
    body.portfolios=picks.filter(input=>input.checked).map(input=>input.value);
    if(!body.portfolios.length)throw Error('Choose at least one portfolio.');
    if(revision)body.supersedes=revision;
    return body;
  }
  let reviewed;
  back.onclick=()=>{
    reviewed=null;review.hidden=true;fields.hidden=next.hidden=false;
    feedback.textContent='';inputs.name.focus();
  };
  form.onsubmit=async event=>{
    event.preventDefault();
    if(save.disabled)return;
    feedback.textContent='';
    try{
      if(!reviewed){
        const body=build();
        review.replaceChildren(reviewHeading,node('p',body.name),pairs(ruleSummary(body)),
          node('p','Elapsed dates replay automatically from retained evidence. Future dates wait for their capture windows. All results are paper only.'),actions);
        reviewed=body;fields.hidden=next.hidden=true;review.hidden=false;
        reviewHeading.focus();
        return;
      }
      save.disabled=back.disabled=true;feedback.textContent='Saving experiment…';
      const value=await readJSON(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(reviewed)});
      location.href=options.afterSave ? options.afterSave(value,configuredPortfolio(reviewed,variant))
        : href(value.id,configuredPortfolio(reviewed,variant),{view:'weekly',mode:reviewed.sizing_mode});
    }catch(error){feedback.textContent=error.message;save.disabled=back.disabled=false;}
  };
  form.append(fields,next,review,feedback);panel.append(form);
  panel.append(options.backHref ? link(revision?'Back to experiment':'Back to experiments',options.backHref)
    : revision?link('Back to experiment',href(revision,variant,{...context,view:'weekly'}))
    :link('Back to experiments','/research?section=experiments'));
  root.append(panel);
}

export function readCampaign(id,variant,mode) {
  return readJSON(`${API}/${encodeURIComponent(id)}?`+new URLSearchParams({variant,...(mode ? {mode}: {})}))
    .then(data=>({...data,variant:data.variant||variant,mode:data.mode||data.config.sizing_mode||'kelly'}));
}

export function campaignDays(campaign) {
  if (!campaign) return [];
  const days=[], day=new Date(campaign.start_date+'T12:00:00Z'), end=new Date(campaign.end_date+'T12:00:00Z');
  while (day<=end) {
    days.push(day.toISOString().slice(0,10));
    day.setUTCDate(day.getUTCDate()+1);
  }
  return days;
}

function campaignHeader(data,period,portfolioHref,modeHref) {
  const {config,variant,mode}=data;
  const heading=card(config.name);
  heading.classList.add('paper-workbench-header');
  heading.append(node('p',`${config.start_date}–${config.end_date} Eastern · Men’s D1 vs. D1 · ${sizingTitle(config,mode)} · Paper experiment`,'workspace-caption'));
  const controls=node('div',undefined,'results-controls');
  controls.append(period);
  const sizing=workbenchSizing(config,data.available_modes || configuredModes(config),mode,modeHref);
  if(sizing)controls.append(sizing);
  const portfolios=node('nav',undefined,'workspace-variant');
  portfolios.setAttribute('aria-label','Paper portfolios');
  for(const key of config.portfolios || allPortfolios){
    const a=link(titles[key],portfolioHref(key),'research-button');
    if(key===variant)a.setAttribute('aria-current','true');
    portfolios.append(a);
  }
  controls.append(portfolios);
  heading.append(controls);
  return heading;
}

const dayStatus={
  scheduled:'Scheduled',
  replay_queued:'Replay queued',
  replaying:'Replaying retained evidence',
  waiting_for_evidence:'Waiting for capture evidence',
  deferred_for_capture:'Waiting for T−10 capture',
  no_usable_capture:'Missing usable T−10 evidence',
  no_selected_tickets:'Valid zero-trade result',
  awaiting_results:'Awaiting sporting results',
  partially_graded:'Partially graded',
  graded:'Graded',
  collecting:'Capture in progress',
  unresolved:'Grading unresolved',
  published:'Replay published',
};

function statusText(day) {
  if(day.replay_state==='replaying') {
    const prior=dayStatus[day.result_state] || (day.result_pending ? 'Grading update pending' : null);
    return [dayStatus.replaying,prior,day.capture_state==='partial' ? 'Partial T−10 coverage' : null].filter(Boolean).join(' · ');
  }
  if(day.error) return 'Replay failed';
  return [dayStatus[day.result_state] || dayStatus[day.replay_state] || dayStatus[day.state] || label(day.state),
    day.capture_state==='partial' ? 'Partial T−10 coverage' : null,
    day.result_pending ? 'Grading update pending' : null, day.retrospective ? 'Retrospective replay' : null].filter(Boolean).join(' · ');
}

export function comparisonCounts(counts) {
  return {
    'Qualify in both modes':count(counts.jointly_qualifying_quotes),
    'Qualify only at fixed profit':count(counts.fixed_profit_only_qualifying_quotes),
    'Qualify only at Kelly size':count(counts.kelly_only_qualifying_quotes),
    'Selected in both modes':count(counts.jointly_selected_quotes),
    'Selected only at fixed profit':count(counts.fixed_profit_only_selected_quotes),
    'Selected only at Kelly size':count(counts.kelly_only_selected_quotes),
    'Best venue changes':count(counts.venue_changes),
  };
}

export function renderScheduledDay(root,data,day,{daily,weekly,dayHref,portfolioHref,modeHref,editHref}) {
  const snapshot=JSON.stringify(day), previous=rendered.get(root);
  if(previous?.heading===root.firstElementChild&&previous.snapshot===snapshot)return;
  const heading=campaignHeader(data,workbenchPeriod(daily,weekly,'daily'),portfolioHref,modeHref);
  const dateLabel=node('label','Game date (Eastern)'), select=node('select');
  select.append(...data.days.map(entry=>new Option(entry.date,entry.date)));
  select.value=day.date;
  select.onchange=()=>dayHref(select.value);
  dateLabel.append(select);
  const form=node('div',undefined,'workspace-form');
  form.append(dateLabel);
  heading.querySelector('.results-controls').append(form);
  const notice=node('div',undefined,'workspace-notice results-status');
  notice.setAttribute('role','status');
  const replaying=['replay_queued','replaying'].includes(day.replay_state);
  notice.append(node('strong',statusText(day)),
    node('p',replaying ? 'Paper financials appear after the retained-evidence replay and grading.'
      : day.error || 'Awaiting retained capture evidence. Paper financials are unavailable.'),
    ...(day.next_check_at ? [node('p',`Next evidence check ${time(day.next_check_at)}`)] : []));
  const actions=node('div',undefined,'workspace-links');
  actions.append(link('Daily coverage and issue decisions','/data?'+new URLSearchParams({
    evidence:'mens-d1',scope:'mens-d1',date:day.date,variant:data.variant,
  })+'#mens-d1-issues'),link('Edit as a new version',editHref,'research-button'));
  heading.append(notice,actions);
  root.replaceChildren(heading);
  rendered.set(root,{heading,snapshot});
}

export function renderCampaign(root,data,{edit=false,daily,weekly,dayHref,portfolioHref,modeHref,editHref,context}={}){
  const {id,variant,config,mode,weekly:weekData}=data;
  if(edit){root.replaceChildren();campaignForm(root,config,id,variant,context);return;}
  const snapshot=JSON.stringify(data), previous=rendered.get(root);
  if(previous?.heading===root.firstElementChild&&previous.snapshot===snapshot)return;
  const qualityOpened=root.querySelector('.paper-quality')?.open;
  root.replaceChildren();
  const heading=campaignHeader(data,workbenchPeriod(daily,weekly,'weekly'),portfolioHref,modeHref);
  const policy=node('details');
  policy.append(node('summary','Experiment rules'),pairs(ruleSummary(config)));
  heading.append(policy);
  const actions=node('div',undefined,'workspace-links');
  actions.append(link('Export daily, weekly and EV analysis',`${API}/${id}?`+new URLSearchParams({variant,mode,export:'1'})),
    link('Collection and results jobs','/settings#mens-d1-jobs'));
  if(config.supersedes)actions.append(link('Open previous experiment version',href(config.supersedes,variant)));
  const revise=node('button','Edit as a new version');
  revise.onclick=()=>{location.href=editHref;};
  actions.append(revise);heading.append(actions);root.append(heading);
  rendered.set(root,{heading,snapshot});
  const week=card('Week / experiment total');week.append(node('p',`${data.reported_days} of ${data.days.length} daily reports available. Pending days and ungraded trades are not zero-result days. Only the latest run for each day is counted.`));
  const s=weekData?.summary, available=Boolean(s&&data.reported_days>0);
  week.append(pairs({'Modeled P/L':available?money(s.pnl_usd):'Pending','ROI on graded stake':available?pct(s.roi):'Pending','Total staked':available?money(s.stake_usd):'Pending','Expected profit':available?money(s.expected_profit_usd):'Pending','Tickets':available?count(s.tickets):'Pending','Ungraded stake':available?money(s.unresolved_stake_usd):'Pending'},'workspace-stats'));
  if(data.days.some(d=>d.result_pending||d.error))week.append(node('p','Some reports are updating. Totals use the last published results shown for each day.'));
  week.append(table(headers,[available?summaryRows(s):Array(headers.length).fill('Pending')]));
  const quality=available&&qualityComparison(weekData.quality);
  if(quality){quality.open=Boolean(qualityOpened);week.append(quality);}
  root.append(week);
  if(data.comparison) {
    const comparison=card('Win profit and Kelly comparison');
    comparison.append(node('p','Counts use dates with both replays available and match the same frozen quotes and exact bets.'),pairs(comparisonCounts(data.comparison)));
    root.append(comparison);
  }
  const days=card('Daily results');days.append(table(['Game date','Recording / results','Next evidence check','Frozen / rebuilt / missing / pending',...headers],data.days.map(day=>{
    const c=day.captures||{}, dateCell=node('div');
    dateCell.append(link(day.date,dayHref(day.date,day.run_id)));
    const older=(day.snapshots||[]).filter(snapshot=>snapshot.id!==day.run_id);
    if(older.length){
      const history=node('details'), revisions=node('ul');
      history.append(node('summary',`Previous snapshots (${count(older.length)})`),revisions);
      for(const snapshot of older){
        const item=node('li');item.append(link(`${time(snapshot.recorded_at)} · ${snapshot.id.slice(0,12)}`,dayHref(day.date,snapshot.id)));revisions.append(item);
      }
      dateCell.append(history);
    }
    const description=day.error && day.replay_state!=='replaying'
      ? 'Replay failed. The next scheduled check will retry.' : statusText(day);
    const financials=day.analysis?summaryRows(day.analysis.summary):Array(headers.length).fill(day.result_state==='no_usable_capture'?'Unavailable':'Pending');
    return [dateCell,description,day.next_check_at?time(day.next_check_at):'—',
      day.captures?`${c.captured||0} / ${c.reconstructed||0} / ${(c.missed||0)+(c.failed||0)+(c.refused||0)+(c.no_task||0)} / ${(c.pending||0)+(c.claimed||0)}`:'Awaiting evidence', ...financials];
  })));root.append(days);
  if(!available)return;
  const buckets=card('EV buckets');buckets.append(node('p','Non-overlapping buckets use unrounded screening EV. They partition the selected portfolio; percentages have no gaps.'));
  buckets.append(table(['Screening EV',...headers],weekData.buckets.map(b=>[band(b),...summaryRows(b.summary)])));root.append(buckets);
  const thresholds=card('What if the minimum EV changed?');thresholds.append(node('p','Separate counterfactual screens over the same retained opportunities. Each minimum reselects the best qualifying venue where applicable. Rows overlap and must not be added together.'));
  thresholds.append(table(['Minimum EV',...headers],weekData.thresholds.map(b=>[`≥${percent(b.minimum)}%`,...summaryRows(b.summary)])));root.append(thresholds);
  const comparisons=card('EV comparisons by day');
  for(const day of data.days.filter(d=>d.analysis)){
    comparisons.append(node('h3',day.date),
      table(['EV bucket',...headers],day.analysis.buckets.map(b=>[band(b),...summaryRows(b.summary)])),
      table(['Minimum EV',...headers],day.analysis.thresholds.map(b=>[`≥${percent(b.minimum)}%`,...summaryRows(b.summary)])));
  }
  root.append(comparisons);
  root.append(node('p','Modeled results assume recorded fee and quoted-size inputs. Full-slate and market completeness can remain unknown; each daily report shows missing captures and sources. Result corrections update the daily and weekly views automatically.'));
}
