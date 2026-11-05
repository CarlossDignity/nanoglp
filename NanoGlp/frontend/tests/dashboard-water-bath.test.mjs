import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join, dirname } from 'node:path';
import { build } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const root = dirname(fileURLToPath(import.meta.url));
const temp = await mkdtemp(join(root, '.water-bath-'));
after(() => rm(temp, { recursive: true, force: true }));
const entry = join(temp, 'dashboard.mjs');
await build({ entryPoints: [join(root, '../src/pages/Dashboard.jsx')], outfile: entry,
  bundle: true, platform: 'node', format: 'esm', packages: 'external', define: { 'import.meta.env': '{}' } });
const { computeWaterBathLoad: load, EquipmentCapacityCard } = await import(pathToFileURL(entry));
const hour = 3600000;
const base = Date.parse('2029-01-01T08:00:00Z');
const iso = (hours) => new Date(base + hours * hour).toISOString();
function study(id, start = 0, polar = true, apolar = true, status = 'PENDING') {
  return { study_id: id, study_code: `WB-${id}`, study_status: 'IN_PROGRESS',
    extraction_polar: polar, extraction_non_polar: apolar,
    steps: [{ id, status, step_type: 'Ekstraksiyon', step_name: 'Kurulum', planned_start: iso(start), planned_end: iso(start + 1.5) }],
    water_bath_reservations: [{ equipment_code: 'EQ-WB-001', step_id: id, window_start: iso(start), window_end: iso(start + 72),
      uses_polar: polar, uses_apolar: apolar }] };
}

test('completing setup does not remove the active reservation', () => {
  const pending = load([study(1)]);
  const completed = load([study(1, 0, true, true, 'COMPLETED')]);
  assert.equal(completed.polarPeak, 1);
  assert.deepEqual(completed, pending);
});

test('short setup retains the authoritative 72-hour window', () => {
  const result = load([study(1)]);
  assert.equal(result.windows[0].end - result.windows[0].start, 72 * hour);
  const moved = study(1);
  moved.steps[0].planned_start = iso(24); // never reconstruct from personnel task times
  assert.equal(load([moved]).windows[0].start, base);
});

test('peak uses half-open boundaries and actual simultaneous overlap', () => {
  assert.equal(load([study(1), study(2, 72)]).polarPeak, 1);
  assert.equal(load([study(1), study(2, 36), study(3, 72)]).nonPolarPeak, 2);
  assert.equal(load([study(1), study(2, 36), study(3, 71)]).polarPeak, 3);
});

test('only explicit polar/apolar reservations count; no guessed fallback', () => {
  const unknown = study(3, 0, null, null);
  const result = load([study(1, 0, true, null), study(2, 0, false, true), unknown, study(4, 0, false, false)]);
  assert.equal(result.polarPeak, 1);
  assert.equal(result.nonPolarPeak, 1);
  assert.equal(result.windows.length, 2);
  const missing = study(5);
  delete missing.water_bath_reservations;
  assert.equal(load([missing]).windows.length, 0);
});

test('cancelled/completed studies, excluded steps and other equipment do not count', () => {
  const cancelled = { ...study(1), study_status: 'CANCELLED' };
  const completed = { ...study(2), study_status: 'COMPLETED' };
  const excluded = study(3); // backend excludes cancelled / historical-unverified steps
  excluded.water_bath_reservations = [];
  const other = study(4);
  other.water_bath_reservations[0].equipment_code = 'EQ-OTHER';
  assert.equal(load([cancelled, completed, excluded, other]).windows.length, 0);
});

test('multiple extraction windows of one study count as one simultaneous study', () => {
  const same = study(1);
  same.water_bath_reservations.push({ ...same.water_bath_reservations[0], step_id: 99, window_start: iso(12), window_end: iso(84) });
  const result = load([same, study(2, 75)]);
  assert.equal(result.polarPeak, 2);
  assert.equal(result.studyCount, 2);
});

test('invalid reservation timestamps do not produce occupancy', () => {
  const invalid = study(1);
  invalid.water_bath_reservations[0].window_start = 'invalid';
  assert.equal(load([invalid]).windows.length, 0);
});

test('actual dashboard card renders recorded capacity, peaks and overload', () => {
  const result = load([study(1, 0, true, false), study(2), study(3, 0, false, true)]);
  const html = renderToStaticMarkup(React.createElement(EquipmentCapacityCard, {
    equipment: { code: 'EQ-WB-001', polar_capacity: 7, non_polar_capacity: 1 }, load: result, loading: false,
  }));
  const text = html.replace(/<[^>]*>/g, '');
  assert.match(text, /2 \/ 7/);
  assert.match(text, /2 \/ 1/);
  assert.match(text, /3 çalışmanın/);
  assert.match(html, /bg-red-500/);
  assert.match(html, /width:100%/);
});
