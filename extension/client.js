import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Soup from 'gi://Soup?version=3.0';

const BASE_URL = 'http://127.0.0.1:17831';

/** A small async-only client for the local bridge. No credentials are sent. */
export class BridgeClient {
    constructor() {
        this._session = new Soup.Session({timeout: 2});
        this._cancellable = null;
        this._destroyed = false;
    }

    async getSummary() {
        return this._request('GET', '/api/v1/summary');
    }

    async refresh() {
        return this._request('POST', '/api/v1/refresh');
    }

    cancel() {
        this._cancellable?.cancel();
        this._cancellable = null;
    }

    destroy() {
        this._destroyed = true;
        this.cancel();
        this._session.abort();
    }

    async _request(method, path) {
        if (this._destroyed)
            throw new Error('Bridge client is destroyed');

        // Only one request is useful for this small cache API; cancelling it
        // prevents a late response from updating a disabled/re-enabled UI.
        this.cancel();
        const cancellable = new Gio.Cancellable();
        this._cancellable = cancellable;
        const message = Soup.Message.new(method, `${BASE_URL}${path}`);
        if (method === 'POST')
            message.request_headers.append('Content-Type', 'application/json');

        try {
            const bytes = await this._session.send_and_read_async(
                message,
                GLib.PRIORITY_DEFAULT,
                cancellable,
                null
            );
            const status = message.get_status();
            if (status < 200 || status >= 300)
                throw new Error(`Bridge returned HTTP ${status}`);

            const text = new TextDecoder().decode(bytes.get_data());
            return text ? JSON.parse(text) : {};
        } finally {
            if (this._cancellable === cancellable)
                this._cancellable = null;
        }
    }
}
