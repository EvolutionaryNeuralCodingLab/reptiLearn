import React from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { api } from '../api.js';
import { SocketContext } from '../socket.js';
import RLMenu from './ui/menu.js';
import RLInput from './ui/input.js';
import { AnalysisSessionPickerView } from './analysis_session_picker_view.js';
import { AnalysisExportModal } from './analysis_export_modal.js';
import { cacheAnalysisFigure, pruneStaleAnalysisFigures, setAnalysisFigureVisible } from '../store/reptilearn_slice.js';

const PANELS = [
    { key: "success", label: "Success rate" },
    { key: "learning_curve", label: "Learning curve" },
    { key: "feeder", label: "Right / left split" },
    { key: "a_to_b", label: "A→B travel time" },
    { key: "all", label: "Run all panels" },
];

const SCOPES = [
    { key: "current", label: "Current session" },
    { key: "selected", label: "Selected sessions" },
    { key: "all_train", label: "All train sessions" },
    { key: "all_exp", label: "All exp sessions" },
];

const ERROR_TOAST_MS = 5000;
export const ANALYSIS_FIGURE_VERSION = 17;

const scopeLabel = (scopeKey) => SCOPES.find((scope) => scope.key === scopeKey)?.label || scopeKey;

const buildCacheKey = (panel, scope, sessionIds = [], trialRange = "") => {
    let base;
    if (scope === "selected") {
        base = `${panel}:selected:${[...sessionIds].sort().join(",")}`;
    } else {
        base = `${panel}:${scope}`;
    }
    const trimmedRange = String(trialRange || "").trim();
    if (trimmedRange) {
        base = `${base}:trials=${trimmedRange}`;
    }
    return `v${ANALYSIS_FIGURE_VERSION}:${base}`;
};

const buildBulkName = (scope, session, sessionIds) => {
    if (scope === "current") {
        return session?.id || "current";
    }
    if (scope === "selected") {
        if (sessionIds.length === 1) {
            return sessionIds[0];
        }
        return `selected (${sessionIds.length})`;
    }
    return scopeLabel(scope);
};

export const AnalysisMenuView = () => {
    const { socket } = React.useContext(SocketContext);
    const dispatch = useDispatch();
    const session = useSelector((state) => state.reptilearn.ctrlState?.session);
    const selectedSessionIds = useSelector((state) => state.reptilearn.analysisSelectedSessionIds);
    const cachedFigures = useSelector((state) => state.reptilearn.analysisFigures);
    const [isRunning, setIsRunning] = React.useState(false);
    const [error, setError] = React.useState(null);
    const [openPicker, setOpenPicker] = React.useState(false);
    const [exportOpen, setExportOpen] = React.useState(false);
    const [trialRange, setTrialRange] = React.useState("");

    React.useEffect(() => {
        dispatch(pruneStaleAnalysisFigures(ANALYSIS_FIGURE_VERSION));
    }, [dispatch]);

    React.useEffect(() => {
        if (!error) {
            return undefined;
        }
        const timer = window.setTimeout(() => setError(null), ERROR_TOAST_MS);
        return () => window.clearTimeout(timer);
    }, [error]);

    const runAnalysis = async (panel, scope, sessionIds = []) => {
        if (scope === "selected" && sessionIds.length === 0) {
            setOpenPicker(true);
            return;
        }

        setIsRunning(true);
        setError(null);
        const bulkName = buildBulkName(scope, session, sessionIds);

        try {
            const result = await api.analysis.magnetoreception(panel, {
                scope,
                sessionIds,
                bulkName,
                trialRange,
            });
            if (result.error) {
                throw new Error(result.error);
            }

            const cacheKey = buildCacheKey(panel, scope, sessionIds, trialRange);
            const panelLabel = result.stats?.panel_label || panel;
            const trimmedTrialRange = String(trialRange || "").trim();
            const scopeSubtitle = scope === "selected"
                ? `${scopeLabel(scope)}: ${sessionIds.join(", ")}`
                : scopeLabel(scope);
            const statusLine = result.stats?.trial_status_line;
            const subtitleParts = [scopeSubtitle];
            if (trimmedTrialRange) {
                subtitleParts.push(`trials ${trimmedTrialRange}`);
            }
            if (statusLine) {
                subtitleParts.push(statusLine);
            }
            const figure = {
                id: `${cacheKey}:${Date.now()}`,
                cacheKey,
                panel,
                scope,
                sessionIds: [...sessionIds],
                bulkName,
                trialRange: trimmedTrialRange,
                title: result.stats?.label || `${panelLabel} · ${bulkName}`,
                subtitle: subtitleParts.join(" · "),
                imageDataUrl: `data:image/png;base64,${result.image}`,
                stats: result.stats,
                isVisible: true,
                createdAt: Date.now(),
            };
            dispatch(cacheAnalysisFigure(figure));
        } catch (err) {
            console.error(err);
            setError(err.message || "Analysis failed");
        } finally {
            setIsRunning(false);
        }
    };

    // Voice commands: the backend broadcasts "voice_analysis" when a spoken
    // phrase matches the analysis allow-list. The ref avoids re-subscribing on
    // every render while still calling the latest runAnalysis closure.
    const runAnalysisRef = React.useRef(runAnalysis);
    runAnalysisRef.current = runAnalysis;

    React.useEffect(() => {
        const handler = (data) => {
            const { panel, scope } = typeof data === 'string' ? JSON.parse(data) : data;
            if (!panel) {
                return;
            }
            runAnalysisRef.current(panel, scope || 'current', []);
        };
        if (!socket) return undefined;
        socket.on('voice_analysis', handler);
        return () => socket.off('voice_analysis', handler);
    }, [socket]);

    const showCachedFigure = (figure) => {
        dispatch(setAnalysisFigureVisible({ id: figure.id, isVisible: true }));
    };

    const savedFigures = [...cachedFigures].sort((a, b) => b.createdAt - a.createdAt);

    return (
        <>
            <RLMenu button={<RLMenu.TopBarMenuButton title="Analysis" />}>
                <RLMenu.ButtonItem onClick={() => setOpenPicker(true)}>
                    Choose sessions...
                </RLMenu.ButtonItem>
                <RLMenu.StaticItem>
                    {selectedSessionIds.length
                        ? `${selectedSessionIds.length} session(s) selected`
                        : "No sessions selected"}
                </RLMenu.StaticItem>
                <RLMenu.SeparatorItem />
                <RLMenu.StaticItem>
                    <div
                        className="flex flex-col gap-1"
                        onClick={(event) => event.stopPropagation()}
                        onKeyDown={(event) => event.stopPropagation()}
                    >
                        <span className="text-xs text-slate-600">Trial range (optional)</span>
                        <RLInput.Text
                            value={trialRange}
                            onChange={(event) => setTrialRange(event.target.value)}
                            placeholder="all · 50 · 120:170"
                            disabled={isRunning}
                        />
                    </div>
                </RLMenu.StaticItem>
                <RLMenu.SeparatorItem />

                {SCOPES.map((scope) => (
                    <React.Fragment key={scope.key}>
                        <RLMenu.HeaderItem>{scope.label}</RLMenu.HeaderItem>
                        {PANELS.map((panel) => (
                            <RLMenu.ButtonItem
                                key={`${scope.key}:${panel.key}`}
                                disabled={
                                    isRunning
                                    || (scope.key === "current" && !session)
                                    || (scope.key === "selected" && selectedSessionIds.length === 0)
                                }
                                onClick={() => runAnalysis(
                                    panel.key,
                                    scope.key,
                                    scope.key === "selected" ? selectedSessionIds : []
                                )}
                            >
                                {panel.label}
                            </RLMenu.ButtonItem>
                        ))}
                        <RLMenu.SeparatorItem />
                    </React.Fragment>
                ))}

                {savedFigures.length > 0 ? (
                    <>
                        <RLMenu.HeaderItem>Show saved figures</RLMenu.HeaderItem>
                        {savedFigures.map((figure) => (
                            <RLMenu.ButtonItem
                                key={`show:${figure.id}`}
                                onClick={() => showCachedFigure(figure)}
                            >
                                {figure.isVisible ? "● " : "○ "}
                                {figure.title}
                            </RLMenu.ButtonItem>
                        ))}
                        <RLMenu.SeparatorItem />
                        <RLMenu.ButtonItem onClick={() => setExportOpen(true)}>
                            Export saved figures...
                        </RLMenu.ButtonItem>
                    </>
                ) : (
                    <RLMenu.StaticItem>No saved figures yet</RLMenu.StaticItem>
                )}
            </RLMenu>

            <AnalysisSessionPickerView open={openPicker} setOpen={setOpenPicker} />
            <AnalysisExportModal
                open={exportOpen}
                setOpen={setExportOpen}
                figures={savedFigures}
            />

            {error ? (
                <div className="fixed top-12 right-4 z-[210] bg-red-100 border border-red-400 text-red-800 px-3 py-2 rounded shadow">
                    {error}
                </div>
            ) : null}
            {isRunning ? (
                <div className="fixed top-12 right-4 z-[210] bg-blue-100 border border-blue-400 text-blue-800 px-3 py-2 rounded shadow">
                    Running analysis...
                </div>
            ) : null}
        </>
    );
};

export default AnalysisMenuView;
