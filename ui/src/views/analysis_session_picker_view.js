import React from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { api } from '../api.js';
import RLButton from './ui/button.js';
import RLModal from './ui/modal.js';
import { setAnalysisSelectedSessions } from '../store/reptilearn_slice.js';

export const AnalysisSessionPickerView = ({ open, setOpen }) => {
    const dispatch = useDispatch();
    const selectedIds = useSelector((state) => state.reptilearn.analysisSelectedSessionIds);
    const [sessionList, setSessionList] = React.useState(null);
    const [localSelection, setLocalSelection] = React.useState([]);

    React.useEffect(() => {
        if (!open) {
            return;
        }
        setLocalSelection([...selectedIds]);
        api.session.get_list().then((res) => setSessionList(res));
    }, [open, selectedIds]);

    const toggleSession = (session) => {
        const sessionId = session[0];
        setLocalSelection((current) => (
            current.includes(sessionId)
                ? current.filter((id) => id !== sessionId)
                : [...current, sessionId]
        ));
    };

    const selectAll = () => {
        if (!sessionList) {
            return;
        }
        setLocalSelection(sessionList.map((session) => session[0]));
    };

    const clearAll = () => {
        setLocalSelection([]);
    };

    const saveSelection = () => {
        dispatch(setAnalysisSelectedSessions(localSelection));
        setOpen(false);
    };

    const content = sessionList ? (
        <div className="flex flex-col gap-3 min-h-0 flex-grow">
            <div className="flex gap-2">
                <RLButton.ModalButton onClick={selectAll}>Select all</RLButton.ModalButton>
                <RLButton.ModalButton onClick={clearAll}>Clear</RLButton.ModalButton>
                <span className="ml-auto self-center text-gray-600">
                    {localSelection.length} selected
                </span>
            </div>
            <div className="overflow-y-auto border border-gray-300 rounded-md flex-grow min-h-[240px]">
                <table className="table w-full">
                    <tbody>
                        {[...sessionList].reverse().map((session) => {
                            const checked = localSelection.includes(session[0]);
                            return (
                                <tr
                                    key={session[2]}
                                    className="border-b border-gray-200 hover:bg-gray-50 cursor-pointer"
                                    onClick={() => toggleSession(session)}
                                >
                                    <td className="px-3 py-2 w-10">
                                        <input
                                            type="checkbox"
                                            checked={checked}
                                            readOnly
                                        />
                                    </td>
                                    <td className="px-3 py-2 font-medium">{session[0]}</td>
                                    <td className="px-3 py-2 text-gray-600">{session[1]}</td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    ) : (
        "Loading..."
    );

    return (
        <RLModal
            open={open}
            setOpen={setOpen}
            header="Select sessions for analysis"
            sizeClasses="max-w-2xl w-11/12 max-h-[80vh]"
            contentOverflowClass="overflow-hidden flex flex-col min-h-[320px]"
            actions={
                <>
                    <RLButton.ModalButton onClick={() => setOpen(false)}>Cancel</RLButton.ModalButton>
                    <RLButton.ModalButton
                        onClick={saveSelection}
                        disabled={localSelection.length === 0}
                        colorClasses="text-blue-700"
                    >
                        Use selected sessions
                    </RLButton.ModalButton>
                </>
            }
        >
            {content}
        </RLModal>
    );
};

export default AnalysisSessionPickerView;
