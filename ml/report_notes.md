## What this means

- **Conversion costs nothing measurable.** Converted accuracy is within 0.1 points of native, while accuracy moves 6 to 9 points from one split of recordings to another. Our radar's coarser Doppler cell (0.41 m/s instead of 0.094 m/s) still keeps what the classifier needs, at least on RAD-DAR's targets.
- **On our simulator the classifier gets about 59% (chance is 33%).** It started at 36%, when simulated targets were single points. Adding micro-Doppler (swinging limbs, turning wheels, spinning rotors) and the car's 4.5 m body (decision 0012) brought cars to 86% and people to 75%. Drones stay at about 7%, mostly called people: real drone recordings are farther away and closer to the noise, while simulated drones are clean.
- **So the rule-based labels stay the default** (decisions 0011, 0012). The classifier ships as an option (`UPCHIRP_LABELER=onnx`, model in `models/`) and takes over when real recordings from our radar show it beats the rules.
- Not comparable with the RAD-DAR paper's figures: the paper stacks three consecutive frames; this model sees one frame, and every test recording is unseen.
