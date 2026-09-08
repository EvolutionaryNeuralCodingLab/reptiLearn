export const ANALYSIS_EXPORT_DIR_KEY = "analysisExportDir";

const sanitizeFilenamePart = (value) => (
    String(value)
        .replace(/[^\w.-]+/g, "_")
        .replace(/^_+|_+$/g, "")
        || "figure"
);

export const figureExportFilename = (figure) => {
    const stamp = new Date(figure.createdAt).toISOString().slice(0, 19).replace(/[:T]/g, "-");
    return `${sanitizeFilenamePart(figure.panel)}_${sanitizeFilenamePart(figure.bulkName)}_${stamp}.png`;
};

export const figureToExportPayload = (figure) => ({
    filename: figureExportFilename(figure),
    image: figure.imageDataUrl.replace(/^data:image\/png;base64,/, ""),
});
