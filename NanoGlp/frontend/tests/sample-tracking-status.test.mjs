import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join, dirname } from 'node:path';
import { build } from 'esbuild';
import React from 'react';
import { create, act } from 'react-test-renderer';

// Full production screen/drawer: only HTTP, auth and navigation are test doubles.
const root = dirname(fileURLToPath(import.meta.url));
const temp = await mkdtemp(join(root, '.sample-status-'));
after(() => rm(temp, { recursive: true, force: true }));
const entry = join(temp, 'tracking.mjs');
const apiNames = ['getSamples', 'getSample', 'getSampleDocuments', 'createSample', 'updateSample', 'planSample',
  'autoScheduleAllSamples', 'importSamplesExcel', 'exportSamplesExcel', 'sampleWorkflowAction',
  'downloadSampleStudyPlan', 'uploadSampleDocuments'];
await build({ entryPoints: [join(root, '../src/pages/SampleTracking.jsx')], outfile: entry,
  bundle: true, platform: 'node', format: 'esm', packages: 'external', define: { 'import.meta.env': '{}' },
  plugins: [{ name: 'tracking-boundaries', setup(b) {
    b.onResolve({ filter: /services\/api$|state\/AuthContext$|^react-router-dom$/ }, args => ({ path: args.path, namespace: 'fixture' }));
    b.onLoad({ filter: /.*/, namespace: 'fixture' }, ({ path }) => ({ contents:
      path.endsWith('AuthContext') ? 'export const useAuth = () => globalThis.trackingFixture.auth;'
        : path === 'react-router-dom' ? `export const useLocation = () => ({});
            export const useNavigate = () => (...args) => globalThis.trackingFixture.routes.push(args);`
        : apiNames.map(name => `export const ${name} = (...args) => globalThis.trackingFixture.request('${name}', args);`).join('\n')
          + '\nexport const extractError = (_, fallback) => fallback; export const extractBlobError = extractError;' }));
  } }],
});
const { default: SampleTracking } = await import(pathToFileURL(entry));
const text = node => node.children.map(c => typeof c === 'string' ? c : text(c)).join('');
function approval(no, signed) {
  return { no, title: no === 6 ? 'Çalışma planının onayı' : 'Final rapor gönderimi', owner: 'ÇY / KG / TBY', kind: 'approval',
    done: signed, state: signed ? 'done' : 'current', approvals: ['ÇY', 'KG', 'TBY'].map((label, i) => ({
      key: String(i), label, full: label, signed, by: signed ? `Kayıtlı İmza ${label}` : null,
      at: signed ? '2026-11-05T10:00:00' : null, can_sign: false,
    })) };
}
async function open({ study = { id: 19, status: 'DRAFT', has_schedule: true }, signed = false, final = false, menus = ['samples', 'planning'] } = {}) {
  const sample = { id: 9, study_code: 'GLP-TEST-9', status: final ? 'COMPLETED' : 'PLANNED', dates: {},
    progress: Number(signed) + Number(final), contacts: [], related: [], study, scheduled: study?.has_schedule === true,
    workflow: [approval(6, signed), approval(11, final)] };
  const before = structuredClone(sample);
  const f = globalThis.trackingFixture = { auth: { allowedMenus: menus }, routes: [], calls: [], request: async (name, args) => {
    f.calls.push({ name, args });
    if (name === 'getSamples') return { data: { items: [sample], permissions: { can_plan: true } } };
    if (name === 'getSample') return { data: sample };
    if (name === 'getSampleDocuments') return { data: { documents: [] } };
    throw new Error(`Unexpected request: ${name}`);
  } };
  let view;
  await act(async () => { view = create(React.createElement(SampleTracking)); });
  await act(async () => { await view.root.findAllByType('tr').find(row => row.props.onClick).props.onClick(); });
  return { view, sample, before, f };
}
const operational = view => text(view.root.findByProps({ 'data-testid': 'operational-study-status' }));
const workflow = (view, no) => view.root.findByProps({ 'data-testid': `workflow-step-${no}` });
function readOnlyResult({ sample, before, f }) {
  assert.deepEqual(sample, before);
  assert.deepEqual(f.calls.map(c => c.name), ['getSamples', 'getSampleDocuments', 'getSample']);
}

test('signed document remains distinct from DRAFT; existing planning link only navigates', async () => {
  const ctx = await open({ signed: true });
  try {
    assert.match(operational(ctx.view), /Taslak.*plan onayı bekleniyor/);
    const step = text(workflow(ctx.view, 6));
    assert.ok(step.includes('Çalışma planının onayı'));
    assert.ok(step.includes('05.11.2026'));
    for (const role of ['ÇY', 'KG', 'TBY']) assert.ok(step.includes(`Kayıtlı İmza ${role}`));
    assert.match(step, /belge imzaları operasyonel plan onayından ayrı/);
    assert.match(step, /Görevleri yürütmek için planlama ekranında plan onayı gerekir/);
    const link = ctx.view.root.findAllByType('button').find(b => text(b) === 'Planlama Ekranında Aç');
    await act(async () => { link.props.onClick(); });
    assert.deepEqual(ctx.f.routes, [['/planning', { state: { selectedStudyId: 19 } }]]);
    readOnlyResult(ctx);
  } finally { ctx.view.unmount(); }
});
test('APPROVED does not fabricate missing document signatures', async () => {
  const ctx = await open({ study: { id: 19, status: 'APPROVED', has_schedule: true } });
  try {
    assert.match(operational(ctx.view), /Onaylı/);
    const step = text(workflow(ctx.view, 6));
    for (const role of ['ÇY', 'KG', 'TBY']) assert.ok(step.includes(`${role} bekleniyor`));
    assert.ok(!step.includes('Kayıtlı İmza'));
    assert.ok(!step.includes('Görevleri yürütmek için'));
    readOnlyResult(ctx);
  } finally { ctx.view.unmount(); }
});
for (const [status, label] of [['DRAFT', 'Taslak'], ['APPROVED', 'Onaylı'], ['IN_PROGRESS', 'Devam ediyor'],
  ['REPORTING', 'Raporlama'], ['COMPLETED', 'Tamamlandı'], ['CANCELLED', 'İptal edildi']]) {
  test(`final report completed with operational ${status}: show both independently`, async () => {
    const ctx = await open({ study: { id: 19, status, has_schedule: true }, final: true });
    try {
      assert.ok(operational(ctx.view).includes(label));
      const step = text(workflow(ctx.view, 11));
      assert.ok(step.includes('Final rapor gönderimi'));
      assert.ok(step.includes('Kayıtlı İmza ÇY'));
      assert.match(step, /operasyonel çalışmayı otomatik olarak tamamlamaz/);
      readOnlyResult(ctx);
    } finally { ctx.view.unmount(); }
  });
}
for (const [study, label] of [[null, 'Bağlı çalışma bulunmuyor'],
  [{ id: 19, status: 'UNRECOGNIZED', has_schedule: false }, 'Bilinmeyen durum (UNRECOGNIZED)'],
  [{ id: 19, has_schedule: false }, 'Bilinmeyen durum']]) {
  test(`missing/unknown operational data: ${label}`, async () => {
    const ctx = await open({ study, signed: true });
    try {
      assert.ok(operational(ctx.view).includes(label));
      assert.ok(!operational(ctx.view).includes('Onaylı'));
      if (study) assert.match(operational(ctx.view), /Takvim oluşturulmamış/);
      assert.equal(ctx.view.root.findAllByType('button').filter(b => text(b) === 'Planlama Ekranında Aç').length, 0);
      readOnlyResult(ctx);
    } finally { ctx.view.unmount(); }
  });
}
test('planning menu permission stays in force while operational status remains visible', async () => {
  const ctx = await open({ menus: ['samples'], signed: true });
  try {
    assert.match(operational(ctx.view), /Taslak/);
    assert.equal(ctx.view.root.findAllByType('button').filter(b => text(b) === 'Planlama Ekranında Aç').length, 0);
    readOnlyResult(ctx);
  } finally { ctx.view.unmount(); }
});
