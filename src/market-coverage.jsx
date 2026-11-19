import React, {useEffect, useMemo, useState} from "react";
// Summary numbers render at once; the per-market / per-input detail (about 1 MB) loads on demand.
import BASE from "../research/data_foundation_ops/phase12_baseline.json";
import STUDIES from "../research/discovery/index.json";

const DETAIL = import.meta.glob("../research/data_foundation_ops/market_coverage.json");
let detailPromise = null;
const KIND = {CERTIFIED: "ok", UNVERIFIED: "chipwarn", NOT_BUILT: "chipwarn", NO_PREGAME_HISTORY: "unv", RIGHTS_BLOCKED: "miss", PAID_OR_NO_SOURCE: "miss", DATA_MISSING: "miss"};
const Chip = ({k = "plain", children, title}) => <span className={"ir-chip ir-" + k} title={title}>{children}</span>;
const fmt = n => n == null ? "n/a" : typeof n === "number" ? n.toLocaleString("en-US") : String(n);
const delta = (a, b) => b == null || a == null || a === b ? null : <small className="ir-why"> ({b > a ? "+" : ""}{fmt(b - a)} since Phase 11)</small>;

function Bar({cls, classes, label}) {
  const tot = classes.reduce((s, c) => s + (cls[c] || 0), 0) || 1;
  return <div className="cov-bar" role="img" aria-label={label}>{classes.filter(c => cls[c]).map(c =>
    <span key={c} className={"cov-seg cov-" + c} style={{flexGrow: cls[c] / tot}} title={`${c.replaceAll("_", " ").toLowerCase()}: ${cls[c]}`}/>)}</div>;
}

function InputRow({k, role, C}) {
  const [open, setOpen] = useState(false);
  const i = C.inputs[k];
  return <li className="mim-card" data-testid="cov-input">
    <button className="mim-linkbtn" aria-expanded={open} onClick={() => setOpen(!open)}><b>{i.l}</b></button> <Chip k={KIND[i.cls]}>{C.class_label[i.cls]}</Chip> {role === "primary" && <Chip>primary</Chip>}
    {open && <div className="ir-why">
      <div><code>{k}</code> · point-in-time: {i.pit.replaceAll("_", " ").toLowerCase()}{i.cert ? <> · certified dataset <code>{i.cert}</code></> : null}</div>
      <div>Checks: {Object.entries(i.chk).map(([c, v]) => <Chip key={c} k={v === "OK" ? "ok" : v === "PARTIAL" ? "chipwarn" : "miss"}>{c}: {v.toLowerCase()}</Chip>)}</div>
      <div>Sources: {i.src.length ? i.src.map(([d, held]) => <Chip key={d} k={held ? "ok" : "miss"} title={held ? "raw data archived" : "not archived"}>{d}{held ? " ✓" : ""}</Chip>) : "none recorded"}</div>
      <div>Gap: {i.gap}</div>
      <div><b>Next:</b> {C.next_action[i.cls]}</div>
    </div>}
  </li>;
}

function Market({m, C}) {
  const [open, setOpen] = useState(false);
  const share = m.certified_primary_share;
  return <li className="mim-card" data-testid="cov-market">
    <button className="mim-linkbtn" aria-expanded={open} onClick={() => setOpen(!open)}><b>{m.label}</b></button>
    <div className="ir-why">{m.n_primary} primary inputs, {fmt(m.primary_cls.CERTIFIED || 0)} certified{share != null ? ` (${Math.round(share * 100)}%)` : ""} · {m.n} predictive inputs in all{m.series.length ? " · " + m.series.slice(0, 4).join(", ") : ""}</div>
    <Bar cls={m.cls} classes={C.classes} label={"coverage of " + m.label}/>
    <div className="ir-why"><b>Next:</b> {m.next}</div>
    {open && <ul className="mim-list">{m.inputs.map(([k, r]) => <InputRow key={k} k={k} role={r} C={C}/>)}</ul>}
  </li>;
}

function Study({s}) {
  return <li className="mim-card" data-testid="cov-study">
    <b>{s.title}</b> <Chip k={s.holdout_scored ? "ok" : "chipwarn"}>{s.holdout_scored ? "holdout scored once" : "holdout sealed"}</Chip>
    <div className="ir-why">{s.sport} · dataset <code>{s.dataset}</code> · test seasons {s.test} · holdout {s.holdout}</div>
    <ul className="ir-fine">{s.findings.map((f, i) => <li key={i}>{f}</li>)}</ul>
    <div className="ir-why">Hypotheses: {s.hypotheses.tested} tested, {s.hypotheses.demonstrated} demonstrated after Holm, {s.hypotheses.suggestive} suggestive only, {s.hypotheses.worse} worse than the reference.</div>
  </li>;
}

export function MarketCoverage() {
  const [C, setC] = useState(null);
  const [sport, setSport] = useState("NFL");
  const [n, setN] = useState(8);
  useEffect(() => { let live = true; detailPromise ||= Object.values(DETAIL)[0]().then(x => x.default || x); detailPromise.then(x => live && setC(x)); return () => { live = false; }; }, []);
  const b = BASE.totals, now = C?.now;
  const S = C?.sports[sport], B = BASE.sports[sport];
  const markets = useMemo(() => S ? S.markets : [], [S]);
  return <div data-testid="market-coverage" data-ready={C ? "yes" : "no"}>
    <h3>Coverage: sport → market → input → source → gap → next action</h3>
    <p className="ir-fine">Six core sports. Every predictive input has exactly one class. Archived raw data, a built feature and a certified input are three different things and are never merged. Before = end of Phase 11.</p>
    <div className="mim-cards" data-testid="cov-totals">
      <div><b>{fmt(now?.cls.CERTIFIED ?? b.cls.CERTIFIED)}</b><small>certified inputs{delta(b.cls.CERTIFIED, now?.cls.CERTIFIED)}</small></div>
      <div><b>{fmt(now?.data_complete_missing_inputs ?? b.data_complete_missing_inputs)}</b><small>missing inputs with all raw data archived{delta(b.data_complete_missing_inputs, now?.data_complete_missing_inputs)}</small></div>
      <div><b>{fmt(now?.cls.NOT_BUILT ?? b.cls.NOT_BUILT)}</b><small>archived, feature not built{delta(b.cls.NOT_BUILT, now?.cls.NOT_BUILT)}</small></div>
      <div><b>{fmt(now?.cls.DATA_MISSING ?? b.cls.DATA_MISSING)}</b><small>raw data not archived{delta(b.cls.DATA_MISSING, now?.cls.DATA_MISSING)}</small></div>
      <div><b>{fmt(now?.cls.RIGHTS_BLOCKED ?? b.cls.RIGHTS_BLOCKED)}</b><small>blocked by rights{delta(b.cls.RIGHTS_BLOCKED, now?.cls.RIGHTS_BLOCKED)}</small></div>
      <div><b>{fmt(now?.missing_primary_slots ?? b.missing_primary_slots)}</b><small>missing primary slots (not verified){delta(b.missing_primary_slots, now?.missing_primary_slots)}</small></div>
    </div>
    <div className="sport-tabs" role="tablist" aria-label="Sport">{Object.keys(BASE.sports).map(s =>
      <button key={s} role="tab" aria-selected={s === sport} className={s === sport ? "on" : ""} onClick={() => { setSport(s); setN(8); }}>{s}</button>)}</div>
    {!C && <p className="ir-fine">Loading market detail…</p>}
    {S && <>
      <table className="cov-table" data-testid="cov-sport-table"><thead><tr><th>Class</th><th>Before</th><th>Now</th></tr></thead><tbody>
        {C.classes.map(c => <tr key={c}><td><span className={"cov-dot cov-" + c}/> {C.class_label[c]}</td><td>{fmt(B.cls[c])}</td><td><b>{fmt(S.cls[c])}</b></td></tr>)}
      </tbody></table>
      <ul className="mim-list" data-testid="cov-markets">{markets.slice(0, n).map(m => <Market key={m.k} m={m} C={C}/>)}</ul>
      {n < markets.length && <button className="button secondary" onClick={() => setN(n + 12)}>Show more markets ({markets.length - n} left)</button>}
    </>}
    <h3>Predictive research (preregistered, out of sample)</h3>
    <p className="ir-fine">Accuracy evidence only. No executable price, liquidity or fee data is used, so nothing below is a claim of betting value.</p>
    <ul className="mim-list">{STUDIES.studies.map(s => <Study key={s.study} s={s}/>)}</ul>
  </div>;
}
