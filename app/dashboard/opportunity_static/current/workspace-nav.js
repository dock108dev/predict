import {applyTheme} from './desk-preferences.js';

export const workspaceNavigation = Object.freeze([
 {href:'/research', label:'Research'},
 {href:'/data', label:'Data'},
 {href:'/settings', label:'Settings'},
]);
for (const nav of document.querySelectorAll('[data-workspace-nav]')) {
 nav.replaceChildren(...workspaceNavigation.map(({href,label})=>{
  const link=document.createElement('a');link.href=href;link.textContent=label;
  if(location.pathname===href)link.setAttribute('aria-current','page');return link;
 }));
}
for (const brand of document.querySelectorAll('.masthead .brand')) brand.href='/research';
applyTheme();
