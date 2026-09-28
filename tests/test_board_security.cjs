'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/dashboard/opportunity_static/board.js', 'utf8');
const attack = 'native"><img src=x onerror="alert(1)">';
const elements = new Map();
const element = id => {
  if (!elements.has(id)) elements.set(id, {value: '', textContent: '', innerHTML: ''});
  return elements.get(id);
};
const sandbox = {
  document: {getElementById: element},
  location: {search: ''},
  URLSearchParams,
  E5State: {select: () => undefined},
  BoardView: {...require('../app/dashboard/opportunity_static/presentation.js'), status: () => 'Unavailable', reasons: () => []},
  fetch: async () => ({json: async () => [{id: attack, label: attack}]})
};
vm.createContext(sandbox);
// Load the real renderer and init functions without installing event handlers.
vm.runInContext(source.slice(0, source.indexOf("$('session').onchange")), sandbox);
sandbox.input = {
  id: attack, display: {profit: '0', return_pct: '0', cash: '0', fees: '0', notional: '0'},
  legs: [{id: attack, label: attack, contract: attack, display: {ask: '0'}}],
  modeled_quantity: '1'
};
const html = vm.runInContext('last={assumptions:"synthetic"}; candidateHTML(input)', sandbox);
assert(!html.includes('<img'), 'native IDs must not create markup');
assert(html.includes('data-explore="native&quot;&gt;&lt;img'));
assert(html.includes('data-candidate="native&quot;&gt;&lt;img'));
// HTML attribute decoding restores the original identifier for normal UI selection.
const decode = s => s.replace(/&quot;/g, '"').replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
assert.equal(decode(html.match(/data-explore="([^"]*)"/)[1]), attack);
(async () => {
  // The absent selected fixture deliberately ends init after catalog rendering.
  await sandbox.init();
  const options = element('session').innerHTML;
  assert(!options.includes('<img'));
  assert(options.includes('<option value="native&quot;&gt;&lt;img'));
  assert.equal(decode(options.match(/value="([^"]*)"/)[1]), attack);
  console.log('PASS: candidate, contract and session identifiers stay escaped and preserve identity');
})().catch(error => {console.error(error); process.exitCode = 1;});

const view=require('../app/dashboard/opportunity_static/presentation.js');
const escape=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
for(const url of ['javascript:alert(1)','JaVaScRiPt:alert(1)','data:text/html,test','file:///tmp/test','//example.com','https://user:secret@example.com','https://example.com/\nsecret','https://[','https://example.com/\\evil',null]){
 assert.equal(view.externalLink(url,'<evidence>',escape),'&lt;evidence&gt;');
}
for(const url of ['https://docs.kalshi.com/fees?a=1&b=2','http://example.com/evidence','https://polymarket.us/event/native%20slug']){
 const link=view.externalLink(url,'<evidence>',escape);
 assert(link.includes('href="'+escape(url)+'"'));
 assert(link.includes('rel="noopener noreferrer"'));
 assert(link.includes('&lt;evidence&gt;'));
}
console.log('PASS: dynamic external links restrict schemes, reject credentials, and escape labels');
