import React from 'react';
import { createPortal } from 'react-dom';

const ORB_STYLES = `
@keyframes rl-orb-drift-a {
  0%, 100% { transform: translate(-18%, -12%) scale(1.05); }
  33% { transform: translate(12%, -8%) scale(1.15); }
  66% { transform: translate(-6%, 14%) scale(0.95); }
}
@keyframes rl-orb-drift-b {
  0%, 100% { transform: translate(14%, 10%) scale(1.1); }
  40% { transform: translate(-16%, 6%) scale(0.92); }
  70% { transform: translate(8%, -14%) scale(1.18); }
}
@keyframes rl-orb-drift-c {
  0%, 100% { transform: translate(-4%, 16%) scale(1); }
  50% { transform: translate(10%, -10%) scale(1.2); }
}
@keyframes rl-orb-breathe {
  0%, 100% { filter: blur(0px); opacity: 0.92; }
  50% { filter: blur(0.4px); opacity: 1; }
}
`;

/**
 * ChatGPT-like cloudy orb that pulses with mic level.
 */
export const VoiceLevelOrb = ({ level = 0, active = false, status = 'listening' }) => {
    if (!active) return null;

    const amp = Math.min(1, Math.max(0, level));
    const recording = status === 'recording';
    const transcribing = status === 'transcribing';

    // Idle ~96px at bottom (smaller so Status stays usable); grows with voice
    const size = 96 + amp * 28;
    const speed = Math.max(0.45, 1.15 - amp * 0.7); // louder → slightly faster drift

    // Soft blue-white (ChatGPT); slight tint by status
    const tint = recording
        ? { a: '#f0d4d8', b: '#d4e0f0', c: '#c8b8c4', glow: 'rgba(232, 180, 190, 0.45)' }
        : transcribing
            ? { a: '#d0e0f8', b: '#eaf0fa', c: '#b0c4e0', glow: 'rgba(160, 190, 240, 0.5)' }
            : { a: '#c8d6e8', b: '#eef2f8', c: '#a8bcd4', glow: 'rgba(170, 195, 225, 0.55)' };

    const node = (
        <div
            className="pointer-events-none fixed inset-x-0 z-[300] flex justify-center"
            style={{
                // Above bottom tab bar; keeps video / analysis panels clear
                bottom: 'max(4.25rem, calc(env(safe-area-inset-bottom, 0px) + 3.75rem))',
                top: 'auto',
            }}
            aria-hidden
        >
            <style>{ORB_STYLES}</style>
            <div
                className="relative flex items-center justify-center"
                style={{
                    width: size + 48,
                    height: size + 48,
                    transform: `scale(${0.96 + amp * 0.1})`,
                    transition: 'width 70ms linear, height 70ms linear, transform 70ms linear',
                }}
            >
                {/* Soft outer aura */}
                <div
                    className="absolute rounded-full"
                    style={{
                        inset: 4,
                        background: `radial-gradient(circle, ${tint.glow} 0%, transparent 68%)`,
                        filter: `blur(${14 + amp * 10}px)`,
                        opacity: 0.55 + amp * 0.35,
                    }}
                />

                {/* Clipped cloudy sphere */}
                <div
                    className="relative overflow-hidden rounded-full"
                    style={{
                        width: size,
                        height: size,
                        background: `radial-gradient(circle at 50% 58%, ${tint.b} 0%, ${tint.a} 42%, ${tint.c} 100%)`,
                        boxShadow: `
                            inset 0 -18px 36px rgba(90, 110, 140, 0.28),
                            inset 0 14px 28px rgba(255, 255, 255, 0.55),
                            0 0 ${20 + amp * 30}px ${tint.glow}
                        `,
                        animation: `rl-orb-breathe ${3.2 * speed}s ease-in-out infinite`,
                    }}
                >
                    {/* Wispy cloud blobs */}
                    <div
                        className="absolute rounded-full"
                        style={{
                            width: '75%',
                            height: '70%',
                            left: '12%',
                            top: '10%',
                            background: `radial-gradient(circle, rgba(255,255,255,0.95) 0%, rgba(230,238,248,0.35) 45%, transparent 70%)`,
                            filter: 'blur(10px)',
                            animation: `rl-orb-drift-a ${7.5 * speed}s ease-in-out infinite`,
                        }}
                    />
                    <div
                        className="absolute rounded-full"
                        style={{
                            width: '80%',
                            height: '75%',
                            left: '5%',
                            top: '20%',
                            background: `radial-gradient(circle, ${tint.a} 0%, rgba(180,200,220,0.4) 40%, transparent 68%)`,
                            filter: 'blur(14px)',
                            mixBlendMode: 'soft-light',
                            animation: `rl-orb-drift-b ${9.2 * speed}s ease-in-out infinite`,
                        }}
                    />
                    <div
                        className="absolute rounded-full"
                        style={{
                            width: '65%',
                            height: '60%',
                            left: '20%',
                            top: '25%',
                            background: 'radial-gradient(circle, rgba(255,255,255,0.85) 0%, transparent 60%)',
                            filter: 'blur(8px)',
                            animation: `rl-orb-drift-c ${6.4 * speed}s ease-in-out infinite`,
                        }}
                    />
                    {/* Specular highlight */}
                    <div
                        className="absolute rounded-full"
                        style={{
                            width: '42%',
                            height: '28%',
                            left: '18%',
                            top: '12%',
                            background: 'radial-gradient(ellipse, rgba(255,255,255,0.9) 0%, transparent 70%)',
                            filter: 'blur(4px)',
                            opacity: 0.75 + amp * 0.2,
                        }}
                    />
                    {/* Lower soft shadow inside sphere */}
                    <div
                        className="absolute inset-0 rounded-full"
                        style={{
                            background: 'radial-gradient(circle at 50% 100%, rgba(70,90,120,0.35) 0%, transparent 55%)',
                        }}
                    />
                </div>
            </div>
        </div>
    );

    return createPortal(node, document.body);
};

/**
 * Attach an AnalyserNode to a MediaStreamSource and report a smoothed 0..1 level.
 */
export const useAudioLevel = (audioCtx, sourceNode, enabled) => {
    const [level, setLevel] = React.useState(0);
    const rafRef = React.useRef(null);
    const smoothRef = React.useRef(0);

    React.useEffect(() => {
        if (!enabled || !audioCtx || !sourceNode) {
            setLevel(0);
            smoothRef.current = 0;
            return undefined;
        }

        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.7;
        sourceNode.connect(analyser);

        const timeData = new Uint8Array(analyser.fftSize);
        const freqData = new Uint8Array(analyser.frequencyBinCount);

        const tick = () => {
            analyser.getByteTimeDomainData(timeData);
            analyser.getByteFrequencyData(freqData);

            let sumSq = 0;
            for (let i = 0; i < timeData.length; i++) {
                const v = (timeData[i] - 128) / 128;
                sumSq += v * v;
            }
            const rms = Math.sqrt(sumSq / timeData.length);

            let speechEnergy = 0;
            const n = freqData.length;
            const start = Math.floor(n * 0.05);
            const end = Math.floor(n * 0.45);
            for (let i = start; i < end; i++) {
                speechEnergy += freqData[i];
            }
            speechEnergy = speechEnergy / ((end - start) * 255);

            const raw = Math.min(1, rms * 4.5 + speechEnergy * 0.85);
            smoothRef.current = smoothRef.current * 0.65 + raw * 0.35;
            setLevel(smoothRef.current);
            rafRef.current = requestAnimationFrame(tick);
        };

        rafRef.current = requestAnimationFrame(tick);

        return () => {
            if (rafRef.current) cancelAnimationFrame(rafRef.current);
            try {
                analyser.disconnect();
            } catch (_) {
                // ignore
            }
            setLevel(0);
            smoothRef.current = 0;
        };
    }, [audioCtx, sourceNode, enabled]);

    return level;
};
