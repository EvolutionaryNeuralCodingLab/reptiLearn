import React from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { Resizable } from 'react-resizable';
import 'react-resizable/css/styles.css';

import { addStream, imageSourceIds, moveStream, removeStream, setStreams, startStreaming, stopStreaming, streamlessSrcIds, updateStream, updateStreamSources } from '../store/reptilearn_slice.js';
import { Bar } from './ui/bar.js';
import RLButton from './ui/button.js';
import { RLListbox, RLSimpleListbox } from './ui/list_box.js';
import { classNames } from './ui/common.js';
import { api, getApiUrl } from '../api.js';
import { RLTooltip } from './ui/tooltip.js';
import { useIsMobile } from '../hooks/use_media_query.js';
import { Zoomable } from './ui/zoomable.js';

const getZoneParams = (params, src_id) => {
    if (!params) return [];
    const sourceId = params.image_source_id;
    if (sourceId && sourceId !== src_id) return [];
    return Object.entries(params)
        .filter(([k, v]) => k.startsWith('point_') && v?.location?.length >= 2);
};

const StreamImage = React.memo(({ src_id, width, height, is_streaming, undistort, show_zones }) => {
    const undistort_param = undistort ? '&undistort=true' : '';
    const zones_param = show_zones ? '&show_zones=true' : '';
    const stream_url = getApiUrl() + `/image_sources/${src_id}/stream?width=${width}${undistort_param}${zones_param}&ts=${Date.now()}`;

    const stream_style = {
        width: width + "px",
        height: height + "px",
        background: 'black',
    };

    return (
        <div style={stream_style}>
            {is_streaming
                ? (
                    <img src={stream_url}
                        key={`${src_id}-${undistort}-${show_zones}`}
                        width={width}
                        height={height}
                        alt={"Video stream " + src_id}
                    />
                ) : <FontAwesomeIcon icon="pause" className="text-gray-500 h-full w-full" transform="shrink-10" />}
        </div>
    );
});

const StreamView = ({ idx, forceWidth = null }) => {
    const dispatch = useDispatch();
    const isMobile = useIsMobile();

    const streams = useSelector((state) => state.reptilearn.streams);
    const video_config = useSelector((state) => state.reptilearn.videoConfig);
    const ctrl_state = useSelector((state) => state.reptilearn.ctrlState);
    const src_ids = useSelector(imageSourceIds);
    const unused_src_ids = useSelector(streamlessSrcIds);

    const [drag, setDrag] = React.useState(false);
    const [draggedOver, setDraggedOver] = React.useState(false);
    const [mouseDownTarget, setMouseDownTarget] = React.useState(null); // drag from handle only
    const [restartStream, setRestartStream] = React.useState(false);
    const [canEscape, setCanEscape] = React.useState(false);

    const dragCount = React.useRef(0); // prevent drag indicator from disappearing on child elements
    const dragHandle = React.useRef();

    const { src_id, width: storedWidth, is_streaming, undistort: undistort_enabled, show_zones: show_zones_enabled } = streams[idx];
    const width = forceWidth || storedWidth;
    const is_acquiring = ctrl_state?.video?.image_sources?.[src_id]?.acquiring;
    const is_running = is_streaming && is_acquiring;
    const has_undistort_config = Boolean(video_config?.image_sources?.[src_id]?.undistort);
    const show_undistort = Boolean(undistort_enabled && has_undistort_config);
    const zone_params = getZoneParams(ctrl_state?.session?.params, src_id);
    const has_zone_params = zone_params.length > 0;
    const show_zones = Boolean(show_zones_enabled && has_zone_params);

    if (!src_ids.includes(src_id)) {
        if (unused_src_ids.length > 0) {
            dispatch(updateStream({ idx: idx, key: "src_id", val: unused_src_ids[0] }))
            return null;
        } else {
            dispatch(removeStream({ idx: idx }));
            return null;
        }
    }

    const src_width = video_config.image_sources[src_id].image_shape[1];
    const src_height = video_config.image_sources[src_id].image_shape[0];

    const stream_btn_icon = is_running ? "pause" : "play";
    const is_dragged_over = draggedOver && !drag;
    const bar_height = 28;

    const get_stream_height = (stream) => {
        const { src_id: id, width: w } = stream;
        const src_width = video_config.image_sources[id].image_shape[1];
        const src_height = video_config.image_sources[id].image_shape[0];

        return src_height * (w / src_width);
    }

    const stream_height = get_stream_height(streams[idx])

    const stream_width_from_height = (height) => {
        const { src_id } = streams[idx];
        const src_width = video_config.image_sources[src_id].image_shape[1];
        const src_height = video_config.image_sources[src_id].image_shape[0];

        return src_width * (height / src_height);
    }

    const on_resize = (_, d) => {
        const requestedHeight = d.size.height - bar_height;

        const closestHeight = (idx > 0)
            ? (() => {
                if (idx < streams.length - 1) {
                    const sh_before = get_stream_height(streams[idx - 1]);
                    const sh_after = get_stream_height(streams[idx + 1]);
                    return (Math.abs(sh_before - requestedHeight) < Math.abs(sh_after - requestedHeight)) ? sh_before : sh_after;
                } else {
                    return get_stream_height(streams[idx - 1]);
                }
            })()
            : (() => {
                if (idx < streams.length - 1) {
                    return get_stream_height(streams[idx + 1])
                } else {
                    return null;
                }
            })();

        const dh = Math.abs(d.size.height - closestHeight - bar_height);

        let target_width;
        if (!canEscape) {
            if (dh < 10) {
                target_width = stream_width_from_height(closestHeight);
                setTimeout(() => setCanEscape(true), 500);
            } else {
                target_width = d.size.width;
            }
        } else {
            target_width = d.size.width;
            if (dh > 10) {
                setCanEscape(false);
            }
        }

        dispatch(updateStream({ idx: idx, key: "width", val: Math.floor(target_width) }));
    };

    const on_resize_start = () => {
        if (is_running) {
            setRestartStream(true);
            dispatch(stopStreaming({ idx }));
        }
    };

    const on_resize_stop = () => {
        if (restartStream) {
            setRestartStream(false);
            dispatch(startStreaming({ idx }));
        }
    };

    const toggle_stream = () => {
        if (is_running) {
            dispatch(stopStreaming({ idx }));
        } else {
            dispatch(startStreaming({ idx }));
        }
    };

    const toggle_undistort = () => {
        dispatch(updateStream({ idx, key: "undistort", val: !undistort_enabled }));
    };

    const toggle_show_zones = () => {
        dispatch(updateStream({ idx, key: "show_zones", val: !show_zones_enabled }));
    };

    const undistort_tooltip = has_undistort_config
        ? (undistort_enabled ? "Disable lens undistort" : "Enable lens undistort")
        : "Set \"undistort\" on this source in video_config.json";

    const zones_tooltip = has_zone_params
        ? (show_zones ? "Hide experiment zones" : "Show experiment zones")
        : "Load a session with point_* zone params";

    const handle_drop = (e) => {
        e.preventDefault();
        dragCount.current = 0;
        setDrag(false);
        setDraggedOver(false);
        const orig_idx = parseInt(e.dataTransfer.getData("text/plain"));
        dispatch(moveStream({ from: orig_idx, to: idx }))
    };

    const handle_dragstart = (e) => {
        if (dragHandle.current.contains(mouseDownTarget)) {
            setDrag(true);
            e.dataTransfer.setData("text/plain", idx);
            e.dataTransfer.effectAllowed = "move";
        } else {
            e.preventDefault();
        }
    };

    const handle_dragover = (e) => {
        if (!drag) {
            // allow dragging over a _different_ stream view
            e.preventDefault();
        }
    };

    const handle_dragenter = () => {
        if (dragCount.current === 0) {
            setDraggedOver(true);
        }
        dragCount.current += 1;
    };

    const handle_dragleave = () => {
        if (dragCount.current === 1) {
            setDraggedOver(false);
        }
        dragCount.current -= 1;
    };

    const toolbar = (
        <Bar>
            <RLButton.BarButton onClick={() => dispatch(removeStream({ idx }))} icon="xmark" />
            <RLSimpleListbox
                header="Image source"
                options={RLListbox.valueOnlyOptions(src_ids)}
                selected={src_id}
                portal
                setSelected={(new_src_id) => dispatch(updateStreamSources({ stream_idx: idx, new_src_id, old_src_id: src_id }))} />
            <RLButton.BarButton onClick={toggle_stream} icon={stream_btn_icon} />
            <RLTooltip content={undistort_tooltip}>
                <RLButton.BarButton
                    onClick={toggle_undistort}
                    disabled={!has_undistort_config}
                    icon="up-right-and-down-left-from-center"
                    className={show_undistort ? "bg-green-100 border-green-400" : undefined}
                />
            </RLTooltip>
            <RLButton.BarButton onClick={() => api.save_image(src_id)} title="Save image" icon="fa-solid fa-file-image" />
            <RLTooltip content={zones_tooltip}>
                <RLButton.BarButton
                    onClick={toggle_show_zones}
                    disabled={!has_zone_params}
                    icon="location-crosshairs"
                    className={show_zones ? "bg-green-100 border-green-400" : undefined}
                />
            </RLTooltip>
            {!isMobile && (
                <div className={classNames("h-4 w-4 my-auto ml-auto cursor-move", draggedOver && "pointer-events-none")} ref={dragHandle}>
                    <FontAwesomeIcon icon="grip-vertical" className="h-4 text-gray-600" transform="up-1" />
                </div>
            )}
        </Bar>
    );

    if (isMobile) {
        return (
            <div
                className="bg-gray-100 w-full border-b border-gray-700"
                style={{ width: '100%', height: stream_height + bar_height + 'px' }}
            >
                {toolbar}
                <Zoomable style={{ width: '100%', height: stream_height + 'px' }}>
                    <StreamImage src_id={src_id} width={width} height={stream_height} is_streaming={is_running} undistort={show_undistort} show_zones={show_zones} />
                </Zoomable>
            </div>
        );
    }

    return (
        <Resizable width={width} height={stream_height + bar_height}
            resizeHandles={['se']}
            lockAspectRatio={true}
            onResize={on_resize}
            onResizeStart={on_resize_start}
            onResizeStop={on_resize_stop}
            minConstraints={[stream_width_from_height(180), 180]}
            maxConstraints={[src_width, src_height]}>

            <div draggable className={classNames("bg-gray-100 inline-block mt-px mr-px border-0", is_dragged_over && "ring-2 ring-green-500")}
                style={{ width: width + 'px', height: stream_height + 28 + 'px' }}
                onDrop={handle_drop} onDragOver={handle_dragover} onDragEnter={handle_dragenter} onDragLeave={handle_dragleave}
                onDragStart={handle_dragstart} onDragEnd={() => setDrag(false)} onMouseDown={(e) => setMouseDownTarget(e.target)} onMouseUp={() => setMouseDownTarget(null)}>
                {toolbar}
                <StreamImage src_id={src_id} width={width} height={stream_height} is_streaming={is_running} undistort={show_undistort} show_zones={show_zones} />
            </div>
        </Resizable>
    );
};

export const StreamGroupView = () => {
    const ctrl_state = useSelector((state) => state.reptilearn.ctrlState);
    const streams = useSelector((state) => state.reptilearn.streams);
    const src_ids = useSelector(imageSourceIds);
    const dispatch = useDispatch();
    const isMobile = useIsMobile();
    const containerRef = React.useRef(null);
    const [mobileWidth, setMobileWidth] = React.useState(
        typeof window !== 'undefined' ? Math.max(window.innerWidth - 2, 160) : 360
    );

    React.useEffect(() => {
        const ls_streams = localStorage.getItem('streams');

        if (ls_streams) {
            dispatch(setStreams(JSON.parse(ls_streams)));
        }
    }, [dispatch]);

    React.useEffect(() => {
        if (localStorage.getItem('streams') || !ctrl_state?.video || !src_ids?.length) {
            return;
        }
        dispatch(addStream({ src_id: src_ids[0] }));
    }, [ctrl_state?.video, src_ids, dispatch]);

    React.useEffect(() => {
        if (!isMobile || !containerRef.current || typeof ResizeObserver === 'undefined') {
            return undefined;
        }
        const el = containerRef.current;
        const ro = new ResizeObserver((entries) => {
            const w = Math.floor(entries[0]?.contentRect?.width || 0);
            if (w > 0) setMobileWidth(w);
        });
        ro.observe(el);
        setMobileWidth(Math.floor(el.clientWidth) || mobileWidth);
        return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isMobile]);

    const stream_views = ctrl_state.video
        ? streams.map((_, idx) => (
            <StreamView
                idx={idx}
                key={idx}
                forceWidth={isMobile ? mobileWidth : null}
            />
        ))
        : null;

    return (
        <div
            ref={containerRef}
            className={classNames(
                isMobile
                    ? 'flex flex-col w-full items-stretch'
                    : 'pr-1 flex flex-row flex-wrap items-start'
            )}
        >
            {stream_views}
        </div>
    );
};
