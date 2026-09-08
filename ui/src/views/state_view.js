import React from "react";
import { useSelector } from "react-redux";
import { Bar } from "./ui/bar";

// import { RLJSONEditor } from "./ui/json_edit";
// import { RLListbox, RLSimpleListbox } from "./ui/list_box";

export const StateView = () => {
    const ctrl_state = useSelector((state) => state.reptilearn.ctrlState);

    if (!ctrl_state) return null;

    const session = ctrl_state?.session;
    const isMagExp =
        session?.experiment === "magnetoreception_exp" ||
        session?.experiment === "magnetoreception_train";

    const isOnboarding =
        session?.experiment === "onboarding";

    if (!isMagExp && !isOnboarding) {
        return (
            <div className="h-full flex flex-col">
                <Bar title="Status" />
                <div className="p-3 text-sm text-gray-500">Not a magnetoreception session</div>
            </div>
        );
    }

    const bTrials = session.magnetoreception_b_trials_count ?? 0;
    const successes = session.magnetoreception_success_count ?? 0;
    const successRight = session.magnetoreception_success_right_count ?? 0;
    const successLeft = session.magnetoreception_success_left_count ?? 0;
    const successRate = bTrials > 0 ? `${((successes / bTrials) * 100).toFixed(0)}%` : '—';

    // const statusPanel = isMagExp && (
    //     <div className="px-3 py-3 bg-gray-100 border-b flex flex-col flex-grow gap-4 text-base">
    //     </div>

    // );

    // const [ctrlStatePath, setCtrlStatePath] = React.useState();
    // const [statePath, setStatePath] = React.useState([]);

    // const update_ctrl_state_path = () => {
    //     if (!statePath || statePath.length === 0) {
    //         setCtrlStatePath(ctrl_state);
    //         return;
    //     }

    //     let cur = ctrl_state;
    //     for (const key of statePath) {
    //         if (cur[key]) {
    //             cur = cur[key];
    //         }
    //         else {
    //             setCtrlStatePath({});
    //             return;
    //         }
    //     }

    //     setCtrlStatePath(cur);
    // };

    // const keys_for_path = (i) => {
    //     let cur = ctrl_state;
    //     for (const key of statePath) {
    //         if (i === 0)
    //             break;

    //         if (cur[key]) {
    //             cur = cur[key];
    //             i--;
    //         }
    //         else {
    //             return [];
    //         }
    //     }

    //     return Object.keys(cur)
    //         .filter(k => cur[k] instanceof Array || cur[k] instanceof Object);
    // };

    // React.useEffect(update_ctrl_state_path, [ctrl_state, statePath]);

    // const state_path_select = (i) => {
    //     const on_change = (value) => {
    //         const state_path = [...statePath];

    //         if (!value) {
    //             setStatePath(statePath.slice(0, i));
    //             return null;
    //         }

    //         state_path[i] = value;
    //         setStatePath(state_path);
    //     };

    //     const opts = RLListbox.valueOnlyOptions([undefined, ...keys_for_path(i)]);

    //     if (opts.length === 1)
    //         return null;

    //     return (
    //         <RLSimpleListbox
    //             placeholder="..."
    //             options={opts}
    //             selected={statePath[i]}
    //             setSelected={on_change}
    //             portal
    //             key={i} />
    //     );
    // };

    if (isOnboarding) {
        return (
            <div className="h-full flex flex-col">
                <Bar title="Status" />
                    <div className="px-3 py-3 bg-gray-100 flex flex-col gap-2 text-sm overflow-y-auto flex-grow">
                        <span>Phase: <b>{session.onboarding_phase ?? '—'}</b></span>
                        <span>Round: <b>{session.onboarding_trial ?? 0}</b></span>
                    </div>
            </div>
        );
    }

    else if (isMagExp) {
        return (
            <div className="h-full flex flex-col">
                <Bar title="Status" />
                    <div className="px-3 py-3 bg-gray-100 flex flex-col gap-2 text-sm overflow-y-auto flex-grow">
                        <span>Phase: <b>{session.magnetoreception_phase ?? '—'}</b></span>
                        <span>Trial: <b>{session.magnetoreception_trial ?? 0}</b></span>
                        <span>Magnet: <b>{session.magnetoreception_magnet_direction ?? '—'}</b></span>
                        <span>Right Feeder 1 dispenses: <b>{session.magnetoreception_right_feeder_1_dispense_count ?? 0}</b></span>
                        <span>Right Feeder 2 dispenses: <b>{session.magnetoreception_right_feeder_2_dispense_count ?? 0}</b></span>
                        <span>Left Feeder 1 dispenses: <b>{session.magnetoreception_left_feeder_1_dispense_count ?? 0}</b></span>
                        <span>Left Feeder 2 dispenses: <b>{session.magnetoreception_left_feeder_2_dispense_count ?? 0}</b></span>
                        <span>Success: <b>{successes}/{bTrials} ({successRate})</b></span>
                        <span>Right ✓: <b>{successRight}</b></span>
                        <span>Left ✓: <b>{successLeft}</b></span>
                    </div>
                    {/* {[
                        ...statePath.map((p, idx) => state_path_select(idx)),
                        state_path_select(statePath.length)
                    ]} */}
                {/* </Bar> */}
                {/* {ctrlStatePath && */}
                    {/* <RLJSONEditor */}
                        {/* // content={{ json: ctrlStatePath }}
                        // readOnly
                        // className="overflow-y-scroll flex-grow"
                        // mainMenuBar={false} */}
                        {/* // navigationBar={false} />} */}
            </div>
        );
    }
}