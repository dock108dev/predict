// Linux touch scrolling can deliver pointerup without synthesizing a click.
// Close on that completed touch, retaining native click for mouse and keyboard.
let releaseGuard;
function guardCompatibilityEvents(){
 releaseGuard?.();
 const stop=event=>{
  // Keyboard, assistive activation, and element.click() have zero click detail.
  if(event.type==='click'&&event.detail===0){clear();return;}
  // A real new mouse/touch/keyboard action clears this guard before activation.
  // A positive-detail mouse event arriving without one is the touch's compatibility event.
  if(event.detail>0||event.pointerType==='touch'||event.sourceCapabilities?.firesTouchEvents){
   event.preventDefault();event.stopImmediatePropagation();
  }
  if(event.type==='click')clear();
 };
 const clear=()=>{
  for(const type of ['mousedown','mouseup','click'])document.removeEventListener(type,stop,true);
  document.removeEventListener('pointerdown',clear,true);
  document.removeEventListener('keydown',clear,true);
  if(releaseGuard===clear)releaseGuard=null;
 };
 for(const type of ['mousedown','mouseup','click'])document.addEventListener(type,stop,true);
 document.addEventListener('pointerdown',clear,true);
 document.addEventListener('keydown',clear,true);
 releaseGuard=clear;
}
export function bindDismissControl(button,close,isOpen){
 button.onclick=close;
 button.addEventListener('pointerup',event=>{
  if(event.pointerType!=='touch'||!event.isPrimary||!isOpen())return;
  const box=button.getBoundingClientRect();
  if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)return;
  // A canceled pan has no pointerup. Release outside the captured button is ignored.
  event.preventDefault();guardCompatibilityEvents();close();
 });
}
export function bindDialogClose(button,dialog,close=()=>dialog.close()){
 bindDismissControl(button,close,()=>dialog.open);
}
