import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { STUDIES } from "./studies.mjs";
import { STORAGE_KEY, STATES, createDraft, filterStudies, makeSnapshot, readSnapshot, validSource } from "./domain.mjs";
import { SPORT_REGISTRY, SPORT_GROUPS, sportLabel, isCustomSport, registryStatus } from "./sport-registry.mjs";
import "./styles.css";

function loadLocal() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? readSnapshot(raw) : { drafts: [], notes: {}, tasks: {} };
  } catch {
    return { drafts: [], notes: {}, tasks: {} };
  }
}
function newLocalId() {
  return "local-" + (typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
}
function ActionButton({ children, onClick, secondary = false, disabled = false }) {
  return <button className={secondary ? "button secondary" : "button"} type="button" onClick={onClick} disabled={disabled}>{children}</button>;
}
function SportOptions({ includeAll = false, customSports = [] }) {
  return <>
    {includeAll && <option value="All sports">All sports</option>}
    {SPORT_GROUPS.map((group) => <optgroup key={group} label={group}>
      {SPORT_REGISTRY.filter((item) => item.group === group).map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
    </optgroup>)}
    {customSports.length > 0 && <optgroup label="Your added sports">
      {customSports.map((id) => <option value={id} key={id}>{sportLabel(id)}</option>)}
    </optgroup>}
    {!includeAll && <option value="__new__">+ Add a new sport…</option>}
  </>;
}
function App() {
  const [local] = useState(loadLocal);
  const [drafts, setDrafts] = useState(local.drafts);
  const [notes, setNotes] = useState(local.notes);
  const [tasks, setTasks] = useState(local.tasks || {});
  const [selectedId, setSelectedId] = useState("nba-selector-tail");
  const [query, setQuery] = useState("");
  const [sport, setSport] = useState("All sports");
  const [state, setState] = useState("All states");
  const [creating, setCreating] = useState(false);
  const [coverageOpen, setCoverageOpen] = useState(false);
  const [customName, setCustomName] = useState("");
  const [question, setQuestion] = useState("");
  const [newSport, setNewSport] = useState("NBA");
  const [message, setMessage] = useState("");
  const importRef = useRef(null);
  const detailRef = useRef(null);
  const formRef = useRef(null);
  const searchRef = useRef(null);
  const all = useMemo(() => [...drafts, ...STUDIES], [drafts]);
  const customSports = useMemo(() => [...new Set(drafts.map((x) => x.sport).filter(isCustomSport))].sort(), [drafts]);
  const visible = useMemo(() => filterStudies(all, query, sport, state), [all, query, sport, state]);
  const selected = visible.find((item) => item.id === selectedId) || visible[0];
  const pending = STUDIES.filter((item) => ["Investigate", "Verify fix", "Discovery needed"].includes(item.status)).length;

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(makeSnapshot(drafts, notes, tasks))); }
    catch { setMessage("Browser storage unavailable. Export your work to keep a copy."); }
  }, [drafts, notes, tasks]);

  useEffect(() => {
    function onKey(event) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault(); searchRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function openStudy(id) {
    setSelectedId(id);
    if (window.matchMedia("(max-width: 800px)").matches) {
      requestAnimationFrame(() => detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    }
  }
  function saveDraft(event) {
    event.preventDefault();
    try {
      const draftSport = newSport === "__new__" ? "Custom: " + customName.trim().replace(/\s+/g, " ") : newSport;
      const draft = createDraft(question, draftSport, newLocalId());
      setDrafts((value) => [draft, ...value]);
      setCreating(false); setQuestion(""); setCustomName(""); setSport("All sports"); setState("All states"); setQuery("");
      setSelectedId(draft.id);
      setMessage("Research question saved locally.");
    } catch (error) { setMessage(error.message); }
  }
  function exportWork() {
    const data = JSON.stringify(makeSnapshot(drafts, notes, tasks), null, 2);
    const url = URL.createObjectURL(new Blob([data], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url; link.download = "sift-alpha-research-export.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    setMessage("Your local research notes were exported.");
  }
  async function importWork(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { setMessage("Import must be smaller than 2 MB."); return; }
    try {
      const imported = readSnapshot(await file.text());
      if (!window.confirm("Replace local drafts and notes with this export?")) return;
      setDrafts(imported.drafts); setNotes(imported.notes); setTasks(imported.tasks || {});
      setSelectedId("nba-selector-tail"); setSport("All sports"); setState("All states"); setQuery("");
      setMessage("Local research restored from export.");
    } catch (error) { setMessage(error.message); }
  }
  function inspectSport(sportId) {
    setSport(sportId); setState("All states"); setQuery(""); setCoverageOpen(false);
    const exists = all.some((item) => item.sport === sportId);
    if (!exists) {
      setNewSport(sportId);
      setCreating(true);
      setMessage("Research is not yet built for " + sportLabel(sportId) + ". Start with one question.");
    } else {
      setMessage("Showing existing " + sportLabel(sportId) + " research.");
    }
    requestAnimationFrame(() => (exists ? searchRef.current : formRef.current)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }
  function toggleTask(id, index) {
    setTasks((current) => {
      const previous = current[id] || [];
      const updated = previous.includes(index) ? previous.filter((n) => n !== index) : [...previous, index];
      return { ...current, [id]: updated };
    });
  }
  async function copyBrief(study) {
    const brief = [
      "SIFT ALPHA RESEARCH BRIEF — RESEARCH ONLY",
      "Sport: " + sportLabel(study.sport),
      "Question: " + study.question,
      "Evidence state: " + study.status + " (as of " + study.date + ")",
      "Finding: " + study.finding,
      "Limitations: " + study.caveat,
      "Next action: " + study.next,
      "Checklist:\n" + study.checklist.map((item, index) => ((tasks[study.id] || []).includes(index) ? "[x] " : "[ ] ") + item).join("\n"),
      "Sources:\n" + (study.sources.length ? study.sources.map((item) => item.url).join("\n") : "Not yet attached"),
      "Working notes:\n" + (notes[study.id] || "(none)"),
      "Research instruction: Verify the sources and point-in-time inputs. Do not assert profitability without independent, executable after-fee evidence."
    ].join("\n\n");
    try { await navigator.clipboard.writeText(brief); setMessage("Research brief copied. You can paste it into Claude or ChatGPT."); }
    catch { setMessage("Clipboard access unavailable. Export your research instead."); }
  }
  return <div className="page">
    <header className="topbar">
      <div className="brand" aria-label="SIFT Alpha"><span className="brand-mark">S</span><strong>SIFT <span>ALPHA</span></strong></div>
      <span className="topbar-right">Research desk <span className="dot">·</span> Local workbench</span>
    </header>
    <main className="shell">
      <section className="intro" aria-labelledby="page-title">
        <div>
          <div className="eyebrow">RESEARCH DESK / 01</div>
          <h1 id="page-title">Pick up the research. Not the dashboard.</h1>
          <p>One place to find a question, read what the evidence says, and do the next useful thing.</p>
        </div>
        <div className="toolbar">
          <ActionButton onClick={() => { setCreating((v) => !v); setMessage(""); }}>{creating ? "Close" : "+ New question"}</ActionButton>
          <ActionButton secondary onClick={() => setCoverageOpen((v) => !v)}>{coverageOpen ? "Close sports" : "Browse sports"}</ActionButton>
          <ActionButton secondary onClick={exportWork}>Export</ActionButton>
          <ActionButton secondary onClick={() => importRef.current?.click()}>Import</ActionButton>
          <input ref={importRef} className="visually-hidden" type="file" accept=".json,application/json" onChange={importWork} aria-label="Import research backup" />
        </div>
      </section>
      <div className="context-row">
        <span><strong>{SPORT_REGISTRY.length}</strong> sports in registry</span>
        <span><strong>{STUDIES.length}</strong> research records</span>
        <span><strong>{pending}</strong> require follow-up</span>
        <span><strong>{drafts.length}</strong> personal drafts</span>
        <span className="safety-note">Research only · No trading or live orders</span>
      </div>
      {coverageOpen && <section className="sport-coverage" aria-label="Sport coverage and research readiness">
        <div className="coverage-intro">
          <div><div className="eyebrow">ALL-SPORT RESEARCH INTAKE</div><h2>Any sport can start with a question.</h2>
          <p>A research repository means infrastructure exists, not a profitable strategy. Sports without one remain on the roadmap until data, markets and models are verified.</p></div>
          <span className="coverage-count">{SPORT_REGISTRY.length} research tracks</span>
        </div>
        <div className="coverage-groups">
          {SPORT_GROUPS.map((group) => <div className="coverage-group" key={group}>
            <h3>{group}</h3>
            {SPORT_REGISTRY.filter((entry) => entry.group === group).map((entry) => <button className="coverage-sport" type="button" key={entry.id} onClick={() => inspectSport(entry.id)}>
              <span><strong>{entry.label}</strong><small>{entry.note || "A separate model and market-evidence review is required."}</small></span>
              <span className="coverage-status">{registryStatus(entry)} <span aria-hidden="true">›</span></span>
            </button>)}
          </div>)}
        </div>
      </section>}
      {message && <div className="message" role="status">{message}<button type="button" aria-label="Dismiss message" onClick={() => setMessage("")}>×</button></div>}
      {creating && <form ref={formRef} className="create-form" onSubmit={saveDraft}>
        <div><div className="eyebrow">NEW RESEARCH QUESTION</div><h2>Start with what you want to learn.</h2><p>No need to define an entire experiment yet.</p></div>
        <label>What is the question?<input autoFocus required minLength={8} maxLength={180} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Example: Do lineup changes create a short pricing delay?" /></label>
        <label>Sport<select value={newSport} onChange={(e) => setNewSport(e.target.value)}><SportOptions customSports={customSports} /></select></label>
        {newSport === "__new__" && <label>New sport name<input value={customName} onChange={(e) => setCustomName(e.target.value)} placeholder="e.g. Cycling" required maxLength={59} /></label>}
        <button className="button" type="submit">Save research question</button>
      </form>}
      <section className="workspace" aria-label="Research workbench">
        <aside className="library" aria-label="Find a study">
          <div className="section-heading"><div><div className="eyebrow">YOUR WORK QUEUE</div><h2>Research library</h2></div><span className="count">{visible.length}</span></div>
          <label className="search-label" htmlFor="search">Find a question or finding</label>
          <input id="search" ref={searchRef} type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search the research…" />
          <div className="filters">
            <label>Sport<select value={sport} onChange={(event) => setSport(event.target.value)}><SportOptions includeAll customSports={customSports} /></select></label>
            <label>Evidence state<select value={state} onChange={(event) => setState(event.target.value)}>{STATES.map((item) => <option key={item}>{item}</option>)}</select></label>
          </div>
          <div className="library-list">
            {visible.length === 0 ? <div className="empty"><strong>No matching research.</strong><p>Try another sport or clear the search.</p><ActionButton secondary onClick={() => { setQuery(""); setSport("All sports"); setState("All states"); }}>Clear filters</ActionButton></div> :
              visible.map((study) => <button type="button" key={study.id} className={"study-row " + (selected?.id === study.id ? "active" : "")} aria-current={selected?.id === study.id ? "true" : undefined} onClick={() => openStudy(study.id)}>
                <span className="study-meta"><span>{sportLabel(study.sport)}</span><span className={"status " + (study.status === "Draft" ? "draft" : "")}>{study.status}</span></span>
                <strong>{study.title}</strong>
                <span className="study-sub">{study.next}</span>
                <span className="date">As of {study.date}</span>
              </button>)}
          </div>
        </aside>
        <article className="detail" ref={detailRef} aria-label="Selected research detail">
          {!selected ? <div className="empty"><strong>Select a research question.</strong><p>Results will appear here.</p></div> :
          <>
            <div className="detail-head">
              <div className="eyebrow">{sportLabel(selected.sport)} / RESEARCH RECORD</div>
              <span className="detail-state">{selected.status}</span>
              <h2>{selected.title}</h2>
              <p className="question">{selected.question}</p>
              <ActionButton secondary onClick={() => copyBrief(selected)}>Copy research brief</ActionButton>
            </div>
            {selected.metrics.length > 0 && <div className="metrics">{selected.metrics.map((metric) => <div key={metric.label}><div className="metric-value">{metric.value}</div><div className="metric-label">{metric.label}</div></div>)}</div>}
            <section className="detail-section"><div className="eyebrow">WHAT THE EVIDENCE SAYS</div><p className="finding">{selected.finding}</p></section>
            <section className="detail-section caution"><div className="eyebrow">WHAT WE CANNOT CLAIM</div><p>{selected.caveat}</p></section>
            <section className="detail-section next"><div className="eyebrow">NEXT USEFUL ACTION</div><p className="next-copy">{selected.next}</p><div className="task-list">{selected.checklist.map((item, index) => <label key={item} className="task"><input type="checkbox" checked={(tasks[selected.id] || []).includes(index)} onChange={() => toggleTask(selected.id, index)} /><span>{item}</span></label>)}</div></section>
            <section className="detail-section"><div className="eyebrow">SOURCE EVIDENCE</div>
              {selected.sources.length ? <ul className="source-list">{selected.sources.filter((item) => validSource(item.url)).map((item) => <li key={item.url}><a href={item.url} target="_blank" rel="noreferrer">{item.label} <span aria-hidden="true">↗</span></a></li>)}</ul> :
              <p className="muted">No source linked. This is a personal draft, not a validated study.</p>}
            </section>
            <section className="detail-section note-box">
              <label htmlFor="research-note"><span className="eyebrow">YOUR WORKING NOTES</span><span className="muted">Saved automatically in this browser; export to keep or transfer them.</span></label>
              <textarea id="research-note" rows={5} maxLength={10000} value={notes[selected.id] || ""} onChange={(event) => setNotes((value) => ({ ...value, [selected.id]: event.target.value }))} placeholder="What should we examine next? What would change the conclusion?" />
              <div className="fine-print">Local notes are not encrypted or synced. Do not put API keys, account details, or sensitive trading strategies here.</div>
            </section>
            <footer className="detail-footer">Record last reviewed: {selected.date} · Source-linked findings are snapshots, not live feeds.</footer>
          </>}
        </article>
      </section>
      <footer className="app-footer">SIFT Alpha · Evidence before conclusions. Research-only prototype, independent of SIFT 3.0.</footer>
    </main>
  </div>;
}
createRoot(document.getElementById("root")).render(<App />);