const kinds = {r:'Table', p:'Partitioned table', v:'View', m:'Materialized view', S:'Sequence', f:'Foreign table'};
const $ = id => document.getElementById('db-' + id);
const isStorageObject = item => item.partition || item.kind === 'S';

function element(tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
}

async function read(view, query = {}) {
  const params = new URLSearchParams(query);
  const response = await fetch('/api/admin/database/' + view + (params.size ? '?' + params : ''));
  if (response.status === 404 && view === 'catalog') {
    throw Error('The database browser is available in the local PostgreSQL app.');
  }
  const result = await response.json();
  if (!response.ok) throw Error(result.error || 'Local database unavailable.');
  return result;
}

function matrix(label, columns) {
  const scroll = element('div');
  scroll.className = 'db-scroll';
  scroll.tabIndex = 0;
  scroll.setAttribute('role', 'region');
  scroll.setAttribute('aria-label', label);
  const table = element('table');
  table.className = 'db-table';
  const head = table.createTHead().insertRow();
  for (const name of columns) {
    const th = element('th', name);
    th.scope = 'col';
    head.append(th);
  }
  scroll.append(table);
  return [scroll, table.createTBody()];
}

function definitions(content, title, entries) {
  const group = element('details');
  group.append(element('summary', title + ' (' + entries.length + ')'));
  if (!entries.length) group.append(element('p', 'None.'));
  for (const entry of entries) {
    group.append(element('strong', entry.name), element('pre', entry.definition));
  }
  content.append(group);
}

function showStructure(data) {
  const content = $('content');
  const [scroll, body] = matrix('Column definitions', ['Column', 'Data type', 'Nullable', 'Default or expression', 'Comment']);
  for (const column of data.columns) {
    const row = body.insertRow();
    for (const value of [column.name, column.type, column.nullable ? 'Yes' : 'No',
      column.identity ? 'Identity (' + (column.identity === 'a' ? 'always' : 'by default') + ')' :
        column.generated ? 'Generated: ' + column.expression : column.expression ?? '—',
      column.comment ?? '—']) {
      row.insertCell().append(element('code', value));
    }
  }
  if (data.comment) content.append(element('p', data.comment));
  if (data.parents.length) content.append(element('p', 'Parent: ' + data.parents.map(p => p.schema + '.' + p.name).join(', ')));
  if (data.partition_key) content.append(element('p', 'Partition key: ' + data.partition_key));
  if (data.partition_bound) content.append(element('p', 'Partition bound: ' + data.partition_bound));
  content.append(scroll);
  definitions(content, 'Constraints', data.constraints);
  definitions(content, 'Indexes', data.indexes);
  if (data.view_sql) {
    const definition = element('details');
    definition.append(element('summary', 'View definition'), element('pre', data.view_sql));
    content.append(definition);
  }
}

export function mountDatabase() {
  const schema = $('schema'), search = $('search'), object = $('object');
  const storage = $('storage');
  const dialog = $('cell-dialog');
  const locationState = new URLSearchParams(location.search);
  let relations = [], visible = [], relation = null, busy = false, cellBusy = false;
  storage.checked = locationState.get('storage') === 'true';
  let mode = locationState.get('view') === 'structure' ? 'structure' : 'rows';
  let currentPage, cellSelection, cellPart;

  function controls() {
    $('refresh').disabled = busy;
    schema.disabled = busy || !schema.options.length;
    search.disabled = busy;
    storage.disabled = busy || !schema.options.length;
    object.disabled = busy || !visible.length;
    $('rows').disabled = busy || !relation?.readable;
    $('structure').disabled = busy;
    $('previous').disabled = busy || currentPage?.previous_offset == null;
    $('next').disabled = busy || currentPage?.next_offset == null;
  }

  function fillObjects(selected) {
    const term = search.value.trim().toLowerCase();
    visible = relations.filter(item => item.schema === schema.value && (storage.checked || !isStorageObject(item)) &&
      (item.name + ' ' + kinds[item.kind] + (item.partition ? ' partition' : '')).toLowerCase().includes(term));
    object.replaceChildren(new Option(storage.checked ? 'Choose an object' : 'Choose a table or view', ''));
    for (const [index, item] of visible.entries()) {
      object.add(new Option(item.name + ' · ' + kinds[item.kind] + (item.partition ? ' partition' : ''), String(index)));
    }
    const found = visible.findIndex(item => item.name === selected);
    object.value = found === -1 ? '' : String(found);
    if (!schema.value) $('status').textContent = 'No project schemas are available.';
    else if (!visible.length) $('status').textContent = term ? 'No results match your search.' :
      storage.checked ? 'This schema has no database objects.' : 'This schema has no top-level tables or views.';
    else $('status').textContent = term ? visible.length + (visible.length === 1 ? ' match' : ' matches') : '';
  }

  function saveSelection() {
    const url = new URL(location.href);
    for (const [key, value] of [
      ['schema', schema.value], ['object', relation?.name], ['view', relation && mode],
      ['storage', storage.checked && 'true']
    ]) {
      if (value) url.searchParams.set(key, value);
      else url.searchParams.delete(key);
    }
    history.replaceState(null, '', url);
  }

  function cellControls() {
    $('cell-previous').disabled = cellBusy || cellPart?.previous_start == null;
    $('cell-next').disabled = cellBusy || cellPart?.next_start == null;
  }

  async function readCell(start) {
    const selected = cellSelection;
    cellBusy = true;
    cellControls();
    $('cell-status').textContent = 'Reading value…';
    try {
      const {preview, ...query} = selected;
      const part = await read('cell', {...query, start});
      if (!dialog.open || cellSelection !== selected) return;
      if (cellPart ? cellPart.fingerprint !== part.fingerprint : !part.text?.startsWith(preview)) {
        throw Error('The value at this row position changed. Close this dialog and reload the rows.');
      }
      cellPart = part;
      $('cell-value').textContent = part.text;
      $('cell-status').textContent = 'Characters ' + (part.start + 1).toLocaleString() + '–' + (part.start + [...part.text].length).toLocaleString() +
        (part.next_start === null ? ' · End of value' : ' · More available') +
        '. Reads use the current row position.';
    } catch (error) {
      if (dialog.open && cellSelection === selected) $('cell-status').textContent = error.message;
    } finally {
      cellBusy = false;
      cellControls();
    }
  }

  function openCell(rowOffset, column, preview) {
    if (busy || cellBusy) return;
    cellSelection = {schema:relation.schema, name:relation.name, offset:rowOffset, column, preview};
    cellPart = null;
    $('cell-title').textContent = column + ' · row ' + (rowOffset + 1).toLocaleString();
    $('cell-value').textContent = '';
    dialog.showModal();
    void readCell(0);
  }

  function showRows(data) {
    const content = $('content');
    const [scroll, body] = matrix('Stored rows', ['Row', ...data.columns]);
    for (const [index, values] of data.rows.entries()) {
      const rowOffset = data.offset + index;
      const row = body.insertRow();
      const position = element('th', (rowOffset + 1).toLocaleString());
      position.scope = 'row';
      row.append(position);
      for (const [i, value] of values.entries()) {
        const cell = row.insertCell();
        if (value === null) cell.append(element('em', 'NULL'));
        else if (!value.text) cell.append(element('em', '(empty string)'));
        else cell.append(element('code', value.text + (value.more ? '…' : '')));
        if (value?.more) {
          const button = element('button', 'Inspect value');
          button.type = 'button';
          button.setAttribute('aria-label', 'Inspect value in ' + data.columns[i] + ', row ' + (rowOffset + 1));
          button.onclick = () => openCell(rowOffset, data.columns[i], value.text);
          cell.append(button);
        }
      }
    }
    if (data.rows.length) content.append(scroll);
    else content.append(element('p', data.offset ? 'No rows at this position. Go back to an earlier page.' : 'This object has no rows.'));
    const order = data.primary_key.length ? 'Ordered by primary key: ' + data.primary_key.join(', ') : 'No primary key; row order may vary.';
    $('read-status').textContent = (data.rows.length ?
      'Rows ' + (data.offset + 1).toLocaleString() + '–' + (data.offset + data.rows.length).toLocaleString() + ' · ' : '') +
      order + ' Live reads can shift between pages.';
    $('paging').hidden = data.previous_offset === null && data.next_offset === null;
  }

  async function inspect(offset = 0) {
    $('selection').hidden = !relation;
    $('paging').hidden = true;
    $('content').replaceChildren();
    currentPage = null;
    if (relation && !relation.readable) mode = 'structure';
    saveSelection();
    if (!relation) {
      controls();
      return;
    }
    busy = true;
    controls();
    $('object-title').textContent = relation.schema + '.' + relation.name;
    $('object-kind').textContent = kinds[relation.kind] + (relation.partition ? ' partition' : '') +
      (relation.readable ? '' : ' · Structure only');
    $('rows').setAttribute('aria-pressed', String(mode === 'rows'));
    $('structure').setAttribute('aria-pressed', String(mode === 'structure'));
    $('read-status').textContent = mode === 'rows' ? 'Reading rows…' : 'Reading structure…';
    try {
      const query = {schema:relation.schema, name:relation.name};
      if (mode === 'rows') {
        currentPage = await read('rows', {...query, offset});
        showRows(currentPage);
      } else {
        const data = await read('structure', query);
        $('read-status').textContent = data.columns.length + ' columns';
        showStructure(data);
      }
    } catch (error) {
      $('read-status').textContent = error.message;
      if (mode === 'rows' && offset) {
        currentPage = {previous_offset:0};
        $('paging').hidden = false;
      }
    } finally {
      busy = false;
      controls();
    }
  }

  async function load(preferredSchema, preferredObject) {
    busy = true;
    controls();
    $('status').textContent = 'Reading database catalog…';
    try {
      const data = await read('catalog');
      relations = data.relations;
      schema.replaceChildren(...data.schemas.map(name => new Option(name, name)));
      schema.value = data.schemas.includes(preferredSchema) ? preferredSchema :
        data.schemas.includes('public') ? 'public' : (data.schemas[0] ?? '');
      $('catalog-summary').textContent = data.database + ' · Read only';
      const selected = relations.find(item => item.schema === preferredSchema && item.name === preferredObject);
      if (selected && isStorageObject(selected)) storage.checked = true;
      fillObjects(selected?.name);
      relation = object.value ? visible[Number(object.value)] : null;
    } catch (error) {
      $('status').textContent = error.message;
      busy = false;
      controls();
      return;
    }
    busy = false;
    await inspect();
  }

  $('refresh').onclick = () => load(schema.value, relation?.name);
  schema.onchange = () => { fillObjects(); relation = null; void inspect(); };
  function filterObjects() {
    fillObjects(relation?.name);
    if (!object.value && relation) { relation = null; void inspect(); }
    else { saveSelection(); controls(); }
  }
  search.oninput = filterObjects;
  storage.onchange = filterObjects;
  object.onchange = () => { relation = object.value ? visible[Number(object.value)] : null; void inspect(); };
  $('rows').onclick = () => { mode = 'rows'; void inspect(); };
  $('structure').onclick = () => { mode = 'structure'; void inspect(); };
  $('previous').onclick = () => inspect(currentPage.previous_offset);
  $('next').onclick = () => inspect(currentPage.next_offset);
  $('cell-previous').onclick = () => readCell(cellPart.previous_start);
  $('cell-next').onclick = () => readCell(cellPart.next_start);
  void load(locationState.get('schema'), locationState.get('object'));
}
