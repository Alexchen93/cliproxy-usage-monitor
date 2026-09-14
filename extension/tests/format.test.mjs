import test from 'node:test';
import assert from 'node:assert/strict';
import {cacheState, clampPercent, formatPanelText, formatReset, providerSummary} from '../format.js';

test('clamps malformed percentages safely', () => {
    assert.equal(clampPercent(-2), 0);
    assert.equal(clampPercent(100.7), 100);
    assert.equal(clampPercent('nope'), null);
});

test('formats Codex and Antigravity panel values only when present', () => {
    assert.equal(formatPanelText({providers: {codex: {summary_used_percent: 42}}}), 'Codex 42%');
    assert.equal(formatPanelText({providers: {antigravity: {summary_used_percent: 61}}}), 'Antigravity 61%');
    assert.equal(formatPanelText({providers: {}}), 'Usage —');
});

test('handles partial data and cache fallbacks', () => {
    assert.equal(providerSummary({providers: {codex: null}}, 'codex'), null);
    assert.equal(cacheState({cache_state: 'cached'}), 'cached');
    assert.equal(cacheState({cache_state: 'live'}, true), 'stale');
    assert.equal(cacheState(null, true), 'offline');
});

test('preserves per-account provider quota records', () => {
    const accounts = [{display_name: 'one@example.com', windows: {five_hour: {used_percent: 12}}}];
    assert.deepEqual(providerSummary({providers: {codex: {accounts}}}, 'codex').accounts, accounts);
});

test('formats valid reset timestamps without throwing', () => {
    assert.match(formatReset(new Date(Date.now() + 61_000).toISOString()), /m$/);
    assert.equal(formatReset('invalid'), null);
});
