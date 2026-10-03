# 0005: Ollama with Qwen2.5 7B as the default agent model

- Date: 2026-10-03
- Owner: Tarik
- Status: accepted

## Context

The agent must work with the network cable unplugged, and there is no API key yet. The dev machine and the planned edge box have no GPU (20 CPU cores, 32 GB RAM).

## Decision

Run models through Ollama, in Docker during development (`upchirp-ollama`, bound to localhost only). Default model `qwen2.5:7b-instruct` (Q4, 4.7 GB), chosen for reliable tool calling at a size a CPU can run. Claude (`claude-opus-5-5`) is one setting away with `UPCHIRP_MODEL=anthropic`.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Hosted model only | Breaks the offline requirement; no key yet |
| vLLM | Needs a GPU (already cut in the plan) |
| Larger local model (14B+) | Too slow on CPU for a demo; evals can revisit |
| Llama 3.1 8B or other 7B to 8B models | Not tested yet; any Ollama model can be swapped in with UPCHIRP_OLLAMA_MODEL and compared on the evals |

## Consequences

An answer takes about 15 to 40 seconds on CPU. Small models fill optional tool arguments with empty strings, so the MCP tools treat "" as "not given". Step 7 compares hosted and local models on the same evals; that comparison decides the bundle's model.
