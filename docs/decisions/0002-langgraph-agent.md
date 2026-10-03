# 0002: LangGraph agent over MCP

- Date: 2026-10-03
- Owner: Tarik
- Status: accepted

## Context

The agent must call radar tools, and changing hardware settings must wait for a human yes.

## Decision

Radar tools live in an MCP server. A LangGraph agent calls them through langchain-mcp-adapters. The chirp config tool is marked destructive and pauses on LangGraph's interrupt until a human approves.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Hand-written tool loop | Works, but rebuilds approval and state handling that LangGraph provides |
| Tools only inside the agent, no MCP | Locks tools to one agent; MCP lets any client use them |

## Consequences

Widely used for tool-calling agents. Adds a framework dependency; keep tool logic in the MCP server so the agent layer stays thin and replaceable.
