# 60-second video: script and shot list

For the step 3 video. Record the screen with the voice over it. Windows: press Win + Alt + R in a browser window to start and stop recording (Xbox Game Bar), or use OBS. About 140 words, read calmly.

**Before recording:** open the live demo in a browser at full screen. Wait until a drone-like target (a red dot) is on the map. One crosses about 90 seconds into the 15-minute loop, and another hovers from about 5 minutes. Have the GitHub repo open in a second tab.

| Time | On screen | Say |
| --- | --- | --- |
| 0 to 8 s | The live view, dots moving | "This is Upchirp: a radar that tracks people, cars and drone-like targets, and an AI agent you can ask about what it saw." |
| 8 to 20 s | Point at the map, then the range and speed picture | "Every dot is a tracked object. The radar measures range, speed and angle; a Kalman tracker follows each one, and simple rules label it." |
| 20 to 38 s | Click the chat, ask: "How many drone-like tracks crossed in the last 10 minutes, and which came closest?" Wait for the answer | "The agent only sees the data through a few read-only tools. It can't change the radar, and every answer comes from what was recorded." |
| 38 to 50 s | Switch to the GitHub tab: scroll to the results table and the evals list | "Every answer is checked against ground truth in CI, including planted faults and hidden prompt injections. If the agent gets worse, the build fails." |
| 50 to 60 s | Scroll to "Offline install" | "The whole system installs from one USB drive on a machine with no internet. The radar hardware is next. Link in the description." |

**Tips:**
- Do it in one take; if a line goes wrong, pause, then say it again, and cut the gap later.
- Keep the mouse still while talking, and move it only to point.
- Export at 1080p. Upload to YouTube as unlisted or to LinkedIn directly, then put the link at the top of the README.
