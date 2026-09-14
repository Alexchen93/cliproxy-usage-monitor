import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import St from 'gi://St';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {BridgeClient} from './client.js';
import {cacheState, formatAge, formatPanelText, formatPercent, formatReset, providerSummary} from './format.js';

const POLL_SECONDS = 30;
const POPUP_REFRESH_AGE_SECONDS = 20;
const STATE_ICONS = {
    live: 'emblem-ok-symbolic',
    cached: 'emblem-synchronizing-symbolic',
    stale: 'dialog-warning-symbolic',
    offline: 'network-offline-symbolic',
};

export const UsageIndicator = GObject.registerClass(
class UsageIndicator extends PanelMenu.Button {
    _init(extensionUuid) {
        super._init(0.0, 'CLIProxy Usage Monitor');
        this._extensionUuid = extensionUuid;
        this._summary = null;
        this._requestFailed = false;
        this._destroyed = false;
        this._pollId = 0;
        this._client = new BridgeClient();

        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        this._icon = new St.Icon({style_class: 'system-status-icon'});
        this._label = new St.Label({text: 'Usage —', y_align: Clutter.ActorAlign.CENTER});
        box.add_child(this._icon);
        box.add_child(this._label);
        this.add_child(box);

        this.menu.connect('open-state-changed', (_menu, open) => {
            if (open)
                this._onMenuOpened();
        });
        this._render();
        this._poll();
        this._pollId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, POLL_SECONDS, () => {
            this._poll();
            return GLib.SOURCE_CONTINUE;
        });
    }

    destroy() {
        this._destroyed = true;
        if (this._pollId) {
            GLib.Source.remove(this._pollId);
            this._pollId = 0;
        }
        this._client.destroy();
        super.destroy();
    }

    async _poll() {
        if (this._destroyed)
            return;
        try {
            const summary = await this._client.getSummary();
            if (this._destroyed)
                return;
            this._summary = summary;
            this._requestFailed = false;
        } catch (_error) {
            // Keep the last good response visible during bridge outages.
            if (this._destroyed)
                return;
            this._requestFailed = true;
        }
        this._render();
    }

    async _onMenuOpened() {
        if (Number(this._summary?.data_age_seconds) > POPUP_REFRESH_AGE_SECONDS)
            this._refreshNonBlocking();
    }

    async _refreshNonBlocking() {
        try {
            await this._client.refresh(); // Bridge returns 202 after scheduling.
        } catch (_error) {
            if (!this._destroyed) {
                this._requestFailed = true;
                this._render();
            }
        }
        // Fetch the cache without holding up the Popup UI.
        if (!this._destroyed)
            this._poll();
    }

    _render() {
        const state = this._summary?.proxy?.online === false
            ? 'offline'
            : cacheState(this._summary, this._requestFailed);
        this._label.set_text(formatPanelText(this._summary));
        this._icon.icon_name = STATE_ICONS[state];
        this._icon.accessible_name = `CLIProxy usage: ${state}`;

        this.menu.removeAll();
        if (!this._summary) {
            this.menu.addMenuItem(this._infoItem('Bridge offline — waiting for data'));
        } else {
            for (const key of ['codex', 'antigravity']) {
                const provider = providerSummary(this._summary, key);
                if (provider)
                    this._addProvider(provider);
            }
            this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            const proxy = this._summary.proxy || {};
            const online = proxy.online === true ? 'Online' : 'Offline';
            const latency = Number.isFinite(Number(proxy.latency_ms)) ? ` · ${Math.round(proxy.latency_ms)} ms` : '';
            this.menu.addMenuItem(this._infoItem(`Proxy  ${online}${latency}`));
            this.menu.addMenuItem(this._infoItem(`Data   ${state} · ${formatAge(this._summary.data_age_seconds)}`));
            if (this._summary.updated_at)
                this.menu.addMenuItem(this._infoItem(`Updated  ${this._summary.updated_at}`));
            if (Array.isArray(this._summary.errors) && this._summary.errors.length)
                this.menu.addMenuItem(this._infoItem('Some provider data is unavailable'));
        }

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const refresh = new PopupMenu.PopupMenuItem('Refresh');
        refresh.connect('activate', () => this._refreshNonBlocking());
        this.menu.addMenuItem(refresh);
        const settings = new PopupMenu.PopupMenuItem('Settings…');
        settings.connect('activate', () => this._openPreferences());
        this.menu.addMenuItem(settings);
    }

    _addProvider(provider) {
        this.menu.addMenuItem(this._infoItem(provider.name));
        if (provider.accounts.length > 0) {
            provider.accounts.forEach((account, index) => {
                if (index > 0)
                    this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
                this._addAccount(account, index + 1);
            });
        } else {
            this._addWindows(provider.windows);
            if (provider.usedPercent !== null && Object.keys(provider.windows).length === 0)
                this.menu.addMenuItem(this._infoItem(`Used  ${formatPercent(provider.usedPercent)}`));
        }
        if (provider.accountsTotal !== null) {
            const available = provider.accountsAvailable === null ? 'unknown' : provider.accountsAvailable;
            this.menu.addMenuItem(this._infoItem(`Accounts  ${available}/${provider.accountsTotal} available${provider.estimated ? ' · estimated' : ''}`));
        }
    }

    _addAccount(account, index) {
        const name = typeof account?.display_name === 'string' ? account.display_name : `Account ${index}`;
        const card = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
        card.add_style_class_name('cliproxy-account-card');
        const content = new St.BoxLayout({vertical: true, x_expand: true});
        const heading = new St.Label({text: `Account ${index} · ${name}`, style_class: 'cliproxy-account-heading'});
        content.add_child(heading);

        if (account?.available === false) {
            content.add_child(new St.Label({text: 'Quota unavailable', style_class: 'cliproxy-account-unavailable'}));
        } else {
            const windows = account?.windows && typeof account.windows === 'object' ? account.windows : {};
            this._addWindows(windows, content);
            if (Object.keys(windows).length === 0)
                content.add_child(new St.Label({text: `Used  ${formatPercent(account?.summary_used_percent)}`, style_class: 'cliproxy-account-unavailable'}));
        }
        card.add_child(content);
        this.menu.addMenuItem(card);
    }

    _addWindows(windows, container = null) {
        const windowLabels = {five_hour: '5h', weekly: 'Weekly'};
        for (const [key, label] of Object.entries(windowLabels)) {
            const window = windows[key];
            if (!window)
                continue;
            const row = this._quotaRow(label, window);
            if (container)
                container.add_child(row);
            else {
                const item = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
                item.add_child(row);
                this.menu.addMenuItem(item);
            }
        }
    }

    _quotaRow(label, window) {
        const remaining = Math.max(0, Math.min(100, Number(window.remaining_percent) || 0));
        const box = new St.BoxLayout({vertical: true, x_expand: true});
        const row = new St.BoxLayout({style_class: 'cliproxy-quota-row', x_expand: true});
        row.add_child(new St.Label({text: label, style_class: 'cliproxy-quota-label'}));
        row.add_child(new St.Label({text: `${Math.round(remaining)}%`, style_class: 'cliproxy-quota-percent'}));

        const track = new St.Widget({style_class: 'cliproxy-quota-track', x_expand: true, y_align: Clutter.ActorAlign.CENTER});
        const level = remaining <= 15 ? 'critical' : remaining <= 40 ? 'warning' : 'good';
        const fill = new St.Widget({
            style_class: `cliproxy-quota-fill cliproxy-quota-${level}`,
            x_align: Clutter.ActorAlign.START,
            y_expand: true,
            width: Math.round(remaining * 1.6),
        });
        track.add_child(fill);
        row.add_child(track);
        box.add_child(row);

        const reset = formatReset(window.reset_at);
        if (reset)
            box.add_child(new St.Label({text: `Reset ${reset}`, style_class: 'cliproxy-quota-reset'}));
        return box;
    }

    _openPreferences() {
        try {
            Gio.Subprocess.new(['gnome-extensions', 'prefs', this._extensionUuid], Gio.SubprocessFlags.NONE);
        } catch (_error) {
            // The popup remains usable even if GNOME's preferences launcher is unavailable.
        }
    }

    _infoItem(text) {
        const item = new PopupMenu.PopupMenuItem(text, {reactive: false, can_focus: false});
        item.label.style_class = 'cliproxy-usage-info';
        return item;
    }
});
