import React from 'react';

import { getApiUrl } from '../api';
import { getSavedServerUrl, isNativeApp, normalizeServerUrl, saveServerUrl } from '../server_config';
import { SocketContext } from '../socket';
import RLButton from './ui/button';
import RLInput from './ui/input';
import RLModal from './ui/modal';

export const ConnectionSettingsForm = ({ onSaved, compact = false }) => {
    const { reconnect } = React.useContext(SocketContext);
    const [url, setUrl] = React.useState(() => getSavedServerUrl() || getApiUrl() || 'http://127.0.0.1:3500');
    const [error, setError] = React.useState(null);

    const save = () => {
        const normalized = normalizeServerUrl(url);
        if (!normalized) {
            setError('Enter a server URL, e.g. http://127.0.0.1:3500');
            return;
        }
        try {
            // Validate URL shape
            // eslint-disable-next-line no-new
            new URL(normalized);
        } catch (_) {
            setError('Invalid URL');
            return;
        }
        setError(null);
        saveServerUrl(normalized);
        reconnect(normalized);
        onSaved?.(normalized);
    };

    const clear = () => {
        if (isNativeApp()) {
            setError('A server URL is required in the mobile app');
            return;
        }
        setError(null);
        saveServerUrl('');
        setUrl('');
        reconnect('');
        onSaved?.('');
    };

    return (
        <div className={compact ? 'flex flex-col gap-2' : 'flex flex-col gap-3 text-left'}>
            <label className="text-sm text-gray-700">
                Server URL
                <RLInput.Text
                    className="mt-1 w-full"
                    value={url}
                    placeholder="http://127.0.0.1:3500"
                    onChange={(e) => setUrl(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && save()}
                />
            </label>
            <p className="text-xs text-gray-500">
                Use your VPN/LAN address or a local SSH tunnel (e.g. http://127.0.0.1:3500).
                ReptiLearn has no authentication — only connect over a trusted network.
            </p>
            {error && <p className="text-xs text-red-600">{error}</p>}
            <div className="flex gap-2 justify-end">
                {!isNativeApp() && (
                    <RLButton.ModalButton onClick={clear}>Use same origin</RLButton.ModalButton>
                )}
                <RLButton.ModalButton colorClasses="text-green-700" onClick={save}>
                    Connect
                </RLButton.ModalButton>
            </div>
        </div>
    );
};

export const ConnectionSettingsModal = ({ open, setOpen }) => (
    <RLModal
        open={open}
        setOpen={setOpen}
        header="Connection"
        sizeClasses="w-full max-w-md sm:max-w-md"
        actions={
            <RLButton.ModalButton onClick={() => setOpen(false)}>Close</RLButton.ModalButton>
        }
    >
        <ConnectionSettingsForm onSaved={() => setOpen(false)} />
    </RLModal>
);

export const WaitingForConnection = () => {
    const { socket } = React.useContext(SocketContext);
    const [showSettings, setShowSettings] = React.useState(() => isNativeApp() || Boolean(getSavedServerUrl()));
    const connected = Boolean(socket?.connected);

    return (
        <div className="font-[Lato] flex h-screen justify-center items-center bg-gray-50 px-4">
            <div className="w-full max-w-md">
                <div className="text-5xl sm:text-8xl mb-4 text-center">ReptiLearn</div>
                <div className="text-xl sm:text-2xl animate-pulse text-center mb-6">
                    {connected ? 'Loading…' : 'Waiting for connection…'}
                </div>
                {!showSettings ? (
                    <div className="text-center">
                        <button
                            type="button"
                            className="text-sm text-blue-700 underline"
                            onClick={() => setShowSettings(true)}
                        >
                            Connection settings
                        </button>
                    </div>
                ) : (
                    <div className="bg-white border border-gray-300 rounded-lg p-4 shadow-sm">
                        <ConnectionSettingsForm />
                    </div>
                )}
            </div>
        </div>
    );
};
