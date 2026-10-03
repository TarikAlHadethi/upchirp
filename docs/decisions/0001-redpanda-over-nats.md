# 0001: Redpanda (Kafka API) for streaming

- Date: 2026-10-03
- Owner: Tarik
- Status: accepted

## Context

Frames, detections and tracks move between services on one small edge box, and replay must push recorded sessions through the same path.

## Decision

Redpanda, using the Kafka API, as a single binary with memory and CPU capped.

## Alternatives considered

| Option | Why not |
| --- | --- |
| NATS JetStream | Fits technically, but Redpanda gives the widely used Kafka API |
| Apache Kafka | Heavier to run on one small box; same API as Redpanda |
| Direct HTTP between services | No replay, no buffering, tight coupling |

## Consequences

Any Kafka client works. Replay becomes a topic publish. Memory limits must be set explicitly or Redpanda takes too much on the edge box.
