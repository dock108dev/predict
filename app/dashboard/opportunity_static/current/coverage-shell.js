import './ui-common.js';
const main=document.querySelector('main');main.prepend(window.PredictUI.adminNav());window.PredictUI.carry(new URLSearchParams(location.search).get('result_id'));
