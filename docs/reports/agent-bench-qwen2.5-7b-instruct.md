# Agent benchmark: qwen2.5:7b-instruct

- Date: 2026-10-03 20:38 UTC
- Machine: Windows AMD64, 20 CPU threads
- Question: "How many drone-like tracks crossed in the last 10 minutes, and how close did the closest one get?" on the default and crossing scenes
- Answers: 10 (5 per scene)

| Measure | Value |
| --- | --- |
| Correct against ground truth | 10 of 10 |
| Latency p50 | 15.5 s |
| Latency p95 | 16.2 s |
| Mean input tokens per answer | 1897 |
| Mean output tokens per answer | 68 |
| Cost per answer | $0 (local CPU) |

## Hosted comparison

Not measured yet: it needs a hosted model (`UPCHIRP_MODEL=anthropic upchirp bench` with an API key, or Bedrock once the account's quota allows it). As a rough estimate only: if Claude Opus 5.5 used the same token counts, one answer would cost about (1897 x $4 + 68 x $20) / 1,000,000 = $0.0089, so about 111 answers per dollar. Real token counts differ between models, so measure before relying on this.

Raw samples:

```json
[
 {
  "scene": "default",
  "seconds": 16.38645730004646,
  "input_tokens": 1894,
  "output_tokens": 69,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 15.435648699989542,
  "input_tokens": 1900,
  "output_tokens": 68,
  "correct": true
 },
 {
  "scene": "default",
  "seconds": 15.639835399924777,
  "input_tokens": 1894,
  "output_tokens": 69,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 15.496029800036922,
  "input_tokens": 1900,
  "output_tokens": 68,
  "correct": true
 },
 {
  "scene": "default",
  "seconds": 16.01039009995293,
  "input_tokens": 1894,
  "output_tokens": 69,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 15.468177199945785,
  "input_tokens": 1900,
  "output_tokens": 68,
  "correct": true
 },
 {
  "scene": "default",
  "seconds": 15.588488699984737,
  "input_tokens": 1894,
  "output_tokens": 69,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 15.407465499942191,
  "input_tokens": 1900,
  "output_tokens": 68,
  "correct": true
 },
 {
  "scene": "default",
  "seconds": 15.578215999994427,
  "input_tokens": 1894,
  "output_tokens": 69,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 15.480699499952607,
  "input_tokens": 1900,
  "output_tokens": 68,
  "correct": true
 }
]
```
