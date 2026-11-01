const clamp = (value, lo, hi) => Math.min(hi, Math.max(lo, value));

const zoneBox = (zones, id) => {
    const zone = (zones || []).find((item) => item.id === id);
    const loc = zone?.location;
    if (!loc || loc.length < 4) return null;
    const x1 = Math.min(loc[0], loc[2]);
    const x2 = Math.max(loc[0], loc[2]);
    const y1 = Math.min(loc[1], loc[3]);
    const y2 = Math.max(loc[1], loc[3]);
    return [x1, y1, x2, y2];
};

/**
 * Camera fraction to a spot on arena.png.
 * Each entry is the camera rectangle [x1, y1, x2, y2] and the matching
 * rectangle on the painting, both with the origin at the top left.
 * The side corridors are the measured frames. The choice, center, and
 * home rectangles follow the arena zones.
 */
const PAINT = {
    home: [0.455, 0.775, 0.525, 0.825],
    leftCorridor: [0.145, 0.36, 0.168, 0.74],
    rightCorridor: [0.832, 0.36, 0.855, 0.74],
    leftChoice: [0.22, 0.318, 0.32, 0.345],
    rightChoice: [0.68, 0.318, 0.84, 0.345],
    center: [0.445, 0.14, 0.53, 0.58],
};

const DEFAULT_CAMERA = {
    home: [0.44, 0.75, 0.57, 1],
    leftChoice: [0.07, 0.05, 0.24, 0.42],
    rightChoice: [0.74, 0.05, 0.92, 0.42],
    center: [0.42, 0.2, 0.59, 0.72],
};

const LEFT_CORRIDOR = [0.21, 0.42, 0.38, 0.76];
const RIGHT_CORRIDOR = [0.57, 0.42, 0.74, 0.76];

const inside = (x, y, box) => x >= box[0] && x <= box[2] && y >= box[1] && y <= box[3];

const mapRect = (x, y, source, destination) => {
    const tx = clamp((x - source[0]) / Math.max(1e-6, source[2] - source[0]), 0, 1);
    const ty = clamp((y - source[1]) / Math.max(1e-6, source[3] - source[1]), 0, 1);
    return {
        x: (destination[0] + tx * (destination[2] - destination[0])) * 960,
        y: (destination[1] + ty * (destination[3] - destination[1])) * 720,
    };
};

const nearest = (x, y, regions) => {
    let best = null;
    regions.forEach((region) => {
        const [x1, y1, x2, y2] = region.source;
        const dx = x < x1 ? x1 - x : x > x2 ? x - x2 : 0;
        const dy = y < y1 ? y1 - y : y > y2 ? y - y2 : 0;
        const distance = dx * dx + dy * dy;
        if (!best || distance < best.distance) best = { distance, region };
    });
    return best.region;
};

/**
 * Camera position onto the painting. Coordinates are pixels of the
 * 960 by 720 picture, origin at the top left.
 */
export const fieldPoint = (sample, zones) => {
    if (!sample || !Number.isFinite(sample.cx) || !Number.isFinite(sample.cy)) return null;
    const cx = sample.cx;
    const cy = sample.cy;
    const camera = {
        home: zoneBox(zones, 'D') || zoneBox(zones, 'C') || DEFAULT_CAMERA.home,
        leftChoice: zoneBox(zones, 'B2') || DEFAULT_CAMERA.leftChoice,
        rightChoice: zoneBox(zones, 'B1') || DEFAULT_CAMERA.rightChoice,
        center: zoneBox(zones, 'A') || DEFAULT_CAMERA.center,
        leftCorridor: LEFT_CORRIDOR,
        rightCorridor: RIGHT_CORRIDOR,
    };
    const regions = Object.keys(PAINT).map((name) => ({
        name,
        source: camera[name],
        destination: PAINT[name],
    }));
    const order = ['home', 'leftCorridor', 'rightCorridor', 'leftChoice', 'rightChoice', 'center'];
    const region = order.map((name) => regions.find((item) => item.name === name))
        .find((item) => inside(cx, cy, item.source))
        || nearest(cx, cy, regions);
    return mapRect(cx, cy, region.source, region.destination);
};

/** Field points for the recent path, split where the turtle jumps corridors. */
export const fieldTrail = (trail, zones) => {
    const segments = [];
    let current = [];
    let previous = null;
    (trail || []).forEach((point) => {
        const mapped = fieldPoint(point, zones);
        if (!mapped) return;
        if (previous && Math.hypot(mapped.x - previous.x, mapped.y - previous.y) > 90) {
            if (current.length > 1) segments.push(current);
            current = [];
        }
        current.push(mapped);
        previous = mapped;
    });
    if (current.length > 1) segments.push(current);
    return segments;
};
