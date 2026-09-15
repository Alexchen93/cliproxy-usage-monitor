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

/**
 * Group model quota buckets by their displayed model family. A provider can add
 * new model names without changing the extension: labels are preferred, vendor
 * prefixes are skipped, and model ids are the fallback.
 */
export function modelSourceGroups(windows) {
    if (!windows || typeof windows !== 'object')
        return [];

    const groups = new Map();
    for (const [modelId, window] of Object.entries(windows)) {
        if (!window || typeof window !== 'object')
            continue;
        const source = modelSourceName(window.label, modelId);
        const key = source.toLocaleLowerCase();
        if (!groups.has(key))
            groups.set(key, {name: source, windows: {}});
        groups.get(key).windows[modelId] = window;
    }
    return [...groups.values()].sort((left, right) => left.name.localeCompare(right.name));
}

function modelSourceName(label, modelId) {
    const candidate = typeof label === 'string' && label.trim() ? label : String(modelId || 'Other');
    const parts = candidate.match(/[A-Za-z][A-Za-z0-9]*/g) || [];
    const vendorPrefixes = new Set(['google', 'anthropic', 'openai', 'meta', 'microsoft', 'xai']);
    const source = parts.find(part => !vendorPrefixes.has(part.toLocaleLowerCase()));
    if (!source)
        return 'Other';
    return source.toLocaleLowerCase() === 'gpt'
        ? 'GPT'
        : source.charAt(0).toLocaleUpperCase() + source.slice(1);
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
