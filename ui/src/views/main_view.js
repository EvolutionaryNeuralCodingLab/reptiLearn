import { ReflexContainer, ReflexSplitter, ReflexElement } from 'react-reflex';
import 'react-reflex/styles.css';

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
import { PhoneMainView } from './phone_view.js';
import { useIsMobile } from '../hooks/use_media_query.js';

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

const DesktopMainView = () => (
    <div className="text-sm flex flex-col h-screen font-[Lato]">
        <div id="portalTarget"></div>
        <TopBar></TopBar>
        <AnalysisPopups />
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
    </div>
);

export const MainView = () => {
    const isMobile = useIsMobile();
    return isMobile ? <PhoneMainView /> : <DesktopMainView />;
};
