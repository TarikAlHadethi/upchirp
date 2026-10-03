# 0008: Plain TypeScript and canvas for the live view, no UI framework

- Date: 2026-10-03
- Owner: Tarik
- Status: accepted

## Context

The plan asks for a thin TypeScript UI: range-Doppler heatmap, angle map, tracks and agent chat, served offline from the edge box.

## Decision

Vite and TypeScript with no framework. Canvas for the map and heatmap, DOM for the table and chat. The built UI (about 6 KB of JavaScript) is served by FastAPI. Agent answers are inserted as text, never HTML, because they can echo untrusted data.

## Alternatives considered

| Option | Why not |
| --- | --- |
| React or Svelte | More to learn and bundle for four panels |
| Grafana as the display | Already cut in the plan |

## Consequences

Small, fast and easy to read. If the UI grows past a few views, revisit a framework.
