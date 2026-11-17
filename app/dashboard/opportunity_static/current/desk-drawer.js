import {boardComparison, markPinned, tradeInspection, pairInspection, tradePreview} from './desk-inspection.js';
import {quoteFreshness, selectedReference} from './desk-quote-display.js';
import {pinLatestSelection, selectionCurrent, selectionIdentity} from './desk-evidence.js';
import {evidenceReason} from './desk-reasons.js';
import {sameBoardUnit} from './desk-ticketboard.js';

const {el, name, num} = window.PredictUI;

export function position(offer, game) {
  const selection = offer.selection || {};
  const participant = game?.participants?.find(p => p.id === selection.participant)?.name || offer.participant || selection.label;
  const line = selection.signed_line ?? offer.market.line;
  const signed = line == null ? '' : `${num(line) > 0 ? '+' : ''}${num(line)}`;
  switch (selection.predicate) {
    case 'win': return `${participant || 'Outcome'} to win`;
    case 'not_win': return `${participant || 'Outcome'} not to win`;
    case 'cover': return `${participant || 'Outcome'} to cover ${signed}`;
    case 'not_cover': return `${participant || 'Outcome'} not to cover ${signed}`;
    case 'over': return `Over ${num(line) ?? ''}`.trim();
    case 'under': return `Under ${num(line) ?? ''}`.trim();
    default: return [participant, selection.predicate?.replaceAll('_', ' '), signed].filter(Boolean).join(' ') || 'Outcome unavailable';
  }
}

function sameOffer(previous, next) {
  if (!previous || !next || previous.venue !== next.venue) return false;
  const sameKey = previous.desk_quote_key ? previous.desk_quote_key === next.desk_quote_key : previous.id === next.id;
  const exact = offer => {
    const selection = offer.selection || {};
    const {market, period, line} = offer.market;
    return JSON.stringify([market, period, selection.participant, selection.predicate, num(selection.signed_line ?? line)]);
  };
  return sameKey && exact(previous) === exact(next);
}

// Keep a selected capture, its dialog history, and its evidence lease together.
export function createDeskDrawer({replay, browse, dataset, retainedResult, gameKey, pageSize, captureMode,
  clock, viewContext, fetchPage, matrixPositions, restoreMatrices, restoreFocus, refreshDesk, unitSize}) {
  const $ = id => document.getElementById(id);
  const dialog = $('trade');
  const filters = $('filters');
  const previewControls = $('preview-controls');
  if (replay || location.pathname === '/arbs') previewControls.remove();
  const amount = $('preview-amount');
  const previewRefresh = $('refresh-preview');
  const refreshComparison = $('refresh-comparison');
  let currentSelection = null;

  function tradeDetails() {
    const {offer, group, game, evidence, pairContext, posted, boardId, size, comparison, closed, loading} = currentSelection;
    dialog.classList.toggle('posted-inspection', !!posted);
    previewControls.hidden = !posted || !!boardId;
    previewRefresh.hidden = !posted || !!boardId || viewContext().autoUpdate;
    refreshComparison.hidden = !boardId || !currentSelection.refreshAvailable;
    const label = position(offer, game);
    $('trade-title').textContent = boardId ? label : `${name(offer.venue)} · ${label}`;
    if (posted) {
      const body = $('trade-body');
      const expanded = [...body.querySelectorAll('details')].map(details => details.open);
      const active = body.contains(document.activeElement) && document.activeElement;
      const activeTag = active?.tagName;
      const detailsIndex = [...body.querySelectorAll('summary')].indexOf(active);
      const top = dialog.scrollTop;
      body.replaceChildren(boardId
        ? boardComparison(offer, group, game, comparison, {clock, size, loading})
        : tradePreview(offer, group, evidence, {clock, closed, loading}));
      [...body.querySelectorAll('details')].forEach((details, index) => { details.open = !!expanded[index]; });
      if (activeTag === 'SUMMARY') body.querySelectorAll('summary')[detailsIndex]?.focus({preventScroll:true});
      if (activeTag === 'A') [...body.querySelectorAll('a')].find(link => link.href === active.href)
        ?.focus({preventScroll:true});
      dialog.scrollTop = top;
      $('latest').hidden = true;
      $('back-to-pair').hidden = true;
      amount.disabled = closed;
      return;
    }
    if (offer.practice_ticket) {
      const model = evidence?.valuation;
      $('trade-title').textContent = label;
      $('trade-body').replaceChildren(el('p', captureMode, 'inspection-mode'),
        boardComparison({...offer, valuation:model}, group, game, model ? [model] : [],
          {clock, size:offer.unit_usd, loading:!evidence}));
      $('latest').hidden = true;
      $('back-to-pair').hidden = true;
      return;
    }
    const capturedAt = dataset === 'practice' ? null
      : evidence?.captured_at || offer.captured_at || currentSelection.capturedAt;
    const mode = currentSelection.historical || replay
      ? [currentSelection.historical ? 'Saved capture' : captureMode, capturedAt && `Captured ${clock(capturedAt)}`]
        .filter(Boolean).join(' · ')
      : captureMode;
    const leg = pairContext?.pair.legs.indexOf(offer.id);
    const pairFee = pairContext?.pair.retail_payoff?.legs?.[leg];
    const pairAcquisition = pairFee?.acquisition_usd ?? pairContext?.pair.inspection?.legs[leg]?.allocation_usd;
    $('trade-body').replaceChildren(tradeInspection(offer, group, evidence, {mode, position:label, basis:currentSelection.basis,
      checkedAt:currentSelection.checkedAt, pinned:currentSelection.pinned, publication:currentSelection.publication,
      pairLeg:!!pairContext, pairFee, pairAcquisition}));
    $('latest').hidden = replay;
    $('back-to-pair').hidden = !currentSelection.pairContext;
  }

  let inspection;
  function pushInspection(depth) {
    if (depth === 1) inspection = {id:crypto.randomUUID(), scrollY:window.scrollY, tableScrolls:matrixPositions(),
      scrollRestoration:window.history.scrollRestoration};
    window.history.scrollRestoration = 'manual';
    window.history.pushState({...window.history.state, predictInspection:{id:inspection.id, depth}}, '');
  }

  async function openTrade(offer, group, game, pairContext = null, opener = document.activeElement) {
    if (!dialog.open) releaseEvidence(currentSelection?.lease);
    const parent = pairContext && {
      nodes:[...$('trade-body').childNodes], scrollTop:dialog.scrollTop,
      title:$('trade-title').textContent, note:$('trade-note').textContent, latestHidden:$('latest').hidden, opener
    };
    const {page, previousReason} = viewContext();
    const previous = Boolean(previousReason);
    currentSelection = {offer, group, game, opener, pairContext,
      basis:page?.basis || filters.elements.basis.value,
      checkedAt:previous ? Date.parse(page?.publication?.read_at) || Date.now() : Date.now(),
      pinned:previous, publication:pairContext?.publication ?? page?.publication, capturedAt:page?.replay?.captured_at};
    if ((browse || offer.board_id) && offer.posted_price && !replay && !pairContext) {
      amount.readOnly = Boolean(offer.board_id);
      const size = offer.board_id ? Number(offer.unit_usd).toFixed(2) : unitSize() || null;
      Object.assign(currentSelection, {posted:true, loading:true, closed:false, size, boardId:offer.board_id});
      amount.value = size ?? '';
    }
    if (parent) {
      currentSelection.parent = parent;
      if (inspection) pushInspection(2);
    } else if (!dialog.open) pushInspection(1);
    $('trade-note').textContent = '';
    tradeDetails();
    if (!dialog.open) dialog.showModal();
    else dialog.querySelector('form button').focus();
    dialog.scrollTop=0;
    const selected=currentSelection;
    if (selected.boardId) {
      await readBoardSelection(selected);
      return;
    }
    if (selected.posted) {
      await readPostedSelection(selected);
      return;
    }
    try {
      const pinned=await pinEvidence(offer, selected.basis);
      if(currentSelection!==selected||!dialog.open){releaseEvidence(pinned.lease);return;}
      Object.assign(selected,pinned);
      const detail = pinned.evidence.desk_offer;
      if (detail) {
        selected.offer = {...detail, ...offer, trade_fee:detail.trade_fee || offer.trade_fee,
          sportsbook:detail.sportsbook || offer.sportsbook};
        if (offer.value == null && detail.reason === 'reference_price_stale') selected.offer.reason = detail.reason;
        if (offer.trade_fee_available === false && detail.trade_fee?.available) {
          selected.offer.trade_fee = {available:false, reason:'fee_outcome_not_published'};
        }
        if (selected.basis === 'sportsbooks' && offer.fair_odds === null) selected.offer.sportsbook = null;
      }
      tradeDetails();
    } catch {
      if(currentSelection===selected&&dialog.open){
        selected.retentionError='Full evidence could not be loaded. Displayed prices and returns remain pinned.';
        $('trade-note').textContent=selected.retentionError;
        $('trade-body').querySelector('.inspection-loading')?.remove();
      }
    }
  }

  function openPair(pair, offers, group, game, opener = document.activeElement) {
    releaseEvidence(currentSelection?.lease);
    releaseEvidence(currentSelection?.pairContext?.lease);
    const {page} = viewContext();
    const context = {pair, publishedPair:pair, offers, group, game, opener, publication:page?.publication,
      capturedAt:page?.replay?.captured_at};
    renderPair(context);
    if (!dialog.open) {
      pushInspection(1);
      dialog.showModal();
    }
    dialog.scrollTop = 0;
    if (!replay && pair.evidence_result_id && !['pair_leg_stale_or_replaced', 'pair_settlement_unverified'].includes(pair.retail_payoff?.reason)) {
      context.reservation = reserveEvidence(pair.evidence_result_id).then(lease => {
        if (dialog.open && (currentSelection === context || currentSelection?.pairContext === context)) {
          context.lease = lease;
          return lease;
        }
        releaseEvidence(lease);
        return null;
      }).catch(() => null);
      if (!pair.inspection) loadPairDetails(context);
    }
    return context;
  }

  async function loadPairDetails(context) {
    const {publishedPair:pair} = context;
    try {
      const lease = await context.reservation;
      if (!lease || !dialog.open || currentSelection !== context) throw Error('Evidence unavailable');
      const query = new URLSearchParams({layout:'desk', id:pair.id, result_id:pair.evidence_result_id, lease_id:lease.lease_id});
      const response = await fetch(`/api/comparison-snapshot/details?${query}`);
      if (!response.ok) throw Error('Evidence unavailable');
      const detail = await response.json();
      if (detail.id !== pair.id || detail.evidence_result_id !== pair.evidence_result_id || !detail.inspection) {
        throw Error('Evidence changed');
      }
      if (!dialog.open || currentSelection !== context) return;
      const retail = pair.retail_payoff;
      const hydrated = {...pair, inspection:detail.inspection, settlement_payouts:detail.settlement_payouts,
        retail_payoff:retail.available && detail.retail_payoff?.available
          ? {...detail.retail_payoff, ...retail}
          : retail.reason && retail.reason === detail.retail_payoff?.reason
            ? {...detail.retail_payoff, ...retail} : retail};
      for (const offer of detail.offers || []) {
        if (context.offers.has(offer.id)) {
          context.offers.set(offer.id, {...offer, ...context.offers.get(offer.id)});
        }
      }
      context.pair = context.publishedPair = hydrated;
      renderPair(context);
    } catch {
      if (dialog.open && currentSelection === context) {
        context.detailsUnavailable = true;
        renderPair(context);
      }
    }
  }

  function renderPair(context) {
    const {pair, offers, group, game} = context;
    currentSelection = context;
    dialog.classList.remove('posted-inspection');
    refreshComparison.hidden = true;
    $('trade-title').textContent = 'Pair payoff';
    $('trade-note').textContent = context.authorityNote || '';
    $('latest').hidden = replay;
    $('back-to-pair').hidden = true;
    const mode = [captureMode, context.authorityNote && 'Earlier published calculation',
      context.capturedAt && `Captured ${clock(context.capturedAt)}`].filter(Boolean).join(' · ');
    const body = $('trade-body');
    previewControls.hidden = true;
    previewRefresh.hidden = true;
    body.replaceChildren(pairInspection(pair, offers, {group, game, position, mode,
      inspect: (offer, opener) => openTrade(offer, group, game, context, opener)}));
    if (!pair.inspection && !replay && pair.evidence_result_id
        && !['pair_leg_stale_or_replaced', 'pair_settlement_unverified'].includes(pair.retail_payoff?.reason)) {
      const message = context.detailsUnavailable
        ? 'The calculation could not be loaded. The captured legs are shown.' : 'Loading the captured calculation…';
      $('trade-note').textContent = message;
    }
  }

  async function openHistorical(capture, id) {
    if (replay || !capture || !id) return;
    const basis = filters.elements.basis.value;
    let lease;
    try {
      const reservation = await fetch('/api/comparison-current/lease', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({result_id:capture})
      });
      if (!reservation.ok) throw Error('Capture unavailable');
      lease = await reservation.json();
      const query = new URLSearchParams({id, result_id:capture, layout:'desk', basis, lease_id:lease.lease_id});
      const detail = await fetch(`/api/comparison-snapshot/details?${query}`);
      if (!detail.ok) throw Error('Capture unavailable');
      const evidence = await detail.json();
      if (!evidence.desk_offer || evidence.row.id !== id) throw Error('Saved offer unavailable');
      if (dialog.open) { releaseEvidence(lease); return; }
      const {game_key, game_title, league, start_at, market} = evidence.row;
      currentSelection = {offer:evidence.desk_offer, group:{game_key, game_title, league, start_at, market},
        basis, lease, evidence, historical:true, checkedAt:evidence.captured_at || evidence.desk_offer.captured_at};
      $('trade-note').textContent = '';
      tradeDetails();
      dialog.showModal();
    } catch {
      releaseEvidence(lease);
      $('notice').textContent = 'The saved offer could not be opened.';
    }
  }

  function returnToPair() {
    const {pairContext, lease, parent} = currentSelection;
    releaseEvidence(lease);
    currentSelection = pairContext;
    $('trade-title').textContent = parent.title;
    $('trade-note').textContent = parent.note;
    $('latest').hidden = parent.latestHidden;
    $('back-to-pair').hidden = true;
    $('trade-body').replaceChildren(...parent.nodes);
    parent.opener.focus({preventScroll:true});
    dialog.scrollTop = parent.scrollTop;
  }

  function dismissInspection() {
    const current = window.history.state?.predictInspection;
    if (inspection && current?.id === inspection.id) {
      if (!inspection.closing) {
        inspection.closing = true;
        window.history.back();
      }
    } else if (currentSelection?.parent) returnToPair();
    else closeInspection();
  }

  dialog.querySelector('form[method="dialog"]').addEventListener('submit', event => {
    event.preventDefault();
    dismissInspection();
  });
  dialog.addEventListener('cancel', event => {
    event.preventDefault();
    dismissInspection();
  });
  $('back-to-pair').onclick = dismissInspection;

  function clearInspectionEntry() {
    const {predictInspection, ...entry} = window.history.state || {};
    if (predictInspection) window.history.replaceState(entry, '');
  }
  // A reload can open directly at a modal entry whose in-memory capture is gone.
  clearInspectionEntry();
  window.addEventListener('popstate', event => {
    const marker = event.state?.predictInspection;
    if (!dialog.open || !inspection) {
      clearInspectionEntry();
      return;
    }
    inspection.closing = false;
    if (marker?.id !== inspection.id) closeInspection();
    else if (marker.depth === 1 && currentSelection?.parent) returnToPair();
    else if (marker.depth === 2 && !currentSelection?.parent) clearInspectionEntry();
  });
  async function releaseEvidence(lease) {
    if (!lease) return;
    try {
      const query = new URLSearchParams({lease_id:lease.lease_id});
      await fetch(`/api/comparison-current/lease?${query}`, {
        method:'DELETE',
        headers:{'Content-Type':'application/json'},
        keepalive:true
      });
    } catch {}
  }

  async function reserveEvidence(result_id) {
    const response = await fetch('/api/comparison-current/lease', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({result_id})
    });
    if (!response.ok) throw Error('Evidence expired');
    return response.json();
  }

  async function pinEvidence(offer, basis) {
    if (offer.live_native_desk || offer.live_aggregate_desk) {
      const query = new URLSearchParams({id:offer.id, layout:'desk', basis, phase:offer.game_state === 'live' ? 'live' : 'pregame'});
      const response = await fetch(`/api/comparison-current/selection?${query}`);
      if (!response.ok) throw Error('Price evidence unavailable');
      const {row, evidence} = await response.json();
      if (!evidence || row?.price_revision !== offer.price_revision ||
          row?.economic_revision !== offer.economic_revision) throw Error('Price or evidence changed');
      return {evidence:{...evidence, desk_offer:row}};
    }
    if (!offer.evidence_result_id) throw Error('Missing exact evidence');
    if (replay) {
      const query = new URLSearchParams({dataset, result_id:offer.evidence_result_id, id:offer.id});
      if (retainedResult) query.set('game_key', gameKey);
      const detail = await fetch(`/api/odds-replay/details?${query}`);
      if (!detail.ok) throw Error('Replay evidence unavailable');
      const evidence = await detail.json();
      if (evidence.row.id !== offer.id || evidence.row.price_revision !== offer.price_revision ||
          evidence.row.economic_revision !== offer.economic_revision) throw Error('Replay revision changed');
      return {evidence};
    }
    const lease = await reserveEvidence(offer.evidence_result_id);
    try {
      const query = new URLSearchParams({layout:'desk', basis,
        result_id:offer.evidence_result_id, id:offer.id, lease_id:lease.lease_id});
      const detail = await fetch(`/api/comparison-snapshot/details?${query}`);
      if (!detail.ok) throw Error();
      const evidence = await detail.json();
      if (evidence.row.id !== offer.id || evidence.row.price_revision !== offer.price_revision ||
          evidence.row.economic_revision !== offer.economic_revision) throw Error();
      return {lease, evidence};
    } catch (error) {
      releaseEvidence(lease);
      throw error;
    }
  }

  function pairIdentity(context) {
    const {publishedPair:pair, offers} = context;
    const payoff = pair.retail_payoff;
    const fees = payoff.legs?.map(leg => [leg.available, leg.classification, leg.quantity, leg.acquisition_usd,
      leg.at_fill_usd, leg.settlement_usd, leg.receipts_usd]);
    return JSON.stringify([pair.id, pair.legs.map(id => {
      const offer = offers.get(id);
      return [offer.id, offer.price_revision, offer.economic_revision, offer.odds, offer.current];
    }),
      payoff.available, payoff.reason, payoff.funding_usd, payoff.states, payoff.sizing, fees, pair.score]);
  }

  async function readPair(selection) {
    const query = new URLSearchParams({
      layout:'desk', view:'arbs', game_key:selection.group.game_key,
      family:selection.group.market.market, period:selection.group.market.period, limit:pageSize
    });
    const {phase} = viewContext();
    if (phase) query.set('phase', phase);
    const ids = [...selection.pair.legs].sort().join('\u001f');
    for (let offset = 0; ; offset += pageSize) {
      query.set('offset', offset);
      const page = await fetchPage(query);
      const group = page.rows?.find(row => row.id === selection.group.id);
      if (group) {
        const offers = new Map(group.offers.map(offer => [offer.id, offer]));
        const pair = group.pairs.find(item => [...item.legs].sort().join('\u001f') === ids && item.retail_payoff?.available
          && item.legs.every(id => sameOffer(selection.offers.get(id), offers.get(id))));
        if (pair) return {pair, publishedPair:pair, group, offers,
          game:page.games?.find(item => item.game_key === group.game_key)};
      }
      if (group || !page.total || offset + pageSize >= page.total) return null;
      if (page.browse_id) query.set('browse_id', page.browse_id);
    }
  }

  async function adoptPair(selection, isActive) {
    const next = await readPair(selection);
    if (!isActive()) return;
    if (!next) {
      adoptionNotice(selection, viewContext().phase === 'pregame' && Date.parse(selection.group.start_at) <= Date.now()
        ? 'Scheduled start passed. The pregame pair remains pinned.'
        : 'A current modeled payoff for these exact legs is unavailable. The earlier capture remains pinned.');
      return;
    }
    const confirmed = await readPair(selection);
    if (!isActive()) return;
    if (!confirmed || pairIdentity(next) !== pairIdentity(confirmed)
        || !confirmed.pair.legs.every(id => selectionCurrent(confirmed.offers.get(id)))) {
      adoptionNotice(selection, 'The pair changed during adoption. The earlier calculation is still pinned.');
      return;
    }
    if (pairIdentity(selection) === pairIdentity(confirmed)) {
      showRefreshResult(selection, 'No newer pair inputs found. The displayed calculation is unchanged.');
      return;
    }
    const replacement = openPair(confirmed.pair, confirmed.offers, confirmed.group, confirmed.game, selection.opener);
    if (dialog.open && currentSelection === replacement) showRefreshResult(replacement, 'Updated both legs and the payoff.');
  }

  function showRefreshResult(selection, message) {
    selection.refreshMessage = message;
    $('trade-note').textContent = message;
  }

  function adoptionNotice(selection, message) {
    selection.adoptionNotice = true;
    $('trade-note').textContent = message;
    if (selection.offer) pinSelectionStatus(selection);
  }

  function unavailableQuote(selection, reason) {
    if (viewContext().phase === 'pregame' && Date.parse(selection.group.start_at) <= Date.now()) {
      return 'Scheduled start passed. The pregame capture remains pinned.';
    }
    return `${evidenceReason(reason, 'No current replacement for this exact quote.')} The earlier capture remains pinned.`;
  }

  function latestQuoteQuery(selection) {
    const {offer, basis} = selection;
    const query = new URLSearchParams({id:offer.id, layout:'desk', basis});
    const {phase} = viewContext();
    if (phase) query.set('phase', phase);
    if (offer.desk_quote_key) query.set('quote_key', offer.desk_quote_key);
    return query;
  }

  function pinSelectionStatus(selection) {
    selection.pinned = true;
    markPinned($('trade-body'), selection.pinned);
  }

  function expireInspection() {
    const selected = currentSelection;
    const pair = selected?.pair ? selected : selected?.pairContext;
    if (!replay && dialog.open && pair) {
      const now = Date.now();
      const closed = viewContext().phase === 'pregame' && Date.parse(pair.group.start_at) <= now;
      const expired = Date.parse(pair.pair.calculation_current_until) <= now
        || pair.pair.legs.some(id => !selectionCurrent(pair.offers.get(id), now));
      if (closed || expired) setPairAuthorityNote(pair, closed ? 'Scheduled start passed. The pregame pair is closed.'
        : 'The published price or fee authority expired.');
    }
    if (selected?.posted) {
      if (!selected.ended && Date.parse(selected.group.start_at) <= Date.now()) closePosted(selected, 'Pregame closed', true);
      return;
    }
    if (!replay && dialog.open && selected?.offer && !selected.historical && !selectionCurrent(selected.offer)) {
      pinSelectionStatus(selected);
    }
  }

  function setPairAuthorityNote(context, note) {
    if (note === context.authorityNote) return;
    context.authorityNote = note;
    if (currentSelection === context) {
      $('trade-note').textContent = note;
      const body = $('trade-body');
      let mode = body.querySelector('.inspection-mode');
      if (note && !mode) {
        mode = el('p', 'Earlier published calculation', 'inspection-mode');
        body.firstElementChild?.after(mode);
      } else if (!note) mode?.remove();
    }
  }

  function closePosted(selected, message, ended = false) {
    if (selected.closed && selected.ended === ended && $('trade-note').textContent === message) return;
    selected.request = (selected.request || 0) + 1;
    selected.closed = true;
    selected.ended = ended;
    selected.loading = false;
    selected.offer = {...selected.offer, valuation:null, sportsbook:null};
    selected.comparison = null;
    selected.refreshAvailable = !ended;
    $('trade-note').textContent = message;
    tradeDetails();
  }

  async function readBoardSelection(selected, refresh = false) {
    const request = selected.request = (selected.request || 0) + 1;
    const active = () => dialog.open && currentSelection === selected && selected.request === request && !selected.ended;
    const finish = message => {
      selected.loading = false;
      $('trade-note').textContent = message;
      tradeDetails();
    };
    try {
      const query = latestQuoteQuery(selected);
      query.set('unit_usd', selected.size);
      let boardId = selected.boardId;
      if (refresh) {
        const page = await fetchPage(new URLSearchParams({
          layout:'desk', phase:'pregame', ranked:'1', summary:'1', unit_usd:selected.size, limit:'1', refresh:'1'
        }));
        if (!active()) return;
        if (page.state === 'read_failed' || !sameBoardUnit(page.selected_usd, selected.size)) throw Error('Board unavailable');
        if (page.state === 'valuation_pending' || page.replacement_pending) {
          finish('The current calculation is still updating. Try refreshing again.');
          return;
        }
        if (page.state !== 'ready' || !page.board_id) throw Error('Board unavailable');
        boardId = page.board_id;
        selected.boardChanged ||= selected.boardId !== boardId;
        query.set('refresh', '1');
      } else {
        query.set('expected_member', selected.offer.evidence_result_id);
      }
      query.set('board_id', boardId);
      const response = await fetch(`/api/comparison-current/selection?${query}`);
      if (!response.ok) throw Error('Selection unavailable');
      const packet = await response.json();
      if (!active()) return;
      if (!packet.row) {
        const ended = packet.reason === 'pregame_closed' || Date.parse(selected.group.start_at) <= Date.now();
        const changed = packet.reason === 'unit_publication_changed';
        closePosted(selected, ended ? 'Pregame closed.' : changed
          ? refresh ? 'This exact offer has no current ranked calculation at this unit.' : 'This offer or its calculation changed. Refresh to check the current offer.'
          : evidenceReason(packet.reason, 'This offer is no longer available for comparison.'), ended);
        return;
      }
      const {row, result_id, comparison} = packet;
      const model = row.valuation;
      if (packet.board_id !== boardId || row.board_id !== boardId || !sameOffer(selected.offer, row) ||
          !sameBoardUnit(row.unit_usd, selected.size) || !model || model.bet_id !== selected.group.id ||
          model.offer_id !== row.id || model.member_result_id !== row.evidence_result_id || model.publication_id !== result_id ||
          model.price_revision !== row.price_revision || model.economic_revision !== row.economic_revision ||
          (!refresh && (row.id !== selected.offer.id || row.evidence_result_id !== selected.offer.evidence_result_id ||
            row.price_revision !== selected.offer.price_revision || row.economic_revision !== selected.offer.economic_revision)) ||
          !sameBoardUnit(model.selected_usd, selected.size) || !Array.isArray(comparison) ||
          !comparison.some(quote => quote.offer_id === row.id && quote.member_result_id === row.evidence_result_id) ||
          comparison.some(quote => quote.publication_id !== result_id || !sameBoardUnit(quote.selected_usd, selected.size))) {
        throw Error('Comparison inputs changed');
      }
      const displayChanged = JSON.stringify([selected.offer.valuation, selected.comparison]) !== JSON.stringify([model, comparison]);
      Object.assign(selected, {offer:row, boardId, comparison, closed:false, refreshAvailable:false});
      if (row.start_at) selected.group = {...selected.group, start_at:row.start_at};
      if (refresh && document.activeElement === refreshComparison) dialog.querySelector('form button').focus();
      if (selected.loading || displayChanged || refresh) finish(refresh ? 'Current calculation loaded.' : '');
      else $('trade-note').textContent = '';
    } catch {
      if (!active()) return;
      selected.refreshAvailable = true;
      finish(selected.offer.valuation ? 'Could not verify current prices. Showing the inspected calculation.'
        : 'The comparison could not be loaded. Refresh to retry.');
    }
  }

  refreshComparison.onclick = async () => {
    const selected = currentSelection;
    if (!selected?.boardId) return;
    refreshComparison.disabled = true;
    $('trade-note').textContent = 'Checking the current calculation…';
    try { await readBoardSelection(selected, true); }
    finally { refreshComparison.disabled = false; }
  };

  async function readPostedSelection(selected, {adopt = false} = {}) {
    const revision = selected.request = (selected.request || 0) + 1;
    const size = selected.size;
    const active = () => dialog.open && selected === currentSelection && selected.request === revision
      && selected.size === size && !selected.ended;
    const query = latestQuoteQuery(selected);
    if (size !== null) query.set('unit_usd', size);
    if (!adopt && selected.offer.evidence_result_id) query.set('expected_member', selected.offer.evidence_result_id);
    try {
      const response = await fetch(`/api/comparison-current/selection?${query}`);
      if (!response.ok) throw Error('Selection unavailable');
      const {row, evidence, reason, withdrawn_from_phase, result_id, comparison} = await response.json();
      if (!active()) return;
      const canAdopt = adopt === 'refresh' || adopt && viewContext().autoUpdate;
      if (withdrawn_from_phase || canAdopt && reason !== 'unit_publication_changed'
          && (!row?.posted_price || !sameOffer(selected.offer, row))) {
        const ended = Date.parse(selected.group.start_at) <= Date.now();
        closePosted(selected, ended ? 'Pregame closed'
          : evidenceReason(reason, 'This posted quote was withdrawn.'), ended);
        return;
      }
      selected.loading = false;
      const model = row?.valuation;
      if (model && (model.offer_id !== row.id || model.member_result_id !== row.evidence_result_id
          || model.publication_id !== result_id || model.price_revision !== row.price_revision
          || model.economic_revision !== row.economic_revision
          || (size === null ? model.selected_usd !== null : num(model.selected_usd) !== Number(size)))) {
        throw Error('Valuation inputs changed');
      }
      if (row?.posted_price && sameOffer(selected.offer, row)
          && (canAdopt || row.price_revision === selected.offer.price_revision
            && row.economic_revision === selected.offer.economic_revision
            && row.evidence_result_id === selected.offer.evidence_result_id)) {
        const before = selected.offer;
        const scheduleChanged = row.start_at && Date.parse(row.start_at) !== Date.parse(selected.group.start_at);
        if (scheduleChanged) selected.group = {...selected.group, start_at:row.start_at};
        selected.closed = false;
        selected.ended = false;
        selected.offer = {...row, odds:row.odds && (row.odds.decimal === before.odds?.decimal ? before.odds : row.odds)};
        selected.evidence = evidence;
        selected.boardId = row.board_id || selected.boardId;
        selected.comparison = comparison;
        $('trade-note').textContent = '';
        if (scheduleChanged || before.price_revision !== row.price_revision || before.economic_revision !== row.economic_revision
            || JSON.stringify(before.valuation) !== JSON.stringify(row.valuation) || !before.valuation) tradeDetails();
        return;
      }
      $('trade-note').textContent = 'A newer quote or calculation is available. Refresh to use it.';
      tradeDetails();
    } catch {
      if (!active()) return;
      selected.loading = false;
      $('trade-note').textContent = 'Could not update this preview. The posted price is still shown.';
      tradeDetails();
    }
  }

  amount?.addEventListener('input', () => {
    if (!currentSelection?.posted) return;
    currentSelection.request = (currentSelection.request || 0) + 1;
    currentSelection.editingSize = true;
    currentSelection.loading = false;
    if (currentSelection.offer.valuation) {
      currentSelection.offer = {...currentSelection.offer, valuation:null};
      tradeDetails();
    }
  });
  function commitSize() {
    if (!currentSelection?.posted || !currentSelection.editingSize || !amount.reportValidity()) return;
    currentSelection.editingSize = false;
    currentSelection.size = amount.value ? Number(amount.value).toFixed(2) : null;
    currentSelection.loading = true;
    currentSelection.offer = {...currentSelection.offer, valuation:null};
    tradeDetails();
    readPostedSelection(currentSelection);
  }
  amount?.addEventListener('change', commitSize);
  amount?.addEventListener('blur', commitSize);
  amount?.addEventListener('keydown', event => { if (event.key === 'Enter') commitSize(); });
  previewRefresh.onclick = refreshDesk;

  $('latest').onclick = async () => {
    const latest = $('latest');
    const selection = currentSelection;
    selection.adoptionNotice = false;
    selection.refreshMessage = '';
    latest.disabled = true;
    $('trade-note').textContent = 'Checking latest price…';
    const isActive = () => dialog.open && currentSelection === selection;
    try {
      if (selection.pair) {
        await adoptPair(selection, isActive);
        return;
      }
      const query = latestQuoteQuery(selection);
      let unavailable;
      const next = await pinLatestSelection({
        read: async () => {
          const response = await fetch(`/api/comparison-current/selection?${query}`);
          if (!response.ok) throw Error('Unavailable');
          const {row, reason} = await response.json();
          unavailable = reason || row?.reason;
          if (!row) return null;
          if (!sameOffer(selection.offer, row)) {
            unavailable = 'selection_exact_outcome_changed';
            return null;
          }
          return selection.offer.value != null && row.value == null ? null : row;
        },
        pin: offer => pinEvidence(offer, selection.basis), release: releaseEvidence, isActive
      });
      if (!isActive()) { if (next.state === 'ready') releaseEvidence(next.lease); return; }
      if (next.state === 'unavailable') {
        adoptionNotice(selection, unavailableQuote(selection, unavailable));
        return;
      }
      if (next.state === 'changed') {
        adoptionNotice(selection, 'The price, fee, or reference changed during adoption. The earlier inspection is still pinned.');
        return;
      }
      if (next.state !== 'ready') return;
      const {offer, evidence, lease} = next;
      const unchanged = selectionIdentity(offer) === selectionIdentity(selection.offer);
      if (unchanged && !selection.pinned && !selection.historical) {
        releaseEvidence(lease);
        showRefreshResult(selection, 'No newer quote or calculation inputs found.');
        return;
      }
      const reference = selectedReference(offer, selection.basis);
      const group = {...selection.group, settlement_match:undefined,
        sportsbook_quotes:reference?.prices?.[0] ? {[reference.book]: [{...reference.prices[0], current:true}]} : undefined};
      currentSelection = {...selection, group, offer, evidence, lease, checkedAt:Date.now(),
        historical:false, pinned:null, retentionError:null, publication:null};
      releaseEvidence(selection.lease);
      tradeDetails();
      showRefreshResult(currentSelection, 'Prices updated.');
    } catch {
      if (isActive()) adoptionNotice(selection, 'Could not check the latest price. The earlier inspection is still pinned.');
    } finally {
      latest.disabled = false;
      if (dialog.open && !latest.hidden && !dialog.contains(document.activeElement)) latest.focus({preventScroll:true});
    }
  };

  function closeInspection() {
    dialog.close();
    finishInspection(true);
  }

  function finishInspection(restoreOpener = false) {
    if (dialog.open || !currentSelection) return;
    const old = currentSelection;
    const position = inspection;
    inspection = null;
    currentSelection = null;
    releaseEvidence(old?.lease);
    releaseEvidence(old?.pairContext?.lease);
    const pair = old?.pairContext?.pair || old?.pair;
    const current = pair
      ? [...$('results').querySelectorAll('[data-pair-id]')].find(item => item.dataset.pairId === pair.id)
      : [...$('results').querySelectorAll(old?.opener?.dataset.calculationId ? '[data-calculation-id]' : '[data-offer-id]')]
        .find(item => (item.dataset.calculationId ?? item.dataset.offerId) === old?.offer?.id
          || old?.offer?.desk_quote_key && item.dataset.deskQuoteKey === old.offer.desk_quote_key);
    const fallback = old?.boardId ? $('board-unit')
      : $('refresh-list').getAttribute('aria-disabled') === 'true' ? filters.elements.search : $('refresh-list');
    const previousOpener = old?.pairContext?.opener || old?.opener;
    const opener = previousOpener?.isConnected ? previousOpener : current;
    const focused = document.activeElement;
    if (opener && (restoreOpener || focused === document.body || focused === document.documentElement || dialog.contains(focused))) {
      opener.focus({preventScroll:true});
    }
    else restoreFocus(fallback);
    if (position) {
      restoreMatrices(position.tableScrolls);
      window.scrollTo(0, position.scrollY);
      window.history.scrollRestoration = position.scrollRestoration;
    }
    if (old.boardChanged) refreshDesk();
  }
  // A native close event follows later. Clean up external closes without moving
  // focus after the user has already reached another control.
  dialog.addEventListener('close', () => finishInspection());
  async function checkSelection(refresh = false) {
    const selected = currentSelection;
    if (selected?.boardId) {
      expireInspection();
      if (dialog.open && !selected.ended && !selected.loading && !refreshComparison.disabled) {
        return readBoardSelection(selected);
      }
      return;
    }
    if (selected?.posted) {
      previewRefresh.hidden = viewContext().autoUpdate;
      expireInspection();
      if (!dialog.open || selected.ended || selected.editingSize || !refresh && !viewContext().autoUpdate) return;
      return readPostedSelection(selected, {adopt:refresh ? 'refresh' : true});
    }
    if (replay || !dialog.open || !selected || selected.historical || selected.adoptionNotice || $('latest').disabled) return;
    expireInspection();
    try {
      if (selected.pair) {
        if (!selected.pair.retail_payoff?.available) return;
        const current = await readPair(selected);
        if (!dialog.open || selected !== currentSelection || selected.adoptionNotice || $('latest').disabled) return;
        if (!current) {
          setPairAuthorityNote(selected, viewContext().phase === 'pregame' && Date.parse(selected.group.start_at) <= Date.now()
            ? 'Scheduled start passed. The pregame pair is closed.'
            : 'A current modeled payoff is unavailable for these exact legs.');
        } else {
          setPairAuthorityNote(selected, '');
          $('trade-note').textContent = pairIdentity(current) !== pairIdentity(selected)
            ? 'Pair inputs changed. Use latest prices to update both legs together.' : selected.refreshMessage || '';
        }
        return;
      }
      const query = latestQuoteQuery(selected);
      const response = await fetch(`/api/comparison-current/selection?${query}`);
      if (!response.ok) return;
      const {row, withdrawn_from_phase, reason} = await response.json();
      if (!dialog.open || selected !== currentSelection || selected.adoptionNotice || $('latest').disabled) return;
      const previous = selected.offer;
      let note = '';
      const currentPhase = viewContext().phase;
      if (withdrawn_from_phase || row?.withdrawn_from_phase ||
          currentPhase === 'pregame' && Date.parse(selected.group.start_at) <= Date.now()) {
        pinSelectionStatus(selected);
        note = evidenceReason(reason, `This quote is no longer eligible for ${currentPhase === 'live' ? 'Live' : 'Pregame'}.`)
          + ' The inspected price remains pinned.';
      } else if (!row?.current || !sameOffer(previous, row)) {
        pinSelectionStatus(selected);
        note = unavailableQuote(selected, row?.current ? 'selection_exact_outcome_changed' : reason || row?.reason);
      }
      else if (selectionIdentity(row) !== selectionIdentity(previous)) {
        pinSelectionStatus(selected);
        const change = row.odds?.decimal === previous.odds?.decimal ? 'Calculation evidence changed.' : 'Price changed.';
        note = `${change} Use latest prices to update the offer, fee and reference together.`;
      }
      $('trade-note').textContent = [note || selected.refreshMessage, selected.retentionError].filter(Boolean).join(' ');
    } catch {}
  }
  setInterval(async () => {
    const selected = currentSelection;
    if (!dialog.open || !selected) return;
    for (const subject of [selected, selected.pairContext]) {
      if (!subject?.lease) continue;
      const result_id = (subject.offer || subject.pair).evidence_result_id;
      try {
        const response = await fetch('/api/comparison-current/lease', {method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({result_id, lease_id:subject.lease.lease_id})});
        if (!response.ok && selected === currentSelection) {
          selected.retentionError = 'Evidence retention expired; displayed inspection remains saved.';
          $('trade-note').textContent = selected.retentionError;
        }
      } catch {}
    }
  }, 30000);

  return {openTrade, openPair, openHistorical, checkSelection, expireInspection, isOpen: () => dialog.open};
}
