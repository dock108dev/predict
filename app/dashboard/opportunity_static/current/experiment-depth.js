import {count, label, node, pairs, pct, table, usd} from './workspace-ui.js';

const scenarioTitles={
  quoted:'Quoted price',
  novig_band:'Novig alternates within −250 to +250',
  no_novig_alternates:'Exclude Novig alternates',
  depth:'Full public book size',
};
const states={
  full_size:'Full size',
  partial_size:'Partial size',
  confirmed_empty:'Confirmed empty',
  above_limit:'Price above limit',
  below_ev_floor:'Below EV floor',
  unknown:'Unknown',
};
const cohortTitles={
  line_role:'Main or alternate',odds_band:'Odds band',distance_from_main:'Distance from main (points)',
  family:'Market family',venue:'Venue',
};
const qty=value=>value == null ? '—' : value;
const rate=value=>value == null ? '—' : pct(value);
const money=value=>value == null ? '—' : usd(value);
const bounds={'below_-250':'Below −250','above_+250':'Above +250','-250_to_+250':'−250 to +250'};

function disposition(depth) {
  const reason=depth.selection_exclusion || depth.reason;
  return [states[depth.status] || label(depth.status),reason && (depth.status==='unknown' || !depth.eligible) ? label(reason) : null]
    .filter(Boolean).join(' · ');
}

export function depthTrade(depth) {
  return pairs({
    'Public book disposition':disposition(depth),
    'Intended stake at quoted price':money(depth.intended_stake_usd),
    'Displayed native quantity within limit':qty(depth.available_native_quantity),
    'Displayed purchase value within limit':money(depth.available_purchase_usd),
    'Modeled average contract price':rate(depth.modeled_average_price),
    'Modeled fees':money(depth.modeled_fee_usd),
    'Modeled winning profit':money(depth.modeled_win_profit_usd),
  });
}

function supportColumns(row) {
  return [count(row.targeted_picks),count(row.usable_books),count(row.full_size),
    rate(row.full_size_per_target),rate(row.full_size_per_usable),rate(row.stake_weighted_displayed_capacity)];
}

export function depthComparison(analysis, followup) {
  const section=node('section',undefined,'experiment-totals');
  const original=analysis.scenarios.quoted;
  const targeted=original.targeted_picks;
  const missingBooks=targeted-original.usable_books;
  section.append(node('h3','Public book comparison'),
    node('p',`${analysis.scope} · ${count(analysis.frozen_game_decisions)} frozen games · ${count(analysis.venue_receipt_games)} games with book receipts.`,
      'workspace-caption'),
    node('p',`${count(original.full_size)} of ${count(targeted)} quoted picks had full displayed size. ${count(original.usable_books)} picks had usable evidence.${missingBooks ? ` Coverage is partial for this comparison, with ${count(missingBooks)} unknown.` : ''} Public book size is displayed capacity. Actual fills remain unknown.`,
      'workspace-caption'));
  section.append(node('p','Stake-weighted capacity uses the displayed gross win amount up to $25. Truncated books contribute only their observed levels.',
    'workspace-caption'));
  const headers=['Picks','Usable books','Full size','Full / picks','Full / usable','Stake-weighted displayed capacity'];
  section.append(table(['Policy',...headers,'Replacements','Games without a pick','Expected paper profit'],
    Object.entries(analysis.scenarios).map(([name,row])=>[
      scenarioTitles[name],...supportColumns(row),count(row.replacements),count(row.games_without_pick),money(row.expected_profit_usd),
    ])));
  const metrics=analysis.request_metrics;
  const operations=node('details');
  operations.append(node('summary','T−10 capture and public requests'),pairs({
    'Original T−10 captures':count(analysis.capture_states.captured ?? 0),
    'Retrospectively reconstructed':count(analysis.capture_states.reconstructed ?? 0),
    'Public book requests':count(metrics.public_requests),
    'Public catalog preparation requests':count(metrics.preparation_requests),
    'Oldest response at decision cutoff':metrics.max_response_age_seconds == null ? '—' : `${metrics.max_response_age_seconds}s`,
    'Longest recorded request':metrics.max_request_latency_ms == null ? '—' : `${metrics.max_request_latency_ms} ms`,
    'Games with later recheck':count(followup?.games ?? 0),
    'Later sides with inconclusive cache reuse':count(followup?.cache_reuse_sides ?? 0),
    'Later observation delay':followup?.games ? `${followup.min_observed_delay_seconds}–${followup.max_observed_delay_seconds}s` : '—',
  }));
  section.append(operations);
  const details=node('details');
  details.append(node('summary','Capacity by quote cohort'));
  for (const [cohort,rows] of Object.entries(analysis.cohorts)) {
    if (!Object.keys(rows).length) continue;
    details.append(node('h4',cohortTitles[cohort]),table([cohortTitles[cohort],...headers],
      Object.entries(rows).map(([key,row])=>[bounds[key] || label(key),...supportColumns(row)])));
  }
  const missing=Object.entries(original.unknown_reasons);
  if (missing.length) details.append(node('h4','Unknown depth on quoted picks'),
    table(['Reason','Picks'],missing.map(([reason,total])=>[label(reason),count(total)])));
  const controls=Object.entries(analysis.main_line_controls.dispositions);
  if (controls.length) details.append(node('h4','Same-game Novig main line controls'),
    table(['Disposition','Controls'],controls.map(([state,total])=>[states[state],count(total)])));
  section.append(details);
  return section;
}

export function depthCandidates(candidates) {
  const section=node('details',undefined,'experiment-totals');
  const content=node('section');
  section.append(node('summary',`Public book observations (${count(candidates.length)})`),content);
  section.addEventListener('toggle',()=>{
    if (!section.open || content.hasChildNodes()) return;
    if (!candidates.length) {
      content.append(node('p','Candidate observations will be listed when a frozen report is available.'));
      return;
    }
    const filter=node('select');
    const caption=node('label','Public book disposition');
    caption.append(filter);
    filter.append(new Option('All dispositions','all'), ...Object.entries(states).map(([id,title])=>new Option(title,id)));
    const observations=node('div');
    content.append(caption,observations);
    const pageSize=30;
    let page=0;
    function paint() {
      const selected=filter.value==='all' ? candidates : candidates.filter(row=>row.depth.status===filter.value);
      const start=page*pageSize;
      const rows=selected.slice(start,start+pageSize);
      const previous=node('button','Previous'), next=node('button','Next');
      previous.type=next.type='button';
      previous.disabled=page===0;
      next.disabled=start+pageSize>=selected.length;
      previous.onclick=()=>{page-=1;paint();};
      next.onclick=()=>{page+=1;paint();};
      const controls=node('div',undefined,'workspace-links');
      const status=node('span',selected.length ? `${count(start+1)}–${count(start+rows.length)} of ${count(selected.length)}` : 'No matching observations');
      status.setAttribute('role','status');
      controls.append(previous,status,next);
      observations.replaceChildren(table(
        ['Date (ET)','Game and selection','Venue','Frozen odds','Intended stake','Native quantity at limit',
          'Modeled price','Fee','Disposition'],
        rows.map(({depth,...row})=>[
          row.game_date,[row.game_title,row.label,row.line].filter(Boolean).join(' · '), label(row.venue),
          qty(row.posted_odds),money(depth.intended_stake_usd),qty(depth.available_native_quantity),
          rate(depth.modeled_average_price),money(depth.modeled_fee_usd),disposition(depth),
        ])),controls);
    }
    filter.onchange=()=>{page=0;paint();};
    paint();
  });
  return section;
}

export function depthDecisions(decisions) {
  const section=node('details',undefined,'experiment-totals');
  section.append(node('summary','Selected quotes by game and policy'));
  section.addEventListener('toggle',()=>{
    if (!section.open || section.childElementCount>1) return;
    if (!decisions.length) {
      section.append(node('p','No frozen game decisions are available.'));
      return;
    }
    section.append(table(['Date (ET)','Game',...Object.values(scenarioTitles)],decisions.map(game=>[
      game.game_date,game.game_title,...Object.keys(scenarioTitles).map(name=>{
        const pick=game.picks[name];
        if (!pick) return '—';
        const selection=[pick.label,pick.line].filter(Boolean).join(' ');
        return [selection,label(pick.venue),pick.posted_odds,money(pick.cash_commitment_usd)].join(' · ');
      }),
    ])));
  });
  return section;
}
