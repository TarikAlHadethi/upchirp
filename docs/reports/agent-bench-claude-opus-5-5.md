# Agent benchmark: claude-opus-5-5

- Date: 2026-10-05 16:33 UTC
- Machine: Linux aarch64, 2 CPU threads
- Question: "How many drone-like tracks crossed in the last 10 minutes, and how close did the closest one get?" on the default and crossing scenes
- Answers: 10 (5 per scene)
- Where: the public demo server (t4g.small, 2 ARM cores), Anthropic API (decision 0015)

| Measure | Value |
| --- | --- |
| Correct against ground truth | 10 of 10 |
| Latency p50 | 9.3 s |
| Latency p95 | 16.7 s |
| Mean input tokens per answer | 3060 |
| Mean output tokens per answer | 393 |
| Cost per answer | $0.0201 |

Raw samples:

```json
[
 {
  "scene": "default",
  "seconds": 12.569019405999938,
  "input_tokens": 3057,
  "output_tokens": 445,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 9.176233915000012,
  "input_tokens": 3063,
  "output_tokens": 388,
  "correct": true
 },
 {
  "scene": "default",
  "seconds": 14.556512660999942,
  "input_tokens": 3057,
  "output_tokens": 427,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 8.731406174999961,
  "input_tokens": 3063,
  "output_tokens": 342,
  "correct": true
 },
 {
  "scene": "default",
  "seconds": 8.972907415000009,
  "input_tokens": 3057,
  "output_tokens": 360,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 18.480364664000035,
  "input_tokens": 3063,
  "output_tokens": 405,
  "correct": true
 },
 {
  "scene": "default",
  "seconds": 9.812361592000002,
  "input_tokens": 3057,
  "output_tokens": 388,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 9.326282636999963,
  "input_tokens": 3063,
  "output_tokens": 376,
  "correct": true
 },
 {
  "scene": "default",
  "seconds": 9.201488286999961,
  "input_tokens": 3057,
  "output_tokens": 407,
  "correct": true
 },
 {
  "scene": "crossing",
  "seconds": 8.908320377999985,
  "input_tokens": 3063,
  "output_tokens": 393,
  "correct": true
 }
]
```
