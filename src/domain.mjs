import { SPORTS as REGISTERED_SPORTS, isCustomSport, sportLabel } from "./sport-registry.mjs";
export const STORAGE_KEY = "sift-alpha-research-desk-v1";
export const SPORTS = REGISTERED_SPORTS;
export const STATES = ["All states", "Investigate", "Evidence against", "No qualified signal", "Verify fix", "Discovery needed", "Draft"];

export function filterStudies(studies, query = "", sport = "All sports", state = "All states") {
  const needle = query.trim().toLocaleLowerCase();
  return studies.filter((study) =>
    (sport === "All sports" || study.sport === sport) &&
    (state === "All states" || study.status === state) &&
    (!needle || [study.title, study.question, study.finding, study.sport, sportLabel(study.sport), study.next]
      .join(" ").toLocaleLowerCase().includes(needle))
  );
}

export function createDraft(question, sport, id) {
  const title = String(question || "").trim().replace(/\s+/g, " ");
  if (title.length < 8 || title.length > 180) throw new Error("Use a research question between 8 and 180 characters.");
  const normalizedSport = { Soccer: "SOCCER", Tennis: "TENNIS" }[sport] || sport;
  if (!SPORTS.slice(1).includes(normalizedSport) && !isCustomSport(normalizedSport)) {
    throw new Error("Select a sport or enter a valid new sport.");
  }
  return {
    id, sport: normalizedSport, title, status: "Draft", date: new Date().toISOString().slice(0, 10),
    question: title, finding: "Not tested — no conclusion.",
    caveat: "Personal local draft. No historical study, strategy validation, or trading authority is implied.",
    next: "State the hypothesis, failure condition, point-in-time inputs, decision cutoff, benchmark and cost assumptions before testing.",
    metrics: [], sources: [],
    checklist: ["Define a falsifiable hypothesis and baseline", "Freeze data vintages and decision rules", "Define independent outcomes and post-fee success criteria"]
  };
}
export function validSource(url) {
  try {
    const value = new URL(url);
    return value.protocol === "https:" && ["github.com", "kalshi.com"].includes(value.hostname);
  } catch { return false; }
}
export function readSnapshot(value) {
  let parsed;
  try { parsed = JSON.parse(value); } catch { throw new Error("That file is not valid JSON."); }
  if (!parsed || parsed.version !== 1 || !Array.isArray(parsed.drafts) || !parsed.notes || typeof parsed.notes !== "object") {
    throw new Error("This is not a SIFT Alpha research-desk export.");
  }
  if (parsed.drafts.length > 250 || Object.keys(parsed.notes).length > 1000) throw new Error("The export exceeds the local desk limits.");
  const drafts = parsed.drafts.map((entry) => {
    if (!entry || typeof entry.id !== "string" || !/^local-[a-zA-Z0-9-]{1,90}$/.test(entry.id)) throw new Error("Invalid draft identifier.");
    const safe = createDraft(entry.question, entry.sport, entry.id);
    safe.date = /^\d{4}-\d{2}-\d{2}$/.test(entry.date || "") ? entry.date : safe.date;
    return safe;
  });
  if (new Set(drafts.map((x) => x.id)).size !== drafts.length) throw new Error("Duplicate draft identifiers.");
  const notes = {};
  for (const [key, note] of Object.entries(parsed.notes)) {
    if (typeof key !== "string" || typeof note !== "string" || note.length > 10000) throw new Error("Invalid research note.");
    notes[key] = note;
  }
  const tasks = {};
  if (parsed.tasks !== undefined && (!parsed.tasks || typeof parsed.tasks !== "object" || Array.isArray(parsed.tasks))) {
    throw new Error("Invalid research checklist data.");
  }
  if (Object.keys(parsed.tasks || {}).length > 1000) throw new Error("Too many research checklists.");
  for (const [key, values] of Object.entries(parsed.tasks || {})) {
    if (!Array.isArray(values) || values.length > 30 || !values.every((v) => Number.isInteger(v) && v >= 0 && v < 30)) {
      throw new Error("Invalid research checklist.");
    }
    tasks[key] = [...new Set(values)];
  }
  return { drafts, notes, tasks };
}
export function makeSnapshot(drafts, notes, tasks = {}) {
  return { version: 1, exportedAt: new Date().toISOString(), drafts, notes, tasks };
}