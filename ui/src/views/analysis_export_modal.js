import React from 'react';
import { api } from '../api.js';
import { ANALYSIS_EXPORT_DIR_KEY, figureToExportPayload } from '../analysis_figures.js';
import RLButton from './ui/button.js';
import RLInput from './ui/input.js';
import RLModal from './ui/modal.js';

const DEFAULT_EXPORT_SUBDIR = "analysis_exports";

export const AnalysisExportModal = ({ open, setOpen, figures, onExported, onError }) => {
    const [outputDir, setOutputDir] = React.useState("");
    const [isExporting, setIsExporting] = React.useState(false);
    const [status, setStatus] = React.useState(null);

    React.useEffect(() => {
        if (!open) {
            return;
        }

        setStatus(null);
        const savedDir = localStorage.getItem(ANALYSIS_EXPORT_DIR_KEY);
        if (savedDir) {
            setOutputDir(savedDir);
            return;
        }

        api.get_config("session_data_root")
            .then((sessionRoot) => {
                const root = String(sessionRoot || "").replace(/\/$/, "");
                setOutputDir(root ? `${root}/${DEFAULT_EXPORT_SUBDIR}` : "");
            })
            .catch(() => {
                setOutputDir("");
            });
    }, [open]);

    const exportFigures = async () => {
        if (!figures?.length) {
            setStatus("No figures selected to export.");
            return;
        }
        if (!outputDir.trim()) {
            setStatus("Enter an export folder path.");
            return;
        }

        setIsExporting(true);
        setStatus(null);
        try {
            const result = await api.analysis.exportFigures(
                outputDir.trim(),
                figures.map(figureToExportPayload),
            );
            if (result.error) {
                throw new Error(result.error);
            }

            localStorage.setItem(ANALYSIS_EXPORT_DIR_KEY, outputDir.trim());
            setStatus(`Saved ${result.count} figure(s) to ${result.output_dir}`);
            onExported?.(result);
        } catch (err) {
            console.error(err);
            const message = err.message || "Export failed";
            setStatus(message);
            onError?.(message);
        } finally {
            setIsExporting(false);
        }
    };

    return (
        <RLModal
            open={open}
            setOpen={setOpen}
            header="Export analysis figures"
            sizeClasses="max-w-xl w-11/12"
            layerClass="z-[220]"
            actions={
                <>
                    <RLButton.ModalButton onClick={() => setOpen(false)} disabled={isExporting}>
                        Cancel
                    </RLButton.ModalButton>
                    <RLButton.ModalButton
                        onClick={exportFigures}
                        disabled={isExporting || !figures?.length}
                        colorClasses="text-blue-700"
                    >
                        {isExporting ? "Exporting..." : "Export"}
                    </RLButton.ModalButton>
                </>
            }
        >
            <div className="flex flex-col gap-3 py-2">
                <p className="text-gray-700">
                    Save {figures?.length || 0} PNG figure(s) to a folder on the ReptiLearn machine.
                </p>
                <label className="flex flex-col gap-1 text-left">
                    <span className="font-medium text-gray-800">Export folder</span>
                    <RLInput.Text
                        value={outputDir}
                        onChange={(event) => setOutputDir(event.target.value)}
                        placeholder="/data/reptilearn/analysis_exports"
                        className="w-full"
                    />
                </label>
                {figures?.length ? (
                    <ul className="text-xs text-gray-600 max-h-32 overflow-y-auto border border-gray-200 rounded-md p-2">
                        {figures.map((figure) => (
                            <li key={figure.id}>{figure.title}</li>
                        ))}
                    </ul>
                ) : null}
                {status ? (
                    <p className={status.startsWith("Saved") ? "text-green-700" : "text-red-700"}>
                        {status}
                    </p>
                ) : null}
            </div>
        </RLModal>
    );
};

export default AnalysisExportModal;
