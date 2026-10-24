const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const path = require('node:path');
const {fixture} = require('./current_board_fixture.cjs');
const copy = v => JSON.parse(JSON.stringify(v));
(async () => {
  const {checkBoard,defaults} = await import(pathToFileURL(path.resolve('app/dashboard/opportunity_static/current/board-client.js')).href);
  const original = copy(fixture.odds);
  const options = {...defaults,view:'odds',filter:'all',game:original.game_key};
  checkBoard(original,options);
  const wire = copy(original);
  const names = [...new Set(wire.prices.flatMap(q=>Object.keys(q)).filter(k=>!['quote_id','quote_revision','field_refs'].includes(k)))].sort();
  wire.price_key_pool=names; wire.price_field_pool=[];
  wire.prices=wire.prices.map(q=>{
    const row={quote_id:q.quote_id,quote_revision:q.quote_revision,field_refs:{}};
    for (const [k,v] of Object.entries(q)) {
      if (['quote_id','quote_revision'].includes(k)) continue;
      if(k==='times') {row.field_refs[String(names.indexOf(k))]=wire.price_field_pool.length;wire.price_field_pool.push(copy(v));}
      else row[String(names.indexOf(k))]=v;
    }
    return row;
  });
  const valid=copy(wire);checkBoard(valid,options);assert.deepEqual(valid,original);
  for (const mutate of [v=>v.price_key_pool.push(v.price_key_pool[0]),v=>v.price_key_pool[0]='__proto__',v=>v.prices[0]['9999']={},v=>v.prices[0].field_refs['9999']=0]) {
    const bad=copy(wire);mutate(bad);assert.throws(()=>checkBoard(bad,options));
  }
  const financial=copy(fixture.ev);const foptions={...defaults,view:'ev',filter:financial.filter,game:financial.game_key};
  checkBoard(financial,foptions);
  const packed=copy(financial);packed.financial_field_pool=[];
  for(const row of packed.rows){row.financial_field_refs={};for(const key of ['freshness','details']) {
    if(row[key]===undefined)continue;
    row.financial_field_refs[key]=packed.financial_field_pool.length;packed.financial_field_pool.push(copy(row[key]));delete row[key];
  }}
  const restored=copy(packed);checkBoard(restored,foptions);assert.deepEqual(restored,financial);
  for(const index of [-1,true,packed.financial_field_pool.length]) {
    const bad=copy(packed);bad.rows[0].financial_field_refs.freshness=index;assert.throws(()=>checkBoard(bad,foptions));
  }
  console.log('PASS exact wide-board decoding and crossed-reference refusals');
})().catch(e=>{console.error(e);process.exitCode=1;});
// Cross-language byte-for-byte logical reconstruction of the refused retained board.
(async()=>{
 const fs=require('node:fs'),zlib=require('node:zlib'),cp=require('node:child_process');
 const {checkBoard,defaults}=await import(pathToFileURL(path.resolve('app/dashboard/opportunity_static/current/board-client.js')).href);
 const old=JSON.parse(zlib.gunzipSync(fs.readFileSync('tests/fixtures/wide-spread-board-20261022.json.gz')));
 const original=copy(old),options={...defaults,view:'odds',filter:'all',game:old.game_key};
 checkBoard(original,options);
 const wire=JSON.parse(cp.execFileSync(process.env.PYTHON || 'python3',['-c',
  'import json,sys; from app.dashboard.comparison_board import compact_price_fields; print(json.dumps(compact_price_fields(json.load(sys.stdin))))'],{input:JSON.stringify(old),maxBuffer:4*1024*1024}));
 const restored=copy(wire);checkBoard(restored,options);assert.deepEqual(restored,original);
 for(const names of [['x','x'],['__proto__'],[true],{}]){const bad=copy(wire);bad.price_object_keys=names;assert.throws(()=>checkBoard(bad,options));}
 for(const key of ['-1','01','999999','1.0','x']) {
  const bad=copy(wire);const field=Object.keys(bad.prices[0]).find(k=>k!=='field_refs' && bad.prices[0][k] && typeof bad.prices[0][k]==='object' && !Array.isArray(bad.prices[0][k]));
  bad.prices[0][field][key]='crossed';assert.throws(()=>checkBoard(bad,options));
 }
 const bad=copy(wire);bad.prices[0].quote_revision='crossed';assert.throws(()=>checkBoard(bad,options));
 console.log('PASS retained 114-price spread Python/browser equality and crossed identities');
})().catch(e=>{console.error(e);process.exitCode=1;});
