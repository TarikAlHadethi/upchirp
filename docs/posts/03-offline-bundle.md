# Draft post 3 (after step 7): installing an AI platform with the network cable unplugged

*Draft. Fill in the hosted vs local numbers once an API key is set up.*

The radar platform I am building has to work with no internet: no cloud, no package downloads, no model API.

So everything ships as one folder: Kubernetes (k3s), every container image, the local AI models, monitoring, and a checksum for every file. `sudo ./install.sh` checks the checksums, then installs. About 20 minutes.

I tested it on a fresh Ubuntu machine with no route to the internet. The first attempt failed in a way I would never have found with the network on: k3s refuses to start when a machine has no default route, which is exactly the state of a box with its cable unplugged. The installer now adds a placeholder route. Second attempt: every service up, and the agent answered the drone question correctly from the local model.

Hosted vs local, same eval:

| | Local (Qwen2.5 7B, CPU) | Hosted (Claude) |
| --- | --- | --- |
| Correct | 10 of 10 | (to measure) |
| Latency p95 | 16.8 s | (to measure) |
| Cost per answer | $0 | (to measure) |

Lesson: test the offline path offline. "It works on my machine" usually means "it works with my machine's internet".

Install guide: (link)
