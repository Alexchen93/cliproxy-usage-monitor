/**
 * Pure presentation helpers. They deliberately accept incomplete bridge data so
 * a partial provider response cannot break the Shell UI.
 */
export function clampPercent(value) {
    if (value === null || value === undefined || value === '')
        return null;
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(0, Math.min(100, Math.round(number))) : null;
}

export function formatPercent(value) {
    const percent = clampPercent(value);
    return percent === null ? '—' : `${percent}%`;
}

export function providerSummary(summary, providerKey) {
    const provider = summary?.providers?.[providerKey];
    if (!provider || typeof provider !== 'object')
        return null;

    return {
        key: providerKey,
        name: provider.display_name || providerKey,
        usedPercent: clampPercent(provider.summary_used_percent),
        accountsTotal: finiteInteger(provider.accounts_total),
        accountsAvailable: finiteInteger(provider.accounts_available),
        estimated: provider.estimated === true,
        accounts: Array.isArray(provider.accounts) ? provider.accounts : [],
        windows: provider.windows && typeof provider.windows === 'object' ? provider.windows : {},
    };
}

export function formatPanelText(summary) {
    const parts = [];
    const codex = providerSummary(summary, 'codex');
    const antigravity = providerSummary(summary, 'antigravity');

    if (codex)
        parts.push(`Codex ${formatPercent(remainingPercent(codex.usedPercent))} left`);
    if (antigravity)
        parts.push(`Antigravity ${formatPercent(remainingPercent(antigravity.usedPercent))} left`);

    return parts.length > 0 ? parts.join(' · ') : 'Usage —';
}

export function remainingPercent(usedPercent) {
    const used = clampPercent(usedPercent);
    return used === null ? null : 100 - used;
}

export function quotaFillWidth(trackWidth, remainingPercent) {
    const track = Number(trackWidth);
    const remaining = clampPercent(remainingPercent);
    if (!Number.isFinite(track) || track <= 0 || remaining === null)
        return 0;
    return Math.round(track * remaining / 100);
}

/** Returns the arithmetic mean remaining quota for complete model quota records. */
export function averageRemainingPercent(windows) {
    if (!windows || typeof windows !== 'object')
        return null;
    const values = Object.values(windows)
        .map(window => clampPercent(window?.remaining_percent))
        .filter(value => value !== null);
    if (values.length === 0)
        return null;
    return values.reduce((total, value) => total + value, 0) / values.length;
}

export function cacheState(summary, requestFailed = false) {
    if (requestFailed)
        return summary ? 'stale' : 'offline';

    switch (summary?.cache_state) {
    case 'live':
    case 'cached':
    case 'stale':
        return summary.cache_state;
    default:
        return summary ? 'cached' : 'offline';
    }
}

export function formatAge(seconds) {
    const age = Number(seconds);
    if (!Number.isFinite(age) || age < 0)
        return 'Unknown';
    if (age < 60)
        return `${Math.round(age)}s ago`;
    if (age < 3600)
        return `${Math.floor(age / 60)}m ago`;
    return `${Math.floor(age / 3600)}h ago`;
}

export function formatReset(resetAt) {
    if (!resetAt)
        return null;
    const reset = new Date(resetAt);
    if (Number.isNaN(reset.getTime()))
        return null;

    const seconds = Math.max(0, Math.round((reset.getTime() - Date.now()) / 1000));
    if (seconds < 60)
        return 'under 1m';
    if (seconds < 3600)
        return `${Math.ceil(seconds / 60)}m`;
    if (seconds < 86400)
        return `${Math.ceil(seconds / 3600)}h`;
    return `${Math.ceil(seconds / 86400)}d`;
}

function finiteInteger(value) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(0, Math.round(number)) : null;
}
