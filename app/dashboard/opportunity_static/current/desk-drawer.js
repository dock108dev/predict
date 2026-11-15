import {markPinned, tradeInspection, pairInspection} from './desk-inspection.js';
import {quoteFreshness, selectedReference} from './opportunity-cards.js';
import {pinLatestSelection, selectionCurrent, selectionIdentity} from './desk-evidence.js';
import {evidenceReason} from './desk-reasons.js';

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

// Keep a selected capture, its dialog history, and its evidence lease together.
export function createDeskDrawer({replay, dataset, retainedResult, gameKey, pageSize, captureMode,
  viewContext, fetchPage, matrixPositions, restoreMatrices, restoreFocus}) {
  const $ = id => document.getElementById(id);
  const dialog = $('trade');
  const filters = $('filters');
  let currentSelection = null;

  function tradeDetails() {
    const {offer, group, game, evidence, pairContext} = currentSelection;
    const label = position(offer, game);
    $('trade-title').textContent = `${name(offer.venue)} · ${label}`;
    const mode = currentSelection.historical ? 'Saved capture · prices at inspection time' : captureMode;
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
    const previous = Boolean(previousReason || opener?.hasAttribute('data-expired-quote'));
    currentSelection = {offer, group, game, opener, pairContext,
      basis:page?.basis || filters.elements.basis.value,
      checkedAt:previous ? Date.parse(page?.publication?.read_at) || Date.now() : Date.now(),
      pinned:previous, publication:pairContext?.publication ?? page?.publication};
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
    try {
      const pinned=await pinEvidence(offer, selected.basis);
      if(currentSelection!==selected||!dialog.open){releaseEvidence(pinned.lease);return;}
      Object.assign(selected,pinned);
      const detail = pinned.evidence.desk_offer;
      if (detail) {
        selected.offer = {...detail, ...offer};
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
    const context = {pair, publishedPair:pair, offers, group, game, opener, publication:viewContext().page?.publication};
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
        retail_payoff:retail.available || retail.reason === detail.retail_payoff?.reason
          ? detail.retail_payoff : {...retail, legs:[]}};
      for (const offer of detail.offers || []) {
        if (context.offers.has(offer.id)) {
          context.offers.set(offer.id, {...offer, ...context.offers.get(offer.id)});
        }
      }
      context.pair = context.publishedPair = hydrated;
      renderPair(context);
    } catch {
      if (dialog.open && currentSelection === context) {
        $('trade-body').replaceChildren(el('p', 'This calculation could not be loaded.'));
        $('latest').hidden = false;
      }
    }
  }

  function renderPair(context) {
    const {pair, offers, group, game} = context;
    currentSelection = context;
    $('trade-title').textContent = 'Pair payoff';
    $('trade-note').textContent = '';
    $('latest').hidden = replay || !pair.inspection;
    $('back-to-pair').hidden = true;
    const customSizing = !replay && pair.inspection && pair.evidence_result_id
      && pair.retail_payoff?.reason !== 'pair_fee_publication_pending';
    const mode = context.requestedStake ? 'Sized from the captured prices and fees' : captureMode;
    const body = $('trade-body');
    if (!pair.inspection && !replay && pair.evidence_result_id
        && !['pair_leg_stale_or_replaced', 'pair_settlement_unverified'].includes(pair.retail_payoff?.reason)) {
      body.replaceChildren(el('p', 'Loading the calculation…', 'desk-meta'));
      return;
    }
    body.replaceChildren(pairInspection(pair, offers, {group, game, position, mode,
      inspect: (offer, opener) => openTrade(offer, group, game, context, opener)}));
    if (customSizing) {
      const form = el('form', null, 'pair-sizing');
      const label = Object.assign(el('label', 'Total stake before fees ($)'), {htmlFor:'pair-stake-amount'});
      const amount = Object.assign(el('input'), {id:'pair-stake-amount', type:'number', min:'0.01', max:'1000000', step:'0.01',
        required:true, value:context.requestedStake ?? '100'});
      const calculate = el('button', 'Size this pair');
      const status = el('p');
      status.setAttribute('role', 'status');
      form.append(label, amount, calculate, status);
      form.addEventListener('submit', async event => {
        event.preventDefault();
        calculate.disabled = true;
        status.textContent = 'Sizing the captured pair…';
        try {
          await sizePair(context, amount.value);
          if (dialog.open && currentSelection === context) $('trade-body').querySelector('form input')?.focus();
        } catch {
          status.textContent = 'Could not size this capture. The previous calculation is still displayed.';
        } finally { calculate.disabled = false; }
      });
      body.prepend(form);
    }
  }

  async function sizePair(context, requestedStake) {
    const lease = await context.reservation;
    if (!lease) throw Error('Pair evidence unavailable');
    const {id, evidence_result_id} = context.pair;
    const query = new URLSearchParams({id, result_id:evidence_result_id, lease_id:lease.lease_id, stake:requestedStake});
    const response = await fetch(`/api/comparison-snapshot/details?${query}`);
    if (!response.ok) throw Error('Pair evidence unavailable');
    const {id:pairID, evidence_result_id:resultID, inspection, retail_payoff, score} = await response.json();
    if (pairID !== id || resultID !== evidence_result_id) throw Error('Pair evidence changed');
    if (dialog.open && currentSelection === context) {
      context.requestedStake = requestedStake;
      context.pair = {...context.pair, inspection, retail_payoff, score};
      renderPair(context);
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
      const pair = group?.pairs.find(item => [...item.legs].sort().join('\u001f') === ids && item.retail_payoff?.available);
      if (pair) return {pair, publishedPair:pair, group, offers:new Map(group.offers.map(offer => [offer.id, offer])),
        game:page.games?.find(item => item.game_key === group.game_key)};
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
        : 'These legs no longer have a current modeled payoff. The earlier calculation is still pinned.');
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
    if (selection.requestedStake) {
      try { await sizePair(replacement, selection.requestedStake); }
      catch {
        if (dialog.open && currentSelection === replacement) showRefreshResult(replacement, 'Updated both legs. The published payoff is shown while custom sizing is unavailable.');
        return;
      }
    }
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

  function pinSelectionStatus(selection) {
    selection.pinned = true;
    markPinned($('trade-body'), selection.pinned);
  }

  function expireInspection() {
    const selected = currentSelection;
    if (!replay && dialog.open && selected?.offer && !selected.historical && !selectionCurrent(selected.offer)) {
      pinSelectionStatus(selected);
    }
  }

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
      const query = new URLSearchParams({id:selection.offer.id, layout:'desk', basis:selection.basis});
      const {phase} = viewContext();
      if (phase) query.set('phase', phase);
      const next = await pinLatestSelection({
        read: async () => {
          const response = await fetch(`/api/comparison-current/selection?${query}`);
          if (!response.ok) throw Error('Unavailable');
          const {row} = await response.json();
          return selection.offer.value != null && row?.value == null ? null : row;
        },
        pin: offer => pinEvidence(offer, selection.basis), release: releaseEvidence, isActive
      });
      if (!isActive()) { if (next.state === 'ready') releaseEvidence(next.lease); return; }
      if (next.state === 'unavailable') {
        adoptionNotice(selection, viewContext().phase === 'pregame' && Date.parse(selection.group.start_at) <= Date.now()
          ? 'Scheduled start passed. The pregame capture remains pinned.'
          : 'No current replacement for this inspection. The earlier capture remains pinned.');
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
        .find(item => (item.dataset.calculationId ?? item.dataset.offerId) === old?.offer?.id);
    const fallback = $('refresh-list').getAttribute('aria-disabled') === 'true' ? filters.elements.search : $('refresh-list');
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
  }
  // A native close event follows later. Clean up external closes without moving
  // focus after the user has already reached another control.
  dialog.addEventListener('close', () => finishInspection());
  async function checkSelection() {
    const selected = currentSelection;
    if (replay || !dialog.open || !selected || selected.historical || selected.adoptionNotice || $('latest').disabled) return;
    expireInspection();
    try {
      if (selected.pair) {
        if (!selected.pair.inspection) return;
        const current = await readPair(selected);
        if (!dialog.open || selected !== currentSelection || selected.adoptionNotice || $('latest').disabled) return;
        $('trade-note').textContent = !current && viewContext().phase === 'pregame' && Date.parse(selected.group.start_at) <= Date.now()
          ? 'Scheduled start passed. The pregame pair remains pinned.'
          : !current ? 'A current modeled payoff is unavailable. The earlier calculation is still pinned.'
          : pairIdentity(current) !== pairIdentity(selected) ? 'Pair inputs changed. Use latest prices to update both legs together.'
            : selected.refreshMessage || '';
        return;
      }
      const query = new URLSearchParams({id:selected.offer.id, layout:'desk', basis:selected.basis});
      const {phase} = viewContext();
      if (phase) query.set('phase', phase);
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
      } else if (!row?.current) {
        pinSelectionStatus(selected);
        note = `${row ? quoteFreshness(row) + '.' : 'Latest price is unavailable.'} The inspected price remains pinned.`;
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
