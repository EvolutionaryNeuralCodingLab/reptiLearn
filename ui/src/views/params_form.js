import React from 'react';
import RLInput from './ui/input.js';

export const MAG_PARAM_EXPERIMENTS = new Set([
    'magnetoreception_exp',
    'magnetoreception_train',
    'magnetoreception_exp_v2',
    'magnetoreception_train_v2',
    'onboarding',
    'magnets_onboarding',
]);

const CAMERA_KEYS = ['bbox_obs_id', 'image_source_id'];
const DETECTION_KEYS = [
    'zone_confirm_frames',
    'zone_confirm_seconds',
    'centroid_smoothing_alpha',
];

const humanize = (key) => {
    if (key.startsWith('point_')) {
        return `Point ${key.slice('point_'.length).toUpperCase()}`;
    }
    const words = key.replace(/_/g, ' ');
    return words.charAt(0).toUpperCase() + words.slice(1);
};

const isZoneParam = (key, value) => (
    key.startsWith('point_')
    && value
    && typeof value === 'object'
    && Array.isArray(value.location)
);

const Field = ({ label, value, disabled, wide, onCommit }) => {
    const shown = value == null ? '' : String(value);
    const [text, setText] = React.useState(shown);

    React.useEffect(() => {
        setText(shown);
    }, [shown]);

    return (
        <label className={wide
            ? "flex flex-col gap-0.5 text-xs text-gray-500 min-w-[12rem] flex-1"
            : "flex flex-col gap-0.5 text-xs text-gray-500"}>
            {label}
            <RLInput.Text
                value={text}
                disabled={disabled}
                className={wide ? 'w-full h-[26px]' : 'w-24 h-[26px]'}
                onChange={(event) => setText(event.target.value)}
                onBlur={() => {
                    if (text === shown) return;
                    if (onCommit(text) === false) setText(shown);
                }}
            />
        </label>
    );
};

const Section = ({ title, children }) => (
    <section className="mb-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">{title}</h3>
        {children}
    </section>
);

const parseNumber = (text, { allowEmpty = false } = {}) => {
    const trimmed = text.trim();
    if (trimmed === '') return allowEmpty ? null : NaN;
    const value = Number(trimmed);
    return Number.isFinite(value) ? value : NaN;
};

export const ParamsForm = ({ params, disabled, onCommit }) => {
    if (!params) return null;

    const zoneKeys = Object.keys(params)
        .filter((key) => isZoneParam(key, params[key]))
        .sort();
    const cameraKeys = CAMERA_KEYS.filter((key) => key in params);
    const detectionKeys = DETECTION_KEYS.filter((key) => key in params);
    const used = new Set([...zoneKeys, ...cameraKeys, ...detectionKeys]);
    const protocolKeys = Object.keys(params).filter((key) => !used.has(key));

    const commitZoneNumber = (key, field, index, text) => {
        const value = parseNumber(text);
        if (!Number.isFinite(value)) return false;
        const zone = { ...params[key] };
        if (field === 'location') {
            zone.location = zone.location.map((item, itemIndex) => (
                itemIndex === index ? value : item
            ));
        } else {
            zone.radius = value;
        }
        onCommit({ ...params, [key]: zone });
        return true;
    };

    const commitScalar = (key, text) => {
        const current = params[key];
        if (typeof current === 'number' || current == null) {
            const value = parseNumber(text, { allowEmpty: key === 'random_seed' });
            if (typeof value === 'number' && !Number.isFinite(value)) return false;
            onCommit({ ...params, [key]: value });
            return true;
        }
        onCommit({ ...params, [key]: text });
        return true;
    };

    return (
        <div className="flex-grow overflow-y-auto px-3 py-2 bg-gray-50">
            {zoneKeys.length > 0 && (
                <Section title="Zones">
                    <div className="flex flex-col gap-2">
                        {zoneKeys.map((key) => {
                            const zone = params[key];
                            const box = zone.location.length === 4;
                            const labels = box ? ['x1', 'y1', 'x2', 'y2'] : ['x', 'y'];
                            return (
                                <div key={key} className="rounded-md border border-gray-200 bg-white px-2 py-2">
                                    <div className="text-sm font-medium text-gray-800 mb-1">{humanize(key)}</div>
                                    <div className="flex flex-wrap gap-2">
                                        {labels.map((label, index) => (
                                            <Field
                                                key={label}
                                                label={label}
                                                value={zone.location[index]}
                                                disabled={disabled}
                                                onCommit={(text) => commitZoneNumber(key, 'location', index, text)}
                                            />
                                        ))}
                                        {!box && 'radius' in zone && (
                                            <Field
                                                label="radius"
                                                value={zone.radius}
                                                disabled={disabled}
                                                onCommit={(text) => commitZoneNumber(key, 'radius', 0, text)}
                                            />
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </Section>
            )}
            {cameraKeys.length > 0 && (
                <Section title="Camera">
                    <div className="flex flex-wrap gap-3">
                        {cameraKeys.map((key) => (
                            <Field
                                key={key}
                                label={humanize(key)}
                                value={params[key]}
                                disabled={disabled}
                                wide
                                onCommit={(text) => commitScalar(key, text)}
                            />
                        ))}
                    </div>
                </Section>
            )}
            {detectionKeys.length > 0 && (
                <Section title="Detection">
                    <div className="flex flex-wrap gap-3">
                        {detectionKeys.map((key) => (
                            <Field
                                key={key}
                                label={humanize(key)}
                                value={params[key]}
                                disabled={disabled}
                                onCommit={(text) => commitScalar(key, text)}
                            />
                        ))}
                    </div>
                </Section>
            )}
            {protocolKeys.length > 0 && (
                <Section title="Protocol">
                    <div className="flex flex-wrap gap-3">
                        {protocolKeys.map((key) => (
                            <Field
                                key={key}
                                label={humanize(key)}
                                value={params[key]}
                                disabled={disabled}
                                onCommit={(text) => commitScalar(key, text)}
                            />
                        ))}
                    </div>
                </Section>
            )}
        </div>
    );
};
