// app.js - front-end logic for Super Search Desktop
const $ = (id) => document.getElementById(id);
let progressTimer = null;
let currentImage = null;

// ---------------------------------------------------------------- status
async function refreshStatus() {
  try {
    const s = await fetch("/api/status").then((r) => r.json());
    const keyMsg = s.api_keys > 0
      ? `${s.api_keys} Gemini key(s) loaded`
      : "⚠ No Gemini key in .env";
    $("statusBar").innerHTML =
      `${keyMsg} · Metadata: ${s.metadata_backend.split(" ")[0]} · ` +
      `Tagged: ${s.stats.completed}/${s.stats.total} · Embedded: ${s.stats.metadata_written}`;
    if (s.last_folder && !$("folderInput").value) $("folderInput").value = s.last_folder;
  } catch (e) {
    $("statusBar").textContent = "backend not reachable";
  }
}

// ---------------------------------------------------------------- browse
$("browseBtn").addEventListener("click", async () => {
  const btn = $("browseBtn");
  btn.disabled = true;
  btn.textContent = "Opening…";
  try {
    const res = await fetch("/api/pick-folder", { method: "POST" }).then((r) => r.json());
    if (res.folder) $("folderInput").value = res.folder;
    else if (res.error) alert("Could not open the folder chooser. Just paste the path instead.\n\n" + res.error);
  } catch (e) {
    alert("Could not open the folder chooser. Just type or paste the folder path in the box.");
  } finally {
    btn.disabled = false;
    btn.textContent = "Browse…";
  }
});

// ---------------------------------------------------------------- start tagging
$("startBtn").addEventListener("click", async () => {
  const folder = $("folderInput").value.trim();
  if (!folder) { alert("Please choose a folder first."); return; }
  $("startBtn").disabled = true;
  $("progressWrap").style.display = "block";
  $("logBox").textContent = "Starting…";

  const res = await fetch("/api/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      folder,
      recursive: $("recursive").checked,
      force: $("force").checked,
    }),
  }).then((r) => r.json());

  if (!res.ok) {
    alert(res.error || "Could not start.");
    $("startBtn").disabled = false;
    return;
  }
  if (progressTimer) clearInterval(progressTimer);
  progressTimer = setInterval(pollProgress, 800);
});

async function pollProgress() {
  const p = await fetch("/api/progress").then((r) => r.json());
  const pct = p.total > 0 ? Math.round((p.done / p.total) * 100) : (p.loading_models ? 5 : 0);
  $("progressFill").style.width = pct + "%";
  let txt = p.loading_models
    ? "Loading AI models (first run can take a minute)…"
    : `${p.done}/${p.total} done · ${p.ok} tagged · ${p.errors} errors · ${p.skipped} skipped`;
  if (!p.loading_models && p.rate) {
    txt += ` · ${p.rate} img/s`;
    if (p.eta_seconds) txt += ` · ~${fmtETA(p.eta_seconds)} left`;
  }
  if (p.current) txt += ` · now: ${p.current}`;
  $("progressText").textContent = txt;
  if (p.log && p.log.length) {
    $("logBox").textContent = p.log.slice(-200).join("\n");
    $("logBox").scrollTop = $("logBox").scrollHeight;
  }
  if (p.finished && !p.running) {
    clearInterval(progressTimer);
    progressTimer = null;
    $("startBtn").disabled = false;
    refreshStatus();
    loadFilters();
    doSearch();
  }
}

// ---------------------------------------------------------------- filters
async function loadFilters() {
  const f = await fetch("/api/filters").then((r) => r.json());
  fill("f_player", f.players, "All players");
  fill("f_event", f.events, "All events");
  fill("f_mood", f.moods, "All moods");
  fill("f_action", f.actions, "All actions");
  fill("f_jersey_color", f.jersey_colors, "All jersey colours");
}
function fill(id, values, allLabel) {
  const sel = $(id);
  const cur = sel.value;
  sel.innerHTML = `<option value="">${allLabel}</option>` +
    (values || []).map((v) => `<option>${escapeHtml(v)}</option>`).join("");
  sel.value = cur;
}

// ---------------------------------------------------------------- search
async function doSearch() {
  const params = new URLSearchParams({
    q: $("searchInput").value.trim(),
    player: $("f_player").value,
    event: $("f_event").value,
    mood: $("f_mood").value,
    action: $("f_action").value,
    jersey_color: $("f_jersey_color").value,
  });
  const data = await fetch("/api/search?" + params).then((r) => r.json());
  renderGrid(data.results);
  $("resultMeta").textContent = `${data.count} image(s) found`;
}

function renderGrid(rows) {
  const grid = $("grid");
  if (!rows || rows.length === 0) {
    grid.innerHTML = `<div class="empty">No images yet. Tag a folder above, then search.</div>`;
    return;
  }
  grid.innerHTML = rows.map((r) => {
    const chips = [r.player_names, r.action, r.event_type, r.mood]
      .filter((x) => x && x.toLowerCase() !== "unknown")
      .slice(0, 4)
      .map((x) => `<span class="chip">${escapeHtml(x)}</span>`).join("");
    return `
      <div class="card" data-id="${r.id}">
        <img loading="lazy" src="/api/thumb?id=${r.id}" alt="" />
        <div class="card-body">
          <div class="card-title">${escapeHtml(r.file_name || "")}</div>
          <div class="card-tags">${chips}</div>
        </div>
      </div>`;
  }).join("");
  grid.querySelectorAll(".card").forEach((c) =>
    c.addEventListener("click", () => openModal(rows.find((x) => x.id == c.dataset.id)))
  );
}

// ---------------------------------------------------------------- modal / edit
const EDITABLE = ["player_names", "event_type", "mood", "action", "location",
  "jersey_color", "apparel", "crowd_present", "caption", "tournament"];
const LABELS = {
  player_names: "Player(s)", event_type: "Event", mood: "Mood", action: "Action",
  location: "Location", jersey_color: "Jersey colour", apparel: "Apparel",
  crowd_present: "Crowd present", caption: "Caption", tournament: "Tournament",
};

function openModal(row) {
  if (!row) return;
  currentImage = row;
  $("modalImg").src = "/api/file?id=" + row.id;
  $("modalName").textContent = row.file_path;
  $("tagFields").innerHTML = EDITABLE.map((k) => `
    <div>
      <label>${LABELS[k]}</label>
      <input data-field="${k}" value="${escapeHtml(row[k] || "")}" />
    </div>`).join("");
  $("verifyBox").style.display = "none";
  $("modal").style.display = "flex";
}
$("modalClose").addEventListener("click", () => ($("modal").style.display = "none"));
$("modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("modal").style.display = "none"; });

$("saveTagsBtn").addEventListener("click", async () => {
  const payload = {};
  $("tagFields").querySelectorAll("input").forEach((i) => (payload[i.dataset.field] = i.value));
  const res = await fetch("/api/edit/" + currentImage.id, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then((r) => r.json());
  if (res.ok) {
    alert("Saved and re-embedded into the image.\n" +
          (res.metadata_note || "") + "\n" + (res.learn_note || ""));
    doSearch();
    loadFilters();
  } else {
    alert(res.error || "Save failed");
  }
});

$("verifyBtn").addEventListener("click", async () => {
  const res = await fetch("/api/metadata?id=" + currentImage.id).then((r) => r.json());
  $("verifyBox").style.display = "block";
  $("verifyBox").textContent =
    "What is actually embedded in this file right now:\n\n" +
    JSON.stringify(res.embedded, null, 2);
});

$("openFileBtn").addEventListener("click", () => window.open("/api/file?id=" + currentImage.id, "_blank"));

// ---------------------------------------------------------------- wire up
$("searchBtn").addEventListener("click", doSearch);
$("searchInput").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
["f_player", "f_event", "f_mood", "f_action", "f_jersey_color"].forEach((id) =>
  $(id).addEventListener("change", doSearch)
);

function fmtETA(sec) {
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.round(sec / 60)} min`;
  return `${(sec / 3600).toFixed(1)} hr`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// initial load
refreshStatus();
loadFilters();
doSearch();
setInterval(refreshStatus, 5000);
