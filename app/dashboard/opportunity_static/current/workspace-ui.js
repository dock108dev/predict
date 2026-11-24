import {number} from './workspace-format.js';

export const byId = id => document.getElementById(id);
export const text = value => value == null || value === '' ? 'Unknown' : String(value);
export const label = value => text(value).replaceAll('_', ' ');
export const count = value => value == null ? 'Unknown' : Number(value).toLocaleString('en-US');
const currency = new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'});
export const usd = value => number(value) == null ? 'Unknown' : currency.format(number(value));
export const pct = value => number(value) == null ? 'Unavailable' : (100 * number(value)).toFixed(2) + '%';
const eastern = new Intl.DateTimeFormat('en-US', {
  timeZone:'America/New_York', month:'short', day:'numeric', year:'numeric',
  hour:'numeric', minute:'2-digit', timeZoneName:'short',
});
export function time(value) {
  const date = new Date(value);
  return value && Number.isFinite(date.getTime()) ? eastern.format(date) : 'Not recorded';
}
export function node(tag, value, className) {
  const element = document.createElement(tag);
  if (value !== undefined) element.textContent = value;
  if (className) element.className = className;
  return element;
}
export function link(title, href, className) {
  const element = node('a', title, className);
  element.href = href;
  return element;
}
export function card(title, action = null) {
  const element = node('article', undefined, 'workspace-card');
  const heading = node('h2', action ? undefined : title);
  if (action) heading.append(action);
  element.append(heading);
  return element;
}
export function list(values, render = value => node('li', value)) {
  const element = node('ul');
  element.append(...values.map(render));
  return element;
}
export function pairs(values, className = 'research-detail-grid') {
  const element = node('dl', undefined, className);
  for (const [key, value] of Object.entries(values)) {
    const dt = node('dt', key), dd = node('dd', text(value));
    if (className === 'workspace-stats') {
      const group = node('div');
      group.append(dt, dd);
      element.append(group);
    } else element.append(dt, dd);
  }
  return element;
}
export function details(title, value) {
  const element = node('details');
  element.append(node('summary', title), node('pre', JSON.stringify(value ?? null, null, 2)));
  return element;
}
export function table(headers, rows) {
  const scroll = node('div', undefined, 'catalog-scroll');
  const element = node('table', undefined, 'catalog-table workspace-table');
  const head = node('thead'), titles = node('tr'), body = node('tbody');
  for (const title of headers) {
    const heading = node('th', title);
    heading.scope = 'col';
    titles.append(heading);
  }
  head.append(titles);
  for (const row of rows) {
    const tr = node('tr');
    for (const [index, value] of row.entries()) {
      const td = node('td');
      td.dataset.label = headers[index];
      if (value instanceof Node) td.append(value);
      else td.textContent = text(value);
      tr.append(td);
    }
    body.append(tr);
  }
  element.append(head, body);
  scroll.append(element);
  return scroll;
}
export function stack(primary, secondary) {
  const element = node('div');
  element.append(node('strong', primary));
  if (secondary) element.append(node('small', secondary));
  return element;
}
export async function readJSON(url, options = {}) {
  const response = await fetch(url, {cache:'no-store', signal:AbortSignal.timeout(60000), ...options});
  const value = await response.json().catch(() => null);
  if (!response.ok || !value) {
    throw Error(value?.error || value?.message || `Stored evidence could not be read (${response.status}).`);
  }
  return value;
}
