# 0007: One PostgreSQL for time series, audit and document search

- Date: 2026-10-03
- Owner: Tarik
- Status: accepted

## Context

The platform stores detections and tracks (time series), the agent's audit log, and embeddings for document search, on one small edge box.

## Decision

One PostgreSQL 16 with TimescaleDB (hypertables for detections and tracks) and pgvector (doc_chunks, 768-dimension embeddings from nomic-embed-text through Ollama). In development it runs from `timescale/timescaledb-ha:pg16` in compose, on port 5433 so it does not clash with other local databases.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Separate vector database (Qdrant, Chroma) | Another service to run and back up offline |
| DuckDB or Parquet only | Already cut; no concurrent writer plus readers |
| Plain Postgres without Timescale | Works now, but retention and downsampling get harder as recordings grow |

## Consequences

One backup, one connection string, SQL for checking agent answers in step 5. The HA image is large (4.4 GB measured; Ollama is 9.4 GB and Redpanda 0.6 GB), which matters for the offline bundle in step 7: look for slimmer images there.
