import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

import {BridgeClient} from './client.js';

export default class CLIProxyUsageMonitorPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        window.set_title('CLIProxy Usage Monitor Settings');
        window.set_default_size(560, 420);

        const page = new Adw.PreferencesPage({title: 'CLIProxyAPI'});
        const sourceGroup = new Adw.PreferencesGroup({
            title: 'Usage data source',
            description: 'The GNOME extension talks only to its local bridge. The bridge connects to your CLIProxyAPI instance over a private network.',
        });
        const remoteUrl = new Adw.EntryRow({
            title: 'CLIProxyAPI URL',
            text: '',
        });
        const managementKey = new Adw.PasswordEntryRow({
            title: 'Management Key',
            text: '',
        });
        managementKey.set_show_apply_button(true);
        sourceGroup.add(remoteUrl);
        sourceGroup.add(managementKey);

        const saveRow = new Adw.ActionRow({
            title: 'Save source settings',
            subtitle: 'A blank Management Key keeps the existing key. It is never displayed after saving.',
        });
        const saveButton = new Gtk.Button({
            label: 'Save',
            css_classes: ['suggested-action'],
            valign: Gtk.Align.CENTER,
        });
        saveRow.add_suffix(saveButton);
        saveRow.activatable_widget = saveButton;
        sourceGroup.add(saveRow);

        const statusGroup = new Adw.PreferencesGroup({title: 'Bridge status'});
        const statusRow = new Adw.ActionRow({title: 'Loading local bridge settings…'});
        statusGroup.add(statusRow);

        page.add(sourceGroup);
        page.add(statusGroup);
        window.add(page);

        const client = new BridgeClient();
        const load = async () => {
            try {
                const settings = await client.getSettings();
                remoteUrl.set_text(settings.remote_base_url || '');
                managementKey.set_text('');
                statusRow.set_title('Local bridge connected');
                statusRow.set_subtitle(settings.management_key_configured
                    ? 'A Management Key is configured. Enter a new value only to replace it.'
                    : 'No Management Key is configured yet.');
            } catch (_error) {
                statusRow.set_title('Local bridge unavailable');
                statusRow.set_subtitle('Start the CLIProxy Usage Bridge, then reopen this window.');
            }
        };

        saveButton.connect('clicked', async () => {
            const payload = {remote_base_url: remoteUrl.get_text().trim()};
            const replacementKey = managementKey.get_text();
            if (replacementKey)
                payload.management_key = replacementKey;

            saveButton.set_sensitive(false);
            statusRow.set_title('Saving source settings…');
            statusRow.set_subtitle('');
            try {
                const settings = await client.updateSettings(payload);
                remoteUrl.set_text(settings.remote_base_url || payload.remote_base_url);
                managementKey.set_text('');
                statusRow.set_title('Source settings saved');
                statusRow.set_subtitle(settings.management_key_configured
                    ? 'The bridge stored the key in its local 0600 configuration file.'
                    : 'A Management Key is still required.');
            } catch (error) {
                statusRow.set_title('Could not save source settings');
                statusRow.set_subtitle(error.message || 'Check the URL and local bridge status.');
            } finally {
                saveButton.set_sensitive(true);
            }
        });

        window.connect('close-request', () => {
            client.destroy();
            return false;
        });
        load();
    }
}
