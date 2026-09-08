import React from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { useSelector } from 'react-redux';

import { StreamGroupView } from './stream_view.js';
import { ExperimentView } from './experiment_view.js';
import { StateView } from './state_view.js';
import { LogView } from './log_view.js';
import { VideoRecordView } from './video_record_view.js';
import { ArenaControlView } from './arena_control_view.js';
import { SessionMenuView } from './session_menu_view.js';
import { TasksView } from './tasks_view.js';
import { AddStreamButton } from './add_stream_button.js';
import { MainMenu } from './main_menu.js';
import { AnalysisMenuView } from './analysis_menu_view.js';
import { AnalysisPopups } from './analysis_popup_view.js';
import { VoiceView } from './voice_view.js';
import { ConnectionSettingsModal } from './connection_settings_view.js';
import { classNames } from './ui/common.js';
import { SocketContext } from '../socket.js';
import { getApiUrl } from '../api.js';

const TABS = [
    { id: 'main', label: 'Main', icon: 'video' },
    { id: 'control', label: 'Control', icon: 'sliders' },
];

const PhoneTopBar = ({ onOpenConnection }) => {
    const { socket } = React.useContext(SocketContext);
    const connected = Boolean(socket?.connected);
    const serverLabel = getApiUrl() || 'same origin';

    return (
        <div className="flex items-center gap-2 border-b-2 border-b-gray-400 bg-gray-200 px-2 py-1.5 text-sm shrink-0">
            <div className="font-semibold truncate">ReptiLearn</div>
            <button
                type="button"
                className="ml-auto flex items-center gap-1.5 text-xs text-gray-700 truncate max-w-[55%]"
                onClick={onOpenConnection}
                title={serverLabel}
            >
                <span className={classNames(
                    'inline-block h-2 w-2 rounded-full shrink-0',
                    connected ? 'bg-green-500' : 'bg-red-500'
                )} />
                <span className="truncate">{connected ? 'Connected' : 'Disconnected'}</span>
            </button>
            <MainMenu />
        </div>
    );
};

const PhoneBottomNav = ({ tab, setTab }) => (
    <nav className="flex border-t-2 border-t-gray-400 bg-gray-200 shrink-0 safe-bottom">
        {TABS.map((t) => {
            const active = tab === t.id;
            return (
                <button
                    key={t.id}
                    type="button"
                    onClick={() => setTab(t.id)}
                    className={classNames(
                        'flex-1 flex flex-col items-center justify-center gap-0.5 py-2 text-xs',
                        active ? 'text-green-700 font-semibold bg-gray-100' : 'text-gray-600'
                    )}
                >
                    <FontAwesomeIcon icon={t.icon} className="h-4 w-4" />
                    {t.label}
                </button>
            );
        })}
    </nav>
);

const MainToolbar = () => (
    <div className="flex flex-wrap items-stretch gap-1 p-1.5 border-b border-gray-400 bg-gray-200 text-sm shrink-0 overflow-x-auto">
        <SessionMenuView />
        <ArenaControlView />
        <VideoRecordView />
        <TasksView />
        <AnalysisMenuView />
        <AddStreamButton />
        <VoiceView />
    </div>
);

export const PhoneMainView = () => {
    const [tab, setTab] = React.useState('main');
    const [connectionOpen, setConnectionOpen] = React.useState(false);
    const ctrlState = useSelector((state) => state.reptilearn.ctrlState);
    const isRunning = Boolean(ctrlState?.session?.is_running);

    return (
        <div className="text-sm flex flex-col h-[100dvh] font-[Lato] overflow-hidden">
            <div id="portalTarget"></div>
            <PhoneTopBar onOpenConnection={() => setConnectionOpen(true)} />
            <ConnectionSettingsModal open={connectionOpen} setOpen={setConnectionOpen} />
            <AnalysisPopups />
            <div className="flex-1 min-h-0 overflow-hidden relative">
                {tab === 'main' && (
                    <div className="h-full flex flex-col overflow-hidden">
                        <MainToolbar />
                        <div className="flex-1 min-h-0 overflow-y-auto bg-gray-700">
                            <StreamGroupView />
                        </div>
                        <div className="h-[32%] min-h-[100px] max-h-[40%] border-t border-gray-400 overflow-hidden shrink-0 bg-white">
                            <StateView />
                        </div>
                    </div>
                )}
                {tab === 'control' && (
                    <div className="h-full flex flex-col overflow-hidden">
                        {isRunning && (
                            <div className="bg-green-100 text-green-800 text-xs px-2 py-1 border-b border-green-300 shrink-0">
                                Experiment running
                            </div>
                        )}
                        <div className="flex-1 min-h-0 overflow-hidden">
                            <ExperimentView />
                        </div>
                        <div className="h-[40%] min-h-[120px] border-t border-gray-300 overflow-hidden shrink-0">
                            <LogView />
                        </div>
                    </div>
                )}
            </div>
            <PhoneBottomNav tab={tab} setTab={setTab} />
        </div>
    );
};
