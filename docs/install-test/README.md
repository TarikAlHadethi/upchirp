# Install test kit (step 8)

Three people install Upchirp from `docs/install.md` with the network off, while you watch and say nothing. You note where each one gets stuck, fix the guide or the installer, and time it before and after. Step 8 is done when the write-up is posted.

## Who

1. A CS classmate (comfortable with a terminal).
2. Someone non-technical (has never opened a terminal).
3. A lecturer (technical, but has never seen the project).

## What you need

- A spare x86_64 computer with Ubuntu 24.04 freshly installed, 16 GB of memory, 60 GB free. Wipe it, or reinstall Ubuntu, between testers, so each one starts fresh. A USB stick with Ubuntu makes the reinstall quick.
- The bundle on a USB drive: `deploy/bundle/build.sh` makes it (about 6 GB, needs the internet once).
- A printed copy of `docs/install.md`, or the file open on another screen. Nothing else.
- One printed copy of `tester-sheet.md` per person, for you to fill in.
- A timer.

## How to run one session (about 45 minutes)

1. Unplug the network cable and turn off Wi-Fi before they sit down.
2. Say only this: "Install this program using the guide. Think out loud. I can't help, but you can stop whenever you want."
3. Start the timer when they first touch the computer.
4. Do not help, point or nod. If they are stuck for 5 minutes, write down exactly where, then give the smallest hint you can and note that you did.
5. Stop the timer when the live view shows **live** and dots move on the map.
6. Ask them the drone question in the chat, then the three questions at the end of the sheet.

## After each session

- Fix the guide (or the installer) for every place someone got stuck, before the next person.
- Commit each fix on its own, with the tester number in the message, so the write-up can link to it.

## After all three

- Run one more time yourself, timed, from a fresh machine, with the fixed guide.
- Fill in `writeup-template.md` and post it (it becomes `docs/posts/05-install-test.md`).
- Mark step 8 done in `docs/progress.md`.
