import {addEVPreview,dismissEVPreview} from './ev-preview.js';
import {explanation} from './pregame-explanation.js';
export {explanation} from './pregame-explanation.js';
import {bindDismissControl} from './dialog-close.js';
// Explanations use the inspected calculation's cashflows, never current board state.
let nextId=0;
let activeMath;
const dismissMath=()=>activeMath?.close();
document.addEventListener('scroll',event=>{
 if(!activeMath||activeMath.popover.contains(event.target))return;
 const target=event.target===document?document.scrollingElement:event.target;
 const before=activeMath.scrollOffsets.get(target);
 // Focusing a lower comparison value can queue a scroll event before opening.
 // Dismiss only for movement after the popover's actual opening position.
 if(!before||before[0]!==target.scrollTop||before[1]!==target.scrollLeft)dismissMath();
},true);
window.addEventListener('resize',dismissMath);
document.addEventListener('close',event=>{if(activeMath&&event.target.contains(activeMath.button))dismissMath();},true);
document.addEventListener('focusin',event=>{if(activeMath&&event.target!==activeMath.button&&!activeMath.popover.contains(event.target))dismissMath();});
document.addEventListener('keydown',event=>{
 if(event.key==='Escape'&&activeMath?.popover.matches(':popover-open')){event.preventDefault();event.stopImmediatePropagation();activeMath.close(true);}
},true);
export function addMath(cell,row,kind){
 const value=cell.querySelector(':scope > span:not(.mobile-label)');
 const button=document.createElement('button');button.type='button';button.className='math-trigger';button.textContent=value.textContent;
 button.dataset.focusKey=row.id+'-'+kind;
 const lines=explanation(row,kind);
 button.setAttribute('aria-label',lines[0]+': '+value.textContent+'. Show calculation');button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-expanded','false');
 value.replaceWith(button);
 if(kind==='ev')addEVPreview(button,cell,row);
 let popover;
 const close=(restore=false)=>{if(popover?.matches(':popover-open'))popover.hidePopover();button.setAttribute('aria-expanded','false');if(activeMath?.button===button)activeMath=null;if(restore&&button.isConnected)button.focus({preventScroll:true});};
 // The board needs the numeric controls now; build explanatory content only on demand.
 const ensurePopover=()=>{
  if(popover)return popover;
  popover=document.createElement('div');popover.className='math-popover';popover.id='math-'+(++nextId);popover.setAttribute('popover','auto');popover.setAttribute('role','dialog');
  const heading=document.createElement('div');heading.className='math-heading';
  const title=document.createElement('strong');title.id=popover.id+'-title';title.textContent=lines[0];popover.setAttribute('aria-labelledby',title.id);
  const done=document.createElement('button');done.type='button';done.className='math-close';done.textContent='Close';done.setAttribute('aria-label','Close calculation');heading.append(title,done);
  const body=document.createElement('div');body.className='math-body';
  lines.slice(1).forEach(line=>{const p=document.createElement('p');p.textContent=line;body.append(p);});
  const note=document.createElement('small');note.textContent='Inputs shown rounded; calculations use the stored exact values.';body.append(note);popover.append(heading,body);
  cell.append(popover);button.setAttribute('aria-controls',popover.id);
  bindDismissControl(done,()=>close(true),()=>popover.matches(':popover-open'));
  popover.addEventListener('toggle',event=>{if(event.newState==='closed'){button.setAttribute('aria-expanded','false');if(activeMath?.popover===popover)activeMath=null;}});
  return popover;
 };
 button.onclick=()=>{
  dismissEVPreview();
  if(popover?.matches(':popover-open')){close(true);return;}
  dismissMath();if(!button.isConnected)return;ensurePopover().showPopover();
  const header=button.closest('dialog')?.querySelector('.dialog-heading');
  const safeTop=Math.max(12,(header?.getBoundingClientRect().bottom||0)+8);
  popover.style.maxHeight=Math.max(40,innerHeight-safeTop-12)+'px';
  const box=button.getBoundingClientRect();
  popover.style.left=Math.max(12,Math.min(innerWidth-popover.offsetWidth-12,box.right-popover.offsetWidth))+'px';
  const below=box.bottom+8,above=box.top-popover.offsetHeight-8;
  popover.style.top=Math.max(safeTop,Math.min(innerHeight-popover.offsetHeight-12,below+popover.offsetHeight<=innerHeight-12?below:above))+'px';
  const scrollOffsets=new Map();for(let parent=button.parentElement;parent;parent=parent.parentElement)scrollOffsets.set(parent,[parent.scrollTop,parent.scrollLeft]);
  scrollOffsets.set(document.scrollingElement,[document.scrollingElement.scrollTop,document.scrollingElement.scrollLeft]);
  button.setAttribute('aria-expanded','true');activeMath={button,popover,close,scrollOffsets};
 };
}
