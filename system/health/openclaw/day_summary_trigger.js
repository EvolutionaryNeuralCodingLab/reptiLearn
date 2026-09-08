/**
 * OpenClaw cron trigger: fire when day_summary.json is a fresh file for today.
 *
 * systemd writes the JSON around 19:55 local. The job is scheduled at 20:00
 * Asia/Jerusalem, so do not also require local hour >= 20: OpenClaw code-mode
 * Date is UTC (20:00 IDT == 17:00 UTC), which previously suppressed the send.
 */
const SUMMARY = "/data/reptilearn/health/day_summary.json";
const MAX_AGE_SEC = 3 * 60 * 60;

function extractText(res) {
  if (res == null) return "";
  const r = res.result ?? res;
  if (typeof r === "string") return r;
  if (typeof r?.details?.aggregated === "string") return r.details.aggregated;
  if (typeof r?.details?.content === "string") return r.details.content;
  if (typeof r?.text === "string") return r.text;
  if (typeof r?.content === "string") return r.content;
  if (Array.isArray(r?.content)) {
    return r.content.map((c) => (typeof c === "string" ? c : c?.text ?? "")).join("\n");
  }
  return "";
}

const JERUSALEM_OFFSET_MS = 3 * 60 * 60 * 1000;

function pad2(n) {
  const s = String(n);
  return s.length < 2 ? "0" + s : s;
}

function jerusalemToday() {
  const d = new Date(Date.now() + JERUSALEM_OFFSET_MS);
  return d.getUTCFullYear() + "-" + pad2(d.getUTCMonth() + 1) + "-" + pad2(d.getUTCDate());
}

let text = "";
try {
  const res = await tools.call("read", { path: SUMMARY });
  text = extractText(res);
} catch (err) {
  json({ fire: false, state: trigger.state ?? {} });
}

let payload = null;
try {
  payload = JSON.parse(String(text).trim());
} catch {
  json({ fire: false, state: trigger.state ?? {} });
}

const date = payload?.date != null ? String(payload.date) : "";
const ts = Number(payload?.ts);
const today = jerusalemToday();
const ageOk = Number.isFinite(ts) && Date.now() / 1000 - ts <= MAX_AGE_SEC;
const prev = trigger.state?.date ?? null;

if (!date || date !== today || !ageOk) {
  json({ fire: false, state: { date: prev } });
} else if (date === prev) {
  json({ fire: false, state: { date } });
} else {
  json({
    fire: true,
    message: "day_summary " + date,
    state: { date },
  });
}
