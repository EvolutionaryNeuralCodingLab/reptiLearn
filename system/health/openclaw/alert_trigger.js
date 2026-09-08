/**
 * OpenClaw cron trigger: fire only when alerts.jsonl has a new last line.
 *
 * First evaluation seeds trigger.state and does not fire (avoids Telegram
 * spam from leftover setup alerts). Subsequent ticks fire only on a new ts.
 *
 * Must return { fire, message?, state? } via json().
 */
const ALERTS = "/data/reptilearn/health/alerts.jsonl";

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

let text = "";
try {
  const res = await tools.call("read", { path: ALERTS, offset: -40, limit: 40 });
  text = extractText(res);
} catch (err) {
  json({ fire: false, state: trigger.state ?? {} });
}

const lines = String(text)
  .split("\n")
  .map((l) => l.trim())
  .filter((l) => l.startsWith("{"));
const last = lines.length ? lines[lines.length - 1] : "";
let key = "";
try {
  const parsed = JSON.parse(last);
  key = parsed.ts != null ? String(parsed.ts) : last;
} catch {
  key = last;
}

const prev = trigger.state?.key ?? null;
if (!last) {
  json({ fire: false, state: { key: prev } });
} else if (prev == null) {
  json({ fire: false, state: { key, seeded: true } });
} else if (key === prev) {
  json({ fire: false, state: { key } });
} else {
  json({
    fire: true,
    message: last.slice(0, 1500),
    state: { key },
  });
}
