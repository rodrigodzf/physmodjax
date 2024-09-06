"""Generator for impulses of different shapes."""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/solver/impulse_generator.ipynb.

# %% auto 0
__all__ = ['Generator', 'Gaussian', 'Gaussian2d', 'NoiseBurst', 'Noise', 'Noise2d', 'SineMode', 'make_pluck_hammer',
           'generate_initial_condition', 'raised_cosine_string', 'raised_cosine_2d', 'create_pluck_modal']

# %% ../../nbs/solver/impulse_generator.ipynb 2
import numpy as np
from typing import Tuple, Optional

# %% ../../nbs/solver/impulse_generator.ipynb 4
class Generator:
    pass

# %% ../../nbs/solver/impulse_generator.ipynb 5
class Gaussian(Generator):
    def __init__(
        self,
        num_points: int = 100,
    ):
        self.x = np.linspace(0, 1, num_points)
        self.dx = self.x[1] - self.x[0]

    def __call__(
        self,
        mean: float = 0.5,  # in percentage w.r.t. the number of points
        std: float = 0.05,  # in percentage w.r.t. the number of points
    ):
        std_corr = np.max([std, self.dx])  # To avoid too narrow gaussians
        return np.exp(-(((self.x - mean) / std_corr) ** 2))

# %% ../../nbs/solver/impulse_generator.ipynb 7
class Gaussian2d(Generator):
    """This class generates a 2D gaussian distribution."""

    def __init__(
        self,
        num_points_x: int = 100,
        aspect_ratio: float = 1.0,  # aspect ratio of the lengths of the two axes, ly/lx
    ):
        self.aspect_ratio = aspect_ratio
        num_points_y = int(np.floor((num_points_x - 1) * aspect_ratio)) + 1
        x = np.linspace(0, 1, num_points_x)
        y = np.linspace(0, aspect_ratio, num_points_y)
        self.dx = x[1] - x[0]
        self.dy = y[1] - y[0]
        self.grid_x, self.grid_y = np.meshgrid(x, y, indexing="ij")

    def __call__(
        self,
        mean: tuple[float, float] = (0.5, 0.5),  # respect to the plate aspect ratio
        std: float = 0.05,  # in percentage w.r.t. the number of points
    ):
        std_corr = np.max([std, self.dx, self.dy])  # To avoid too narrow gaussians
        return np.exp(
            -(
                (self.grid_x - mean[0]) ** 2
                + (self.grid_y - self.aspect_ratio * mean[1]) ** 2
            )
            / (std**2)
        )

# %% ../../nbs/solver/impulse_generator.ipynb 9
class NoiseBurst(Generator):
    def __init__(
        self,
        num_points: int = 100,
    ):
        self.num_points = num_points
        self.x = np.linspace(0, 1, num_points)
        self.gaussian = Gaussian(num_points)
        self.dx = self.x[1] - self.x[0]

    def __call__(
        self,
        rng: np.random.Generator,
        noise_range=[0, 1],
        burst_mean: float = 0.5,
        burst_std: float = 0.1,
    ):
        std_corr = np.max([burst_std, self.dx])  # To avoid too narrow gaussian envelope
        y = rng.uniform(*noise_range, self.num_points) * self.gaussian(
            burst_mean, burst_std
        )
        return y

# %% ../../nbs/solver/impulse_generator.ipynb 11
class Noise(Generator):
    def __init__(
        self,
        num_points: int = 100,
    ):
        self.num_points = num_points
        self.x = np.linspace(0, 1, num_points)
        self.dx = self.x[1] - self.x[0]

    def __call__(
        self,
        rng: np.random.Generator,
        noise_range=[0, 1],
    ):
        y = rng.uniform(*noise_range, self.num_points)
        return y

# %% ../../nbs/solver/impulse_generator.ipynb 12
class Noise2d(Generator):
    def __init__(
        self,
        num_points_x: int = 100,
        aspect_ratio: float = 1.0,  # aspect ratio of the lengths of the two axes, ly/lx
    ):
        self.num_points_x = num_points_x
        num_points_y = int(np.floor((num_points_x - 1) * aspect_ratio)) + 1
        self.num_points_y = num_points_y
        self.dx = 1 / (num_points_x - 1)

    def __call__(
        self,
        rng: np.random.Generator,
        noise_range=[0, 1],
    ):
        z = rng.uniform(*noise_range, (self.num_points_x, self.num_points_y))
        return z

# %% ../../nbs/solver/impulse_generator.ipynb 14
class SineMode(Generator):
    def __init__(
        self,
        num_points: int = 100,
    ):
        self.x = np.linspace(0, 1, num_points)
        self.dx = self.x[1] - self.x[0]

    def __call__(
        self,
        k: int = 1,
    ):
        assert k > 0, "k must be positive"
        return np.sin(np.pi * k * self.x)

# %% ../../nbs/solver/impulse_generator.ipynb 15
# All these only applies for 1D


from typing import Type


def make_pluck_hammer(
    y: np.ndarray,
    ic_type: str = "pluck",  # "pluck" or "hammer"
) -> Tuple[np.ndarray, np.ndarray]:
    if ic_type == "pluck":
        return y, np.zeros_like(y)
    elif ic_type == "hammer":
        return np.zeros_like(y), y
    else:
        raise ValueError(f"ic_type should be either 'pluck' or 'hammer', got {ic_type}")


def generate_initial_condition(
    rng: np.random.Generator = np.random.default_rng(42),
    generator: Generator = Gaussian(),
    ic_type: str = "pluck",  # "pluck" or "hammer"
    ic_max_amplitude: float = 1.0,  # Amplitude of the initial condition, when ic_amplitude_random is True, this is the upper bound
    ic_min_amplitude: float = 0.0,  # only used when ic_amplitude_random is True
    ic_amplitude_random: bool = False,  # If True, the amplitude is chosen randomly between ic_min_amplitude and ic_max_amplitude
    ic_sine_k: int = 1,  # only used when ic_type is "sine"
) -> Tuple[np.ndarray, np.ndarray]:  # a tuple of position and velocity
    # Check that ic_max_amplitude is larger than ic_min_amplitude
    if ic_amplitude_random:
        assert ic_max_amplitude > ic_min_amplitude, (
            f"ic_max_amplitude should be larger than ic_min_amplitude, got "
            f"ic_max_amplitude={ic_max_amplitude} and ic_min_amplitude={ic_min_amplitude}"
        )
    # TODO: Mean and std are hard-coded, could be made more flexible
    mean = rng.uniform(0.3, 0.7)
    min_std = 2 * generator.dx
    std = rng.uniform(min_std, 0.1)
    if isinstance(generator, Gaussian):
        y = generator(mean, std)
    elif isinstance(generator, NoiseBurst):
        y = generator(rng, noise_range=[0, 1], burst_mean=mean, burst_std=std)
    elif isinstance(generator, Noise):
        y = generator(rng, noise_range=[0, 1])
    elif isinstance(generator, SineMode):
        y = generator(k=ic_sine_k)
    elif isinstance(generator, Gaussian2d):
        mean = (rng.uniform(0.3, 0.7), rng.uniform(0.3, 0.7))
        y = generator(mean, std)
    elif isinstance(generator, Noise2d):
        y = generator(rng, noise_range=[0, 1])
    else:
        raise TypeError(
            f"generator should be either Gaussian, Noise, Sine or NoiseBurst, got {type(generator)}"
        )
    # Normalize the amplitude to the desired value
    if ic_amplitude_random:
        amplitude = rng.uniform(ic_min_amplitude, ic_max_amplitude)
    else:
        amplitude = ic_max_amplitude

    y = y * amplitude / np.max(np.abs(y))
    return make_pluck_hammer(y, ic_type)

# %% ../../nbs/solver/impulse_generator.ipynb 19
def raised_cosine_string(
    excitation_type: str = "pluck",
    c0: float = 0.5,  # peak amplitude in newtons
    x_0: float = 0.1,  # center of the excitation in meters
    width: float = 0.1,  # width of the excitation in meters
    length: float = 1.0,  # total length of the string in meters
    grid_points: int = 101,  # number of points along the string
):
    x = np.linspace(0, length, grid_points)
    excitation = np.zeros_like(x)

    for i, xi in enumerate(x):
        if abs(xi - x_0) <= width:
            excitation[i] = c0 * 0.5 * (1 + np.cos(np.pi * (xi - x_0) / width))
        else:
            excitation[i] = 0

    return excitation


def raised_cosine_2d(
    grid_x,  # number of points along the x direction
    grid_y,  # number of points along the y direction
    c0: float = 0.5,  # peak amplitude in newtons
    x_0: float = 0.1,  # center of the excitation in x direction
    y_0: float = 0.1,  # center of the excitation in y direction
    width: float = 0.1,  # width of the excitation in meters
    excitation_type: str = "pluck",
):
    distance = np.sqrt((grid_x - x_0) ** 2 + (grid_y - y_0) ** 2)
    excitation = np.where(
        distance <= width, c0 * 0.5 * (1 + np.cos(np.pi * distance / width)), 0
    )

    return excitation

# %% ../../nbs/solver/impulse_generator.ipynb 24
def create_pluck_modal(
    wavenumbers: np.ndarray,
    xe: float = 0.28,  # pluck position in m
    hi: float = 0.03,  # initial deflection in m
    length: float = 1.0,  # length of the string in m
) -> np.ndarray:
    """
    Create a pluck excitation for a string with a given length and pluck position.
    The pluck is modeled in the modal domain. This function is based on the function https://github.com/julian-parker/DAFX22_FNO.

    Parameters
    ----------
    wavenumbers : np.ndarray
        The wavenumbers of the modes.
    xe : float
        The position of the pluck in meters.
    hi : float
        The initial deflection of the string in meters.
    length : float
        The length of the string in meters.

    Returns
    -------
    np.ndarray
        The pluck excitation in the modal domain.
    """

    return (
        hi
        * (length / (length - xe) * np.sin(wavenumbers * xe) / (wavenumbers * xe))
        / wavenumbers
    )