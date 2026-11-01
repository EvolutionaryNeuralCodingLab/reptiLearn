import React from 'react';
import { ReflexContainer, ReflexSplitter, ReflexElement } from 'react-reflex';
import 'react-reflex/styles.css';

import { StreamGroupView } from './stream_view.js';
import { LocationView } from './location_view.js';
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
import { PhoneMainView } from './phone_view.js';
import { useIsMobile } from '../hooks/use_media_query.js';
import { classNames } from './ui/common.js';

const WORKSPACES = [
    { id: 'stream', label: 'Stream' },
    { id: 'location', label: 'Location' },
];

const WorkspaceSwitch = ({ tab, setTab }) => (
    <div className="flex flex-row border-b-2 border-gray-300 bg-gray-100 shrink-0">
        {WORKSPACES.map((item) => (
            <button
                key={item.id}
                type="button"
                onClick={() => setTab(item.id)}
                className={classNames(
                    'px-3 py-1 text-sm font-medium',
                    tab === item.id
                        ? 'bg-white text-blue-600'
                        : 'text-gray-700 hover:bg-gray-200'
                )}
            >
                {item.label}
            </button>
        ))}
    </div>
);

export const TopBar = () => {
    return (
        <div className='border-b-2 border-b-gray-400 bg-gray-200 flex w-full overflow-visible text-sm'>
            <MainMenu/>
            <VideoRecordView/>
            <TasksView/>
            <ArenaControlView/>
            <SessionMenuView/>
            <AnalysisMenuView/>
            <AddStreamButton/>
            <VoiceView/>
        </div>
    );
};

const DesktopMainView = () => {
    const [workspace, setWorkspace] = React.useState('stream');
    return (
    <div className="text-sm flex flex-col h-screen font-[Lato]">
        <div id="portalTarget"></div>
        <TopBar></TopBar>
        <WorkspaceSwitch tab={workspace} setTab={setWorkspace} />
        <AnalysisPopups />
        {workspace === 'location' ? (
            <div className="flex flex-col flex-1 min-h-0">
                <LocationView />
            </div>
        ) : (
        <ReflexContainer orientation="horizontal" windowResizeAware={true} className='flex flex-grow'>
            <ReflexElement>
                <ReflexContainer orientation="vertical" windowResizeAware={true}>
                    <ReflexElement flex={0.65} className="bg-gray-700">
                        <StreamGroupView />
                    </ReflexElement>
                    <ReflexSplitter />
                    <ReflexElement minSize={422}>
                        <ReflexContainer orientation="horizontal">
                            <ReflexElement minSize={26} style={{ overflow: "hidden" }}>
                                <ExperimentView/>
                            </ReflexElement>
                            <ReflexSplitter />
                            <ReflexElement minSize={26} style={{ overflow: "hidden" }}>
                                <StateView/>
                            </ReflexElement>
                        </ReflexContainer>
                    </ReflexElement>
                </ReflexContainer>
            </ReflexElement>
            <ReflexSplitter />
            <ReflexElement minSize={26} flex={0.2} style={{ overflow: "hidden" }}>
                <LogView />
            </ReflexElement>
        </ReflexContainer>
        )}
    </div>
    );
};

export const MainView = () => {
    const isMobile = useIsMobile();
    return isMobile ? <PhoneMainView /> : <DesktopMainView />;
};
