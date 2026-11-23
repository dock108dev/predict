import {applyTheme} from './desk-preferences.js';

export const workspaceNavigation = Object.freeze([
 {href:'/data', label:'Data'},
 {href:'/experiments', label:'Experiments'},
 {href:'/settings', label:'Settings'},
]);
for (const nav of document.querySelectorAll('[data-workspace-nav]')) {
 nav.replaceChildren(...workspaceNavigation.map(({href,label})=>{
  const link=document.createElement('a');link.href=href;link.textContent=label;
  if(location.pathname===href)link.setAttribute('aria-current','page');return link;
 }));
}
applyTheme();
