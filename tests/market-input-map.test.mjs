import {test} from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {execFileSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import {classifyEdge,parseCSV} from "../scripts/build-market-input-map.mjs";

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"..");
const folder=path.join(root,"public/market-input-map");
const out=(name)=>fs.readFileSync(path.join(folder,name),"utf8");
let map;
test("generate a reproducible approved-catalog dependency map",()=>{
  const cmd=()=>{
    const report=JSON.parse(execFileSync(process.execPath,["scripts/build-market-input-map.mjs"],
      {cwd:root,encoding:"utf8",maxBuffer:10*1024*1024}));
    return report;
  };
  const first=cmd();
  const hash1=out("graph.json");
  const second=cmd();
  assert.equal(hash1,out("graph.json"),"rebuilding changes graph output");
  assert.deepEqual(first.summary,second.summary);
  assert.equal(first.summary.inputs,1649);
  assert.equal(first.summary.archetypes,170);
  assert.equal(first.summary.predictiveSlots,3670);
  assert.equal(first.summary.primaryMissing,949);
  assert.equal(first.summary.primaryCovered,327);
  map=JSON.parse(hash1);
  assert.equal(map.status,"RESEARCH_ONLY");
  assert.equal(map.inputs.length,1649);
  assert.equal(map.markets.length,170);
  assert.equal(new Set(map.inputs.map(i=>i.key)).size,1649);
  assert.equal(new Set(map.markets.map(m=>m.id)).size,170);
  assert.equal(map.report.unmappedMarketArchetypes.length,0,"every archetype should resolve to the catalog");
});
test("every market-input requirement is represented once, including excluded benchmarks",()=>{
  assert.ok(map);
  const edges=new Set(map.edges.map(e=>e.market+"|"+e.input));
  assert.equal(edges.size,map.edges.length);
  assert.equal(map.summary.marketEdges,map.edges.length);
  for(const m of map.markets){
    assert.equal(map.edges.filter(e=>e.market===m.id).length,m.inputs.length);
    assert.equal(new Set(m.inputs).size,m.inputs.length);
  }
  assert.ok(map.edges.some(e=>e.kind==="MARKET_DERIVED_BENCHMARK"));
  assert.ok(map.edges.some(e=>e.kind==="RULES_SETTLEMENT_METADATA"));
  assert.ok(map.edges.some(e=>e.kind==="PREDICTIVE"&&e.primary));
  assert.ok(map.inputs.some(i=>i.status==="DATA_IN_HAND"));
});
test("dataset requirements are traceable and deduplicated, never summed across datasets",()=>{
  const dsSet=new Set(map.datasets.map(d=>d.id));
  const inpSet=new Set(map.inputs.map(i=>i.key));
  assert.equal(new Set(map.datasetEdges.map(e=>e.dataset+"|"+e.input)).size,map.datasetEdges.length);
  for(const edge of map.datasetEdges){
    assert.ok(dsSet.has(edge.dataset));
    assert.ok(inpSet.has(edge.input));
    assert.ok(edge.fields.length>0||edge.fieldEvidence==="FIELD_UNMAPPED");
  }
  for(const q of map.queue){
    assert.equal(new Set(q.impactMarkets).size,q.distinctMarkets);
    assert.equal(new Set(q.impactedInputs).size,q.distinctInputs);
    assert.ok(q.potentialPrimarySlots>=q.distinctMarkets);
    assert.ok(q.next.length>10);
    assert.match(q.caveat,/not be summed|overlap/i);
  }
});
test("CSV exports match the exact normalized graph rows and retain identifiers",()=>{
  const expected={
    "market-input-edges.csv":map.edges.length,
    "distinct-inputs.csv":map.inputs.length,
    "dataset-input-edges.csv":map.datasetEdges.length,
    "acquisition-queue.csv":map.queue.length,
  };
  for(const [file,rows] of Object.entries(expected)){
    const records=parseCSV(out(file));
    assert.equal(records.length,rows,file);
    assert.ok(records.every(r=>Object.values(r).every(v=>typeof v==="string")));
  }
  assert.ok(JSON.parse(out("reconciliation.json")).unmapped);
});
test("role classification refuses to mix price, rules, operations and predictions",()=>{
  const row={settlement_ops_ids:["m.settlement_truth"],calibration_ids:["m.strike_hit_rates"]};
  assert.equal(classifyEdge("m.external_lines","EXCLUDED_MARKET",row,{}),"MARKET_DERIVED_BENCHMARK");
  assert.equal(classifyEdge("m.rules_text","FREE_ACCESSIBLE",row,{}),"RULES_SETTLEMENT_METADATA");
  assert.equal(classifyEdge("m.settlement_truth","FREE_ACCESSIBLE",row,{}),"SETTLEMENT_OPERATIONS");
  assert.equal(classifyEdge("m.strike_hit_rates","FREE_ACCESSIBLE",row,{}),"CALIBRATION_OPERATIONS");
  assert.equal(classifyEdge("nba.minutes","FULL",row,{}),"PREDICTIVE");
});
test("RFC4180 field parser retains quoted commas/newlines",()=>{
  const r=parseCSV('a,b,c\r\n"one, two","line1\nline2","quoted ""text"""\r\n');
  assert.deepEqual(r,[{a:"one, two",b:"line1\nline2",c:'quoted "text"'}]);
});
