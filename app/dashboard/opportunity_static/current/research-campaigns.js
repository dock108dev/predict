import {card,count,label,link,node,pairs,pct,readJSON,table,time,usd} from './workspace-ui.js';

const API='/api/research/workspace/campaigns';
const titles={best_venue:'Best venue only',all_venues:'All qualifying venues'};
const href=(id,variant='best_venue')=>'/research?'+new URLSearchParams({section:'experiments',campaign:id,variant});
const percent=value=>String(Number(value.split('/')[0])/(Number(value.split('/')[1])||1)*100);
const summaryRows=s=>[count(s.tickets),usd(s.stake_usd),usd(s.expected_profit_usd),usd(s.return_usd),usd(s.pnl_usd),pct(s.roi),`${count(s.wins)} / ${count(s.losses)} / ${count(s.unresolved)}`];
const headers=['Tickets','Staked','Expected profit','Returned','Modeled P/L','ROI on graded stake','Win / loss / unresolved'];
const band=b=>`${percent(b.minimum)}%${b.maximum?'–<'+percent(b.maximum)+'%':'+'}`;

export function campaignList(values){
  const root=card('Daily & weekly experiments');
  root.append(node('p','Paper-only schedules, daily results and EV comparisons.'));
  for(const c of values||[])root.append(node('p'),link(`${c.name} · ${c.start_date}–${c.end_date} · ${percent(c.kelly_multiplier)}% Kelly`,href(c.id),'research-button'));
  root.append(link('Create a scheduled experiment','/research?section=experiments&view=schedule','research-button'));
  return root;
}

export function campaignForm(root,config=null){
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
  const explain=()=>{const scale=Number(inputs.reference_bankroll_usd.value)*Number(inputs.kelly_multiplier.value)/100;preview.textContent=`At −110 and 4% EV, this sizing commits about ${usd(scale*.04/(100/110))}. No portfolio budget cap or intraday compounding. Both venue variants are recorded.`;};
  form.addEventListener('input',explain);explain();
  const submit=node('button','Save and schedule experiment');submit.type='submit';
  form.onsubmit=async event=>{event.preventDefault();submit.disabled=true;feedback.textContent='Saving schedule…';
    try{const body=Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.value]));
      for(const key of ['minimum_ev','kelly_multiplier'])body[key]=String(Number(body[key])/100);
      body.bucket_edges=body.bucket_edges.split(',').map(v=>String(Number(v.trim())/100));
      const value=await readJSON(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      location.href=href(value.id);
    }catch(error){feedback.textContent=error.message;submit.disabled=false;}};
  form.append(preview,submit,feedback);panel.append(form);root.append(panel);
}

export async function renderCampaign(root,id,variant,current){
  const data=await readJSON(`${API}/${id}?`+new URLSearchParams({variant}));if(!current())return;
  root.replaceChildren();const {config,weekly}=data;
  const heading=card(config.name);heading.append(node('p',`${config.start_date}–${config.end_date} Eastern · Men’s D1 NCAAB · Paper only`));
  heading.append(node('p',`${percent(config.kelly_multiplier)}% of full Kelly on ${usd(config.reference_bankroll_usd)}; minimum EV ${percent(config.minimum_ev)}%. Historical days are retrospective replays. New dates are automatically recorded from retained T−10 evidence.`));
  const nav=node('div',undefined,'workspace-variant');for(const key of Object.keys(titles)){const a=link(titles[key],href(id,key),'research-button');if(key===variant)a.setAttribute('aria-current','true');nav.append(a);}heading.append(nav);
  heading.append(link('Export daily, weekly and EV analysis',`${API}/${id}?`+new URLSearchParams({variant,export:'1'})));
  const revise=node('button','Edit as a new version');revise.onclick=()=>{campaignForm(root,config);revise.disabled=true;};heading.append(revise);root.append(heading);
  const week=card('Week / experiment total');week.append(node('p',`${data.reported_days} of ${data.days.length} daily reports available. Pending days and ungraded trades are not zero-result days. Only the latest run for each day is counted.`));
  const s=weekly.summary, available=data.reported_days>0;
  week.append(pairs({'Modeled P/L':available?usd(s.pnl_usd):'Pending','ROI on graded stake':available?pct(s.roi):'Pending','Total staked':available?usd(s.stake_usd):'Pending','Expected profit':available?usd(s.expected_profit_usd):'Pending','Tickets':available?count(s.tickets):'Pending','Ungraded stake':available?usd(s.unresolved_stake_usd):'Pending'},'workspace-stats'));
  if(data.days.some(d=>d.result_pending||d.error))week.append(node('p','Some reports are updating. Totals use the last published results shown for each day.'));
  week.append(table(headers,[available?summaryRows(s):Array(headers.length).fill('Pending')]));root.append(week);
  const days=card('Daily results');days.append(table(['Game date','Recording / results','Frozen / rebuilt / missing / pending',...headers],data.days.map(day=>{
    const c=day.captures||{};const open=day.run_id?link(day.date,'/research?'+new URLSearchParams({section:'experiments',scope:'mens-d1',date:day.date,run:day.run_id,variant})):day.date;
    const description=day.error||`${label(day.state)} · ${label(day.result_state||'waiting for day')}${day.result_pending?' · updating':''}${day.retrospective?' · retrospective':''}`;
    return [open,description,`${c.captured||0} / ${c.reconstructed||0} / ${(c.missed||0)+(c.failed||0)+(c.refused||0)+(c.no_task||0)} / ${(c.pending||0)+(c.claimed||0)}`, ...day.analysis?summaryRows(day.analysis.summary):Array(headers.length).fill('Pending')];
  })));root.append(days);
  const buckets=card('EV buckets');buckets.append(node('p','Non-overlapping buckets use unrounded screening EV. They partition the selected portfolio; percentages have no gaps.'));
  buckets.append(table(['Screening EV',...headers],weekly.buckets.map(b=>[band(b),...summaryRows(b.summary)])));root.append(buckets);
  const thresholds=card('What if the minimum EV changed?');thresholds.append(node('p','Separate counterfactual screens over the same retained opportunities. Each minimum reselects the best qualifying venue where applicable. Rows overlap and must not be added together.'));
  thresholds.append(table(['Minimum EV',...headers],weekly.thresholds.map(b=>[`≥${percent(b.minimum)}%`,...summaryRows(b.summary)])));root.append(thresholds);
  const daily=card('EV comparisons by day');for(const day of data.days.filter(d=>d.analysis)){daily.append(node('h3',day.date),table(['EV bucket',...headers],day.analysis.buckets.map(b=>[band(b),...summaryRows(b.summary)])),table(['Minimum EV',...headers],day.analysis.thresholds.map(b=>[`≥${percent(b.minimum)}%`,...summaryRows(b.summary)])));}root.append(daily);
  root.append(node('p','Modeled results assume recorded fee and quoted-size inputs. Full-slate and market completeness can remain unknown; each daily report shows missing captures and sources. Result corrections update the daily and weekly views automatically.'));
}
