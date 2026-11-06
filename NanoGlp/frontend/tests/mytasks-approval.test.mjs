import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join, dirname } from 'node:path';
import { build } from 'esbuild';
import React from 'react';
import { create, act } from 'react-test-renderer';

// Render the complete production page, with only HTTP/auth boundaries replaced.
const root = dirname(fileURLToPath(import.meta.url));
const temp = await mkdtemp(join(root, '.mytasks-'));
after(() => rm(temp, { recursive: true, force: true }));
const entry = join(temp, 'mytasks.mjs');
await build({ entryPoints: [join(root, '../src/pages/MyTasks.jsx')], outfile: entry,
  bundle: true, platform: 'node', format: 'esm', packages: 'external', define: { 'import.meta.env': '{}' },
  plugins: [{ name: 'task-boundaries', setup(b) {
    b.onResolve({ filter: /services\/api$|state\/AuthContext$/ }, (args) => ({ path: args.path, namespace: 'fixture' }));
    b.onLoad({ filter: /.*/, namespace: 'fixture' }, ({ path }) => ({ contents: path.endsWith('AuthContext')
      ? 'export const useAuth = () => globalThis.taskFixture.auth;'
      : `export const getMyTasks = async () => ({data: globalThis.taskFixture.data});
         export const updateStepStatus = async (...args) => { globalThis.taskFixture.calls.push(args); };
         export const extractError = (_, fallback) => fallback;` }));
  } }],
});
const { default: MyTasks } = await import(pathToFileURL(entry));
function task(study_status, status = 'PENDING') {
  return { id: 71, study_code: 'PREVIEW-71', study_status, status, step_name: 'Observation', study_day: 7,
    planned_start: '2026-11-05T09:00:00', planned_end: '2026-11-05T12:00:00', duration_minutes: 180,
    requires_reference_time: true, actual_reference_time: '2026-11-04T10:00:00', actual_start: null,
    assignee_names: ['Technician'] };
}
async function page(studyStatus, stepStatus = 'PENDING', readOnly = false) {
  const row = task(studyStatus, stepStatus);
  globalThis.taskFixture = { calls: [], auth: { user: { full_name: 'Technician', role: 'TECHNICIAN' }, isReadOnly: readOnly },
    data: { todays_tasks: [row], all_assigned_tasks: [row] } };
  let renderer;
  await act(async () => { renderer = create(React.createElement(MyTasks)); });
  return renderer;
}
const byId = (view, id) => view.root.findByProps({ 'data-testid': `${id}-71` });
const text = (element) => element.children.map(c => typeof c === 'string' ? c : text(c)).join('');

for (const status of ['DRAFT', 'COMPLETED', 'CANCELLED', undefined, 'UNKNOWN']) {
  for (const stepStatus of ['PENDING', 'IN_PROGRESS']) {
  test(`${status}/${stepStatus}: both views keep preview but disable execution and actual inputs`, async () => {
    const view = await page(status, stepStatus);
    try {
      assert.ok(text(view.root).includes('PREVIEW-71'));
      if (status === 'DRAFT') assert.ok(text(view.root).includes('Plan onayı bekleniyor'));
      for (const id of [...(stepStatus === 'PENDING' ? ['start-task-btn'] : []), 'complete-task-btn', 'save-ref-time-btn', 'toggle-actual-times-btn',
        'actual-start-input', 'actual-end-input', 'preserve-missing-actuals', 'ref-time-input', 'deviation-note-input']) {
        assert.equal(byId(view, id).props.disabled, true, id);
      }
      const table = view.root.findByType('table');
      const action = table.findAllByType('button').find(b => text(b) === (stepStatus === 'PENDING' ? 'Başlat' : 'Tamamla'));
      assert.equal(action.props.disabled, true, 'all-tasks table action');
      // Even direct callback invocation cannot submit a closed study.
      await act(async () => { await byId(view, 'complete-task-btn').props.onClick();
        await byId(view, 'save-ref-time-btn').props.onClick(); await action.props.onClick(); });
      assert.deepEqual(globalThis.taskFixture.calls, []);
    } finally { view.unmount(); }
  });
  }
}
for (const status of ['APPROVED', 'IN_PROGRESS']) {
  test(`${status}: both views retain normal, reference and late-entry actions`, async () => {
    const view = await page(status);
    try {
      for (const id of ['start-task-btn', 'complete-task-btn', 'save-ref-time-btn', 'actual-start-input', 'actual-end-input', 'preserve-missing-actuals', 'ref-time-input']) {
        assert.ok(!byId(view, id).props.disabled, id);
      }
      const action = view.root.findByType('table').findAllByType('button').find(b => text(b) === 'Başlat');
      assert.ok(!action.props.disabled);
      await act(async () => { await byId(view, 'start-task-btn').props.onClick(); });
      assert.deepEqual(globalThis.taskFixture.calls.pop(), [71, { status: 'IN_PROGRESS' }]);
      await act(async () => { await action.props.onClick(); });
      assert.deepEqual(globalThis.taskFixture.calls.pop(), [71, { status: 'IN_PROGRESS' }]);
      await act(async () => { await byId(view, 'save-ref-time-btn').props.onClick(); });
      assert.deepEqual(globalThis.taskFixture.calls.pop(), [71, { actual_reference_time: '2026-11-04T10:00:00' }]);
      await act(async () => { byId(view, 'preserve-missing-actuals').props.onChange({ target: { checked: true } }); });
      await act(async () => { await byId(view, 'complete-task-btn').props.onClick(); });
      assert.deepEqual(globalThis.taskFixture.calls.pop(), [71, {status: 'COMPLETED', preserve_missing_actuals: true, actual_start_unknown: true, actual_end_unknown: true}]);
    } finally { view.unmount(); }
  });
  test(`${status}: all-tasks table can complete a started task`, async () => {
    const view = await page(status, 'IN_PROGRESS');
    try {
      const action = view.root.findByType('table').findAllByType('button').find(b => text(b) === 'Tamamla');
      assert.ok(!action.props.disabled);
      await act(async () => { await action.props.onClick(); });
      assert.deepEqual(globalThis.taskFixture.calls.pop(), [71, { status: 'COMPLETED' }]);
    } finally { view.unmount(); }
  });
}
test('read-only roles still have no execution controls', async () => {
  const view = await page('APPROVED', 'PENDING', true);
  try { assert.equal(view.root.findAllByType('button').filter(b => /Başlat|Tamamla|Kaydet/.test(text(b))).length, 0); }
  finally { view.unmount(); }
});
