"""Patches from our own simulator, labelled by ground truth, to measure simulated accuracy.

Runs the real pipeline (clutter map, CFAR), takes each detection that matches an
in-view target, and cuts the same kind of patch the classifier sees on real data.
"""

import numpy as np
import numpy.typing as npt

from upchirp.classify.patches import CLASSES, cut_patch, our_doppler_cells
from upchirp.pipeline import Pipeline
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import get_scene


def simulated_patches(scenes: tuple[str, ...] = ("default", "crossing"),
                      seeds: tuple[int, ...] = (0, 1, 2)
                      ) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.int64]]:
    xs: list[npt.NDArray[np.float32]] = []
    ys: list[int] = []
    for scene in scenes:
        for seed in seeds:
            base = get_scene(scene)
            # targets with their real size, as the classifier sees them on real data
            sized = tuple(t.model_copy(update={"extended": True}) for t in base.targets)
            sim = Simulator(base.model_copy(update={"targets": sized}), session_id="patches",
                            start_ns=0, seed=seed)
            pipe = Pipeline(sim.chirp, sim.array)
            n_d = our_doppler_cells(sim.chirp)
            for frame, truth in sim.run():
                result = pipe.process(frame)
                power = pipe.detector.last_power
                if power is None:
                    continue
                for t in truth:
                    if not t.in_view:
                        continue
                    near = [d for d in result.detections
                            if abs(d.range_m - t.range_m) <= 1.5
                            and abs(d.radial_velocity_mps - t.radial_velocity_mps) <= 0.8]
                    if near:
                        d = max(near, key=lambda d: d.snr_db)
                        xs.append(cut_patch(power, d.doppler_bin, d.range_bin, n_d))
                        ys.append(CLASSES.index(t.label))
    return np.stack(xs), np.array(ys, dtype=np.int64)
