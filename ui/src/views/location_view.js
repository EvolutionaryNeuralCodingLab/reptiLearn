import React from 'react';
import { ReflexContainer, ReflexSplitter, ReflexElement } from 'react-reflex';
import { useSelector } from 'react-redux';

import { api } from '../api.js';
import { Bar } from './ui/bar.js';
import RLButton from './ui/button.js';
import { classNames } from './ui/common.js';
import {
    WALLS,
    doorsAt,
    facingAt,
    formatClock,
    formatDuration,
    formatPlayhead,
    magnetAt,
    playbackFacts,
    rewardsAt,
    positionHeld,
    sampleAt,
    statsAt,
    zoneSecondsFromSegments,
    trailBefore,
    trialIndexAt,
    trialList,
    zoneAt,
} from './location_model.js';
import LocationScene from './location_scene.js';

const SPEEDS = [0.5, 1, 1.5, 2];
const END_EPSILON = 0.05;
const LIVE_POLL_MS = 100;
const TRACK_POLL_MS = 700;

const sessionDirName = (dataDir) => {
    if (!dataDir) return null;
    const parts = String(dataDir).split(/[/\\]/).filter(Boolean);
    return parts.length ? parts[parts.length - 1] : null;
};

const ArenaSchematic = ({
    zones,
    doors,
    trail,
    sample,
    facing,
    held,
    magnetDirection,
    foodCount,
}) => {
    const hostRef = React.useRef(null);
    const [box, setBox] = React.useState({ w: 0, h: 0 });

    React.useEffect(() => {
        const el = hostRef.current;
        if (!el) return undefined;
        const update = () => setBox({ w: el.clientWidth, h: el.clientHeight });
        update();
        const observer = new ResizeObserver(update);
        observer.observe(el);
        return () => observer.disconnect();
    }, []);

    const aspect = 960 / 720;
    let drawW = box.w;
    let drawH = drawW / aspect;
    if (drawH > box.h) {
        drawH = box.h;
        drawW = drawH * aspect;
    }

    return (
        <div ref={hostRef} className="w-full h-full overflow-hidden flex items-center justify-center" style={{ background: '#1a7eb8' }}>
            {drawW > 0 && drawH > 0 && (
                <LocationScene
                    width={drawW}
                    height={drawH}
                    zones={zones}
                    doors={doors}
                    trail={trail}
                    sample={sample}
                    facing={facing}
                    held={held}
                    magnetDirection={magnetDirection}
                    foodCount={foodCount}
                />
            )}
        </div>
    );
};


const SpeedButton = ({ value, speed, onSelect }) => (
    <button
        type="button"
        onClick={() => onSelect(value)}
        className={classNames(
            'px-1.5 h-[22px] border rounded-[4px] font-medium',
            speed === value
                ? 'bg-blue-600 text-white border-blue-700'
                : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-200'
        )}
    >
        {value}x
    </button>
);

const LocationPlayer = ({
    mode,
    playing,
    speed,
    setSpeed,
    playhead,
    start,
    end,
    onScrub,
    canLive,
    canPlay,
    trials,
    trialIndex,
    onTogglePlay,
    onSelectTrial,
    sessions,
    currentDir,
    currentId,
    selectedDir,
    onSelectSession,
    stacked = false,
}) => {
    const selectedTrialRef = React.useRef(null);
    React.useEffect(() => {
        selectedTrialRef.current?.scrollIntoView({ block: 'nearest' });
    }, [trialIndex, trials.length]);
    const rows = [...(sessions || [])].reverse();
    const knownCurrent = currentDir && rows.some((row) => row[2] === currentDir);
    const currentTrial = trialIndex >= 0 ? trials[trialIndex] : null;
    const canPrev = trialIndex > 0 || (currentTrial && Number.isFinite(playhead) && playhead - currentTrial.t > 1);
    const canNext = trialIndex >= 0 && trialIndex < trials.length - 1;

    return (
        <div className={classNames(
            'flex flex-col bg-white',
            stacked ? '' : 'h-full overflow-hidden'
        )}>
            <Bar title="Playback" className={stacked ? 'flex-wrap' : ''}>
                <span className={classNames(
                    'flex items-center px-1 font-semibold',
                    mode === 'live' ? 'text-green-700' : 'text-blue-700'
                )}>
                    {mode === 'live' ? 'Live' : 'Controlled'}
                </span>
                <RLButton.BarButton
                    text="Prev"
                    onClick={() => onSelectTrial(
                        currentTrial && Number.isFinite(playhead) && playhead - currentTrial.t > 1
                            ? trialIndex
                            : trialIndex - 1
                    )}
                    disabled={!canPrev}
                />
                <RLButton.BarButton
                    text="Next"
                    onClick={() => onSelectTrial(canNext ? trialIndex + 1 : null)}
                    disabled={!canNext && !(canLive && mode !== 'live')}
                />
                <RLButton.BarButton
                    text={playing ? 'Pause' : 'Play'}
                    onClick={onTogglePlay}
                    disabled={mode === 'live' || !canPlay}
                />
                {SPEEDS.map((value) => (
                    <SpeedButton key={value} value={value} speed={speed} onSelect={setSpeed} />
                ))}
            </Bar>
            <div className="px-2 py-1 border-b border-gray-200">
                <input
                    type="range"
                    className="w-full"
                    min={Number.isFinite(start) ? start : 0}
                    max={Number.isFinite(end) ? end : 0}
                    step={0.1}
                    value={
                        Number.isFinite(start) && Number.isFinite(end) && Number.isFinite(playhead)
                            ? Math.min(end, Math.max(start, playhead))
                            : 0
                    }
                    disabled={!canPlay}
                    onChange={(event) => onScrub(Number(event.target.value))}
                    aria-label="Session time"
                />
            </div>
            <div className="px-2 py-1 border-b border-gray-200 text-xs text-gray-600">
                {currentTrial
                    ? `Trial ${currentTrial.trial} · ${formatPlayhead(playhead)}`
                    : (Number.isFinite(playhead) && playhead > 1e9 ? formatPlayhead(playhead) : '—')}
                {mode === 'live' && canLive && (
                    <div className="text-gray-500">Showing the live position. Choose a trial to replay.</div>
                )}
            </div>
            <Bar title="Trials" />
            <div className={stacked ? 'max-h-40 overflow-y-auto' : 'flex-1 overflow-y-auto min-h-0'}>
                {trials.map((item, index) => (
                    <button
                        key={`${item.t}-${item.trial}`}
                        type="button"
                        onClick={() => onSelectTrial(index)}
                        ref={index === trialIndex ? selectedTrialRef : null}
                        className={classNames(
                            'w-full text-left px-2 py-1 border-b border-gray-100 hover:bg-gray-100',
                            index === trialIndex ? 'bg-blue-50' : 'bg-white'
                        )}
                    >
                        <div className={classNames('font-medium', index === trialIndex ? 'text-blue-700' : 'text-gray-800')}>
                            Trial {item.trial}
                        </div>
                        <div className="text-xs text-gray-500 truncate">
                            {formatPlayhead(item.t)}
                            {item.outcome === 'correct' && ' · correct'}
                            {item.outcome === 'incorrect' && ` · incorrect${item.choice ? ` ${item.choice}` : ''}`}
                            {!item.outcome && ' · in progress'}
                        </div>
                    </button>
                ))}
                {trials.length === 0 && (
                    <div className="p-2 text-gray-500">No trials</div>
                )}
            </div>
            <Bar title="Sessions" />
            <div className={stacked ? 'max-h-40 overflow-y-auto border-b border-gray-200' : 'flex-1 overflow-y-auto'}>
                {currentDir && !knownCurrent && (
                    <SessionRow
                        title={currentId || currentDir}
                        detail="open session"
                        selected={!selectedDir}
                        onClick={() => onSelectSession(currentDir)}
                    />
                )}
                {rows.map((row) => {
                    const dir = row[2];
                    const isCurrent = dir === currentDir;
                    const selected = isCurrent ? !selectedDir : selectedDir === dir;
                    return (
                        <SessionRow
                            key={dir}
                            title={row[0]}
                            detail={isCurrent ? 'open session' : String(row[1] ?? '')}
                            selected={selected}
                            onClick={() => onSelectSession(dir)}
                        />
                    );
                })}
                {rows.length === 0 && !currentDir && (
                    <div className="p-2 text-gray-500">No sessions</div>
                )}
            </div>
        </div>
    );
};

const SessionRow = ({ title, detail, selected, onClick }) => (
    <button
        type="button"
        onClick={onClick}
        className={classNames(
            'w-full text-left px-2 py-1 border-b border-gray-100 hover:bg-gray-100',
            selected ? 'bg-blue-50' : 'bg-white'
        )}
    >
        <div className={classNames('font-medium', selected ? 'text-blue-700' : 'text-gray-800')}>{title}</div>
        <div className="text-xs text-gray-500 truncate">{detail}</div>
    </button>
);

const Fact = ({ label, value }) => (
    <div className="flex justify-between gap-3 py-0.5">
        <dt className="text-gray-500">{label}</dt>
        <dd className="font-medium text-gray-900 text-right">{value}</dd>
    </div>
);

const LocationNumbers = ({
    playhead,
    start,
    facts,
    zone,
    sample,
    stats,
    zones,
    flow = false,
}) => {
    const elapsed = Number.isFinite(start) && Number.isFinite(playhead) ? playhead - start : null;
    const zoneRows = (zones || []).filter((zoneItem) => stats.zoneSeconds[zoneItem.id] != null);
    return (
        <div className={classNames(
            'bg-white',
            flow ? '' : 'h-full flex flex-col overflow-hidden'
        )}>
            <Bar title="Stats" />
            <dl className="px-2 py-1 text-sm">
                <Fact label="Date" value={formatPlayhead(playhead)} />
                <Fact label="Time" value={formatClock(elapsed ?? 0)} />
                <Fact label="Trial" value={facts.trial ?? '—'} />
                <Fact label="Phase" value={facts.phase ?? '—'} />
                <Fact label="Zone" value={zone?.id ?? '—'} />
                <Fact label="x" value={sample ? sample.cx.toFixed(3) : '—'} />
                <Fact label="y" value={sample ? sample.cy.toFixed(3) : '—'} />
            </dl>
            <Bar title="Up to playhead" />
            <div className={classNames(
                'px-2 py-1 text-sm',
                flow ? '' : 'flex-1 overflow-y-auto'
            )}>
                <dl>
                    <Fact label="Trials" value={stats.trials} />
                    <Fact label="Correct" value={stats.correct} />
                    <Fact label="Incorrect" value={stats.incorrect} />
                </dl>
                <div className="mt-2 text-xs font-semibold text-gray-500">Time in zone for current trial</div>
                <dl>
                    {zoneRows.map((zoneItem) => (
                        <Fact
                            key={zoneItem.key}
                            label={zoneItem.id}
                            value={stats.zonePending ? '…' : formatDuration(stats.zoneSeconds[zoneItem.id] || 0)}
                        />
                    ))}
                    {zoneRows.length === 0 && (
                        <div className="text-gray-400 py-1">No zones</div>
                    )}
                </dl>
            </div>
        </div>
    );
};

export const LocationView = ({ stacked = false }) => {
    const ctrlState = useSelector((state) => state.reptilearn.ctrlState);
    const currentDir = sessionDirName(ctrlState?.session?.data_dir);
    const currentId = ctrlState?.session?.id || null;

    const [sessions, setSessions] = React.useState([]);
    const [track, setTrack] = React.useState(null);
    const [error, setError] = React.useState(null);
    const [mode, setMode] = React.useState('live');
    const [playing, setPlaying] = React.useState(false);
    const [speed, setSpeed] = React.useState(1);
    const [playhead, setPlayhead] = React.useState(null);
    const [liveSample, setLiveSample] = React.useState(null);
    const [selectedDir, setSelectedDir] = React.useState(null);

    const selectedDirRef = React.useRef(null);
    const modeRef = React.useRef('live');
    const playingRef = React.useRef(false);
    const speedRef = React.useRef(1);
    const playheadRef = React.useRef(null);
    const requestSeq = React.useRef(0);
    const startRef = React.useRef(null);
    const endRef = React.useRef(null);
    const canLiveRef = React.useRef(false);

    const samples = track?.samples || [];
    const events = track?.events || [];
    const zones = track?.zones || [];
    const imageWidth = track?.image_width || 0;
    const imageHeight = track?.image_height || 0;
    const canLive = Boolean(track?.is_current);
    const start = Number.isFinite(track?.span_start) ? track.span_start : null;
    let end = Number.isFinite(track?.span_end) ? track.span_end : null;
    if (canLive && liveSample && Number.isFinite(liveSample.t)) {
        end = end == null ? liveSample.t : Math.max(end, liveSample.t);
    }

    startRef.current = start;
    endRef.current = end;
    canLiveRef.current = canLive;
    speedRef.current = speed;

    React.useEffect(() => {
        let cancel = false;
        const loadList = () => {
            api.session.get_list()
                .then((list) => {
                    if (!cancel) setSessions(Array.isArray(list) ? list : []);
                })
                .catch(() => {});
        };
        loadList();
        const id = setInterval(loadList, 8000);
        return () => {
            cancel = true;
            clearInterval(id);
        };
    }, []);

    const acceptTrack = React.useCallback((data) => {
        if (!data) return;
        if (data.error) {
            setError(data.error);
            return;
        }
        setError(null);
        const play = playheadRef.current;
        if (Number.isFinite(play) && Number.isFinite(data.at) && Math.abs(data.at - play) > 20) return;
        setTrack(data);
        if (!data.is_current) {
            if (modeRef.current !== 'controlled') {
                modeRef.current = 'controlled';
                setMode('controlled');
            }
            if (!Number.isFinite(playheadRef.current) && Number.isFinite(data.span_start)) {
                playheadRef.current = data.span_start;
                setPlayhead(data.span_start);
            }
            return;
        }
        if (modeRef.current === 'live') {
            const endT = Number.isFinite(data.span_end) ? data.span_end : null;
            if (endT != null && (playheadRef.current == null || playheadRef.current < endT)) {
                playheadRef.current = endT;
                setPlayhead(endT);
            }
        }
    }, []);

    const fetchTrack = React.useCallback((dir, at) => {
        const mine = requestSeq.current + 1;
        requestSeq.current = mine;
        return api.location.track(dir, Number.isFinite(at) ? at : null)
            .then((data) => {
                if (mine !== requestSeq.current || selectedDirRef.current !== dir) return null;
                return data;
            });
    }, []);

    React.useEffect(() => {
        let cancel = false;
        let busy = false;
        const load = () => {
            if (busy) return;
            busy = true;
            const dir = selectedDirRef.current;
            fetchTrack(dir, playheadRef.current)
                .then((data) => {
                    if (!cancel) acceptTrack(data);
                })
                .catch((err) => {
                    if (!cancel) setError(err.message || 'Could not load the track');
                })
                .finally(() => {
                    busy = false;
                });
        };
        load();
        const id = setInterval(load, TRACK_POLL_MS);
        return () => {
            cancel = true;
            clearInterval(id);
        };
    }, [currentDir, acceptTrack, fetchTrack]);

    React.useEffect(() => {
        if (mode !== 'live' || !canLive) return undefined;
        let cancel = false;
        const poll = () => {
            api.location.live()
                .then((data) => {
                    if (cancel || modeRef.current !== 'live') return;
                    const sample = data?.sample || null;
                    setLiveSample(sample);
                    if (sample && Number.isFinite(sample.t)) {
                        playheadRef.current = sample.t;
                        setPlayhead(sample.t);
                    }
                })
                .catch(() => {});
        };
        poll();
        const id = setInterval(poll, LIVE_POLL_MS);
        return () => {
            cancel = true;
            clearInterval(id);
        };
    }, [mode, canLive]);

    React.useEffect(() => {
        if (!playing || mode !== 'controlled') return undefined;
        let frame = 0;
        let last = performance.now();
        const tick = (now) => {
            const dt = Math.min(0.1, (now - last) / 1000);
            last = now;
            const barEnd = endRef.current;
            const barStart = startRef.current;
            if (Number.isFinite(barEnd) && Number.isFinite(playheadRef.current)) {
                let next = playheadRef.current + dt * speedRef.current;
                if (Number.isFinite(barStart) && next < barStart) next = barStart;
                if (next >= barEnd - END_EPSILON) {
                    next = barEnd;
                    playingRef.current = false;
                    playheadRef.current = next;
                    setPlayhead(next);
                    setPlaying(false);
                    if (canLiveRef.current) {
                        modeRef.current = 'live';
                        setMode('live');
                    }
                    return;
                }
                playheadRef.current = next;
                setPlayhead(next);
            }
            frame = requestAnimationFrame(tick);
        };
        frame = requestAnimationFrame(tick);
        return () => cancelAnimationFrame(frame);
    }, [playing, mode]);

    const onScrub = (value) => {
        if (!Number.isFinite(value)) return;
        playingRef.current = false;
        setPlaying(false);
        const barEnd = endRef.current;
        if (canLiveRef.current && Number.isFinite(barEnd) && value >= barEnd - END_EPSILON) {
            modeRef.current = 'live';
            setMode('live');
            playheadRef.current = barEnd;
            setPlayhead(barEnd);
            return;
        }
        modeRef.current = 'controlled';
        setMode('controlled');
        playheadRef.current = value;
        setPlayhead(value);
        fetchTrack(selectedDirRef.current, value)
            .then((data) => acceptTrack(data))
            .catch((err) => setError(err.message || 'Could not load the track'));
    };

    const onTogglePlay = () => {
        if (modeRef.current === 'live') return;
        const barEnd = endRef.current;
        if (
            !playingRef.current
            && canLiveRef.current
            && Number.isFinite(barEnd)
            && Number.isFinite(playheadRef.current)
            && playheadRef.current >= barEnd - END_EPSILON
        ) {
            modeRef.current = 'live';
            setMode('live');
            return;
        }
        playingRef.current = !playingRef.current;
        setPlaying(playingRef.current);
    };

    const onSelectTrial = (index) => {
        if (index == null) {
            const barEnd = endRef.current;
            if (canLiveRef.current && Number.isFinite(barEnd)) onScrub(barEnd);
            return;
        }
        const trial = trials[index];
        if (trial) onScrub(trial.t);
    };

    const onSelectSession = (dir) => {
        const followCurrent = Boolean(dir) && dir === currentDir;
        const nextSelected = followCurrent ? null : dir;
        selectedDirRef.current = nextSelected;
        setSelectedDir(nextSelected);
        playingRef.current = false;
        setPlaying(false);
        playheadRef.current = null;
        const requested = followCurrent ? null : dir;
        fetchTrack(requested, null)
            .then((data) => {
                if (!data || selectedDirRef.current !== nextSelected) return;
                setError(null);
                const at = data.is_current ? data.span_end : data.span_start;
                if (Number.isFinite(at)) {
                    playheadRef.current = at;
                    setPlayhead(at);
                }
                if (data.is_current) {
                    modeRef.current = 'live';
                    setMode('live');
                    setTrack(data);
                    return null;
                }
                modeRef.current = 'controlled';
                setMode('controlled');
                setLiveSample(null);
                if (!Number.isFinite(at)) {
                    setTrack(data);
                    return null;
                }
                return fetchTrack(requested, at);
            })
            .then((data) => {
                if (data) acceptTrack(data);
            })
            .catch((err) => setError(err.message || 'Could not load the session'));
    };

    const trials = trialList(events);
    const clock = playhead ?? end ?? 0;
    const trialIndex = trialIndexAt(trials, clock);
    const shownSample = mode === 'live' && liveSample
        ? liveSample
        : sampleAt(samples, clock);
    const held = positionHeld(shownSample, clock);
    const facing = facingAt(
        clock,
        events,
        zones,
        shownSample,
        Boolean(track?.has_point_d),
        imageWidth,
        imageHeight,
    );
    const facts = playbackFacts(clock, events);
    const zone = zoneAt(shownSample, zones, imageWidth, imageHeight);
    const baseStats = statsAt(clock, events, samples, zones, imageWidth, imageHeight);
    const zonePending = track?.zone_ready === false;
    const stats = zonePending
        ? { ...baseStats, zonePending: true }
        : {
            ...baseStats,
            zonePending: false,
            zoneSeconds: track?.zone_ready
                ? zoneSecondsFromSegments(track.zone_segments, clock, zones)
                : baseStats.zoneSeconds,
        };
    const doors = doorsAt(clock, events);
    const magnetDirection = magnetAt(clock, events);
    const foodCount = rewardsAt(clock, events);
    const trail = held ? [] : trailBefore(samples, clock);
    const displayFacing = shownSample ? facing : null;

    const player = (
        <LocationPlayer
            mode={mode}
            playing={playing}
            speed={speed}
            setSpeed={setSpeed}
            playhead={clock}
            start={start}
            end={end}
            onScrub={onScrub}
            canLive={canLive}
            canPlay={Number.isFinite(start) && Number.isFinite(end) && end - start > END_EPSILON}
            trials={trials}
            trialIndex={trialIndex}
            onTogglePlay={onTogglePlay}
            onSelectTrial={onSelectTrial}
            sessions={sessions}
            currentDir={currentDir}
            currentId={currentId}
            selectedDir={selectedDir}
            onSelectSession={onSelectSession}
            stacked={stacked}
        />
    );
    const numbers = (
        <LocationNumbers
            playhead={playhead}
            start={start}
            facts={facts}
            zone={zone}
            sample={shownSample}
            stats={stats}
            zones={zones}
            flow={stacked}
        />
    );
    const schematic = (
        <div className="h-full flex flex-col" style={{ background: '#1d6fa8' }}>
            {error && (
                <div className="bg-red-100 text-red-800 text-xs px-2 py-1 shrink-0">{error}</div>
            )}
            {track?.ready === false && !error && (
                <div className="bg-amber-100 text-amber-900 text-xs px-2 py-1 shrink-0">Loading session track…</div>
            )}
            {held && !error && (
                <div className="bg-amber-100 text-amber-900 text-xs px-2 py-1 shrink-0">
                    No position recorded. The turtle is holding the last detection.
                </div>
            )}
            <div className="flex-1 min-h-0">
                <ArenaSchematic
                    zones={zones}
                    doors={doors}
                    trail={trail}
                    sample={shownSample}
                    facing={displayFacing || WALLS.back}
                    held={held}
                    magnetDirection={magnetDirection}
                    foodCount={foodCount}
                />
            </div>
        </div>
    );

    if (stacked) {
        return (
            <div className="h-full flex flex-col overflow-hidden">
                <div
                    className="w-full max-h-[62%] shrink-0 min-h-0 overflow-hidden"
                    style={{ aspectRatio: '4 / 3' }}
                >
                    {schematic}
                </div>
                <div className="flex-1 min-h-0 overflow-y-auto border-t border-gray-400 bg-white">
                    {player}
                    {numbers}
                </div>
            </div>
        );
    }

    return (
        <ReflexContainer orientation="vertical" windowResizeAware={true} className="flex-1 min-h-0">
            <ReflexElement flex={0.65} style={{ background: '#1d6fa8' }}>
                {schematic}
            </ReflexElement>
            <ReflexSplitter />
            <ReflexElement minSize={200}>
                <ReflexContainer orientation="horizontal">
                    <ReflexElement minSize={260} style={{ overflow: 'hidden' }}>
                        {player}
                    </ReflexElement>
                    <ReflexSplitter />
                    <ReflexElement minSize={220} style={{ overflow: 'hidden' }}>
                        {numbers}
                    </ReflexElement>
                </ReflexContainer>
            </ReflexElement>
        </ReflexContainer>
    );
};
