/** Playback helpers for the location tab. Times are epoch seconds. */

export const WALLS = {
    back: { id: 'back', dx: 0, dy: -1, label: 'back wall' },
    front: { id: 'front', dx: 0, dy: 1, label: 'front wall' },
    right: { id: 'right', dx: 1, dy: 0, label: 'right wall' },
    left: { id: 'left', dx: -1, dy: 0, label: 'left wall' },
};

const GAP_SECONDS = 0.5;
const PATH_HOLD_SECONDS = 20;
const TRAIL_SECONDS = 4;

export const eventSuffix = (event) => {
    const name = event?.event || '';
    const slash = name.lastIndexOf('/');
    return slash >= 0 ? name.slice(slash + 1) : name;
};

const zoneArea = (zone, imageWidth, imageHeight) => {
    const loc = zone.location || [];
    if (loc.length >= 4) {
        return Math.abs((loc[2] - loc[0]) * (loc[3] - loc[1]));
    }
    if (loc.length >= 2 && zone.radius != null && imageWidth && imageHeight) {
        const r = zone.radius * Math.min(imageWidth, imageHeight);
        return Math.PI * r * r;
    }
    return Infinity;
};

export const zoneContains = (zone, cx, cy, imageWidth, imageHeight) => {
    const loc = zone.location || [];
    if (loc.length >= 4) {
        return cx >= loc[0] && cx <= loc[2] && cy >= loc[1] && cy <= loc[3];
    }
    if (loc.length >= 2 && zone.radius != null && imageWidth && imageHeight) {
        const px = cx * imageWidth;
        const py = cy * imageHeight;
        const zx = loc[0] * imageWidth;
        const zy = loc[1] * imageHeight;
        const r = zone.radius * Math.min(imageWidth, imageHeight);
        const dx = px - zx;
        const dy = py - zy;
        return dx * dx + dy * dy <= r * r;
    }
    return false;
};

/** Smallest zone that contains the centroid, or null. */
export const zoneAt = (sample, zones, imageWidth, imageHeight) => {
    if (!sample || !zones?.length) {
        return null;
    }
    let best = null;
    let bestArea = Infinity;
    for (const zone of zones) {
        if (!zoneContains(zone, sample.cx, sample.cy, imageWidth, imageHeight)) {
            continue;
        }
        const area = zoneArea(zone, imageWidth, imageHeight);
        if (area < bestArea) {
            best = zone;
            bestArea = area;
        }
    }
    return best;
};

const wallForZoneId = (id) => {
    if (id === 'A') return WALLS.back;
    if (id === 'B1' || id === 'C1') return WALLS.right;
    if (id === 'B2' || id === 'C2') return WALLS.left;
    if (id === 'D' || id === 'C') return WALLS.front;
    return null;
};

const sideWall = (value) => {
    const zone = value?.zone;
    if (zone === 'B1' || zone === 'C1') return WALLS.right;
    if (zone === 'B2' || zone === 'C2') return WALLS.left;
    if (value?.cycle_side === 'left') return WALLS.left;
    if (value?.cycle_side === 'right') return WALLS.right;
    return WALLS.right;
};

const isReturnEvent = (event, hasPointD) => {
    const name = eventSuffix(event);
    if (
        name === 'point_d'
        || name === 'point_d_via_a'
        || name === 'c_dwell_complete'
        || name === 'b_hold_complete'
        || name === 'exit_door'
    ) {
        return true;
    }
    if (name !== 'phase_change') {
        return false;
    }
    const phase = event.value?.phase;
    if (phase === 'd') return true;
    return !hasPointD && phase === 'c';
};

/**
 * Facing for a regular route: back until the side choice, side until the
 * return, then front until the next trial. Without a trial, use the zone.
 */
export const facingAt = (t, events, zones, sample, hasPointD, imageWidth, imageHeight) => {
    let lastStart = null;
    for (const event of events || []) {
        if (event.t > t) break;
        if (eventSuffix(event) === 'trial_start') lastStart = event;
    }
    if (!lastStart) {
        const zone = zoneAt(sample, zones, imageWidth, imageHeight);
        return (zone && wallForZoneId(zone.id)) || WALLS.back;
    }
    let pointB = null;
    for (const event of events) {
        if (event.t > t) break;
        if (event.t < lastStart.t) continue;
        if (eventSuffix(event) === 'point_b') pointB = event;
    }
    if (!pointB) return WALLS.back;
    for (const event of events) {
        if (event.t > t) break;
        if (event.t < pointB.t) continue;
        if (isReturnEvent(event, hasPointD)) return WALLS.front;
    }
    return sideWall(pointB.value);
};

const indexAt = (samples, t) => {
    if (!samples?.length || !Number.isFinite(t) || t < samples[0].t) {
        return -1;
    }
    let lo = 0;
    let hi = samples.length - 1;
    while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (samples[mid].t <= t) lo = mid;
        else hi = mid - 1;
    }
    return lo;
};

/** Last sample at or before t. Null when t is before the first sample. */
export const sampleAt = (samples, t) => {
    const index = indexAt(samples, t);
    return index < 0 ? null : samples[index];
};

/** True when the playhead is past the last stored position. */
export const positionHeld = (sample, t) => (
    Boolean(sample)
    && Number.isFinite(t)
    && Number.isFinite(sample.t)
    && t - sample.t > PATH_HOLD_SECONDS
);

/** Recent positions ending at t, stopping at a missing-path gap. */
export const trailBefore = (samples, t, seconds = TRAIL_SECONDS) => {
    const index = indexAt(samples, t);
    if (index < 0) return [];
    const points = [];
    let newer = samples[index];
    for (let i = index; i >= 0; i -= 1) {
        const sample = samples[i];
        if (t - sample.t > seconds) break;
        if (newer.t - sample.t > GAP_SECONDS) break;
        points.push(sample);
        newer = sample;
    }
    points.reverse();
    return points;
};

const zoneBox = (zones, id) => {
    const zone = (zones || []).find((item) => item.id === id);
    const loc = zone?.location;
    if (!loc || loc.length < 4) return null;
    const x1 = Math.min(loc[0], loc[2]);
    const x2 = Math.max(loc[0], loc[2]);
    const y1 = Math.min(loc[1], loc[3]);
    const y2 = Math.max(loc[1], loc[3]);
    if (x2 - x1 < 0.02 || y2 - y1 < 0.02) return null;
    return { x1, y1, x2, y2 };
};

const doorWidthFor = (box) => {
    const corridor = box.x2 - box.x1;
    return Math.min(0.07, Math.max(0.04, corridor * 0.32));
};

/**
 * Blocks, doors, and paths in normalized camera coordinates.
 * Blocks fill the gaps beside the center lane and run the lane's height.
 * The choice zones are the side corridors, not the blocks. Null when the
 * zones do not form a left and right corridor.
 */
export const furnitureFromZones = (zones) => {
    const center = zoneBox(zones, 'A');
    const rightChoice = zoneBox(zones, 'B1');
    const leftChoice = zoneBox(zones, 'B2');
    const front = zoneBox(zones, 'D') || zoneBox(zones, 'C');
    if (!center || !rightChoice || !leftChoice) return null;
    const floorBottom = front ? Math.min(0.98, front.y2) : 0.98;
    const blockBottom = front ? Math.min(front.y1, floorBottom - 0.04) : Math.min(center.y2, 0.78);
    const blockTop = Math.min(center.y1, blockBottom - 0.2);
    if (blockBottom - blockTop < 0.12) return null;
    const left = {
        x: leftChoice.x2,
        y: blockTop,
        w: center.x1 - leftChoice.x2,
        h: blockBottom - blockTop,
    };
    const right = {
        x: center.x2,
        y: blockTop,
        w: rightChoice.x1 - center.x2,
        h: blockBottom - blockTop,
    };
    if (left.w < 0.03 || right.w < 0.03) return null;
    const rail = 0.02;
    const leftDoorW = doorWidthFor(leftChoice);
    const rightDoorW = doorWidthFor(rightChoice);
    const columnX = (box, doorW) => (box.x1 + box.x2) / 2 - doorW / 2;
    const leftDoorX = columnX(leftChoice, leftDoorW);
    const rightDoorX = columnX(rightChoice, rightDoorW);
    const spanX1 = Math.min(leftChoice.x1, center.x1);
    const spanX2 = Math.max(rightChoice.x2, center.x2);
    return {
        left,
        right,
        paths: {
            home: {
                x: spanX1,
                y: blockBottom,
                w: spanX2 - spanX1,
                h: Math.max(0.04, floorBottom - blockBottom),
            },
            left: { x: leftChoice.x1, y: rail, w: leftChoice.x2 - leftChoice.x1, h: floorBottom - rail },
            right: { x: rightChoice.x1, y: rail, w: rightChoice.x2 - rightChoice.x1, h: floorBottom - rail },
            center: { x: center.x1, y: rail, w: center.x2 - center.x1, h: floorBottom - rail },
        },
        doors: {
            backLeft: { x: leftDoorX, y: rail, w: leftDoorW, h: Math.max(0.05, blockTop - rail) },
            backRight: { x: rightDoorX, y: rail, w: rightDoorW, h: Math.max(0.05, blockTop - rail) },
            frontLeft: { x: leftDoorX, y: blockBottom, w: leftDoorW, h: Math.max(0.05, floorBottom - blockBottom) },
            frontRight: { x: rightDoorX, y: blockBottom, w: rightDoorW, h: Math.max(0.05, floorBottom - blockBottom) },
        },
    };
};

const closeDoors = () => ({
    backLeft: false,
    backRight: false,
    frontLeft: false,
    frontRight: false,
});

/** Magnet pairing recorded on the trial that contains t. */
export const magnetAt = (t, events) => {
    let direction = null;
    for (const event of events || []) {
        if (event.t > t) break;
        if (eventSuffix(event) === 'trial_start' && event.value?.magnet_direction) {
            direction = event.value.magnet_direction;
        }
    }
    return direction;
};

const choiceDoorSide = (value) => {
    const raw = value?.back_doors || value?.back_door_to_open || value?.cycle_side;
    if (raw === 'left' || raw === 'right') return raw;
    if (raw === 'both' || raw === 'both_open') return 'both';
    return null;
};

/** Food dispenses up to t. Uses reward events, or correct choices when those are absent. */
export const rewardsAt = (t, events) => {
    let rewards = 0;
    let sawReward = false;
    let correct = 0;
    for (const event of events || []) {
        if (event.t > t) break;
        const name = eventSuffix(event);
        const value = event.value || {};
        if (name === 'reward') {
            sawReward = true;
            if (value.dispensed !== false) rewards += 1;
        } else if (name === 'point_b' && value.reason === 'correct_choice') {
            correct += 1;
        }
    }
    return sawReward ? rewards : correct;
};

/** Which doors are open at t. Back is the top of the camera image. */
export const doorsAt = (t, events) => {
    const doors = closeDoors();
    let choiceSide = null;
    for (const event of events || []) {
        if (event.t > t) break;
        const name = eventSuffix(event);
        const value = event.value || {};
        if (name === 'trial_start') {
            Object.assign(doors, closeDoors());
            choiceSide = choiceDoorSide(value);
        } else if (
            name === 'waiting_at_a'
            || (name === 'phase_change' && (value.phase === 'a' || value.phase === 'a_delay'))
        ) {
            Object.assign(doors, closeDoors());
        } else if (name === 'back_doors_open' || (name === 'phase_change' && value.phase === 'b')) {
            const side = choiceDoorSide(value) || choiceSide;
            doors.backLeft = side === 'left' || side === 'both' || side == null;
            doors.backRight = side === 'right' || side === 'both' || side == null;
            doors.frontLeft = false;
            doors.frontRight = false;
        } else if (name === 'point_b' || (name === 'phase_change' && value.phase === 'b_wait')) {
            doors.backLeft = false;
            doors.backRight = false;
        } else if (name === 'exit_door') {
            doors.backLeft = false;
            doors.backRight = false;
            const side = value.door_opened
                || (value.zone === 'B1' ? 'right' : value.zone === 'B2' ? 'left' : null);
            doors.frontLeft = side === 'left' || side === 'both' || side == null;
            doors.frontRight = side === 'right' || side === 'both' || side == null;
        }
    }
    return doors;
};

/** One row per trial start, with the choice recorded before the next trial. */
export const trialList = (events) => {
    const trials = [];
    for (const event of events || []) {
        if (eventSuffix(event) !== 'trial_start') continue;
        trials.push({
            t: event.t,
            trial: event.value?.trial ?? trials.length + 1,
            outcome: null,
            choice: null,
        });
    }
    let index = 0;
    for (const event of events || []) {
        if (eventSuffix(event) !== 'point_b') continue;
        while (index + 1 < trials.length && trials[index + 1].t <= event.t) index += 1;
        if (!trials.length || event.t < trials[0].t) continue;
        const reason = event.value?.reason;
        if (reason === 'correct_choice') trials[index].outcome = 'correct';
        else if (reason === 'incorrect_side') trials[index].outcome = 'incorrect';
        trials[index].choice = event.value?.zone || null;
    }
    return trials;
};

/** Index of the trial whose start is the latest at or before t. */
export const trialIndexAt = (trials, t) => {
    if (!trials?.length || !Number.isFinite(t)) return -1;
    let index = -1;
    for (let i = 0; i < trials.length; i += 1) {
        if (trials[i].t <= t + 1e-3) index = i;
        else break;
    }
    return index;
};

export const playbackFacts = (t, events) => {
    let trial = null;
    let phase = null;
    for (const event of events || []) {
        if (event.t > t) break;
        const name = eventSuffix(event);
        const value = event.value || {};
        if (name === 'trial_start') {
            trial = value.trial ?? trial;
            phase = value.phase ?? phase;
        } else if (name === 'phase_change' && value.phase) {
            phase = value.phase;
        } else if (name === 'c_dwell_complete' || name === 'b_hold_complete') {
            phase = 'd';
        } else if (name === 'exit_door') {
            phase = 'c';
        } else if (name === 'point_d' || name === 'point_d_via_a' || name === 'waiting_at_a') {
            phase = 'a';
        }
    }
    return { trial, phase };
};

/** Zone seconds from the server's counted stretches, clipped to the playhead. */
export const zoneSecondsFromSegments = (segments, t, zones) => {
    const zoneSeconds = {};
    for (const zone of zones || []) zoneSeconds[zone.id] = 0;
    for (const segment of segments || []) {
        if (!Number.isFinite(segment.t0) || !Number.isFinite(segment.t1)) continue;
        if (segment.t0 >= t) break;
        const dt = Math.min(segment.t1, t) - segment.t0;
        if (dt <= 0 || !segment.zone) continue;
        zoneSeconds[segment.zone] = (zoneSeconds[segment.zone] || 0) + dt;
    }
    return zoneSeconds;
};

export const statsAt = (t, events, samples, zones, imageWidth, imageHeight) => {
    let trials = 0;
    let correct = 0;
    let incorrect = 0;
    for (const event of events || []) {
        if (event.t > t) break;
        const name = eventSuffix(event);
        if (name === 'trial_start') trials += 1;
        if (name === 'point_b') {
            const reason = event.value?.reason;
            if (reason === 'correct_choice') correct += 1;
            else if (reason === 'incorrect_side') incorrect += 1;
        }
    }
    const zoneSeconds = {};
    for (const zone of zones || []) {
        zoneSeconds[zone.id] = 0;
    }
    let trialStart = null;
    for (const event of events || []) {
        if (event.t > t) break;
        if (eventSuffix(event) === 'trial_start') trialStart = event.t;
    }
    const points = [];
    for (const sample of samples || []) {
        if (sample.t > t) break;
        if (trialStart == null || sample.t < trialStart) continue;
        points.push(sample);
    }
    for (let i = 1; i < points.length; i += 1) {
        const dt = points[i].t - points[i - 1].t;
        if (!(dt > 0) || dt > GAP_SECONDS) continue;
        const zone = zoneAt(points[i - 1], zones, imageWidth, imageHeight);
        if (zone) zoneSeconds[zone.id] = (zoneSeconds[zone.id] || 0) + dt;
    }
    return { trials, correct, incorrect, zoneSeconds };
};

export const formatPlayhead = (epochSeconds) => {
    if (!Number.isFinite(epochSeconds)) return '—';
    const date = new Date(epochSeconds * 1000);
    if (Number.isNaN(date.getTime())) return '—';
    const pad = (value) => String(value).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
};

export const formatClock = (seconds) => {
    if (!Number.isFinite(seconds)) return '—';
    const sign = seconds < 0 ? '-' : '';
    const abs = Math.abs(seconds);
    const whole = Math.floor(abs);
    const secs = whole % 60;
    const mins = Math.floor(whole / 60) % 60;
    const hours = Math.floor(whole / 3600);
    const tenths = Math.floor((abs - whole) * 10);
    const body = hours > 0
        ? `${hours}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
        : `${mins}:${String(secs).padStart(2, '0')}.${tenths}`;
    return sign + body;
};

export const formatDuration = (seconds) => {
    if (!Number.isFinite(seconds) || seconds < 0.5) return '0:00';
    const whole = Math.round(seconds);
    const secs = whole % 60;
    const mins = Math.floor(whole / 60);
    return `${mins}:${String(secs).padStart(2, '0')}`;
};
