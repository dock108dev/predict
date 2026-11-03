import { el, venue, words, price, labelsFor, marketFamily, observationState, observationStateLabel } from "./board-elements.js";

// Exact price ordering only. Financial estimates are never calculated here.
function rational(value) {
  const parts = String(value).split("/");
  if (parts.length === 2) return [BigInt(parts[0]), BigInt(parts[1])];
  const [whole, decimal = ""] = parts[0].split(".");
  return [BigInt(whole + decimal), 10n ** BigInt(decimal.length)];
}
function cost(q) {
  if (!q.common_odds?.supported || !q.original) return null;
  try {
    const [n, d] = rational(q.original.value);
    if (q.original.units === "decimal_odds") return n > d ? [d, n] : null;
    if (q.original.units === "american_odds") return n > 0n ? [100n*d,n+100n*d] : n < 0n ? [-n,100n*d-n] : null;
    const [p, pd] = rational(q.original.payout);
    return n > 0n && p > 0n ? [n*pd,d*p] : null;
  } catch { return null; }
}
function compare(a,b) {
  const x=cost(a), y=cost(b);
  if (!x || !y) return Number(!x)-Number(!y);
  const v=x[0]*y[1]-y[0]*x[1];
  return v<0n?-1:v>0n?1:0;
}
export function groupedPriceRows(board) {
  const byId = new Map(board.prices.map(q=>[q.quote_id,q]));
  if (board.grouped_odds?.version === "predict-grouped-odds-1") return board.grouped_odds.rows.map(r=>({ ...r,
    quotes:Object.values(r.cells).flat().map(id=>byId.get(id)).filter(Boolean)})).filter(r=>r.quotes.length);
  // Compatibility with retained publications; same declared identity contract.
  const groups=new Map();
  for (const q of board.prices) {
    const s=q.selection || {}, m=q.market || {}, comparable=q.same_outcome?.supported === true && Array.isArray(q.same_outcome.key);
    const id=JSON.stringify(comparable?["comparable",q.same_outcome.key]:["unqualified_display",m.market,m.period,s.participant,s.predicate,s.signed_line ?? m.line]);
    if (!groups.has(id)) groups.set(id,{id,comparable,quotes:[],reason_codes:[]});
    const row=groups.get(id);row.quotes.push(q);
    if (!comparable) row.reason_codes.push(q.same_outcome?.reason || "comparison_identity_unavailable");
  }
  return [...groups.values()];
}
export function cellOffers(group,source,now=Date.now()) {
  const quotes=group.quotes.filter(q=>q.venue===source).sort((a,b)=>
    Number(observationState(a,now)!=="current")-Number(observationState(b,now)!=="current") ||
    compare(a,b) || a.quote_id.localeCompare(b.quote_id));
  return quotes;
}
export function bestPrices(group,now=Date.now()) {
  if (!group.comparable) return new Set();
  const qs=group.quotes.filter(q=>q.venue!=="pinnacle" && observationState(q,now)==="current" && cost(q) &&
    (!q.source?.quote_side || q.source.quote_side==="buy"));
  qs.sort((a,b)=>compare(a,b)||a.quote_id.localeCompare(b.quote_id));
  return new Set(qs.filter(q=>qs.length && compare(q,qs[0])===0).map(q=>q.quote_id));
}
export function renderOddsGrid(root,game,board,onOriginal) {
  const books=["novig","prophetx","kalshi","polymarket_us","pinnacle"];
  const labels=labelsFor(game.participants), groups=groupedPriceRows(board);
  const familyGroups=new Map();
  for (const group of groups) {
    const q=group.quotes[0], key=marketFamily(q)+":"+(q.market?.period || "full_game");
    if (!familyGroups.has(key)) familyGroups.set(key,[]);
    familyGroups.get(key).push(group);
  }
  function row(group,table) {
    const first=group.quotes[0], line=el("tr"), name=el("th",labels.selection(first,false));
    name.scope="row";
    if (!group.comparable) name.append(el("small","Terms unqualified", "odds-qualification"));
    line.append(name);const best=bestPrices(group);
    for (const book of books) {
      const cell=el("td"), offers=cellOffers(group,book);
      const references=book === "pinnacle" ? (board.reference_prices || []).filter(q=>
        ({moneyline:"winner"}[q.market.family] || q.market.family)===marketFamily(first) &&
        q.market.period===(first.market?.period || "full_game") && q.selection.participant===first.selection.participant &&
        q.selection.predicate===first.selection.predicate && String(q.selection.signed_line ?? "")===String(first.selection.signed_line ?? "")) : [];
      if (!offers.length && !references.length) cell.append(el("span","—"));
      for (const [referenceIndex,q] of references.entries()) {
        const d=el("details");d.dataset.key=game.game_key+":reference:"+q.id;
        d.append(el("summary",price(q)),el("small","Reference only · captured price"));
        d.append(el("pre",JSON.stringify({original:q.original,source:q.source,times:q.times},null,2)));
        if (!referenceIndex) cell.append(d);
        else {
          let more=cell.querySelector(".reference-alternates");
          if (!more) {more=el("details",undefined,"reference-alternates");more.append(el("summary","Other reference observations"));cell.append(more);}
          more.append(d);
        }
      }
      function offer(q, target) {
        const button=el("button",price(q),best.has(q.quote_id)?"best-price":"");
        button.dataset.key=game.game_key+":"+q.quote_id;
        button.onclick=()=>onOriginal(q,button,game);
        button.title=venue(book)+" · "+labels.selection(q)+" · Original "+q.original.value+" "+words(q.original.units)+" · Source "+(q.times?.source_at || q.freshness?.source_at || "Unknown")+" · Received "+(q.times?.received_at || q.freshness?.received_at || "Unknown")+" · Original inputs";
        target.append(button,el("small",observationStateLabel(observationState(q))));
        if (best.has(q.quote_id)) target.append(el("small","Best before costs"));
      }
      if (offers.length) offer(offers[0],cell);
      if (offers.length>1) {
        const more=el("details");more.dataset.key=game.game_key+":"+group.id+":"+book;
        more.append(el("summary",(offers.length-1)+" other instrument"+(offers.length>2?"s":"")));
        for (const q of offers.slice(1)) offer(q,more);
        cell.append(more);
      }
      line.append(cell);
    }
    table.append(line);
  }
  for (const [key,items] of familyGroups) {
    root.append(el("h3",words(key.replace(":"," · "))));
    const byLine=new Map();
    for (const group of items) {
      const q=group.quotes[0], s=q.selection, value=s.signed_line ?? q.market?.line;
      const line=(s.predicate==="not_win"?"native-complements:":"")+(value == null?"winner":String(marketFamily(q)==="spread" && s.participant!==game.participants?.find(p=>p.role==="home")?.id ? -Number(value) : Number(value)));
      if (!byLine.has(line)) byLine.set(line,[]);
      byLine.get(line).push(group);
    }
    const ordered=[...byLine.entries()].sort((a,b)=>Number(a[0].startsWith("native"))-Number(b[0].startsWith("native")) ||
      new Set(b[1].flatMap(g=>g.quotes.map(q=>q.venue))).size-new Set(a[1].flatMap(g=>g.quotes.map(q=>q.venue))).size || a[0].localeCompare(b[0]));
    function table(target,rows) {
      const wrap=el("div",undefined,"odds-table-scroll"), t=el("table",undefined,"consolidated-odds"), head=el("thead"), tr=el("tr");
      tr.append(el("th","Outcome / line"),...books.map(b=>el("th",venue(b)+(b==="pinnacle"?" · Reference":""))));head.append(tr);t.append(head);
      const body=el("tbody");for (const group of rows) row(group,body);t.append(body);wrap.append(t);target.append(wrap);
    }
    if (ordered.length) table(root,ordered[0][1]);
    if (ordered.length>1) {
      const more=el("details",undefined,"odds-alternates");more.dataset.key=game.game_key+":"+key+":alternates";
      more.append(el("summary","Alternate lines & native outcomes · "+(ordered.length-1)+" groups"));
      table(more,ordered.slice(1).flatMap(x=>x[1]));root.append(more);
    }
  }
}
