# Agent benchmark: qwen2.5:7b-instruct

- Date: 2026-10-03 08:10 UTC
- Machine: Windows AMD64, 20 CPU threads
- Question: "How many drone-like tracks crossed in the last 10 minutes, and how close did the closest one get?" on the default and crossing scenes
- Answers: 10 (5 per scene)

| Measure | Value |
| --- | --- |
| Correct against ground truth | 10 of 10 |
| Latency p50 | 15.9 s |
| Latency p95 | 16.8 s |
| Mean input tokens per answer | 1764 |
| Mean output tokens per answer | 68 |
| Cost per answer | $0 (local CPU) |

## Hosted comparison

Not measured yet: it needs an Anthropic API key (`UPCHIRP_MODEL=anthropic upchirp bench`). As a rough estimate only: if Claude Opus 5.5 used the same token counts, one answer would cost about (1764 x $4 + 68 x $20) / 1,000,000 = $0.0084, so about 120 answers per dollar. Real token counts differ between models, so measure before relying on this.

Raw samples:

```json
[
 {
  "scene": "default",
  "seconds": 16.978867499972694,
  "input_tokens": 1763,
  "output_tokens": 69,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 15.880473400000483,
  "input_tokens": 1766,
  "output_tokens": 68,
  "correct": true
 },
 {
  "scene": "default",
  "seconds": 15.997106999973767,
  "input_tokens": 1763,
  "output_tokens": 69,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 15.971534200012684,
  "input_tokens": 1766,
  "output_tokens": 68,
  "correct": true
 },
 {
  "scene": "default",
  "seconds": 16.478634000057355,
  "input_tokens": 1763,
  "output_tokens": 69,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 15.73540000000503,
  "input_tokens": 1766,
  "output_tokens": 68,
  "correct": true
 },
 {
  "scene": "default",
  "seconds": 15.924428900005296,
  "input_tokens": 1763,
  "output_tokens": 69,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 15.822446299949661,
  "input_tokens": 1766,
  "output_tokens": 68,
  "correct": true
 },
 {
  "scene": "default",
  "seconds": 15.689672700013034,
  "input_tokens": 1763,
  "output_tokens": 69,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 15.913478700094856,
  "input_tokens": 1766,
  "output_tokens": 68,
  "correct": true
 }
]
```
