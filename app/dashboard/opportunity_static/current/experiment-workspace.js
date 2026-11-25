import {byId,card,count,link,node,pairs,pct,readJSON,table,time,usd} from './workspace-ui.js';
import {band,campaignDays,campaignForm,configuredModes,configuredPortfolio,mainFirstRule,ruleSummary,sizingTitle} from './research-campaigns.js';
import {coverageURL,ledgerKeys} from './mens-d1-coverage.js';
import {oddsBreakdown,renderResults} from './research-results.js';
import {qualityComparison} from './research-quality.js';
import {renderRun,renderSavedEvidence} from './research-run.js';

const endpoint='/api/research/workspace';
// The saved Win $10 campaign has a fixed-profit results page. Other campaigns use their own rules.
const win10Campaign='521543a8363cd0a945e792726e387a23b2003e743fe7364945cd2ebfb5d65864';
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

function wantsDetails(query) {
  return ['run','result','ticket','evidence',...ledgerKeys].some(key=>query.has(key)) ||
    (query.get('view')==='daily' && query.has('mode'));
}

function currentDestination(campaign, query, savedDate) {
  const details=wantsDetails(query);
  const requested=query.get('date') || savedDate;
  const view=query.get('view');
  const usesDate=details || requested || view==='daily';
  const date=campaignDays(campaign).includes(requested) ? requested : usesDate ? defaultDate(campaign) : null;
  return {campaign:campaign.id,date,variant:configuredPortfolio(campaign,query.get('variant')),
    view:view==='weekly' && !details ? view : null,ledger_view:details ? 'trades' : null};
}

function versionNotice(message, title, destination) {
  const notice=node('aside',undefined,'workspace-notice experiment-version-notice');
  notice.append(node('p',message),action(title,destination));
  return notice;
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

function roi(summary) {
  if (summary?.roi == null) return '—';
  const percent=summary.roi_percent == null ? pct(summary.roi) : summary.roi_percent+'%';
  return percent+' on '+usd(summary.roi_stake_usd)+' graded stake';
}

function metrics(summary, selection=summary) {
  return [
    quantity(selection?.tickets),quantity(summary?.resolved ?? (selection ? 0 : null)),
    money(selection?.stake_usd),money(selection?.expected_profit_usd),
    selection?.expected_roi_percent == null ? '—' : selection.expected_roi_percent+'%',
    money(summary?.return_usd),money(summary?.pnl_usd),roi(summary),money(summary?.pnl_vs_expected_usd),
  ];
}
const metricLabels=['Selected trades','Graded trades','Stake','Expected paper profit','Expected ROI',
  'Return on graded trades','Paper P/L','ROI','P/L vs expected (graded)'];
const metricBasis='Expected profit and ROI use entry EV and all selected stake. Return, paper P/L, realized ROI and P/L vs expected use graded trades.';

function summaryTable(config, modes, rows) {
  const cells=(tag, values)=>values.map(value=>{
    const cell=node(tag);
    if (value instanceof Node) cell.append(value);
    else cell.textContent=value;
    return cell;
  });
  const summary=node('table');
  const head=node('thead'), headings=node('tr');
  headings.append(...cells('th',['Paper results',...modes.map(mode=>sizingTitle(config,mode))]));
  for (const heading of headings.children) heading.scope='col';
  head.append(headings);
  const body=node('tbody');
  for (const [heading,value] of rows) {
    const row=node('tr'), title=node('th',heading);
    title.scope='row';
    row.append(title,...cells('td',modes.map(value)));
    body.append(row);
  }
  summary.append(head,body);
  return summary;
}

function comparisonTable(data, context) {
  const {config,modes}=data;
  const values=Object.fromEntries(context.sizingModes.map(mode=>{
    const day=modes[mode], summary=day.analysis?.summary;
    return [mode,metrics(summary,day.selection || summary)];
  }));
  return summaryTable(config,context.sizingModes,[
    ['Status',mode=>{
      const day=modes[mode];
      return node('span',context.visible || day.run_id ? dayStatus(day) : 'No saved snapshot','experiment-status');
    }],
    ...metricLabels.map((label,index)=>[label,mode=>values[mode][index]]),
    ['Details',mode=>modes[mode].run_id
      ? action('Inspect games and trades',url({...context.base,mode,run:modes[mode].run_id}))
      : context.visible ? 'Awaiting saved evidence' : 'Unavailable'],
  ]);
}

function campaignPath(id, variant, mode, options={}) {
  return campaignAPI(id)+'?'+new URLSearchParams({variant,mode,comparison:'0',...options});
}

function campaignRules(config, context) {
  const rules=context.campaign===win10Campaign ? {...config,kelly_comparison:false} : config;
  const detail=node('details');
  detail.append(node('summary','Experiment rules'),pairs(ruleSummary(rules)));
  return detail;
}

function renderCampaignResults(body, reports, config, context) {
  const primary=reports[0];
  const through=primary.as_of ? gameDate.format(new Date(primary.as_of)) : gameDate.format(new Date());
  const days=primary.days.filter(day=>day.date<=through);
  const date=value=>displayDate.format(new Date(value+'T12:00:00Z'));
  const values=Object.fromEntries(reports.map(report=>[report.mode,
    metrics(report.weekly?.summary,report.selection || report.weekly?.summary)]));
  const panel=node('section');
  panel.append(node('h3','Campaign to date'));
  if (days.length) {
    panel.append(node('p',date(config.start_date)+' through '+date(days.at(-1).date)+' (Eastern)','workspace-caption'));
    panel.append(summaryTable(config,context.sizingModes,[
      ...metricLabels.map((label,index)=>[label,mode=>values[mode][index]]),
      ['Ungraded trades',mode=>{
        const report=reports.find(value=>value.mode===mode);
        const selected=report.selection?.tickets ?? report.weekly?.summary.tickets;
        return quantity(selected == null ? null : selected-(report.weekly?.summary.resolved || 0));
      }],
    ]));
    panel.append(node('p',metricBasis,'workspace-caption'));
  }
  if (!days.length || reports.every(report=>!report.selection && !report.weekly)) {
    panel.append(node('p','Waiting for the first saved selections.'));
  }
  if (days.some(day=>day.capture_state==='partial' || day.capture_state==='missing')) {
    panel.append(node('p','Some dates have missing T−10 captures. Totals use the selections supported by retained evidence.','workspace-caption'));
  }
  if (days.length) {
    const dates=node('section');
    dates.append(node('h3','Results by date'),table(['Game date (Eastern)','Status',...metricLabels],
      days.map(day=>[
        link(date(day.date),url({...context.base,date:day.date})),
        dayStatus(day),
        ...metrics(day.analysis?.summary,day.selection || day.analysis?.summary),
      ])));
    panel.append(dates);
  }
  for (const report of reports) {
    const odds=oddsBreakdown(report.selection?.odds_buckets,reports.length>1 ? sizingTitle(config,report.mode) : '');
    if (odds) panel.append(odds);
    if (!report.weekly) continue;
    const analysis=node('details');
    const suffix=reports.length>1 ? ' · '+sizingTitle(config,report.mode) : '';
    analysis.append(node('summary','EV and quote evidence'+suffix),
      node('h4','EV buckets'),table(['Screening EV',...metricLabels],
        report.weekly.buckets.map(bucket=>[band(bucket),...metrics(bucket.summary)])),
      node('h4','Minimum EV comparisons'),
      node('p','Each row applies a different minimum to the same saved offers.'),
      table(['Minimum EV',...metricLabels],
        report.weekly.thresholds.map(bucket=>['≥'+pct(bucket.minimum),...metrics(bucket.summary)])));
    const quality=qualityComparison(report.weekly.quality);
    if (quality) analysis.append(quality);
    panel.append(analysis);
  }
  const links=node('div',undefined,'workspace-links');
  for (const report of reports) {
    const title=reports.length>1 ? 'Export '+sizingTitle(config,report.mode)+' campaign results' : 'Export campaign results';
    links.append(action(title,campaignPath(context.campaign,context.variant,report.mode,{export:'1'})));
  }
  body.replaceChildren(panel,campaignRules(config,context),links);
}

function showResults(config, visible, context) {
  const panel=card(config.name);
  panel.classList.add('experiment-comparison');
  if (context.currentHref) panel.append(versionNotice('Archived experiment · previous rules',
    'Open current results',context.currentHref));
  if (context.archiveHref) panel.append(versionNotice('This link used previous rules. Showing current results.',
    'Open archived snapshot',context.archiveHref));
  const scope=visible ? 'Men’s Division I vs. Division I' : 'Archived experiment';
  panel.append(node('p', scope+' · Paper · T−10 · EV ≥'+pct(config.minimum_ev),'workspace-caption'));
  if (config.portfolio_rule===mainFirstRule.id) panel.append(node('p',mainFirstRule.title,'workspace-caption'));
  const dates=campaignDays(config).map(value=>[value,displayDate.format(new Date(value+'T12:00:00Z'))]);
  const portfolios=(config.portfolios || Object.keys(portfolioTitles)).map(value=>[value,portfolioTitles[value]]);
  const period=node('nav',undefined,'workspace-variant');
  period.setAttribute('aria-label','Results period');
  const totalLink=action('Campaign to date',url({...context.base,date:null}));
  const dailyLink=action('By day',url({...context.base,date:context.date}));
  (context.cumulative ? totalLink : dailyLink).setAttribute('aria-current','page');
  period.append(totalLink,dailyLink);
  panel.append(period);
  const controls=node('div',undefined,'experiment-controls');
  const changeSelection=override=>{
    const latest=new URLSearchParams(location.search);
    change({...context.base,date:context.cumulative ? undefined : latest.get('date') || context.date,
      variant:latest.get('variant') || context.variant,...override});
  };
  if (visible && context.experiments.length>1) {
    controls.append(field('Experiment',context.experiments.map(item=>[item.id,item.name]),context.campaign,
      campaign=>change({campaign}), 'experiment-choice'));
  }
  if (!context.cumulative) controls.append(
    field('Game date (Eastern)',dates,context.date,date=>changeSelection({date}),'experiment-date'));
  controls.append(field('Portfolio',portfolios,context.variant,variant=>changeSelection({variant}),'experiment-portfolio'));
  const refresh=node('button','Refresh results');
  refresh.type='button';
  refresh.onclick=()=>render({keepComparison:true});
  controls.append(refresh);
  if (visible) controls.append(action('Edit experiment',url({...context.base,view:'revise'})));
  panel.append(controls);
  const body=node('div');
  body.id='experiment-comparison-body';
  body.append(node('p','Reading retained captures and grades…','workspace-caption'));
  panel.append(body);
  return panel;
}

function paintDay(body,data,config,context) {
  const {sizingModes}=context;
  const gameRules=campaignRules(config,context);
  if (data) {
    body.replaceChildren(comparisonTable(data,context));
    const days=sizingModes.map(mode=>data.modes[mode]);
    if (days.some(day=>day.capture_state==='partial')) {
      body.append(node('p','Partial T−10 coverage. Saved results reflect only the usable captures so far.','workspace-caption'));
    }
    const captures=days[0]?.captures || {};
    const pending=(captures.pending || 0)+(captures.claimed || 0);
    if (pending) body.append(node('p',
      `${count(pending)} ${pending===1 ? 'game awaiting its' : 'games awaiting their'} T−10 capture in the latest snapshot.`,
      'workspace-caption'));
    body.append(node('p',metricBasis,'workspace-caption'));
    for (const mode of sizingModes) {
      const odds=oddsBreakdown(data.modes[mode].selection?.odds_buckets,sizingModes.length>1 ? sizingTitle(config,mode) : '');
      if (odds) body.append(odds);
    }
    const history=node('details');
    history.append(node('summary','Saved snapshots'),node('p','Select a published snapshot to inspect its recorded selections and grade history.'));
    for (const mode of sizingModes) {
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
    const [day]=days;
    if (sizingModes.length===1) {
      if (day.analysis && day.result_id) links.append(action('Export results',runAPI(day.run_id)+'/results?'+new URLSearchParams({
        variant:context.variant,version:day.result_id,export:'report',
      })));
      else if (day.run_id) links.append(action('Export dated offer ledger',runAPI(day.run_id)+'/offers'));
    } else {
      links.append(action('Export comparison',campaignAPI(context.campaign)+'/days/'+context.date+'?'+new URLSearchParams({
        variant:context.variant,export:'1',
      })));
    }
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
      history.replaceState(history.state,'',detailLink(query,{ticket:null,evidence:null}));
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
  const savedSnapshot=query.get('snapshot')==='1' || (context.latestRun && context.latestRun!==id);
  if (savedSnapshot && !context.currentHref) {
    mount.insertBefore(node('p','Saved snapshot · selections are frozen. The results above use the latest available snapshots.','workspace-notice'),resultRoot);
  }
  const href=overrides=>url({...initial,...overrides});
  const paper=String(selected.report.policy.execution || '').startsWith('paper_only');
  const audit=panel=>{
    renderRun(panel,selected,{
      embedded:Boolean(campaign),variant,variantLink:key=>href({variant:key,result:null,trade:null}),
      ticketLink:ticket=>href({ticket:ticket.id}),
      gameLink:game=>href({evidence:game.game_id}),
      exportLink:runAPI(id)+'?export=1',offerExportLink:runAPI(id)+'/offers',
      priorRunLink:prior=>href({run:prior,result:null,trade:null,snapshot:'1'}),
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
          history.pushState(history.state,'',url(next));
          paint(next);
        },
        pinned:Boolean(params.result),showSnapshotOdds:!campaign || savedSnapshot || Boolean(params.result),
        game:params.game,trade:params.trade,
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
  let query=new URLSearchParams(location.search);
  const isCreate=['create','schedule'].includes(query.get('view'));
  if (source.open) source.close();
  if (isCreate) {
    root.replaceChildren();
    setStatus();
    campaignForm(root,null,null,undefined,undefined,{
      dataFilters:query.get('from')==='data' ? query : null,backHref:url(),
      afterSave:(value,variant)=>url({campaign:value.id,variant}),
    });
    return;
  }
  setStatus('Reading experiments…');
  try {
    const {campaigns,successors={}}=await readJSON(endpoint+'/campaigns');
    if (version!==requestVersion) return;
    const pinned=query.get('snapshot')==='1' || hash.test(query.get('result') || '');
    const requestedCampaign=query.get('campaign');
    const knownSuccessor=!pinned && campaigns.some(item=>item.id===successors[requestedCampaign]);
    const run=query.get('run');
    let selected;
    if (hash.test(run || '') && (!knownSuccessor || !query.has('date'))) {
      const readRun=readJSON(runAPI(run));
      selected=await (knownSuccessor ? readRun.catch(()=>null) : readRun);
    }
    if (version!==requestVersion) return;
    const original=requestedCampaign || selected?.definition.campaign_id;
    const successor=campaigns.find(item=>item.id===successors[original]);
    const redirected=successor && !pinned;
    if (redirected) {
      const editing=query.get('view')==='revise';
      const destination=currentDestination(successor,query,selected?.run.date);
      if (editing) Object.assign(destination,{view:'revise',ledger_view:null});
      const archiveHref=url({...Object.fromEntries(query),campaign:original,snapshot:'1',
        view:editing ? null : query.get('view')});
      history.replaceState({experimentRedirect:{campaign:successor.id,archiveHref}},'',url(destination));
      query=new URLSearchParams(present(destination));
      selected=null;
    }
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
    const mode=query.get('mode');
    const detailRequested=wantsDetails(query);
    const cumulative=!(detailRequested || query.get('view')==='daily' || (wanted && query.get('view')!=='weekly'));
    const base={campaign:id,date:cumulative ? undefined : date,variant,...(!known ? {snapshot:'1'} : {})};
    if (known && query.get('view')==='revise') {
      root.replaceChildren();
      setStatus();
      campaignForm(root,config,id,variant,base,{
        backHref:url({campaign:id,date:query.get('date'),variant}),
        afterSave:(value,key)=>url({campaign:value.id,date:query.get('date'),variant:key}),
      });
      return;
    }
    const sizingModes=id===win10Campaign ? ['fixed_profit'] : configuredModes(config);
    const currentHref=successor && !redirected ? url(currentDestination(successor,query,wanted)) : null;
    const redirect=history.state?.experimentRedirect;
    const archiveHref=redirect?.campaign===id ? redirect.archiveHref : null;
    const context={base,campaign:id,date,variant,config,sizingModes,cumulative,experiments:campaigns,
      visible:Boolean(known),archiveHref,currentHref};
    let body=keepComparison && !redirected && root.querySelector('#experiment-comparison-body');
    if (!body) {
      const heading=showResults(config,known,context);
      root.replaceChildren(heading);
      body=heading.querySelector('#experiment-comparison-body');
    }
    if (cumulative) {
      const reports=await Promise.all(sizingModes.map(mode=>readJSON(campaignPath(id,variant,mode))));
      if (version!==requestVersion) return;
      renderCampaignResults(body,reports,config,context);
      setStatus();
      return;
    }
    const data=await readJSON(campaignAPI(id)+'/days/'+date+'?'+new URLSearchParams({variant}));
    if (version!==requestVersion) return;
    paintDay(body,data,config,context);
    setStatus();
    // Archived links can still open the explicitly selected frozen evidence.
    if (!selected && detailRequested) {
      const chosen=mode && data.modes[mode] ? mode : sizingModes[0];
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
