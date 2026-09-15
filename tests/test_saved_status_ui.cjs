// Focused DOM boundary: a reopened session cannot borrow an active counter.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const elements=new Map();
const document={getElementById(id){if(!elements.has(id))elements.set(id,{value:'',options:[],firstChild:{},textContent:'',innerHTML:''});return elements.get(id)},querySelectorAll(){return []}};
const source=fs.readFileSync('app/dashboard/static/app.js','utf8');
const context=vm.createContext({document,setTimeout(){},console});
vm.runInContext(source.slice(0,source.indexOf("document.querySelectorAll('.tab').forEach(b=>b.onclick")),context);
vm.runInContext(`renderTables=()=>{};renderCoverage=()=>{};
mode='historical';savedSid='older';state={mode:'synthetic',state:'scanning',messages:999};
view={receipts:22,messages:7,session:{id:'older',saved_status:{label:'Saved with capture gaps',origin:'Captured from a live feed',current_status:'Saved observations—not live',explanation:'Recorded gaps',unprocessed:32,rejected:null,lifecycle:'complete'}}};render();`,context);
assert.equal(elements.get('receipt-count').textContent,'22 retained observations · 7 stream messages');
assert.match(elements.get('saved-summary').innerHTML,/Unprocessed: 32 · Rejected: Unknown/);
vm.runInContext('view.messages=null;render()',context);
assert.equal(elements.get('receipt-count').textContent,'22 retained observations · Unknown stream messages');
vm.runInContext(`mode='synthetic';savedSid=null;view={receipts:4};render()`,context);
assert.equal(elements.get('receipt-count').textContent,'4 retained observations · 999 stream messages');
console.log('PASS: saved known/unknown message counts, shared summary, active own counter');
