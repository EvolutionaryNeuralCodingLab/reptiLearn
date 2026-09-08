const STORAGE_KEY = 'reptilearn_server_url';

export const isNativeApp = () => {
    try {
        return Boolean(window.Capacitor?.isNativePlatform?.());
    } catch (_) {
        return false;
    }
};

export const getSavedServerUrl = () => {
    try {
        const value = localStorage.getItem(STORAGE_KEY);
        return value ? value.trim() : '';
    } catch (_) {
        return '';
    }
};

export const normalizeServerUrl = (url) => {
    if (!url) return '';
    let normalized = url.trim().replace(/\/+$/, '');
    if (!normalized) return '';
    if (!/^https?:\/\//i.test(normalized)) {
        normalized = `http://${normalized}`;
    }
    return normalized;
};

export const saveServerUrl = (url) => {
    const normalized = normalizeServerUrl(url);
    try {
        if (normalized) {
            localStorage.setItem(STORAGE_KEY, normalized);
        } else {
            localStorage.removeItem(STORAGE_KEY);
        }
    } catch (_) {
        // ignore quota / private mode
    }
    return normalized;
};

/** REST base URL (no trailing slash). Empty means same-origin. */
export const resolveApiUrl = (developmentMode = false) => {
    const saved = normalizeServerUrl(getSavedServerUrl());
    if (saved) return saved;
    if (developmentMode) {
        return `http://${window.location.hostname}:3500`;
    }
    if (isNativeApp()) {
        // Capacitor WebView is not the Flask origin; require an explicit URL.
        return '';
    }
    return '';
};

/** Socket.IO connection URL. Empty/undefined means same-origin. */
export const resolveSocketUrl = (developmentMode = false) => {
    return resolveApiUrl(developmentMode);
};
