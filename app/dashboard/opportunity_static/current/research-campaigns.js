import {card,count,label,link,node,pairs,pct,readJSON,table,time,usd} from './workspace-ui.js';
import {qualityComparison} from './research-quality.js';
import {number} from './workspace-format.js';

const API='/api/research/workspace/campaigns';
const titles={best_venue:'Best venue only',all_venues:'All qualifying venues'};
const href=(id,variant='best_venue')=>'/research?'+new URLSearchParams({section:'experiments',campaign:id,variant});
const dayHref=(day,run,variant)=>'/research?'+new URLSearchParams({section:'experiments',scope:'mens-d1',date:day,run,variant});
const money=value=>value==null?'—':usd(value);
const summaryRows=s=>[count(s.tickets),money(s.stake_usd),money(s.expected_profit_usd),money(s.return_usd),money(s.pnl_usd),pct(s.roi),`${count(s.wins)} / ${count(s.losses)} / ${count(s.unresolved)}`];
const headers=['Tickets','Staked','Expected profit','Returned','Modeled P/L','ROI on graded stake','Win / loss / unresolved'];
const band=b=>`${percent(b.minimum)}%${b.maximum?'–<'+percent(b.maximum)+'%':'+'}`;
const rendered = new WeakMap();

function rescale(input, numerator, denominator) {
  const raw = String(input).trim();
  const decimal = /^(\d*)(?:\.(\d+))?$/.exec(raw);
  const fraction = /^(\d+)\/(\d+)$/.exec(raw);
  if (!raw || raw.length > 32 || (!decimal && !fraction)) throw Error('Enter percentages as decimals or fractions.');
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
const decimalRate=value=>rescale(value,1n,100n);

export function campaignList(values){
  const root=card('Daily & weekly experiments');
  root.append(node('p','Paper-only schedules, daily results and EV comparisons.'));
  for(const c of values||[])root.append(node('p'),link(`${c.name} · ${c.start_date}–${c.end_date} · ${percent(c.kelly_multiplier)}% Kelly`,href(c.id),'research-button'));
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

export async function renderCampaign(root,id,variant,current,{edit=false}={}){
  const data=await readJSON(`${API}/${id}?`+new URLSearchParams({variant}));
  if(!current()||root.querySelector('form'))return;
  if(edit){root.replaceChildren();campaignForm(root,data.config,id,variant);return;}
  const snapshot=JSON.stringify(data), previous=rendered.get(root);
  if(previous?.heading===root.firstElementChild&&previous.snapshot===snapshot)return;
  const qualityOpened=root.querySelector('.paper-quality')?.open;
  root.replaceChildren();const {config,weekly}=data;
  const heading=card(config.name);heading.append(node('p',`${config.start_date}–${config.end_date} Eastern · Men’s D1 NCAAB · Paper only`));
  heading.append(node('p',`${percent(config.kelly_multiplier)}% of full Kelly on ${usd(config.reference_bankroll_usd)}; minimum EV ${percent(config.minimum_ev)}%. Historical days are retrospective replays. New dates are automatically recorded from retained T−10 evidence.`));
  const nav=node('div',undefined,'workspace-variant');for(const key of Object.keys(titles)){const a=link(titles[key],href(id,key),'research-button');if(key===variant)a.setAttribute('aria-current','true');nav.append(a);}heading.append(nav);
  const actions=node('div',undefined,'workspace-links');
  actions.append(link('Export daily, weekly and EV analysis',`${API}/${id}?`+new URLSearchParams({variant,export:'1'})),
    link('Collection and results jobs','/settings#mens-d1-jobs'));
  if(config.supersedes)actions.append(link('Open previous experiment version',href(config.supersedes,variant)));
  const revise=node('button','Edit as a new version');
  revise.onclick=()=>{location.href=href(id,variant)+'&view=revise';};
  actions.append(revise);heading.append(actions);root.append(heading);
  rendered.set(root,{heading,snapshot});
  const week=card('Week / experiment total');week.append(node('p',`${data.reported_days} of ${data.days.length} daily reports available. Pending days and ungraded trades are not zero-result days. Only the latest run for each day is counted.`));
  const s=weekly?.summary, available=Boolean(s&&data.reported_days>0);
  week.append(pairs({'Modeled P/L':available?money(s.pnl_usd):'Pending','ROI on graded stake':available?pct(s.roi):'Pending','Total staked':available?money(s.stake_usd):'Pending','Expected profit':available?money(s.expected_profit_usd):'Pending','Tickets':available?count(s.tickets):'Pending','Ungraded stake':available?money(s.unresolved_stake_usd):'Pending'},'workspace-stats'));
  if(data.days.some(d=>d.result_pending||d.error))week.append(node('p','Some reports are updating. Totals use the last published results shown for each day.'));
  week.append(table(headers,[available?summaryRows(s):Array(headers.length).fill('Pending')]));
  const quality=available&&qualityComparison(weekly.quality);
  if(quality){quality.open=Boolean(qualityOpened);week.append(quality);}
  root.append(week);
  const days=card('Daily results');days.append(table(['Game date','Recording / results','Next evidence check','Frozen / rebuilt / missing / pending',...headers],data.days.map(day=>{
    const c=day.captures||{}, dateCell=node('div');
    dateCell.append(day.run_id?link(day.date,dayHref(day.date,day.run_id,variant)):node('span',day.date));
    const older=(day.snapshots||[]).filter(snapshot=>snapshot.id!==day.run_id);
    if(older.length){
      const history=node('details'), revisions=node('ul');
      history.append(node('summary',`Previous snapshots (${count(older.length)})`),revisions);
      for(const snapshot of older){
        const item=node('li');item.append(link(`${time(snapshot.recorded_at)} · ${snapshot.id.slice(0,12)}`,dayHref(day.date,snapshot.id,variant)));revisions.append(item);
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
  buckets.append(table(['Screening EV',...headers],weekly.buckets.map(b=>[band(b),...summaryRows(b.summary)])));root.append(buckets);
  const thresholds=card('What if the minimum EV changed?');thresholds.append(node('p','Separate counterfactual screens over the same retained opportunities. Each minimum reselects the best qualifying venue where applicable. Rows overlap and must not be added together.'));
  thresholds.append(table(['Minimum EV',...headers],weekly.thresholds.map(b=>[`≥${percent(b.minimum)}%`,...summaryRows(b.summary)])));root.append(thresholds);
  const daily=card('EV comparisons by day');for(const day of data.days.filter(d=>d.analysis)){daily.append(node('h3',day.date),table(['EV bucket',...headers],day.analysis.buckets.map(b=>[band(b),...summaryRows(b.summary)])),table(['Minimum EV',...headers],day.analysis.thresholds.map(b=>[`≥${percent(b.minimum)}%`,...summaryRows(b.summary)])));}root.append(daily);
  root.append(node('p','Modeled results assume recorded fee and quoted-size inputs. Full-slate and market completeness can remain unknown; each daily report shows missing captures and sources. Result corrections update the daily and weekly views automatically.'));
}
