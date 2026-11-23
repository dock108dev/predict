"""Saved-bookmark journeys keep their owning snapshot and valid zero prices."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_saved_capture_uses_explicit_owner_and_keeps_zero_source_price():
    script = r"""
import assert from 'node:assert/strict';
import {renderSavedCapture} from './app/dashboard/opportunity_static/current/data-captures.js';
class Element {
 constructor(tag) {this.tag=tag;this.children=[];this.dataset={};this.attributes={};this.textContent='';}
 append(...items) {this.children.push(...items);}
 replaceChildren(...items) {this.children=[...items];}
 setAttribute(key,value) {this.attributes[key]=value;}
 removeAttribute(key) {delete this.attributes[key];}
}
globalThis.document={createElement:tag=>new Element(tag)};
const allText=element=>element.textContent+' '+element.children.map(item=>typeof item==='string'?item:allText(item)).join(' ');
const row={id:'exact-bet',venue:'fixture-book',original:{value:0},game_title:'Fixture game',market:{market:'total',line:'150'},side:'over',times:{source_at:'2026-11-22T21:00:00Z',received_at:'2026-11-22T21:00:01Z'}};
const calls=[];
globalThis.fetch=async url=>{calls.push(String(url));return {ok:true,json:async()=>String(url).includes('/details')?{row,result_id:'saved-one',captured_at:'2026-11-22T21:00:01Z'}:{rows:[row],id:'saved-one',total:1,captured_at:'2026-11-22T21:00:01Z'}};};
function context() {const dialog=new Element('dialog');dialog.open=false;dialog.showModal=()=>{dialog.open=true;};return {inspectRoot:new Element('section'),inspectTitle:new Element('h2'),dialog};}
const root=new Element('section'),ctx=context();
let cleanup=await renderSavedCapture(root,new URLSearchParams({result_id:'saved-one',game:'game-one',selection:'exact-bet'}),ctx);
assert.equal(new URL(calls[0],'http://local').pathname,'/api/comparison-snapshot','manual capture+game must stay with its snapshot owner');
assert.equal(new URL(calls[1],'http://local').pathname,'/api/comparison-snapshot/details');
assert.match(allText(ctx.inspectRoot),/Source price\s+0/,'a received zero price must not become unavailable');
cleanup();calls.length=0;
cleanup=await renderSavedCapture(new Element('section'),new URLSearchParams({game_capture:'automatic-one',game_key:'game-one',selection:'exact-bet'}),context());
assert.equal(new URL(calls[0],'http://local').pathname,'/api/odds-replay');
assert.equal(new URL(calls[0],'http://local').searchParams.get('dataset'),'retained');
assert.equal(new URL(calls[1],'http://local').searchParams.get('result_id'),'automatic-one');
cleanup();calls.length=0;
cleanup=await renderSavedCapture(new Element('section'),new URLSearchParams({dataset:'frozen',game_key:'game-one',selection:'exact-bet'}),context());
assert.equal(new URL(calls[0],'http://local').searchParams.get('dataset'),'frozen');
cleanup();
"""
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
