"""Live simulator source. Ground truth is available from the Simulator itself."""

from collections.abc import Iterator

from upchirp.frame import Frame
from upchirp.sim.engine import Simulator


class SimSource:
    def __init__(self, simulator: Simulator) -> None:
        self.simulator = simulator

    def frames(self) -> Iterator[Frame]:
        for frame, _truth in self.simulator.run():
            yield frame
