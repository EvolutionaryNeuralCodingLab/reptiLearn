import React from 'react';

const MIN_SCALE = 1;
const MAX_SCALE = 4;

const dist = (t1, t2) => {
    const dx = t1.clientX - t2.clientX;
    const dy = t1.clientY - t2.clientY;
    return Math.hypot(dx, dy);
};

const mid = (t1, t2) => ({
    x: (t1.clientX + t2.clientX) / 2,
    y: (t1.clientY + t2.clientY) / 2,
});

/**
 * Pinch-to-zoom + pan wrapper for mobile video streams.
 * Double-tap toggles between 1x and 2x.
 */
export const Zoomable = ({ children, className, style }) => {
    const viewportRef = React.useRef(null);
    const [scale, setScale] = React.useState(1);
    const [tx, setTx] = React.useState(0);
    const [ty, setTy] = React.useState(0);

    const gesture = React.useRef({
        mode: null, // 'pinch' | 'pan'
        startDist: 0,
        startScale: 1,
        startTx: 0,
        startTy: 0,
        startMid: { x: 0, y: 0 },
        panX: 0,
        panY: 0,
        lastTap: 0,
    });

    const clampPan = React.useCallback((nextScale, nextTx, nextTy) => {
        const el = viewportRef.current;
        if (!el) return { tx: nextTx, ty: nextTy };
        const { clientWidth: w, clientHeight: h } = el;
        const maxX = Math.max(0, (w * (nextScale - 1)) / 2);
        const maxY = Math.max(0, (h * (nextScale - 1)) / 2);
        return {
            tx: Math.max(-maxX, Math.min(maxX, nextTx)),
            ty: Math.max(-maxY, Math.min(maxY, nextTy)),
        };
    }, []);

    const onTouchStart = (e) => {
        const g = gesture.current;
        if (e.touches.length === 2) {
            e.preventDefault();
            g.mode = 'pinch';
            g.startDist = dist(e.touches[0], e.touches[1]);
            g.startScale = scale;
            g.startTx = tx;
            g.startTy = ty;
            g.startMid = mid(e.touches[0], e.touches[1]);
        } else if (e.touches.length === 1 && scale > 1) {
            g.mode = 'pan';
            g.panX = e.touches[0].clientX;
            g.panY = e.touches[0].clientY;
            g.startTx = tx;
            g.startTy = ty;
        } else {
            g.mode = null;
        }
    };

    const onTouchMove = (e) => {
        const g = gesture.current;
        if (g.mode === 'pinch' && e.touches.length === 2) {
            e.preventDefault();
            const d = dist(e.touches[0], e.touches[1]);
            if (g.startDist < 1) return;
            const nextScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, g.startScale * (d / g.startDist)));
            const m = mid(e.touches[0], e.touches[1]);
            const rect = viewportRef.current?.getBoundingClientRect();
            if (rect) {
                // Keep content under pinch midpoint roughly stable
                const cx = m.x - rect.left - rect.width / 2;
                const cy = m.y - rect.top - rect.height / 2;
                const ratio = nextScale / g.startScale;
                const nextTx = cx - (cx - g.startTx) * ratio;
                const nextTy = cy - (cy - g.startTy) * ratio;
                const clamped = clampPan(nextScale, nextTx, nextTy);
                setScale(nextScale);
                setTx(clamped.tx);
                setTy(clamped.ty);
            } else {
                setScale(nextScale);
            }
        } else if (g.mode === 'pan' && e.touches.length === 1 && scale > 1) {
            e.preventDefault();
            const dx = e.touches[0].clientX - g.panX;
            const dy = e.touches[0].clientY - g.panY;
            const clamped = clampPan(scale, g.startTx + dx, g.startTy + dy);
            setTx(clamped.tx);
            setTy(clamped.ty);
        }
    };

    const onTouchEnd = (e) => {
        const g = gesture.current;
        if (e.touches.length === 0) {
            // Double-tap zoom
            if (g.mode !== 'pinch' && e.changedTouches.length === 1) {
                const now = Date.now();
                if (now - g.lastTap < 280) {
                    if (scale > 1.05) {
                        setScale(1);
                        setTx(0);
                        setTy(0);
                    } else {
                        setScale(2);
                        setTx(0);
                        setTy(0);
                    }
                    g.lastTap = 0;
                } else {
                    g.lastTap = now;
                }
            }
            g.mode = null;
        } else if (e.touches.length === 1 && scale > 1) {
            g.mode = 'pan';
            g.panX = e.touches[0].clientX;
            g.panY = e.touches[0].clientY;
            g.startTx = tx;
            g.startTy = ty;
        }
    };

    const zoomBy = (delta) => {
        const nextScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale + delta));
        const clamped = clampPan(nextScale, tx, ty);
        setScale(nextScale);
        setTx(clamped.tx);
        setTy(clamped.ty);
        if (nextScale <= 1) {
            setTx(0);
            setTy(0);
        }
    };

    const reset = () => {
        setScale(1);
        setTx(0);
        setTy(0);
    };

    return (
        <div className={className} style={{ ...style, position: 'relative', touchAction: 'none' }}>
            <div
                ref={viewportRef}
                className="overflow-hidden w-full h-full"
                onTouchStart={onTouchStart}
                onTouchMove={onTouchMove}
                onTouchEnd={onTouchEnd}
                onTouchCancel={onTouchEnd}
            >
                <div
                    style={{
                        width: '100%',
                        height: '100%',
                        transform: `translate(${tx}px, ${ty}px) scale(${scale})`,
                        transformOrigin: 'center center',
                        willChange: 'transform',
                    }}
                >
                    {children}
                </div>
            </div>
            <div className="absolute bottom-1 right-1 flex gap-1 z-10">
                <button
                    type="button"
                    className="h-7 w-7 rounded bg-black/60 text-white text-sm leading-none"
                    onClick={() => zoomBy(-0.4)}
                    aria-label="Zoom out"
                >
                    −
                </button>
                <button
                    type="button"
                    className="h-7 min-w-[2rem] px-1 rounded bg-black/60 text-white text-[10px] leading-none"
                    onClick={reset}
                    aria-label="Reset zoom"
                >
                    {scale.toFixed(1)}×
                </button>
                <button
                    type="button"
                    className="h-7 w-7 rounded bg-black/60 text-white text-sm leading-none"
                    onClick={() => zoomBy(0.4)}
                    aria-label="Zoom in"
                >
                    +
                </button>
            </div>
        </div>
    );
};
