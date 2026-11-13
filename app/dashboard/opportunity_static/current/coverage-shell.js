import './ui-common.js';
const nav = window.PredictUI.adminNav();
nav.querySelector('[aria-current]')?.removeAttribute('aria-current');
nav.querySelector('a[href="/admin?section=coverage"]')?.setAttribute('aria-current', 'page');
document.querySelector('main').prepend(nav);
window.PredictUI.carry(new URLSearchParams(location.search).get('result_id'));
