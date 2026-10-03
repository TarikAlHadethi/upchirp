# 0003: Every frame source is an adapter

- Date: 2026-10-03
- Owner: Tarik and Abdullah
- Status: accepted

## Context

Tarik's work starts months before Abdullah's hardware exists, and the hardware will change (coffee-can, FPGA, rev A, rev B).

## Decision

The simulator, replay, the sound card capture and the FPGA board each publish the same Frame message to the `frames` topic. The pipeline reads only that topic.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Pipeline reads hardware directly | Blocks software on hardware and breaks the replay demo |
| Separate pipelines per source | Duplicated code; evals would not compare like with like |

## Consequences

Swapping sources is a config change, and every eval can rerun on real data unchanged. The Frame message is a contract: changes need a new decision record.
