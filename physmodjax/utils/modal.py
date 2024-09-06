"""Utils for converting between modal and physical coordinates."""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/utils/modal.ipynb.

# %% auto 0
__all__ = ['create_modal_matrix', 'to_displacement', 'to_modal', 'create_pluck_modal']

# %% ../../nbs/utils/modal.ipynb 2
import numpy as np

# %% ../../nbs/utils/modal.ipynb 4
def create_modal_matrix(
    mode_numbers: np.ndarray,  # array of mode numbers (integers)
    string_length: float = 1.0,  # total length of the string in meters
    grid: np.ndarray = None,  # grid of points to evaluate the modes on
) -> np.ndarray:
    """
    Creates a matrix with the modal shapes as columns.

    :param mode_numbers: Array of mode numbers, representing different vibration modes.
    :param string_length: Total length of the string.
    :param grid: Grid of points to evaluate the modes on.
    :return: Matrix with the modal shapes as columns (shape: (grid.size, mode_numbers.size)).
    """

    return np.sin(np.outer(grid, mode_numbers * np.pi / string_length))

# %% ../../nbs/utils/modal.ipynb 7
def to_displacement(
    modal_amplitudes: np.ndarray,  # Amplitudes in the modal domain
    modal_shapes: np.ndarray,  # Modal shapes (eigenvectors)
    string_length: float = 1.0,  # Length of the string in meters
) -> np.ndarray:
    """
    Convert modal amplitudes to physical displacement along the string.

    :param modal_amplitudes: Array of amplitudes in the modal domain.
    :param modal_shapes: Matrix of modal shapes (each column is a mode shape).
    :param string_length: Length of the string.
    :return: Array of physical displacements at the grid points.
    """
    # Calculate scaling factor for modal shapes
    scaling_factor = 2 / string_length

    # Multiply modal shapes by modal amplitudes and scale
    physical_displacement = scaling_factor * modal_shapes @ modal_amplitudes

    return physical_displacement


def to_modal(
    physical_displacement: np.ndarray,  # Displacement at grid points
    modal_shapes: np.ndarray,  # Modal shapes (eigenvectors)
    string_length: float = 1.0,  # Length of the string in meters
    num_gridpoints: int = 100,  # Number of grid points
) -> np.ndarray:
    """
    Convert physical displacement to modal amplitudes.

    :param physical_displacement: Array of displacements at grid points.
    :param modal_shapes: Matrix of modal shapes (each column is a mode shape).
    :param string_length: Length of the string.
    :param num_gridpoints: Number of grid points along the string.
    :return: Array of amplitudes in the modal domain.
    """
    # Calculate scaling factor for conversion to modal domain
    scaling_factor = string_length / num_gridpoints

    # Multiply transpose of modal shapes by physical displacement and scale
    modal_amplitudes = scaling_factor * modal_shapes.T @ physical_displacement

    return modal_amplitudes

# %% ../../nbs/utils/modal.ipynb 8
def create_pluck_modal(
    mode_numbers: np.ndarray,  # array of mode numbers (integers)
    pluck_position: float = 0.28,  # position of pluck on the string in meters
    initial_deflection: float = 0.03,  # initial deflection of the string in meters
    string_length: float = 1.0,  # total length of the string in meters
) -> np.ndarray:
    """
    Calculate the Fourier-Sine coefficients of the initial deflection
    of a plucked string in modal coordinates.

    :param modes: Array of mode numbers, representing different vibration modes.
    :param pluck_position: Position of the pluck on the string.
    :param initial_deflection: Initial displacement of the string at the pluck position.
    :param string_length: Total length of the string.
    :return: Array of Fourier-Sine coefficients for each mode.
    """

    # Calculate the wave number for each mode
    wave_numbers = mode_numbers * np.pi / string_length

    # Scaling factor for the initial deflection
    deflection_scaling = initial_deflection * (
        string_length / (string_length - pluck_position)
    )

    # Compute the Fourier-Sine coefficients
    fourier_coefficients = (
        deflection_scaling
        * np.sin(wave_numbers * pluck_position)
        / (wave_numbers * pluck_position)
    )
    fourier_coefficients /= wave_numbers

    return fourier_coefficients
