import React from 'react';
import { Dialog, Transition } from '@headlessui/react';
import { useDispatch, useSelector } from 'react-redux';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { removeAnalysisFigure, setAnalysisFigureVisible } from '../store/reptilearn_slice.js';
import { AnalysisExportModal } from './analysis_export_modal.js';

const formatStats = (stats) => {
    if (!stats?.summary) {
        return null;
    }
    const { summary, feeder, a_to_b: aToB } = stats;
    const parts = [
        `${summary.successes}/${summary.total} correct (${summary.success_pct.toFixed(1)}%)`,
    ];
    if (feeder) {
        const leftTotal = feeder.left_total ?? feeder.left;
        const rightTotal = feeder.right_total ?? feeder.right;
        parts.push(
            `Left ${feeder.left}/${leftTotal}, Right ${feeder.right}/${rightTotal}`,
        );
    }
    if (aToB?.count) {
        parts.push(`A→B mean ${aToB.mean_formatted}, median ${aToB.median_formatted}`);
    }
    return parts.join(" · ");
};

export const AnalysisPopups = () => {
    const dispatch = useDispatch();
    const figures = useSelector((state) => state.reptilearn.analysisFigures);
    const [exportOpen, setExportOpen] = React.useState(false);
    const [exportFigures, setExportFigures] = React.useState([]);
    const visibleFigure = figures
        .filter((figure) => figure.isVisible)
        .sort((a, b) => b.createdAt - a.createdAt)[0] || null;

    const minimize = () => {
        if (!visibleFigure) {
            return;
        }
        dispatch(setAnalysisFigureVisible({ id: visibleFigure.id, isVisible: false }));
    };

    const dismiss = () => {
        if (!visibleFigure) {
            return;
        }
        dispatch(removeAnalysisFigure(visibleFigure.id));
    };

    return (
        <>
        <Transition.Root show={!!visibleFigure} as={React.Fragment}>
            <Dialog as="div" className="relative z-[200]" onClose={minimize}>
                <Transition.Child
                    as={React.Fragment}
                    enter="ease-out duration-200"
                    enterFrom="opacity-0"
                    enterTo="opacity-100"
                    leave="ease-in duration-150"
                    leaveFrom="opacity-100"
                    leaveTo="opacity-0"
                >
                    <div className="fixed inset-0 bg-gray-900/70 transition-opacity" />
                </Transition.Child>

                <div className="fixed inset-0 z-10 overflow-y-auto">
                    <div className="flex min-h-full items-center justify-center p-4 sm:p-6">
                        <Transition.Child
                            as={React.Fragment}
                            enter="ease-out duration-200"
                            enterFrom="opacity-0 translate-y-4 sm:scale-95"
                            enterTo="opacity-100 translate-y-0 sm:scale-100"
                            leave="ease-in duration-150"
                            leaveFrom="opacity-100 translate-y-0 sm:scale-100"
                            leaveTo="opacity-0 translate-y-4 sm:scale-95"
                        >
                            <Dialog.Panel className="relative w-full max-w-5xl transform overflow-hidden rounded-lg bg-white text-left shadow-2xl transition-all">
                                <button
                                    type="button"
                                    className="absolute right-4 top-4 text-gray-500 hover:text-gray-800"
                                    title="Minimize"
                                    onClick={minimize}
                                >
                                    <FontAwesomeIcon icon="xmark" className="h-5 w-5" />
                                </button>

                                <div className="px-6 pt-8 pb-4 text-center">
                                    <Dialog.Title className="text-2xl font-bold text-gray-900 pr-8">
                                        {visibleFigure?.title}
                                    </Dialog.Title>
                                    {visibleFigure?.subtitle ? (
                                        <p className="mt-2 text-sm text-gray-600">
                                            {visibleFigure.subtitle}
                                        </p>
                                    ) : null}
                                    {formatStats(visibleFigure?.stats) ? (
                                        <p className="mt-3 text-sm text-gray-700">
                                            {formatStats(visibleFigure.stats)}
                                        </p>
                                    ) : null}
                                </div>

                                <div className="px-6 pb-4 max-h-[65vh] overflow-auto bg-gray-50 border-y border-gray-200">
                                    {visibleFigure ? (
                                        <img
                                            src={visibleFigure.imageDataUrl}
                                            alt={visibleFigure.title}
                                            className="max-w-full h-auto mx-auto"
                                        />
                                    ) : null}
                                </div>

                                <div className="px-6 py-5 flex flex-col items-center gap-3 bg-white">
                                    <button
                                        type="button"
                                        className="w-full max-w-md rounded-md bg-blue-700 px-4 py-3 text-white font-semibold hover:bg-blue-800"
                                        onClick={minimize}
                                    >
                                        Minimize
                                    </button>
                                    <button
                                        type="button"
                                        className="w-full max-w-md rounded-md border border-gray-300 px-4 py-3 text-gray-800 font-semibold hover:bg-gray-50"
                                        onClick={() => {
                                            setExportFigures(visibleFigure ? [visibleFigure] : []);
                                            setExportOpen(true);
                                        }}
                                    >
                                        Export to folder...
                                    </button>
                                    <button
                                        type="button"
                                        className="text-sm text-gray-700 underline hover:text-gray-900"
                                        onClick={dismiss}
                                    >
                                        Remove saved figure
                                    </button>
                                </div>
                            </Dialog.Panel>
                        </Transition.Child>
                    </div>
                </div>
            </Dialog>
        </Transition.Root>

            <AnalysisExportModal
                open={exportOpen}
                setOpen={setExportOpen}
                figures={exportFigures}
            />
        </>
    );
};

export default AnalysisPopups;
