"""Radar configuration: chirp settings and receive array geometry.

Field names follow the chirp config draft in docs/architecture.md.
chirp_duration_s is the sweep time (it sets the slope). Chirps repeat every
chirp_interval_s, which defaults to the sweep time (back to back, no idle time);
a radar that sweeps up and down, like the coffee-can, repeats every two sweeps.
max_range_bin limits detection to the bins that can hold echoes: with a real
(one-sided) beat signal only the lower half does.
"""

from pydantic import BaseModel, ConfigDict

SPEED_OF_LIGHT_MPS = 299_792_458.0


class ChirpConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = "default-v0"
    f_start_hz: float = 5.725e9
    bandwidth_hz: float = 150e6
    chirp_duration_s: float = 1e-3
    n_chirps: int = 64
    n_samples: int = 256
    sample_rate_hz: float = 256e3
    chirp_interval_s: float | None = None
    max_range_bin: int | None = None

    @property
    def repeat_s(self) -> float:
        return self.chirp_interval_s or self.chirp_duration_s

    @property
    def slope_hz_per_s(self) -> float:
        return self.bandwidth_hz / self.chirp_duration_s

    @property
    def wavelength_m(self) -> float:
        return SPEED_OF_LIGHT_MPS / self.f_start_hz

    @property
    def range_bin_m(self) -> float:
        """Range covered by one range FFT bin (complex sampling)."""
        return SPEED_OF_LIGHT_MPS * self.sample_rate_hz / (2 * self.slope_hz_per_s * self.n_samples)

    @property
    def max_range_m(self) -> float:
        return self.range_bin_m * self.n_samples

    @property
    def velocity_bin_mps(self) -> float:
        """Radial velocity covered by one Doppler FFT bin."""
        return self.wavelength_m / (2 * self.n_chirps * self.repeat_s)

    @property
    def max_velocity_mps(self) -> float:
        """Largest radial speed before Doppler wraps around."""
        return self.wavelength_m / (4 * self.repeat_s)

    @property
    def frame_duration_s(self) -> float:
        return self.n_chirps * self.repeat_s


class ArrayConfig(BaseModel):
    """Uniform linear receive array along the x axis, facing +y."""

    model_config = ConfigDict(frozen=True)

    n_rx: int = 2
    spacing_wavelengths: float = 0.5
