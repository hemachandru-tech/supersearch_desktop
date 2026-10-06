// ss/api.js  — load BEFORE the screen scripts in the HTML.
const BASE = ""; // same-origin (served by FastAPI).

async function j(method, path, body) {
  const res = await fetch(BASE + path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    let msg = `Error ${res.status}: ${res.statusText}`;
    try {
      const parsed = JSON.parse(text);
      if (parsed.error) msg = parsed.error;
    } catch(e) {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

window.api = {
  // --- existing endpoints ---
  filters:  ()                 => j("GET",  "/api/filters"),   // library distinct values + master taxonomy
  roster:   ()                 => j("GET",  "/api/roster"),    // master player list (lazy; loads classifier only)
  search:   (q, filters)       => {
    const params = { q: q || "" };
    if (filters) {
      if (filters.player) params.player = filters.player;
      if (filters.event) params.event = filters.event;
      if (filters.mood) params.mood = filters.mood;
      if (filters.action) params.action = filters.action;
      if (filters.jersey) params.jersey_color = filters.jersey;
    }
    return j("GET", `/api/search?` + new URLSearchParams(params));
  },
  metadata: (id)               => j("GET",  `/api/metadata?id=${encodeURIComponent(id)}`),
  thumbURL: (id)               => `${BASE}/api/thumb?id=${encodeURIComponent(id)}`,   // use as <img src>
  startTagging: (folder, opts) => j("POST", "/api/start", { folder, ...opts }),
  stopTagging:  ()             => j("POST", "/api/stop"),
  progress: ()                 => j("GET",  "/api/progress"),
  browse:   ()                 => j("POST", "/api/pick-folder"),     // opens native folder picker, returns {folder}

  // --- new endpoints ---
  save:     (id, fields)       => j("POST", `/api/edit/${encodeURIComponent(id)}`, fields),
  verify:   (id)               => j("GET",  `/api/verify?id=${encodeURIComponent(id)}`),
  resolveFace: (payload)       => j("POST", "/api/face/resolve", payload),
  refresh:  ()                 => j("POST", "/api/refresh"),   // sync library with disk
};
