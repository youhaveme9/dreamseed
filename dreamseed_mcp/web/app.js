"use strict";

const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="dreamseed-session"]').content;
let activeJob = null;
let busy = false;
let selectedSeed = "-7333811035076652275";
let searchCriteria = null;
let selectedVersion = "1.21.3";
let previewUrl = null;
let mesh = null;
let terrainGrid = null;
let yaw = 0.6;
let pitch = 0.65;

function example(operation) {
  const criteria = searchCriteria || {
    minecraft_version: "1.21.3", reference_point: {x: 0, z: 0},
    hard_constraints: [
      {id: "plains", type: "biome_at", biome: "plains", y: 64},
      {id: "village", type: "structure_within", structure: "village", radius: 500}
    ], soft_preferences: [{type: "minimize_distance", constraint_id: "village", weight: 1}]
  };
  if (operation === "search") return {...criteria, budget: {strategy: "sampled", sample_seed: "20261020", max_candidates: 50000, max_seconds: 5, workers: 4}, max_results: 3};
  if (operation === "candidate") return {...criteria, seed: selectedSeed, max_seconds: 120};
  if (operation === "compare") return {...criteria, seeds: [...new Set([selectedSeed, "2579", "0"])]};
  if (operation === "verify") return {minecraft_version: selectedVersion, seed: selectedSeed, structures: ["village", "pillager_outpost"], probe_surfaces: true, max_seconds: 120};
  if (operation === "terrain") return {minecraft_version: selectedVersion, seed: selectedSeed, area: {center: {x: 48, z: 16}, radius: 32, sample_step: 16}, preferences: [{metric: "relief_blocks", target: 40, tolerance: 40, weight: 1}], include_preview: true, include_mesh: true, max_seconds: 120};
  return {minecraft_version: selectedVersion, seed: selectedSeed, area: {center: {x: 0, z: 0}, radius: 512, sample_step: 32, y: 96}, structures: ["village", "pillager_outpost"], ...(operation === "inspect" ? {include_biome_map: true} : {})};
}

async function api(operation, body) {
  const response = await fetch(`/api/${operation}`, {method: "POST", headers: {"Content-Type": "application/json", "X-DreamSeed-Token": token}, body: JSON.stringify(body)});
  const data = await response.json();
  if (!data.ok) throw new Error(`${data.error.code}: ${data.error.message}${data.error.details ? "\n" + JSON.stringify(data.error.details) : ""}`);
  return data;
}

function show(data) {
  $("output").textContent = JSON.stringify(data, null, 2);
  $("seeds").replaceChildren();
  const results = data.results || data.comparison?.results || [];
  for (const result of results) {
    const card = document.createElement("div"); card.className = "seed-card";
    const code = document.createElement("code"); code.textContent = result.seed; card.append(code);
    const facts = document.createElement("p");
    facts.textContent = `Score ${Number(result.soft_preference_score || 0).toFixed(2)} · ${result.validation_status || (result.meets_all_hard_constraints ? "matches" : "rejected")}`;
    card.append(facts);
    for (const operation of ["inspect", "terrain", "candidate"]) {
      const button = document.createElement("button"); button.className = "quiet"; button.textContent = operation;
      button.addEventListener("click", () => { selectedSeed = result.seed; selectedVersion = result.minecraft_version; $("operation").value = operation; loadExample(); });
      card.append(button);
    }
    $("seeds").append(card);
  }
  const rendering = data.rendering || data.verification?.rendering || data.terrain?.preview;
  $("preview").replaceChildren();
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  if (rendering?.svg) {
    previewUrl = URL.createObjectURL(new Blob([rendering.svg], {type: "image/svg+xml"}));
    const image = document.createElement("img"); image.src = previewUrl; image.alt = data.terrain ? "Generated surface heightmap" : "Sampled biome map";
    $("preview").append(image);
  }
  mesh = data.terrain?.preview?.mesh || null;
  terrainGrid = data.terrain?.grid || null;
  $("download").hidden = !mesh;
  $("terrain-canvas").hidden = !terrainGrid;
  $("mesh-help").hidden = !terrainGrid;
  if (terrainGrid) drawTerrain();
}

function drawTerrain() {
  if (!terrainGrid) return;
  const canvas = $("terrain-canvas"), ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const g = terrainGrid, step = g.sample_step;
  const heights = g.rows.flat().filter(Boolean).map((cell) => cell.surface_y - 1);
  const mean = heights.reduce((a, b) => a + b, 0) / Math.max(1, heights.length);
  const extent = Math.max(step, (g.width - 1) * step, Math.max(...heights, mean) - Math.min(...heights, mean));
  const scale = Math.min(canvas.width, canvas.height) * 0.6 / extent;
  function vertex(r, c) {
    const x = (c - (g.width - 1) / 2) * step, z = (r - (g.height - 1) / 2) * step, y = g.rows[r][c].surface_y - 1 - mean;
    const rx = x * Math.cos(yaw) - z * Math.sin(yaw), rz = x * Math.sin(yaw) + z * Math.cos(yaw);
    return [canvas.width / 2 + rx * scale, canvas.height / 2 + (rz * Math.sin(pitch) - y * Math.cos(pitch)) * scale, rz * Math.cos(pitch) + y * Math.sin(pitch)];
  }
  const faces = [];
  for (let r = 0; r < g.height - 1; r++) for (let c = 0; c < g.width - 1; c++) {
    const corners = [[r,c],[r+1,c],[r,c+1],[r+1,c+1]];
    if (corners.some(([row,col]) => !g.rows[row][col])) continue;
    for (const triangle of [[0,1,2],[2,1,3]]) {
      const coords = triangle.map((index) => corners[index]);
      const points = coords.map(([row,col]) => vertex(row,col));
      const water = coords.some(([row,col]) => g.rows[row][col].is_water);
      faces.push({points, depth: points.reduce((sum, point) => sum + point[2], 0) / 3, water});
    }
  }
  faces.sort((a,b) => b.depth - a.depth);
  for (const face of faces) {
    ctx.beginPath(); face.points.forEach((point,index) => index ? ctx.lineTo(point[0],point[1]) : ctx.moveTo(point[0],point[1])); ctx.closePath();
    ctx.fillStyle = face.water ? "#237abb" : "#85a969"; ctx.fill(); ctx.strokeStyle = "#2d5139"; ctx.lineWidth = .6; ctx.stroke();
  }
}

function loadExample() { $("request").value = JSON.stringify(example($("operation").value), null, 2); }
$("example").addEventListener("click", loadExample);
$("operation").addEventListener("change", loadExample);
$("run").addEventListener("click", async () => {
  if (busy) return;
  busy = true; $("run").disabled = true; $("state").textContent = "WORKING";
  try {
    const operation = $("operation").value, request = JSON.parse($("request").value);
    $("status").textContent = operation === "terrain" || operation === "verify" || operation === "candidate" ? "Starting isolated official Minecraft verification. This can take a minute." : "Running the native engine…";
    let data = await api(operation, request);
    if (operation === "search") {
      searchCriteria = Object.fromEntries(Object.entries(request).filter(([key]) => ["minecraft_version","reference_point","hard_constraints","soft_preferences"].includes(key)));
      show(data);
      activeJob = data.job_id; $("cancel").disabled = false;
      while (true) {
        const status = await api("status", {job_id: activeJob});
        $("state").textContent = status.state.toUpperCase();
        $("status").textContent = `${status.candidates_evaluated.toLocaleString()} candidates · ${status.matching_seeds_found} matches · ${status.elapsed_seconds.toFixed(1)} seconds`;
        data = await api("results", {job_id: activeJob}); show(data);
        if (!["queued","running","cancelling"].includes(status.state)) break;
        await new Promise((resolve) => setTimeout(resolve, 600));
      }
      $("status").textContent += ` · ${data.coverage || "partial coverage"}. All distances use explicit anchors, not world spawn.`;
    } else {
      show(data); $("state").textContent = "COMPLETE";
      $("status").textContent = data.terrain ? `${data.terrain.grid.observed_sample_count} generated samples · relief ${data.terrain.analysis.metrics.relief_blocks} blocks · control heights ${data.terrain.control_heights_match === true ? "confirmed" : "incomplete"}` : "Engine request complete. Read validation status and caveats in the structured output.";
    }
  } catch (error) { $("state").textContent = "ERROR"; $("status").textContent = error.message; }
  finally { busy = false; activeJob = null; $("run").disabled = false; $("cancel").disabled = true; }
});
$("cancel").addEventListener("click", async () => {
  if (!activeJob) return;
  $("cancel").disabled = true;
  try { await api("cancel", {job_id: activeJob}); } catch (error) { $("status").textContent = error.message; }
});
$("download").addEventListener("click", () => {
  if (!mesh) return;
  const url = URL.createObjectURL(new Blob([mesh.obj], {type: "text/plain"}));
  const link = document.createElement("a"); link.href = url; link.download = "dreamseed-surface.obj"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
let drag = null;
$("terrain-canvas").addEventListener("pointerdown", (event) => { drag = [event.clientX,event.clientY]; event.target.setPointerCapture(event.pointerId); });
$("terrain-canvas").addEventListener("pointermove", (event) => { if (!drag) return; yaw += (event.clientX-drag[0]) * .01; pitch = Math.max(.1,Math.min(1.5,pitch+(event.clientY-drag[1]) * .005)); drag = [event.clientX,event.clientY]; drawTerrain(); });
for (const name of ["pointerup","pointercancel","lostpointercapture"]) $("terrain-canvas").addEventListener(name, () => { drag = null; });
loadExample();
api("capabilities", {}).then(({capabilities}) => { $("capabilities").textContent = `JAVA ${capabilities.minecraft_versions.join(" / ")} · ${capabilities.structure_filters.types.length} STRUCTURES · OFFICIAL VERIFIER ${capabilities.authoritative_verification.available ? "READY" : "NOT INSTALLED"}`; }).catch((error) => { $("capabilities").textContent = error.message; });
