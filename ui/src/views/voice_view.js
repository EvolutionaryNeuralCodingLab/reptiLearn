import React from 'react';
import { useSelector } from 'react-redux';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import RLButton from './ui/button.js';
import { RLTooltip } from './ui/tooltip.js';
import { classNames } from './ui/common.js';
import { SocketContext } from '../socket.js';
import { VoiceLevelOrb, useAudioLevel } from './voice_level_orb.js';

const STATUS_INFO = {
    loading: { text: 'Loading voice models...', color: 'bg-yellow-400' },
    listening: { text: 'Listening', color: 'bg-green-500' },
    recording: { text: 'Recording...', color: 'bg-red-500' },
    transcribing: { text: 'Transcribing...', color: 'bg-blue-500' },
    error: { text: 'Voice error', color: 'bg-red-700' },
};

export const VoiceView = () => {
    const { socket } = React.useContext(SocketContext);
    const ctrl_state = useSelector((state) => state.reptilearn.ctrlState);
    const voice = ctrl_state?.voice;
    const [streaming, setStreaming] = React.useState(false);
    const [micError, setMicError] = React.useState(null);
    const [audioGraph, setAudioGraph] = React.useState({ ctx: null, source: null });
    const audioRef = React.useRef(null);

    const level = useAudioLevel(audioGraph.ctx, audioGraph.source, streaming);

    const stop_streaming = React.useCallback(() => {
        const audio = audioRef.current;
        audioRef.current = null;
        setAudioGraph({ ctx: null, source: null });
        if (audio) {
            try {
                socket.emit('voice_cancel');
                audio.node.port.onmessage = null;
                audio.node.disconnect();
                audio.source.disconnect();
                audio.stream.getTracks().forEach((t) => t.stop());
                audio.ctx.close();
            } catch (e) {
                console.error('Error while stopping voice capture:', e);
            }
        }
        setStreaming(false);
    }, [socket]);

    React.useEffect(() => stop_streaming, [stop_streaming]);

    const start_streaming = async () => {
        if (audioRef.current) {
            return;
        }
        setMicError(null);
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                },
            });
            const ctx = new AudioContext();
            await ctx.audioWorklet.addModule(process.env.PUBLIC_URL + '/voice-worklet.js');
            const source = ctx.createMediaStreamSource(stream);
            const node = new AudioWorkletNode(ctx, 'voice-capture');
            node.port.onmessage = (e) => socket.emit('voice_audio', e.data);
            source.connect(node);
            audioRef.current = { ctx, stream, source, node };
            setAudioGraph({ ctx, source });
            setStreaming(true);
        } catch (e) {
            console.error('Could not start microphone capture:', e);
            const name = e?.name || '';
            const detail = e?.message || String(e);
            setMicError(
                name === 'NotAllowedError' || name === 'PermissionDeniedError'
                    ? 'Microphone permission denied. Allow mic access for ReptiLearn in Android settings, then try again.'
                    : `Microphone unavailable (${detail}). On Android the app needs RECORD_AUDIO permission; in a browser use HTTPS or localhost.`
            );
        }
    };

    const toggle_mic = () => {
        if (streaming) {
            stop_streaming();
        } else {
            start_streaming();
        }
    };

    const manual_listen = async () => {
        if (!audioRef.current) {
            await start_streaming();
        }
        if (audioRef.current) {
            socket.emit('voice_trigger');
        }
    };

    if (!voice || voice.status === 'disabled') {
        return null;
    }

    const wake_unavailable = voice.status !== 'loading' && !voice.wake_available;
    const status_info = STATUS_INFO[voice.status] || { text: voice.status, color: 'bg-gray-400' };
    const status_text = micError
        ? micError
        : voice.status === 'error'
            ? voice.error || status_info.text
            : !streaming
                ? 'Mic off'
                : voice.status === 'listening'
                    ? (voice.wake_available ? 'Listening for wake word' : 'Ready (use Listen button)')
                    : status_info.text;

    const tooltip_lines = [status_text];
    if (voice.last_transcript) {
        tooltip_lines.push(`Heard: "${voice.last_transcript}"`);
        tooltip_lines.push(voice.last_action ? `Action: ${voice.last_action}` : 'No matching command');
    }

    return (
        <>
            <RLTooltip content={streaming ? 'Stop voice capture' : 'Start voice capture (wake word)'}>
                <RLButton.TopBarButton
                    onClick={toggle_mic}
                    className={streaming ? 'text-red-600' : undefined}
                    icon={['fas', streaming ? 'microphone' : 'microphone-slash']} />
            </RLTooltip>
            <RLTooltip content={wake_unavailable
                ? 'Wake word is unavailable. Click to listen for a voice command now.'
                : 'Listen for a voice command without the wake word'}>
                <RLButton.TopBarButton
                    onClick={manual_listen}
                    disabled={voice.status === 'loading' || voice.status === 'error'}
                    className={classNames(wake_unavailable && 'bg-yellow-100 border-yellow-500 text-yellow-800 hover:bg-yellow-200')}
                    icon={['fas', 'ear-listen']}
                    text="Listen" />
            </RLTooltip>
            <RLTooltip content={<div>{tooltip_lines.map((l, i) => <div key={i}>{l}</div>)}</div>}>
                <div className="flex items-center gap-1 px-2 text-gray-600 whitespace-nowrap">
                    <span className={classNames('inline-block w-2 h-2 rounded-full',
                        (streaming || voice.status === 'error' || voice.status === 'loading') ? status_info.color : 'bg-gray-400')} />
                    <span className="max-w-[220px] overflow-hidden text-ellipsis">
                        {status_text}
                        {voice.last_transcript && voice.status === 'listening' && !micError && (
                            <span className="text-gray-400"> — "{voice.last_transcript}"</span>
                        )}
                    </span>
                    {streaming && voice.status === 'recording' && (
                        <FontAwesomeIcon icon="fa-solid fa-circle" className="h-[8px] w-[8px] text-red-500 animate-pulse" />
                    )}
                </div>
            </RLTooltip>
            <VoiceLevelOrb
                active={streaming}
                level={level}
                status={voice.status || 'listening'}
            />
        </>
    );
};
