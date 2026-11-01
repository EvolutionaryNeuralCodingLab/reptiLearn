import React from "react";
import { useSelector } from "react-redux";
import { Bar } from "./ui/bar";

const MAGNETORECEPTION_EXPERIMENTS = new Set([
    "magnetoreception_exp",
    "magnetoreception_train",
    "magnetoreception_exp_v2",
    "magnetoreception_train_v2",
]);

/** @returns {{ prefix: string, trialKey: string } | null} */
const magStatePrefix = (experiment) => {
    switch (experiment) {
        case "magnetoreception_exp":
        case "magnetoreception_train":
            return { prefix: "magnetoreception_", trialKey: "trial" };
        case "magnetoreception_exp_v2":
            return { prefix: "magnetoreception_v2_", trialKey: "trial_num" };
        case "magnetoreception_train_v2":
            return { prefix: "magnetoreception_train_v2_", trialKey: "trial_num" };
        default:
            return null;
    }
};

const formatTrialStatus = (status, reasons) => {
    if (status !== "good" && status !== "bad") {
        return "—";
    }
    const list = Array.isArray(reasons)
        ? reasons.filter(Boolean)
        : String(reasons || "")
            .split(",")
            .map((part) => part.trim())
            .filter(Boolean);
    if (status === "good" || list.length === 0) {
        return status;
    }
    return `bad: ${list.join(", ")}`;
};

const readMagSessionStats = (session) => {
    const spec = magStatePrefix(session.experiment);
    if (!spec) {
        return null;
    }

    const { prefix, trialKey } = spec;
    const get = (key) => session[prefix + key];

    const bTrials = get("b_trials_count") ?? 0;
    const successes = get("success_count") ?? 0;
    const successRight = get("success_right_count") ?? 0;
    const successLeft = get("success_left_count") ?? 0;
    const successRate =
        bTrials > 0 ? `${((successes / bTrials) * 100).toFixed(0)}%` : "—";

    const choiceCorrect = get("choice_correct");
    let choiceCorrectLabel = "—";
    if (choiceCorrect === true) {
        choiceCorrectLabel = "yes";
    } else if (choiceCorrect === false) {
        choiceCorrectLabel = "no";
    }

    return {
        phase: get("phase"),
        trial: get(trialKey) ?? 0,
        magnet: get("magnet_direction"),
        bStage: get("b_stage"),
        choiceSide: get("choice_side"),
        choiceCorrectLabel,
        rightFeeder1: get("right_feeder_1_dispense_count") ?? 0,
        rightFeeder2: get("right_feeder_2_dispense_count") ?? 0,
        leftFeeder1: get("left_feeder_1_dispense_count") ?? 0,
        leftFeeder2: get("left_feeder_2_dispense_count") ?? 0,
        bTrials,
        successes,
        successRight,
        successLeft,
        successRate,
        isV2: trialKey === "trial_num",
        trialStatus: formatTrialStatus(get("trial_status"), get("trial_status_reasons")),
        trialStatusDetail: get("trial_status_detail") || "",
        lastTrial: get("last_trial_status_trial"),
        lastTrialStatus: formatTrialStatus(
            get("last_trial_status"),
            get("last_trial_status_reasons"),
        ),
        lastTrialDetail: get("last_trial_status_detail") || "",
    };
};

export const StateView = () => {
    const ctrl_state = useSelector((state) => state.reptilearn.ctrlState);

    if (!ctrl_state) return null;

    const session = ctrl_state?.session;
    const experiment = session?.experiment;

    const isMagExp = MAGNETORECEPTION_EXPERIMENTS.has(experiment);
    const isOnboarding = experiment === "onboarding";
    const isMagnetsOnboarding = experiment === "magnets_onboarding";

    if (!isMagExp && !isOnboarding && !isMagnetsOnboarding) {
        return (
            <div className="h-full flex flex-col">
                <Bar title="Status" />
                <div className="p-3 text-sm text-gray-500">Not a magnetoreception session</div>
            </div>
        );
    }

    if (isOnboarding || isMagnetsOnboarding) {
        const phase = isMagnetsOnboarding
            ? session.magnets_onboarding_phase
            : session.onboarding_phase;
        const round = isMagnetsOnboarding
            ? (session.magnets_onboarding_trial ?? session.magnets_onboarding_trial_num)
            : session.onboarding_trial;
        return (
            <div className="h-full flex flex-col">
                <Bar title="Status" />
                <div className="px-3 py-3 bg-gray-100 flex flex-col gap-2 text-sm overflow-y-auto flex-grow">
                    <span>Phase: <b>{phase ?? "—"}</b></span>
                    <span>Round: <b>{round ?? 0}</b></span>
                    {isMagnetsOnboarding && (
                        <span>Magnet: <b>{session.magnets_onboarding_magnet_direction ?? "—"}</b></span>
                    )}
                    {isMagnetsOnboarding && (
                        <span>
                            Trial status: <b>{formatTrialStatus(
                                session.magnets_onboarding_trial_status,
                                session.magnets_onboarding_trial_status_reasons,
                            )}</b>
                        </span>
                    )}
                    {isMagnetsOnboarding && session.magnets_onboarding_trial_status_detail ? (
                        <span>{session.magnets_onboarding_trial_status_detail}</span>
                    ) : null}
                    {isMagnetsOnboarding && session.magnets_onboarding_last_trial_status ? (
                        <span>
                            Last trial {session.magnets_onboarding_last_trial_status_trial ?? ""}: <b>{formatTrialStatus(
                                session.magnets_onboarding_last_trial_status,
                                session.magnets_onboarding_last_trial_status_reasons,
                            )}</b>
                            {session.magnets_onboarding_last_trial_status_detail
                                ? ` (${session.magnets_onboarding_last_trial_status_detail})`
                                : ""}
                        </span>
                    ) : null}
                </div>
            </div>
        );
    }

    const stats = readMagSessionStats(session);
    if (!stats) {
        return null;
    }

    return (
        <div className="h-full flex flex-col">
            <Bar title="Status" />
            <div className="px-3 py-3 bg-gray-100 flex flex-col gap-2 text-sm overflow-y-auto flex-grow">
                <span>Phase: <b>{stats.phase ?? "—"}</b></span>
                <span>Trial: <b>{stats.trial}</b></span>
                <span>Magnet: <b>{stats.magnet ?? "—"}</b></span>
                {stats.isV2 && stats.bStage != null && stats.bStage !== "" && (
                    <span>B stage: <b>{stats.bStage}</b></span>
                )}
                {stats.isV2 && stats.choiceSide != null && stats.choiceSide !== "" && (
                    <span>Choice side: <b>{stats.choiceSide}</b></span>
                )}
                {stats.isV2 && stats.choiceCorrectLabel !== "—" && (
                    <span>Choice correct: <b>{stats.choiceCorrectLabel}</b></span>
                )}
                {stats.isV2 && (
                    <span>Trial status: <b>{stats.trialStatus}</b></span>
                )}
                {stats.isV2 && stats.trialStatusDetail ? (
                    <span>{stats.trialStatusDetail}</span>
                ) : null}
                {stats.isV2 && stats.lastTrialStatus !== "—" && (
                    <span>
                        Last trial {stats.lastTrial ?? ""}: <b>{stats.lastTrialStatus}</b>
                        {stats.lastTrialDetail ? ` (${stats.lastTrialDetail})` : ""}
                    </span>
                )}
                <span>Right Feeder 1 dispenses: <b>{stats.rightFeeder1}</b></span>
                <span>Right Feeder 2 dispenses: <b>{stats.rightFeeder2}</b></span>
                <span>Left Feeder 1 dispenses: <b>{stats.leftFeeder1}</b></span>
                <span>Left Feeder 2 dispenses: <b>{stats.leftFeeder2}</b></span>
                <span>Success: <b>{stats.successes}/{stats.bTrials} ({stats.successRate})</b></span>
                <span>Right ✓: <b>{stats.successRight}</b></span>
                <span>Left ✓: <b>{stats.successLeft}</b></span>
            </div>
        </div>
    );
};
