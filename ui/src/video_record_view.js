import React from 'react';
import {api_url} from './config.js';
import { Dropdown } from 'semantic-ui-react';
import { Icon } from 'semantic-ui-react';

export const VideoRecordView = ({ctrl_state}) => {
    const prefix_input_ref = React.useRef();
    
    if (ctrl_state == null)
	return null;

    const image_sources = Object.keys(ctrl_state.image_sources);
    const is_recording = ctrl_state.video_record.is_recording;
    const ttl_trigger_state = ctrl_state.video_record.ttl_trigger;
    
    const toggle_recording = (e) => {
        if (is_recording) {
            fetch(api_url + "/video_record/stop");
        }
        else {
            const prefix = prefix_input_ref.current.value;
            fetch(api_url + `/video_record/set_prefix/${prefix}`)
                .then(res => fetch(api_url + "/video_record/start"));
        }
    };

    const toggle_ttl_trigger = (e) => {
        if (ctrl_state.video_record.ttl_trigger) {
            fetch(api_url + "/video_record/stop_trigger");
        }
        else {
            fetch(api_url + "/video_record/start_trigger");
        }      
    };
    
    const src_changed = (src_id) => {
        if (ctrl_state.video_record.selected_sources.includes(src_id)) {
            fetch(api_url + `/video_record/unselect_source/${src_id}`);
        }
        else {
            fetch(api_url + `/video_record/select_source/${src_id}`);
        }
    };

    const sources_dropdown = (() => {
        const items = image_sources.map(src_id => {
            const selected = ctrl_state.video_record.selected_sources.indexOf(src_id) !== -1;
            return <Dropdown.Item text={src_id}
                                  icon={selected ? "check circle outline" : "circle outline"}
                                  onClick={() => src_changed(src_id)}
                                  key={src_id}/>;
        });
        return (
            <Dropdown text='Record Sources' disabled={is_recording}>
              <Dropdown.Menu>
                {items}
              </Dropdown.Menu>
            </Dropdown>
        );
    })();

    return (
        <span className="video_record_view">
          <input type="text"
                 name="prefix_input"
                 placeholder="video name"
                 ref={prefix_input_ref}
                 disabled={is_recording}
          />
          <button onClick={toggle_recording}
                  title={is_recording ? "Stop recording" : "Start recording"}>
            <Icon size="small" fitted name={is_recording ? "stop circle" : "circle"}/>
          </button>
          <button onClick={toggle_ttl_trigger}>
            {ttl_trigger_state ? "Stop Trigger" : "Start Trigger"}
          </button>
          <button disabled={is_recording}>
            {sources_dropdown}
          </button>
        </span>
    );
};