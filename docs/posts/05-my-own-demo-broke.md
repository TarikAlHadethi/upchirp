# Draft post 5: I asked my own demo its headline question, and it got it wrong

*Draft for LinkedIn or a blog. Numbers are from the repo, 4 to 5 October 2026.*

Upchirp is an offline radar data platform with an AI agent. Its demo asks one question: "How many drone-like tracks crossed in the last 10 minutes, and which came closest?" Every eval passed. Then I ran the real system for 12 minutes and asked it myself.

It said 4. There were 3. And it named the wrong track as the closest.

The evals had missed it because they ran short scenes of about 10 seconds. A long run exposed three things:

1. **A person labelled as a drone for a second.** A person's radar echo fluctuates. My labeller decided after 3 echoes, and 3 weak ones in a row happen about 2.5% of the time. Now a drone-like label needs 10 echoes (1 second; a fluke about once in 10,000), and until then the track says "unknown". Holding back is not the same as being wrong, so the eval now scores those separately.
2. **The model misread a list.** The tool returned every track, and the model had to find the closest itself. A small model got that wrong. Now the tool states the closest track directly. The model only has to copy it.
3. **The count over 15 minutes.** My first long run counted 24 drone-like objects where there were 4: a drone hovering beside a tree broke into 20 short pieces. Joining pieces of something standing still fixed most of it.

Then the public demo went down. Its message broker kept 6 hours of raw radar frames, about 9 GB an hour, on a 30 GB disk. Raw frames now live 10 minutes, the database keeps 3 days, and a check opens the demo every 6 hours and emails me if it fails.

What I took from it:

- Run the real thing, for a long time, and ask it the question users will ask. Short evals had all passed.
- Turn every failure into a test. The long run is now an eval: the drone count must match the truth exactly.
- Make the tool do the arithmetic. Small models copy numbers well and compare them badly.

Repo: https://github.com/TarikAlHadethi/upchirp
Live demo: http://ec2-51-21-241-160.eu-north-1.compute.amazonaws.com
