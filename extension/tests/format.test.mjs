import test from 'node:test';
import assert from 'node:assert/strict';
import {averageRemainingPercent, cacheState, clampPercent, formatPanelText, formatReset, providerSummary, quotaFillWidth, remainingPercent} from '../format.js';

test('clamps malformed percentages safely', () => {
    assert.equal(clampPercent(-2), 0);
    assert.equal(clampPercent(100.7), 100);
    assert.equal(clampPercent('nope'), null);
});

test('formats all Codex account 5h quotas and omits Antigravity from the panel', () => {
    const accounts = [
        {windows: {five_hour: {remaining_percent: 77}}},
        {windows: {five_hour: {remaining_percent: 100}}},
    ];
    assert.equal(formatPanelText({providers: {codex: {accounts}, antigravity: {summary_used_percent: 61}}}), 'Codex 1 77% left · Codex 2 100% left');
    assert.equal(formatPanelText({providers: {codex: {summary_used_percent: 42}}}), 'Codex 58% left');
    assert.equal(formatPanelText({providers: {antigravity: {summary_used_percent: 61}}}), 'Usage —');
    assert.equal(formatPanelText({providers: {}}), 'Usage —');
});

test('converts used quota to remaining quota', () => {
    assert.equal(remainingPercent(10), 90);
    assert.equal(remainingPercent(100), 0);
    assert.equal(remainingPercent(null), null);
});

test('sizes quota fills from the actual track allocation', () => {
    assert.equal(quotaFillWidth(213, 100), 213);
    assert.equal(quotaFillWidth(213, 50), 107);
    assert.equal(quotaFillWidth(213, 0), 0);
    assert.equal(quotaFillWidth(213, null), 0);
});

test('keeps a half quota at half of a fractional monitor allocation', () => {
    assert.equal(quotaFillWidth(213.6, 100), 214);
    assert.equal(quotaFillWidth(213.6, 50), 107);
    assert.equal(quotaFillWidth(213.6, 0), 0);
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


test('uses one stable fixed track width for every quota window', () => {
    assert.equal(quotaFillWidth(160, 100), 160);
    assert.equal(quotaFillWidth(160, 84), 134);
    assert.equal(quotaFillWidth(160, 44), 70);
    assert.equal(quotaFillWidth(160, 0), 0);
});


test('averages complete model remaining quotas and skips malformed values', () => {
    assert.equal(averageRemainingPercent({one: {remaining_percent: 100}, two: {remaining_percent: 40}, broken: {remaining_percent: 'bad'}}), 70);
    assert.equal(averageRemainingPercent({broken: {remaining_percent: null}}), null);
    assert.equal(averageRemainingPercent(null), null);
});
