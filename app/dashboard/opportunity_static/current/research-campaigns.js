import {card,count,label,link,node,pairs,pct,readJSON,table,time,usd} from './workspace-ui.js';
import {qualityComparison} from './research-quality.js';
import {number} from './workspace-format.js';

const API='/api/research/workspace/campaigns';
const titles={best_venue:'Best venue only',all_venues:'All qualifying venues'};
export const campaignHref=(id,variant='best_venue',context={})=>'/research?'+new URLSearchParams({
  section:'experiments',campaign:id,variant,...context,
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
  root.append(node('p','Paper-only schedules, daily results and EV comparisons.'));
  for(const c of values||[])root.append(node('p'),link(`${c.name} · ${c.start_date}–${c.end_date} · ${percent(c.kelly_multiplier)}% Kelly`,href(c.id,'best_venue',{view:'daily'}),'research-button'));
  root.append(link('Create a scheduled experiment','/research?section=experiments&view=schedule','research-button'));
  return root;
}

export function campaignForm(root,config=null,revision=null,variant='best_venue'){
  const panel=card(config?'Create a revised experiment':'Create a daily paper experiment');
  panel.append(node('p','Changes create a separate experiment. Earlier definitions and runs remain available. Dates use Eastern time.'));
  const form=node('form',undefined,'campaign-form'), inputs={};
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const get=type=>parts.find(p=>p.type===type).value;
  const monday=new Date(`${get('year')}-${get('month')}-${get('day')}T12:00:00Z`);monday.setUTCDate(monday.getUTCDate()-(monday.getUTCDay()+6)%7);
  const sunday=new Date(monday);sunday.setUTCDate(sunday.getUTCDate()+6);
  const defaults={name:'NCAAB daily experiment',start_date:monday.toISOString().slice(0,10),end_date:sunday.toISOString().slice(0,10),minimum_ev:'4',kelly_multiplier:'2.5',reference_bankroll_usd:'10000',bucket_edges:'4, 8, 15, 25'};
  if(config)Object.assign(defaults,config,{minimum_ev:percent(config.minimum_ev),kelly_multiplier:percent(config.kelly_multiplier),bucket_edges:config.bucket_edges.map(percent).join(', ')});
  for(const [key,title,type] of [['name','Experiment name','text'],['start_date','First game date','date'],['end_date','Last game date','date'],['minimum_ev','Minimum EV (%)','text'],['kelly_multiplier','Full Kelly used (%)','text'],['reference_bankroll_usd','Sizing reference ($)','text'],['bucket_edges','EV bucket boundaries (%)','text']]){
    const lab=node('label',title),input=node('input');input.name=key;input.type=type;input.value=defaults[key];input.required=true;
    lab.append(input);form.append(lab);inputs[key]=input;
  }
  const preview=node('p'),feedback=node('p');feedback.setAttribute('role','status');
  const explain=()=>{const scale=number(inputs.reference_bankroll_usd.value)*number(inputs.kelly_multiplier.value)/100;preview.textContent=`At −110 and 4% EV, this sizing commits about ${usd(scale*.04/(100/110))}. No portfolio budget cap or intraday compounding. Both venue variants are recorded.`;};
  form.addEventListener('input',explain);explain();
  const submit=node('button','Save and schedule experiment');submit.type='submit';
  form.onsubmit=async event=>{event.preventDefault();submit.disabled=true;feedback.textContent='Saving schedule…';
    try{const body=Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.value]));
      for(const key of ['minimum_ev','kelly_multiplier'])body[key]=decimalRate(body[key]);
      body.bucket_edges=body.bucket_edges.split(',').map(decimalRate);
      if(revision)body.supersedes=revision;
      const value=await readJSON(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      location.href=href(value.id,variant);
    }catch(error){feedback.textContent=error.message;submit.disabled=false;}};
  form.append(preview,submit,feedback);panel.append(form);
  panel.append(revision?link('Back to daily & weekly results',href(revision,variant)):link('Back to experiments','/research?section=experiments'));
  root.append(panel);
}

export function readCampaign(id,variant) {
  return readJSON(`${API}/${encodeURIComponent(id)}?`+new URLSearchParams({variant}))
    .then(data=>({...data,variant}));
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

function campaignHeader(config,variant,period,portfolioHref) {
  const heading=card(config.name);
  heading.classList.add('paper-workbench-header');
  heading.append(node('p',`${config.start_date}–${config.end_date} Eastern · Men’s D1 NCAAB · Paper experiment`,'workspace-caption'));
  const controls=node('div',undefined,'results-controls');
  const portfolios=node('nav',undefined,'workspace-variant');
  portfolios.setAttribute('aria-label','Paper portfolios');
  for(const [key,title] of Object.entries(titles)){
    const a=link(title,portfolioHref(key),'research-button');
    if(key===variant)a.setAttribute('aria-current','true');
    portfolios.append(a);
  }
  controls.append(period,portfolios);
  heading.append(controls);
  return heading;
}

export function renderScheduledDay(root,data,day,{daily,weekly,dayHref,portfolioHref}) {
  const snapshot=JSON.stringify(day), previous=rendered.get(root);
  if(previous?.heading===root.firstElementChild&&previous.snapshot===snapshot)return;
  const heading=campaignHeader(data.config,data.variant,workbenchPeriod(daily,weekly,'daily'),portfolioHref);
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
  notice.append(node('strong',day.error?'Daily report unavailable':label(day.state)),
    node('p',day.error || 'Awaiting retained capture evidence. Paper financials are unavailable.'),
    ...(day.next_check_at ? [node('p',`Next evidence check ${time(day.next_check_at)}`)] : []));
  heading.append(notice,link('Daily coverage and issue decisions','/data?'+new URLSearchParams({
    evidence:'mens-d1',scope:'mens-d1',date:day.date,variant:data.variant,
  })+'#mens-d1-issues'));
  root.replaceChildren(heading);
  rendered.set(root,{heading,snapshot});
}

export function renderCampaign(root,data,{edit=false,daily,weekly,dayHref,portfolioHref}={}){
  const {id,variant,config,weekly:weekData}=data;
  if(edit){root.replaceChildren();campaignForm(root,config,id,variant);return;}
  const snapshot=JSON.stringify(data), previous=rendered.get(root);
  if(previous?.heading===root.firstElementChild&&previous.snapshot===snapshot)return;
  const qualityOpened=root.querySelector('.paper-quality')?.open;
  root.replaceChildren();
  const heading=campaignHeader(config,variant,workbenchPeriod(daily,weekly,'weekly'),portfolioHref);
  const policy=node('details');
  policy.append(node('summary','Experiment rules'),node('p',`${percent(config.kelly_multiplier)}% of full Kelly on ${usd(config.reference_bankroll_usd)}; minimum EV ${percent(config.minimum_ev)}%. Historical days are retrospective replays. New dates are automatically recorded from retained T−10 evidence.`));
  heading.append(policy);
  const actions=node('div',undefined,'workspace-links');
  actions.append(link('Export daily, weekly and EV analysis',`${API}/${id}?`+new URLSearchParams({variant,export:'1'})),
    link('Collection and results jobs','/settings#mens-d1-jobs'));
  if(config.supersedes)actions.append(link('Open previous experiment version',href(config.supersedes,variant)));
  const revise=node('button','Edit as a new version');
  revise.onclick=()=>{location.href=href(id,variant)+'&view=revise';};
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
    const description=day.error||`${label(day.state)} · ${label(day.result_state||'waiting for day')}${day.result_pending?' · updating':''}${day.retrospective?' · retrospective':''}`;
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
