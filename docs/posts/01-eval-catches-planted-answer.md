# Draft post 1 (after step 3): my eval caught a wrong answer I planted

*Draft for LinkedIn or a blog. Edit freely; numbers are from the repo on 3 October 2026.*

I am building an AI agent that answers questions about what a radar saw: "How many drone-like tracks crossed in the last 10 minutes, and which came closest?"

The easy part was getting an answer. The hard part is knowing when the answer is wrong.

So every answer is checked against ground truth. The radar data comes from a simulator, so I know exactly where every person, car and drone-like target was. The check pulls the count and the closest range out of the agent's sentence and compares them with the truth.

Then I tried to break it. I planted a fault in the agent's tools: every "closest range" came back 25 m too far. The agent repeated the wrong number with full confidence ("closest at 55.11 metres"). The eval failed, as it should. The real answer was 30.2 m.

Three things I learned:

1. Check answers against something the agent cannot touch. My expected answers come from the simulator's ground truth and from plain SQL, never from the agent's own tools.
2. Prove the check can fail. An eval that has never caught a planted fault is a guess.
3. Small models fill in blanks badly. My local 7B model sent an empty string as the session id; the tools now treat that as "latest". The audit log showed it in one line.

The agent runs offline on a 7B model on a CPU: 10 of 10 correct on the benchmark, about 16 seconds an answer, no network.

Repo: (link)
