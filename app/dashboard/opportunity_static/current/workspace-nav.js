import {applyTheme} from './desk-preferences.js';
import {coverageContext, coverageURL} from './mens-d1-coverage.js';

export const workspaceNavigation = Object.freeze([
 {href:'/research', label:'Research'},
 {href:'/data', label:'Data'},
 {href:'/settings', label:'Settings'},
]);
export function renderWorkspaceNavigation() {
 const query = new URLSearchParams(location.search), coverage = query.get('scope') === 'mens-d1' || query.get('evidence') === 'mens-d1';
 const destinations = coverage ? {
  '/data':coverageURL(query),
  '/research':'/research?' + new URLSearchParams({section:'experiments', ...coverageContext(query)}),
  '/settings':'/settings?' + new URLSearchParams(coverageContext(query)) + '#mens-d1-jobs',
 } : {};
 for (const nav of document.querySelectorAll('[data-workspace-nav]')) {
  nav.replaceChildren(...workspaceNavigation.map(({href,label})=>{
   const link=document.createElement('a');link.href=destinations[href] || href;link.textContent=label;
   if(location.pathname===href)link.setAttribute('aria-current','page');return link;
  }));
 }
}
renderWorkspaceNavigation();
window.addEventListener('popstate', renderWorkspaceNavigation);
window.addEventListener('workspace-context', renderWorkspaceNavigation);
for (const brand of document.querySelectorAll('.masthead .brand')) brand.href='/research';
applyTheme();
