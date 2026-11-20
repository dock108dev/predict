import {bookName} from './pregame-labels.js';

let active,nextId=0;
export function dismissEVPreview(){active?.();}
export function addEVPreview(button,cell,row){
 let preview;
 const hide=()=>{if(preview?.matches(':popover-open'))preview.hidePopover();if(active===hide)active=null;};
 const show=()=>{
  if(button.getAttribute('aria-expanded')==='true'||!button.isConnected)return;
  dismissEVPreview();
  if(!preview){
   const reference=row.reference||{},prices=Array.isArray(reference.prices)?reference.prices:[];
   const selected=prices.find(price=>price.side===reference.selected_outcome);
   preview=document.createElement('div');preview.className='ev-preview';preview.setAttribute('popover','manual');preview.setAttribute('role','tooltip');
   preview.id='ev-reference-'+(++nextId);
   const title=document.createElement('strong');title.textContent='EV reference';preview.append(title);
   for(const [label,value]of [['Book',bookName(reference.book)||'Unavailable'],['Quoted odds',selected?.price_american??'Unavailable'],['Fair odds (no vig)',row.display?.fair_odds??'Unavailable']]){
    const line=document.createElement('div'),name=document.createElement('span'),number=document.createElement('b');name.textContent=label;number.textContent=value;line.append(name,number);preview.append(line);
   }
   cell.append(preview);button.setAttribute('aria-describedby',preview.id);
  }
  preview.showPopover();
  const box=button.getBoundingClientRect(),gap=8;
  preview.style.left=Math.max(8,Math.min(innerWidth-preview.offsetWidth-8,box.right-preview.offsetWidth))+'px';
  const below=box.bottom+gap,above=box.top-preview.offsetHeight-gap;
  preview.style.top=Math.max(8,below+preview.offsetHeight<=innerHeight-8?below:above)+'px';
  active=hide;
 };
 button.addEventListener('pointerenter',event=>{if(event.pointerType==='mouse')show();});
 button.addEventListener('pointerleave',hide);
 button.addEventListener('focus',show);
 button.addEventListener('blur',hide);
 button.addEventListener('click',hide);
}
document.addEventListener('scroll',dismissEVPreview,true);
window.addEventListener('resize',dismissEVPreview);
document.addEventListener('close',dismissEVPreview,true);
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&active){event.preventDefault();event.stopImmediatePropagation();dismissEVPreview();}},true);
