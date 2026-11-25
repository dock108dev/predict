import {byId,card,count,link,node,pairs,pct,readJSON,time,usd} from './workspace-ui.js';
import {campaignDays,campaignForm,configuredModes,configuredPortfolio,ruleSummary,sizingTitle} from './research-campaigns.js';
import {coverageURL,ledgerKeys} from './mens-d1-coverage.js';
import {renderResults} from './research-results.js';
import {renderRun,renderSavedEvidence} from './research-run.js';

const endpoint='/api/research/workspace';
const root=byId('experiment-view');
const status=byId('experiments-status');
const source=byId('experiment-source');
const portfolioTitles={best_venue:'Best venue only',all_venues:'All qualifying venues'};
const hash=/^[0-9a-f]{64}$/;
let requestVersion=0;

const present=values=>Object.fromEntries(Object.entries(values).filter(([,value])=>value!=null));
const url=(overrides={})=>{
  const params=new URLSearchParams(present(overrides));
  return '/experiments'+(params.size ? '?'+params : '');
};
const runAPI=id=>endpoint+'/runs/'+encodeURIComponent(id);
const campaignAPI=id=>endpoint+'/campaigns/'+encodeURIComponent(id);
const money=value=>value==null ? '—' : usd(value);
const quantity=value=>value==null ? '—' : count(value);
const action=(name,destination)=>link(name,destination,'research-button');
const gameDate=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'});
const displayDate=new Intl.DateTimeFormat('en-US',{timeZone:'UTC',month:'short',day:'numeric',year:'numeric'});

function defaultDate(config) {
  // Start with the latest elapsed game date for a campaign already in progress.
  const yesterday=new Date(gameDate.format(new Date())+'T12:00:00Z');
  yesterday.setUTCDate(yesterday.getUTCDate()-1);
  return [config.start_date,yesterday.toISOString().slice(0,10),config.end_date].sort()[1];
}

function setStatus(message='') {
  status.textContent=message;
  status.hidden=!message;
}

function field(title, options, value, change, inputId) {
  const wrapper=node('label'), caption=node('span',title);
  const select=node('select');
  select.id=inputId;
  caption.id=inputId+'-label';
  select.setAttribute('aria-labelledby',caption.id);
  select.append(...options.map(([id,caption])=>new Option(caption,id)));
  select.value=value;
  select.onchange=()=>change(select.value);
  wrapper.append(caption,select);
  return wrapper;
}

function dayStatus(day) {
  const result={
    no_selected_tickets:'Valid zero-trade result',
    partially_graded:'Partially graded',
    graded:'Graded',
    awaiting_results:'Awaiting sporting results',
    unresolved:'Unresolved grades',
    collecting:'Capturing or grading',
  };
  if (day.error) return 'Replay failed';
  if (day.result_error) return day.analysis ? 'Saved grades · grading update failed' : 'Grading failed';
  if (day.capture_state==='missing') return 'Missing usable T−10 evidence';
  if (day.replay_state==='scheduled') return 'Scheduled';
  if (day.replay_state==='replaying') return day.run_id ? 'Saved snapshot · replaying update' : 'Replaying retained odds';
  if (day.replay_state==='replay_queued') return 'Replay queued';
  if (!day.run_id || day.capture_state==='pending') return 'Capture in progress · awaiting T−10 odds';
  if (day.result_pending) return day.analysis ? 'Saved grades · update pending' : 'Selected trades saved · grades pending';
  return result[day.result_state] || 'Saved snapshot';
}

function comparisonTable(data, context) {
  const {config,modes}=data;
  const modeNames=configuredModes(config);
  const cells=(tag, values)=>values.map(value=>{
    const cell=node(tag);
    if (value instanceof Node) cell.append(value);
    else cell.textContent=value;
    return cell;
  });
  const table=node('table');
  const head=node('thead'), headings=node('tr');
  headings.append(...cells('th',['Paper results',...modeNames.map(mode=>sizingTitle(config,mode))]));
  for (const heading of headings.children) heading.scope='col';
  head.append(headings);
  const body=node('tbody');
  const rows=[
    ['Status',day=>node('span',context.visible || day.run_id ? dayStatus(day) : 'No saved snapshot','experiment-status')],
    ['Selected trades',day=>quantity(day.analysis?.summary.tickets ?? day.selection?.tickets)],
    ['Graded trades',day=>quantity(day.analysis?.summary.resolved ?? (day.selection ? 0 : null))],
    ['Stake',day=>money(day.analysis?.summary.stake_usd ?? day.selection?.stake_usd)],
    ['Return on graded trades',day=>money(day.analysis?.summary.return_usd)],
    ['Paper P/L',day=>money(day.analysis?.summary.pnl_usd)],
    ['ROI',day=>{
      const {roi,roi_percent,roi_stake_usd}=day.analysis?.summary || {};
      return roi==null ? '—' : (roi_percent == null ? pct(roi) : roi_percent+'%')+' on '+usd(roi_stake_usd)+' graded stake';
    }],
    ['Details',(day,mode)=>day.run_id ? action('Inspect games and trades',url({...context.base,mode,run:day.run_id}))
      : context.visible ? 'Awaiting saved evidence' : 'Unavailable'],
  ];
  for (const [heading,value] of rows) {
    const row=node('tr'), title=node('th',heading);
    title.scope='row';
    row.append(title,...cells('td',modeNames.map(mode=>value(modes[mode],mode))));
    body.append(row);
  }
  table.append(head,body);
  return table;
}

function showDay(data, config, visible, context, change) {
  const panel=card(config.name);
  panel.classList.add('experiment-comparison');
  const scope=visible ? 'Men’s Division I vs. Division I' : 'Archived experiment';
  panel.append(node('p', scope+' · Paper · T−10 · EV ≥'+pct(config.minimum_ev),'workspace-caption'));
  const sizes=configuredModes(config);
  const dates=campaignDays(config).map(value=>[value,displayDate.format(new Date(value+'T12:00:00Z'))]);
  const portfolios=(config.portfolios || Object.keys(portfolioTitles)).map(value=>[value,portfolioTitles[value]]);
  const controls=node('div',undefined,'experiment-controls');
  const changeSelection=override=>{
    const latest=new URLSearchParams(location.search);
    change({campaign:context.campaign,date:latest.get('date') || context.date,
      variant:latest.get('variant') || context.variant,...override});
  };
  if (context.experiments.length>1) {
    controls.append(field('Experiment',context.experiments.map(item=>[item.id,item.name]),context.campaign,
      campaign=>change({campaign}), 'experiment-choice'));
  }
  controls.append(
    field('Game date (Eastern)',dates,context.date,date=>changeSelection({date}),'experiment-date'),
    field('Portfolio',portfolios,context.variant,variant=>changeSelection({variant}),'experiment-portfolio'));
  const refresh=node('button','Refresh results');
  refresh.type='button';
  refresh.onclick=()=>render({keepComparison:true});
  controls.append(refresh);
  panel.append(controls);
  const body=node('div');
  body.id='experiment-comparison-body';
  paintDay(body,data,config,context,sizes);
  panel.append(body);
  return panel;
}

function paintDay(body,data,config,context,sizes=configuredModes(config)) {
  const gameRules=node('details');
  gameRules.append(node('summary','Experiment rules'),pairs(ruleSummary(config)));
  if (data) {
    body.replaceChildren(comparisonTable(data,context));
    const days=Object.values(data.modes);
    if (days.some(day=>day.capture_state==='partial')) {
      body.append(node('p','Partial T−10 coverage. Saved results reflect only the usable captures so far.','workspace-caption'));
    }
    const captures=days[0]?.captures || {};
    const pending=(captures.pending || 0)+(captures.claimed || 0);
    if (pending) body.append(node('p',
      `${count(pending)} ${pending===1 ? 'game awaiting its' : 'games awaiting their'} T−10 capture in the latest snapshot.`,
      'workspace-caption'));
    body.append(node('p','Stake includes every selected trade. Return, paper P/L and ROI use graded trades.','workspace-caption'));
    const history=node('details');
    history.append(node('summary','Saved snapshots'),node('p','Select a published snapshot to inspect its recorded selections and grade history.'));
    for (const mode of sizes) {
      history.append(node('h3',sizingTitle(config,mode)));
      const snapshots=data.modes[mode].snapshots;
      if (!snapshots.length) history.append(node('p','No snapshot published yet.'));
      else {
        const list=node('ul');
        for (const snapshot of snapshots) {
          const item=node('li');
          item.append(link(time(snapshot.recorded_at),url({...context.base,mode,run:snapshot.id,snapshot:'1'})));
          list.append(item);
        }
        history.append(list);
      }
    }
    const links=node('div',undefined,'workspace-links');
    links.append(action('Export comparison',campaignAPI(context.campaign)+'/days/'+context.date+'?'+new URLSearchParams({
      variant:context.variant,export:'1',
    })));
    if (context.visible) links.append(link('Edit as a new version',url({...context.base,view:'revise'})));
    body.append(gameRules,history,links);
  } else {
    body.replaceChildren(node('p','Reading retained captures and grades…','workspace-caption'),gameRules);
  }
}

function detailLink(query,changes) {
  return url({...Object.fromEntries(query),...changes});
}

async function sourceDialog(id, query, version) {
  const ticket=query.get('ticket'), evidence=query.get('evidence');
  const selected=ticket || evidence;
  if (!hash.test(selected || '')) return;
  const content=byId('experiment-source-content');
  byId('experiment-source-title').textContent=ticket ? 'Saved paper trade' : 'Frozen game evidence';
  content.replaceChildren(node('p','Reading saved evidence…'));
  const openedAt=location.pathname+location.search;
  source.onclose=()=>{
    if (openedAt===location.pathname+location.search) {
      history.replaceState(null,'',detailLink(query,{ticket:null,evidence:null}));
    }
  };
  if (!source.open) source.showModal();
  try {
    const evidence=await readJSON(runAPI(id)+(ticket ? '/tickets/' : '/evidence/')+selected);
    if (version!==requestVersion) return;
    renderSavedEvidence(content,evidence,{
      ticket:Boolean(ticket),exportLink:runAPI(id)+'?export=1',
      gameLink:game=>detailLink(query,{evidence:game,ticket:null}),
    });
  } catch (error) {
    if (version===requestVersion) content.replaceChildren(node('p',error.message));
  }
}

async function openDetail(mount,selected,query,context,version) {
  const id=selected.run.id;
  const {config,date,variant,campaign}=context;
  const mode=selected.definition.sizing_mode || selected.report.policy.sizing_mode || 'kelly';
  const base={...context.base,date,campaign,mode,run:id};
  const initial={...Object.fromEntries(query),...base,ticket:null,evidence:null};
  const resultRoot=node('div');
  const heading=node('h2',sizingTitle(config,mode)+' · games and trades');
  heading.tabIndex=-1;
  mount.replaceChildren(heading, resultRoot);
  if (query.get('snapshot')==='1' || (context.latestRun && context.latestRun!==id)) {
    mount.insertBefore(node('p','Saved snapshot · selections are frozen. The comparison above uses the latest available snapshots.','workspace-notice'),resultRoot);
  }
  const href=overrides=>url({...initial,...overrides});
  const paper=String(selected.report.policy.execution || '').startsWith('paper_only');
  const audit=panel=>{
    renderRun(panel,selected,{
      embedded:Boolean(campaign),variant,variantLink:key=>href({variant:key,result:null,trade:null}),
      ticketLink:ticket=>href({ticket:ticket.id}),
      gameLink:game=>href({evidence:game.game_id}),
      exportLink:runAPI(id)+'?export=1',offerExportLink:runAPI(id)+'/offers',
      priorRunLink:prior=>href({run:prior,result:null,trade:null}),
    });
  };
  if (!paper) audit(resultRoot);
  else {
    const details=node('details',undefined,'workspace-panel');
    details.append(node('summary','Original selection and capture evidence'));
    details.addEventListener('toggle',()=>{if (details.open && details.childElementCount===1) audit(details);});
    mount.append(details);
    const tickets=new Map();
    const inspect=(container, trade, loaded)=>{
      container.append(node('p','Reading frozen quote and sizing calculation…'));
      if (!tickets.has(trade.id)) tickets.set(trade.id,readJSON(runAPI(id)+'/tickets/'+trade.id));
      tickets.get(trade.id).then(evidence=>{
        if (version!==requestVersion || !container.isConnected) return;
        loaded?.(evidence);
        renderSavedEvidence(container,evidence,{
          ticket:true,resultReview:true,exportLink:runAPI(id)+'?export=1',
          gameLink:game=>href({evidence:game}),
        });
      }).catch(error=>{
        tickets.delete(trade.id);
        if (container.isConnected) container.replaceChildren(node('p',error.message));
      });
    };
    let analysis;
    try {
      const filters=new URLSearchParams(present({variant,version:initial.result}));
      analysis=await readJSON(runAPI(id)+'/results?'+filters);
    } catch(error) {
      analysis={error:error.message};
    }
    if (version!==requestVersion) return;
    function paint(params) {
      const navigation={
        embedded:true,variant,mode,config,params,href:overrides=>url({...params,...overrides}),
        go:overrides=>{
          const next={...params,...overrides};
          history.pushState(null,'',url(next));
          paint(next);
        },
        pinned:Boolean(params.result),game:params.game,trade:params.trade,
        filter:['traded','zero','missing','unresolved','frozen','reconstructed'].includes(params.filter) ? params.filter : 'all',
        tradeFilter:['win','loss','push','void','unresolved'].includes(params.trade_filter) ? params.trade_filter : 'all',
        modeHref:(target,trade)=>url({...base,mode:target,run:selected.sizing_runs?.[target],
          sizing_quote:trade?.frozen_quote_id,sizing_bet:trade?.equivalent_bet_id}),
        coverageHref:game=>coverageURL(new URLSearchParams(present({...base,scope:'mens-d1'})),
          {coverage_game:game.occurrence_id || game.game_id})+'#mens-d1-issues',
      };
      renderResults(resultRoot,selected,analysis,navigation,inspect);
    }
    paint(initial);
  }
  if (version!==requestVersion) return;
  if (query.get('trade') || query.get('game')) {
    mount.querySelector('.paper-result-trade h3, .paper-result-trade h4, .paper-result-game h3')?.focus();
  } else if (query.has('run') && !source.open) {
    heading.focus({preventScroll:true});
  }
  await sourceDialog(id,query,version);
}

function change(overrides) {
  history.pushState(null,'',url(overrides));
  render();
}

async function showArchive(selected,query,version) {
  const variant=query.get('variant')==='all_venues' ? 'all_venues' : 'best_venue';
  const config=selected.report.policy;
  root.replaceChildren();
  const section=node('section',undefined,'experiment-detail');
  root.append(node('p','Archived experiment · saved run evidence','workspace-notice'),section);
  const context={date:selected.run.date,variant,config,base:{run:selected.run.id,variant}};
  await openDetail(section,selected,query,context,version);
}

async function render({keepComparison=false}={}) {
  const version=++requestVersion;
  const query=new URLSearchParams(location.search);
  const isCreate=['create','schedule'].includes(query.get('view'));
  if (source.open) source.close();
  if (isCreate) {
    root.replaceChildren();
    setStatus();
    campaignForm(root,null,null,undefined,undefined,{
      dataFilters:query.get('from')==='data' ? query : null,backHref:url(),
      afterSave:(value,variant)=>url({campaign:value.id,variant,date:defaultDate(value)}),
    });
    return;
  }
  setStatus('Reading experiments…');
  try {
    const {campaigns}=await readJSON(endpoint+'/campaigns');
    if (version!==requestVersion) return;
    const run=query.get('run');
    let selected;
    if (hash.test(run || '')) selected=await readJSON(runAPI(run));
    if (version!==requestVersion) return;
    if (selected && !selected.definition.campaign_id) {
      setStatus();
      await showArchive(selected,query,version);
      return;
    }
    const id=query.get('campaign') || selected?.definition.campaign_id || campaigns[0]?.id;
    if (!id) {
      root.replaceChildren(node('p','No saved experiments are available. Create an experiment to replay retained paper data.'));
      setStatus();
      return;
    }
    const known=campaigns.find(experiment=>experiment.id===id);
    const config=known || (await readJSON(campaignAPI(id))).config;
    if (version!==requestVersion) return;
    const dates=campaignDays(config);
    const wanted=selected?.run.date || query.get('date');
    const date=dates.includes(wanted) ? wanted : defaultDate(config);
    const variant=configuredPortfolio(config,query.get('variant'));
    const base={campaign:id,date,variant};
    if (query.get('view')==='revise') {
      root.replaceChildren();
      setStatus();
      campaignForm(root,config,id,variant,base,{
        backHref:url(base),afterSave:(value,key)=>url({campaign:value.id,date,variant:key}),
      });
      return;
    }
    const context={base,campaign:id,date,variant,config,experiments:campaigns,visible:Boolean(known)};
    let body=keepComparison && root.querySelector('#experiment-comparison-body');
    if (!body) {
      const heading=showDay(null,config,known,context,change);
      root.replaceChildren(heading);
      body=heading.querySelector('#experiment-comparison-body');
    }
    const data=await readJSON(campaignAPI(id)+'/days/'+date+'?'+new URLSearchParams({variant}));
    if (version!==requestVersion) return;
    paintDay(body,data,config,context);
    setStatus();
    // Archived links can still open the explicitly selected frozen evidence.
    const mode=query.get('mode');
    const oldDetail=(query.get('view')==='daily' && mode) || ledgerKeys.some(key=>query.has(key));
    if (!selected && oldDetail) {
      const chosen=mode && data.modes[mode] ? mode : configuredModes(config)[0];
      const runId=data.modes[chosen]?.run_id;
      if (runId) selected=await readJSON(runAPI(runId));
    }
    if (version!==requestVersion || !selected) return;
    if (selected.definition.campaign_id!==id) {
      setStatus('The saved run belongs to another experiment.');
      return;
    }
    const detail=node('section',undefined,'experiment-detail');
    root.querySelector('.experiment-detail')?.remove();
    root.append(detail);
    context.latestRun=data.modes[selected.definition.sizing_mode || 'kelly']?.run_id;
    await openDetail(detail,selected,query,context,version);
  } catch(error) {
    if (version===requestVersion) setStatus(error.message);
  }
}

window.addEventListener('popstate',()=>render());
render();
