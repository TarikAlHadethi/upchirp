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

Measured on 5 October 2026 with the same question and scenes (`agent-bench-claude-opus-5-5.md`):

| | Local (Qwen2.5 7B, this PC) | Hosted (Claude Opus 5.5, demo server) |
| --- | --- | --- |
| Correct | 10 of 10 | 10 of 10 |
| Latency p50 | 15.5 s | 9.3 s |
| Latency p95 | 16.2 s | 16.7 s |
| Tokens in / out per answer | 1897 / 68 | 3060 / 393 |
| Cost per answer | $0 | $0.0201 |

Both answer correctly. The hosted model is faster on a typical answer and costs about 2 cents; the local one needs no network and costs nothing per answer.

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
