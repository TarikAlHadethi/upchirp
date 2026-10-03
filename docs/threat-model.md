# Threat model

One page. What can go wrong with Upchirp, what stops it, and which test proves it. Updated at step 5; revisit at step 6 (public demo) and step 10 (real hardware).

## What we protect

| Asset | Why it matters |
| --- | --- |
| Radar settings (chirp config) | A bad change can leave the ISM band or blind the radar |
| Answers about what the radar saw | People act on them; a wrong count is worse than no answer |
| Recordings, tracks, audit log | Evidence of what happened and of what the agent did |
| Cloud account and budget (step 6) | Real money |

## Who or what we defend against

- **Planted text.** Anyone who can write into something the agent reads: operator notes on a recording, frame `meta`, a document in `docs/`. This is the main threat, because the agent reads it with its tools.
- **Public demo visitors (step 6).** Anyone with the link can ask anything, as often as they like.
- **A wrong or tampered tool.** A bug or a compromised component returns bad data.
- **The model itself.** Small local models guess, copy numbers from the wrong place, or follow instructions they should ignore.

Out of scope for now: someone with shell access to the edge box, and radio attacks on the radar (jamming, spoofing echoes).

## Threats and controls

| Threat | Controls | Tested by |
| --- | --- | --- |
| Planted text makes the agent change radar settings | 1. Settings changes need a human yes (LangGraph interrupt). 2. The change is blocked outright unless the user's own question asked for one. 3. The tool does not exist in public mode. 4. Limits keep any config inside 5.725 to 5.875 GHz | `tests/test_agent_safety.py` (approve, deny, blocked, public mode, out of band); `evals/test_injection.py` |
| Planted text makes the agent report false numbers | 1. Notes, scene names and doc passages come back marked untrusted, with a notice. 2. System prompt: track numbers only from track tools. 3. Grounding guard in code: an answer about tracks without a track tool call is sent back once | `evals/test_injection.py` (notes and docs); `tests/test_agent_safety.py::test_grounding_guard` |
| Agent calls a tool it should not have | Allowlist applied when the agent starts, whatever the MCP server offers | `tests/test_agent_safety.py::test_tools_off_the_allowlist_never_run` |
| Wrong data from a tool goes unnoticed | Answers checked against ground truth and against SQL; planted wrong tool output must fail the check | `evals/test_agent.py`, `evals/test_agent_sql.py` |
| Pipeline regression gives wrong tracks | Detection, tracking and label gates on two scenes; planted angle fault must fail | `evals/test_detection_tracking.py` |
| Agent output injects code into the web page | Answers are inserted as text, never HTML | Code review of `ui/src/main.ts` (no `innerHTML`) |
| No record of what the agent did | Every question, tool call, approval, block and answer goes to the audit log | `evals/test_agent.py::test_audit_log_records_question_tools_and_answer` |
| Secrets leak from the repo | `.env` git-ignored; AWS by role (step 6); no keys on the demo server | `.gitignore`; review at step 6 |
| Services reachable from the network | Compose binds every port to 127.0.0.1; dev database password is for local use only | `compose.yaml` |
| Public demo abuse and cost (step 6) | 1. Read-only tools: the server registers only read tools in public mode, and the agent keeps only read tools whatever the server offers. 2. Rate limit per address. 3. Daily spend cap: each question holds an estimate of its cost until its real cost is known, so a burst cannot slip past; a failed answer is still charged; an unknown paid model is charged at the highest known price. 4. AWS budget alarm | `tests/test_platform.py` (limits, budget held by questions in flight, unknown model never free); `tests/test_agent_safety.py::test_public_agent_never_sees_control_tools` |
| Secrets leak into logs | Alert errors are logged as an HTTP status, never the URL (Telegram's holds the bot token); httpx request logging is turned down | `tests/test_alerts.py::test_bot_token_never_reaches_the_log` |
| Paths or server details leak through errors | Session ids must be plain names; errors never include server paths | `tests/test_agent_safety.py::test_session_ids_are_plain_names` |

## Known gaps

- **The model still takes the bait sometimes.** With planted operator notes, the local model (Qwen2.5 7B) tried the planted settings change in 4 of 8 runs measured on 3 October 2026 (and 0 of 3 before the untrusted marking was added, so the samples are too small to say the marking made it worse). The code guard blocked every attempt, so nothing ran, and every answer was still correct. With planted documents it copied the fake numbers in 3 of 3 runs until the grounding guard was added, then 0 of 5. A stronger model should be compared on the same evals (step 7).
- **The intent check is keyword based.** A user question that mentions "settings" for another reason still allows the request through to the human approval step, which remains the final control.
- **The grounding guard fires once per question.** If the model ignores the nudge, a wrong answer can still come out; the evals measure how often.
- **Frame `meta` is not yet shown to the agent.** When it is, it needs the same untrusted marking and an eval like the notes one.
- **A drone hiding near clutter is missed.** A small target at nearly the same range and speed as a tree with moving leaves cannot be separated with two receive channels (decision 0010). Someone who knows this could hide a drone near trees.
- **RCS-based labels can be fooled** by anything with the wrong radar cross section. They are a stand-in until step 9 and are always called "drone-like".
