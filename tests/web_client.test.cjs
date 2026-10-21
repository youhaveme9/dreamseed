"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

async function main() {
  const base = process.argv[2];
  const html = await (await fetch(base)).text();
  const session = html.match(/name="dreamseed-session" content="([^"]+)"/)[1];
  let triangleFills = 0;
  class Element {
    constructor() { this.listeners = new Map(); this.children = []; this.value = ""; this.textContent = ""; this.width = 720; this.height = 440; }
    addEventListener(name, fn) { this.listeners.set(name, fn); }
    append(child) { this.children.push(child); }
    replaceChildren(...children) { this.children = children; }
    click() { return this.listeners.get("click")?.(); }
    getContext() { return {clearRect() {},beginPath() {},lineTo() {},moveTo() {},closePath() {},fill() { triangleFills++; },stroke() {}}; }
  }
  const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map((match) => [match[1], new Element()]));
  elements.get("operation").value = "search";
  const document = {
    getElementById(id) { assert(elements.has(id), `Unknown DOM id ${id}`); return elements.get(id); },
    querySelector() { return {content: session}; }, createElement() { return new Element(); }
  };
  const context = vm.createContext({document, fetch: (url, options) => fetch(base + url, options), URL, Blob, setTimeout, console});
  const source = fs.readFileSync(path.join(__dirname, "../dreamseed_mcp/web/app.js"), "utf8");
  vm.runInContext(source, context);
  const request = {
    minecraft_version: "1.21.1", reference_point: {x: 0,z: 0},
    hard_constraints: [{id: "plains",type: "biome_at",biome: "plains",y: 64},
      {id: "village",type: "structure_within",structure: "village",radius: 32}],
    soft_preferences: [{type: "minimize_distance",constraint_id: "village",weight: 1}],
    budget: {strategy: "sequential",start_seed: "2579",max_candidates: 1,max_seconds: 2,workers: 1},max_results: 1
  };
  elements.get("request").value = JSON.stringify(request);
  await elements.get("run").click();
  const output = JSON.parse(elements.get("output").textContent);
  assert.equal(output.state, "completed");
  assert.equal(output.results[0].seed, "2579");
  assert.equal(output.results[0].soft_preference_score, 100);
  const card = elements.get("seeds").children[0];
  await card.children.find((element) => element.textContent === "candidate").click();
  const refined = JSON.parse(elements.get("request").value);
  assert.equal(refined.minecraft_version, request.minecraft_version);
  assert.deepEqual(refined.hard_constraints, request.hard_constraints);
  assert.deepEqual(refined.soft_preferences, request.soft_preferences);
  const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/java_1_21_3_terrain.json"), "utf8"));
  context.surfaceFixture = {terrain: {
    grid: {width: 5,height: 5,sample_step: 16,rows: fixture.surface_y_rows.map((row) => row.map((surface_y) => ({surface_y,is_water: false})))},
    preview: {svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>',mesh: {obj: "v 0 101 0\n"}}
  }};
  vm.runInContext("show(surfaceFixture)", context);
  assert.equal(triangleFills, 32);
  assert.equal(elements.get("terrain-canvas").hidden, false);
  assert.equal(elements.get("download").hidden, false);
  console.log(JSON.stringify({ok: true,actual_engine_search: true,criteria_preserved: true,surface_triangles: triangleFills,dom: "synthetic_unit_harness_not_visual_browser_validation"}));
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
