import "./style.css";

type Label = "person" | "car" | "drone_like" | "unknown";

interface Track {
  track_id: number;
  confirmed: boolean;
  x_m: number;
  y_m: number;
  range_m: number;
  azimuth_deg: number;
  speed_mps: number;
  radial_velocity_mps: number;
  label: Label;
}

interface Head {
  run_id: string;
  session_id: string;
  frame_index: number;
  timestamp_ns: number;
}

type LiveMessage =
  | (Head & { type: "tracks"; tracks: Track[] })
  | (Head & {
      type: "rdmaps";
      shape: [number, number];
      range_bin_m: number;
      velocity_bin_mps: number;
      encoding?: "zlib";
      data: string;
    });

const COLORS: Record<Label, string> = {
  person: "#60a5fa",
  car: "#f59e0b",
  drone_like: "#f43f5e",
  unknown: "#94a3b8",
};
const LABEL_TEXT: Record<Label, string> = {
  person: "person",
  car: "car",
  drone_like: "drone-like",
  unknown: "…",
};
const MAP_RANGE_M = 80;
const RD_MAX_RANGE_BINS = 100;
const TRAIL = 60;

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const mapCanvas = $<HTMLCanvasElement>("map");
const rdCanvas = $<HTMLCanvasElement>("rd");

// ---------- state ----------
let runId = "";
let tracks: Track[] = [];
const trails = new Map<number, Array<[number, number]>>();

function resetRun(id: string): void {
  runId = id;
  trails.clear();
  $("run").textContent = `run ${id}`;
}

// ---------- top-down map ----------
function fitCanvas(c: HTMLCanvasElement): CanvasRenderingContext2D {
  const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth;
  const h = c.clientHeight;
  if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
  }
  const ctx = c.getContext("2d")!;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

function drawMap(): void {
  const ctx = fitCanvas(mapCanvas);
  const w = mapCanvas.clientWidth;
  const h = mapCanvas.clientHeight;
  ctx.clearRect(0, 0, w, h);
  const scale = Math.min((h - 24) / MAP_RANGE_M, w / 2 / MAP_RANGE_M);
  if (!(scale > 0)) return; // not laid out yet
  const ox = w / 2;
  const oy = h - 16; // room for the ring labels below the baseline
  const px = (x: number, y: number): [number, number] => [ox + x * scale, oy - y * scale];

  // field of view and range rings
  ctx.strokeStyle = "#1e2b3a";
  ctx.fillStyle = "#7d90a5"; // readable on the dark map (contrast above 4.5:1)
  ctx.font = "11px system-ui";
  ctx.lineWidth = 1;
  // Ring labels sit on the right-hand baseline, where targets rarely are, not on the
  // centre line where people walk; every 20 m when rings are too close for every 10 m.
  const labelStep = 10 * scale < 34 ? 20 : 10;
  let lastRight = -Infinity; // skip a label that would run into the one before it
  ctx.textAlign = "center";
  for (let r = 10; r <= MAP_RANGE_M; r += 10) {
    ctx.beginPath();
    ctx.arc(ox, oy, r * scale, Math.PI, 2 * Math.PI);
    ctx.stroke();
    if (r % labelStep === 0) {
      const text = `${r} m`;
      const half = ctx.measureText(text).width / 2;
      const x = Math.min(ox + r * scale, w - half - 2); // keep it on screen
      if (x - half > lastRight + 4) {
        ctx.fillText(text, x, oy + 13);
        lastRight = x + half;
      }
    }
  }
  ctx.textAlign = "start";
  for (const deg of [-60, -30, 0, 30, 60]) {
    const a = (deg * Math.PI) / 180;
    const [x, y] = px(MAP_RANGE_M * Math.sin(a), MAP_RANGE_M * Math.cos(a));
    ctx.beginPath();
    ctx.moveTo(ox, oy);
    ctx.lineTo(x, y);
    ctx.stroke();
  }
  ctx.fillStyle = "#38bdf8";
  ctx.beginPath();
  ctx.arc(ox, oy, 5, 0, 2 * Math.PI);
  ctx.fill();

  // trails, then tracks; a label that would overlap one already drawn moves down a line
  const placed: Array<[number, number, number]> = []; // x, y, width of each label
  for (const t of tracks) {
    const color = COLORS[t.label] ?? COLORS.unknown;
    const trail = trails.get(t.track_id) ?? [];
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.35;
    ctx.beginPath();
    trail.forEach(([x, y], i) => {
      const [a, b] = px(x, y);
      if (i === 0) ctx.moveTo(a, b);
      else ctx.lineTo(a, b);
    });
    ctx.stroke();
    ctx.globalAlpha = 1;
    const [a, b] = px(t.x_m, t.y_m);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(a, b, t.label === "car" ? 7 : 5.5, 0, 2 * Math.PI);
    ctx.fill();
    ctx.fillStyle = "#dbe6f0";
    const text = `${t.track_id} ${LABEL_TEXT[t.label] ?? ""}`;
    const tw = ctx.measureText(text).width;
    let ly = b + 4;
    while (placed.some(([x, y, pw]) => Math.abs(y - ly) < 13 && a + 9 < x + pw && x < a + 9 + tw)) {
      ly += 13;
    }
    placed.push([a + 9, ly, tw]);
    ctx.fillText(text, a + 9, ly);
  }
}

// ---------- range-Doppler heatmap ----------
const LUT = buildLut();

function buildLut(): Uint8ClampedArray {
  // dark blue -> teal -> yellow -> white, readable on a dark page
  const stops: Array<[number, [number, number, number]]> = [
    [0, [7, 11, 16]],
    [0.35, [14, 60, 110]],
    [0.6, [20, 150, 160]],
    [0.85, [250, 210, 70]],
    [1, [255, 255, 255]],
  ];
  const lut = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    const v = i / 255;
    let k = 0;
    while (k < stops.length - 2 && v > stops[k + 1][0]) k++;
    const [v0, c0] = stops[k];
    const [v1, c1] = stops[k + 1];
    const f = (v - v0) / (v1 - v0);
    for (let j = 0; j < 3; j++) lut[i * 3 + j] = c0[j] + (c1[j] - c0[j]) * f;
  }
  return lut;
}

type RdMessage = Extract<LiveMessage, { type: "rdmaps" }>;

async function rdBytes(msg: RdMessage): Promise<Uint8Array> {
  const raw = Uint8Array.from(atob(msg.data), (c) => c.charCodeAt(0));
  if (msg.encoding !== "zlib") return raw;
  // zlib is what the browser calls "deflate"
  const stream = new Blob([raw]).stream().pipeThrough(new DecompressionStream("deflate"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

// Only the newest picture matters: while one is being unpacked, newer ones replace the
// waiting one instead of queueing up.
let rdBusy = false;
let rdNext: RdMessage | null = null;

async function showRd(msg: RdMessage): Promise<void> {
  if (rdBusy) {
    rdNext = msg;
    return;
  }
  rdBusy = true;
  try {
    drawRd(msg, await rdBytes(msg));
  } catch {
    /* a damaged picture is skipped; the next one comes in 0.1 s */
  } finally {
    rdBusy = false;
    const next = rdNext;
    rdNext = null;
    if (next) void showRd(next);
  }
}

function drawRd(msg: RdMessage, bytes: Uint8Array): void {
  const [nDop, nRng] = msg.shape;
  const cols = Math.min(nRng, RD_MAX_RANGE_BINS);
  const img = new ImageData(cols, nDop);
  for (let d = 0; d < nDop; d++) {
    const row = nDop - 1 - d; // positive speed at the top
    for (let r = 0; r < cols; r++) {
      const v = bytes[d * nRng + r];
      const o = (row * cols + r) * 4;
      img.data[o] = LUT[v * 3];
      img.data[o + 1] = LUT[v * 3 + 1];
      img.data[o + 2] = LUT[v * 3 + 2];
      img.data[o + 3] = 255;
    }
  }
  const off = new OffscreenCanvas(cols, nDop);
  off.getContext("2d")!.putImageData(img, 0, 0);
  const ctx = fitCanvas(rdCanvas);
  const w = rdCanvas.clientWidth;
  const h = rdCanvas.clientHeight;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(off, 0, 0, w, h);

  ctx.fillStyle = "rgba(219,230,240,0.8)";
  ctx.font = "11px system-ui";
  for (let m = 20; m < cols * msg.range_bin_m; m += 20) {
    ctx.fillText(`${m}`, (m / msg.range_bin_m / cols) * w + 2, h - 4);
  }
  const vmax = (nDop / 2) * msg.velocity_bin_mps;
  ctx.fillText(`+${vmax.toFixed(0)} m/s`, 4, 12);
  ctx.fillText(`-${vmax.toFixed(0)} m/s`, 4, h - 16);
}

// ---------- track table ----------
function renderTable(): void {
  const body = $("track-rows");
  body.replaceChildren(
    ...[...tracks]
      .sort((a, b) => a.range_m - b.range_m)
      .map((t) => {
        const tr = document.createElement("tr");
        const cells: Array<[string, boolean]> = [
          [String(t.track_id), false],
          [LABEL_TEXT[t.label] ?? t.label, false],
          [`${t.range_m.toFixed(1)} m`, true],
          [`${Math.round(t.azimuth_deg) || 0}°`, true], // || 0: no "-0°"
          [`${t.speed_mps.toFixed(1)} m/s`, true],
        ];
        for (const [text, num] of cells) {
          const td = document.createElement("td");
          td.textContent = text;
          if (num) td.className = "num";
          tr.append(td);
        }
        tr.firstElementChild!.setAttribute("style", `color:${COLORS[t.label] ?? COLORS.unknown}`);
        return tr;
      }),
  );
  if (tracks.length === 0) {
    // say why the table is empty instead of leaving it blank
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.className = "muted";
    td.textContent = "Nothing tracked right now. A track is confirmed after a few frames; " +
      "at the start of a run the radar first learns the empty scene (about 2 s).";
    tr.append(td);
    body.append(tr);
  }
  $("track-count").textContent = `${tracks.length} confirmed`;
}

// ---------- live connection ----------
function connect(): void {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
  const conn = $("conn");
  ws.onopen = () => {
    conn.textContent = "live";
    conn.className = "pill on";
  };
  ws.onclose = () => {
    conn.textContent = "offline";
    conn.className = "pill off";
    setTimeout(connect, 2000);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data) as LiveMessage;
    if (msg.run_id !== runId) resetRun(msg.run_id);
    $("clock").textContent = new Date(msg.timestamp_ns / 1e6).toISOString().slice(11, 21) + " UTC";
    if (msg.type === "tracks") {
      tracks = msg.tracks.filter((t) => t.confirmed);
      for (const t of tracks) {
        const trail = trails.get(t.track_id) ?? [];
        trail.push([t.x_m, t.y_m]);
        if (trail.length > TRAIL) trail.shift();
        trails.set(t.track_id, trail);
      }
      // forget trails of tracks that have ended, so a long live run does not grow forever
      const live = new Set(tracks.map((t) => t.track_id));
      for (const id of trails.keys()) if (!live.has(id)) trails.delete(id);
      drawMap();
      renderTable();
    } else if (msg.type === "rdmaps") {
      void showRd(msg);
    }
  };
}

// ---------- chat ----------
const log = $("chat-log");
const MAX_MESSAGES = 200;

function bubble(kind: string, text: string): HTMLDivElement {
  const div = document.createElement("div");
  div.className = `msg ${kind}`;
  div.textContent = text; // plain text only: answers may echo untrusted data
  log.append(div);
  while (log.childElementCount > MAX_MESSAGES) log.firstElementChild?.remove();
  log.scrollTop = log.scrollHeight;
  return div;
}

interface Turn {
  thread_id: string;
  status: "answered" | "needs_approval";
  answer?: string;
  tool_calls?: Array<{ name: string; args: unknown }>;
}

async function post(path: string, body: unknown): Promise<Turn> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const d = ((await res.json()) as { detail?: unknown }).detail;
      if (typeof d === "string") detail = d;
      else if (d !== undefined) detail = JSON.stringify(d); // validation errors are a list
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return (await res.json()) as Turn;
}

async function waitFor(work: Promise<Turn>): Promise<void> {
  const wait = bubble("agent wait", "Thinking…");
  const started = Date.now();
  const timer = setInterval(() => {
    wait.textContent = `Thinking… ${Math.round((Date.now() - started) / 1000)} s`;
  }, 1000);
  try {
    show(await work);
  } catch (e) {
    bubble("agent", (e as Error).message);
  } finally {
    clearInterval(timer);
    wait.remove();
  }
}

function show(turn: Turn): void {
  if (turn.status === "answered") {
    bubble("agent", turn.answer ?? "");
    return;
  }
  const box = bubble("agent approval", "The agent wants to change radar settings. Allow it?");
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(turn.tool_calls, null, 2);
  const yes = document.createElement("button");
  yes.textContent = "Approve";
  const no = document.createElement("button");
  no.textContent = "Deny";
  no.className = "secondary";
  const decide = (approve: boolean) => {
    yes.disabled = no.disabled = true;
    void waitFor(post(`/api/ask/${turn.thread_id}/decision`, { approve }));
  };
  yes.onclick = () => decide(true);
  no.onclick = () => decide(false);
  box.append(pre, yes, " ", no);
  yes.focus(); // keyboard users land on the choice
}

$<HTMLFormElement>("chat-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const input = $<HTMLInputElement>("chat-input");
  const question = input.value.trim() || input.placeholder;
  input.value = "";
  bubble("user", question);
  void waitFor(post("/api/ask", { question }));
});

window.addEventListener("resize", drawMap);
connect();
requestAnimationFrame(drawMap);
