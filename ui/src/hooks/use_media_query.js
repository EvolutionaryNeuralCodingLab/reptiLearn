import React from 'react';

export const useMediaQuery = (query) => {
    const getMatch = React.useCallback(() => {
        if (typeof window === 'undefined' || !window.matchMedia) {
            return false;
        }
        return window.matchMedia(query).matches;
    }, [query]);

    const [matches, setMatches] = React.useState(getMatch);

    React.useEffect(() => {
        if (typeof window === 'undefined' || !window.matchMedia) {
            return undefined;
        }
        const mql = window.matchMedia(query);
        const onChange = (event) => setMatches(event.matches);
        setMatches(mql.matches);
        if (mql.addEventListener) {
            mql.addEventListener('change', onChange);
            return () => mql.removeEventListener('change', onChange);
        }
        mql.addListener(onChange);
        return () => mql.removeListener(onChange);
    }, [query]);

    return matches;
};

/** True below Tailwind `md` (768px). */
export const useIsMobile = () => useMediaQuery('(max-width: 767px)');
