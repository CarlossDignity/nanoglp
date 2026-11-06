import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join, dirname } from 'node:path';
import { build } from 'esbuild';
import React from 'react';
import { create, act } from 'react-test-renderer';

// Real Planning component + real API download helper; Axios adapter is the HTTP boundary.
const root = dirname(fileURLToPath(import.meta.url));
const temp = await mkdtemp(join(root, '.planning-export-'));
after(() => rm(temp, { recursive: true, force: true }));
const entry = join(temp, 'planning.mjs');
await build({ stdin: { contents: `export { default as Planning } from '../src/pages/Planning.jsx';
  export { default as api } from '../src/services/api.js';`, resolveDir: root }, outfile: entry,
  bundle: true, platform: 'node', format: 'esm', packages: 'external', define: { 'import.meta.env': '{}' },
  plugins: [{ name: 'planning-boundaries', setup(b) {
    b.onResolve({ filter: /state\/AuthContext$|^react-router-dom$/ }, args => ({ path: args.path, namespace: 'fixture' }));
    b.onLoad({ filter: /.*/, namespace: 'fixture' }, ({ path }) => ({ contents: path.endsWith('AuthContext')
      ? 'export const useAuth = () => ({ isReadOnly: true, role: "QA", isExecutive: false });'
      : 'export const useLocation = () => ({search: "", state: null}); export const useNavigate = () => () => {};' }));
  } }],
});
const { Planning, api } = await import(pathToFileURL(entry));
const text = node => node.children.map(c => typeof c === 'string' ? c : text(c)).join('');
const named = (view, label) => view.root.findByProps({ 'aria-label': label });
const button = (view, fragment) => view.root.findAllByType('button').find(b => text(b).includes(fragment));
const exporter = (view, mode) => view.root.findByProps({ 'data-testid': `export-operation-${mode}` });
async function open() {
  const f = { calls: [], downloads: [], blobs: [], revoked: [], fail: false, block: null };
  globalThis.localStorage = { getItem: () => 'fixture-token' };
  globalThis.window = { location: { search: '' }, URL: {
    createObjectURL: blob => { f.blobs.push(blob); return 'blob:export-test'; },
    revokeObjectURL: url => f.revoked.push(url),
  } };
  globalThis.document = { body: { appendChild: () => {} }, createElement: () => ({
    click() { f.downloads.push({ name: this.download, href: this.href }); }, remove() {},
  }) };
  api.defaults.adapter = async config => {
    f.calls.push(config);
    let data;
    let headers = {};
    if (config.url === '/planning/templates') data = { templates: [] };
    else if (config.url === '/personnel/') data = [];
    else if (config.url === '/planning/studies/1/schedule') data = {study_id: 1, study_code: 'XLS-A', study_status: 'DRAFT', steps: [], conflicts: []};
    else if (config.url === '/planning/calendar') data = {
      studies: [{study_id: 1, study_code: 'XLS-A', study_status: 'DRAFT', steps: []},
                {study_id: 2, study_code: 'XLS-B', study_status: 'APPROVED', steps: []}],
      all_steps: [], default_focus_date: '2026-11-05', default_focus_week: '2026-11-02',
    };
    else if (config.url === '/planning/export-excel') {
      assert.equal(config.responseType, 'blob');
      assert.equal(config.headers.Authorization, 'Bearer fixture-token');
      if (f.block) await f.block;
      if (f.fail) throw { response: { data: new Blob([JSON.stringify({detail: 'İndirme reddedildi'})]) } };
      data = new Blob(['xlsx-fixture']);
      headers = {'content-disposition': `attachment; filename="operasyon-plani-${config.params.view}-${config.params.target_date}.xlsx"`};
    } else throw new Error(`Unexpected API call: ${config.url}`);
    return { data, status: 200, statusText: 'OK', headers, config };
  };
  let view;
  await act(async () => { view = create(React.createElement(Planning)); });
  return { view, f };
}
function onlyReads(f) {
  assert.ok(f.calls.every(c => c.method === 'get'));
  assert.ok(f.calls.every(c => ['/planning/templates', '/personnel/', '/planning/calendar', '/planning/studies/1/schedule', '/planning/export-excel'].includes(c.url)));
}

test('weekly download normalizes Sunday to Monday and sends selected study; QA can download', async () => {
  const {view, f} = await open();
  try {
    await act(async () => { button(view, 'Haftalık Master Takvim').props.onClick(); });
    await act(async () => { named(view, 'Haftalık plan tarihi').props.onChange({target: {value: '2026-11-08'}});
      named(view, 'Operasyon planı çalışma filtresi').props.onChange({target: {value: 'XLS-A'}}); });
    assert.equal(named(view, 'Haftalık plan tarihi').props.value, '2026-11-02');
    await act(async () => { await exporter(view, 'weekly').props.onClick(); });
    assert.deepEqual(f.calls.at(-1).params, { view: 'weekly', target_date: '2026-11-02', study_code: 'XLS-A' });
    assert.equal(f.downloads[0].name, 'operasyon-plani-weekly-2026-11-02.xlsx');
    assert.match(f.blobs[0].type, /spreadsheetml.sheet/);
    assert.deepEqual(f.revoked, ['blob:export-test']);
    onlyReads(f);
  } finally { view.unmount(); }
});

test('daily view keeps current study filter, sends selected day, and ALL omits filter', async () => {
  const {view, f} = await open();
  try {
    await act(async () => { button(view, 'Haftalık Master Takvim').props.onClick(); });
    await act(async () => { named(view, 'Operasyon planı çalışma filtresi').props.onChange({target: {value: 'XLS-B'}}); });
    await act(async () => { button(view, 'Günlük Saatlik Akış').props.onClick(); });
    assert.equal(named(view, 'Operasyon planı çalışma filtresi').props.value, 'XLS-B');
    await act(async () => { named(view, 'Günlük plan tarihi').props.onChange({target: {value: '2027-01-01'}}); });
    await act(async () => { await exporter(view, 'daily').props.onClick(); });
    assert.deepEqual(f.calls.at(-1).params, {view: 'daily', target_date: '2027-01-01', study_code: 'XLS-B'});
    await act(async () => { named(view, 'Operasyon planı çalışma filtresi').props.onChange({target: {value: 'ALL'}}); });
    await act(async () => { await exporter(view, 'daily').props.onClick(); });
    assert.deepEqual(f.calls.at(-1).params, {view: 'daily', target_date: '2027-01-01'});
    onlyReads(f);
  } finally { view.unmount(); }
});

test('download is disabled in flight and errors remain visible without mutation requests', async () => {
  const {view, f} = await open();
  try {
    await act(async () => { button(view, 'Günlük Saatlik Akış').props.onClick(); });
    let release;
    f.block = new Promise(resolve => { release = resolve; });
    f.fail = true;
    let download;
    await act(async () => { download = exporter(view, 'daily').props.onClick(); });
    assert.equal(exporter(view, 'daily').props.disabled, true);
    await act(async () => { release(); await download; });
    assert.equal(exporter(view, 'daily').props.disabled, false);
    assert.match(text(view.root), /İndirme reddedildi/);
    assert.equal(f.downloads.length, 0);
    await act(async () => { named(view, 'Günlük plan tarihi').props.onChange({target: {value: ''}}); });
    assert.equal(exporter(view, 'daily').props.disabled, true);
    onlyReads(f);
  } finally { view.unmount(); }
});
