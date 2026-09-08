import io from 'socket.io-client';
import React from 'react';

import { getSocketUrl } from './api';

const createSocket = (url) => {
    const isNative = Boolean(window.Capacitor?.isNativePlatform?.());
    // Empty string / undefined → same-origin (browser served by Flask).
    if (!url) {
        if (isNative) {
            return io({ autoConnect: false, transports: ['websocket', 'polling'] });
        }
        return io({ transports: ['websocket', 'polling'] });
    }
    return io(url, { transports: ['websocket', 'polling'] });
};

export const SocketContext = React.createContext(null);

export const SocketProvider = ({ children }) => {
    const [socket, setSocket] = React.useState(() => createSocket(getSocketUrl()));

    const reconnect = React.useCallback((url) => {
        setSocket((prev) => {
            try {
                prev.removeAllListeners();
                prev.disconnect();
            } catch (_) {
                // ignore
            }
            const next = createSocket(url || undefined);
            if (!next.connected && next.io?.opts?.autoConnect !== false) {
                next.connect();
            }
            return next;
        });
    }, []);

    const value = React.useMemo(() => ({ socket, reconnect }), [socket, reconnect]);

    return (
        <SocketContext.Provider value={value}>
            {children}
        </SocketContext.Provider>
    );
};

/** Prefer SocketContext; kept for modules that emit before hooks are available. */
export const getSocket = (contextValue) => contextValue?.socket;
