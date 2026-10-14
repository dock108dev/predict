'use strict';
class Element{
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attributes={};this.style={};this._text='';this.className='';this.scrollTop=0;this.hidden=false;this.value='';this.id='';this.open=false;
    this.classList={add:(...names)=>{this.className=[...new Set([...this.className.split(' ').filter(Boolean),...names])].join(' ');},remove:(...names)=>{this.className=this.className.split(' ').filter(x=>!names.includes(x)).join(' ');},contains:name=>this.className.split(' ').includes(name),toggle:(name,yes)=>{if(yes??!this.classList.contains(name)){this.classList.add(name);return true;}this.classList.remove(name);return false;}};
  }
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}
  get parentElement(){return this.parentNode||null;}
  append(...nodes){for(const node of nodes){node.remove();this.children.push(node);node.parentNode=this;}}
  replaceChildren(...nodes){for(const node of this.children)node.parentNode=null;this.children=[];this._text='';this.append(...nodes);}
  insertBefore(node,before){node.remove();const i=before?this.children.indexOf(before):this.children.length;this.children.splice(i<0?this.children.length:i,0,node);node.parentNode=this;}
  remove(){if(this.parentNode){const i=this.parentNode.children.indexOf(this);if(i>=0)this.parentNode.children.splice(i,1);}this.parentNode=null;}
  replaceWith(node){const parent=this.parentNode;if(parent){parent.insertBefore(node,this);this.remove();}}
  setAttribute(key,value){this.attributes[key]=String(value);}
  removeAttribute(key){delete this.attributes[key];}
  toggleAttribute(key,on){if(on)this.setAttribute(key,'');else this.removeAttribute(key);}
  matches(selector){if(selector.startsWith('#'))return this.id===selector.slice(1);if(selector.startsWith('.'))return this.classList.contains(selector.slice(1));if(selector==='details[open]')return this.tagName==='DETAILS'&&this.open;if(selector.startsWith('[data-')){const key=selector.slice(6,-1).replace(/-([a-z])/g,(_,x)=>x.toUpperCase());return this.dataset[key]!==undefined;}return this.tagName===selector.toUpperCase();}
  querySelectorAll(selectors){const parts=selectors.split(',');const result=[];const visit=node=>{for(const child of node.children){if(parts.some(x=>child.matches(x)))result.push(child);visit(child);}};visit(this);return result;}
  querySelector(selector){if(selector.startsWith('#')&&selector.includes(':'))throw new SyntaxError('Unescaped native identity is not a CSS selector');return this.querySelectorAll(selector)[0]||null;}
  focus(){document.activeElement=this;}
  contains(other){return other===this||this.children.some(x=>x.contains(other));}
  getClientRects(){return [1];}
  getBoundingClientRect(){return {top:0,bottom:100};}
  addEventListener(type,fn){this['on'+type]=fn;}
}
global.document={activeElement:null,body:new Element('body'),createElement:tag=>new Element(tag),getElementById:id=>{const find=node=>node.id===id?node:node.children.map(find).find(Boolean);return find(document.body);}};

module.exports={Element};
