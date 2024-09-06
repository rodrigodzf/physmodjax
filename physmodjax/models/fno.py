# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/models/fno.ipynb.

# %% auto 0
__all__ = ['BatchedFNO1D', 'BatchedFNO2D', 'SpectralConv1d', 'SpectralLayers1d', 'FNO1D', 'SpectralConv2d', 'FNO2D']

# %% ../../nbs/models/fno.ipynb 7
import flax.linen as nn
from flax.linen.initializers import uniform
import jax.numpy as jnp
from einops import rearrange
from typing import Tuple
import jax
from ..utils.data import create_grid

# %% ../../nbs/models/fno.ipynb 8
class SpectralConv1d(nn.Module):
    """Spectral Convolution Layer for 1D inputs.
    The n_modes parameter should be set to the length of the output for now, as it is not clear that the truncation is done correctly
    """

    in_channels: int  # number of input channels (last dimension of input)
    d_vars: int  # number of output channels (last dimension of output)
    n_modes: int  # number of fourier modes to use
    linear_conv: bool = (
        True  # whether to use linear convolution or circular convolution
    )

    def setup(self):
        weight_shape = (self.in_channels, self.d_vars, self.n_modes)
        scale = 1 / (self.in_channels * self.d_vars)

        self.weight_real = self.param(
            "weight_real", uniform(scale=scale), weight_shape  # cant use complex64
        )
        self.weight_imag = self.param(
            "weight_imag", uniform(scale=scale), weight_shape  # cant use complex64
        )

    def __call__(
        self,
        x: jnp.ndarray,  # (w, c)
    ):
        W, C = x.shape

        # get the fourier coefficients along the spatial dimension
        # we pad the inputs so that we perform a linear convolution
        X = jnp.fft.rfft(x, n=W * 2 - 1, axis=-2, norm="ortho")

        # truncate to the first n_modes coefficients
        X = X[: self.n_modes, :]

        # multiply by the fourier coefficients of the kernel
        complex_weight = self.weight_real + 1j * self.weight_imag
        X = jnp.einsum("ki,iok->ko", X, complex_weight)

        # inverse fourier transform along dimension N and remove padding
        x = jnp.fft.irfft(X, axis=-2, norm="ortho")[:W]

        return x

# %% ../../nbs/models/fno.ipynb 11
class SpectralLayers1d(nn.Module):
    """Stack of 1D Spectral Convolution Layers"""

    n_channels: int  # number of hidden channels
    n_modes: int  # number of fourier modes to keep
    linear_conv: bool = True  # whether to use linear convolution
    n_layers: int = 4  # number of layers
    activation: nn.Module = nn.relu  # activation function

    def setup(self):
        self.layers_conv = [
            SpectralConv1d(
                in_channels=self.n_channels,
                d_vars=self.n_channels,
                n_modes=self.n_modes,
                linear_conv=self.linear_conv,
            )
            for _ in range(self.n_layers)
        ]

        self.layers_w = [
            nn.Conv(features=self.n_channels, kernel_size=(1,))
            for _ in range(self.n_layers)
        ]

    def __call__(
        self,
        x,  # (grid_points, channels)
    ) -> jnp.ndarray:  # (grid_points, channels)
        for conv, w in zip(self.layers_conv, self.layers_w):
            x1 = conv(x)
            x2 = w(x)
            x = self.activation(x1 + x2)

        return x

# %% ../../nbs/models/fno.ipynb 14
class FNO1D(nn.Module):
    hidden_channels: int  # number of hidden channels
    n_modes: int  # number of fourier modes to keep
    d_vars: int = 1  # number of output channels
    linear_conv: bool = True  # whether to use linear convolution
    n_layers: int = 4  # number of layers
    n_steps: int = None  # number of steps to output
    activation: nn.Module = nn.gelu  # activation function
    norm: str = ("layer",)  # normalization layer
    training: bool = True  # whether to train the model

    @nn.compact
    def __call__(
        self,
        x,  # input (T, W, C)
    ):
        """
        The input to the FNO1D model is a 1D signal of shape (t, w, c)
        where w is the spatial dimension and c is the number of channels.
        The channel dimension is typically 1 for scalar fields. However, it can be
        can also contain multiple time steps as channels or contain multiple scalar fields.
        """

        # we need to make time as a channel dimension for the spectral layers
        x = rearrange(x, "t w c -> w (t c)")

        spectral_layers = SpectralLayers1d(
            n_channels=self.hidden_channels,
            n_modes=self.n_modes,
            linear_conv=True,
            n_layers=self.n_layers,
            activation=self.activation,
        )

        h = nn.Dense(features=self.hidden_channels)(
            x
        )  # lift the input to the hidden state
        h = spectral_layers(h)

        # Down lift the hidden state to the output using a tiny mlp
        y = nn.Sequential(
            [
                nn.Dense(features=128),
                self.activation,
                nn.Dense(features=self.d_vars * self.n_steps),
            ]
        )(h)

        # rearrange the output to the original shape
        y = rearrange(y, "w (t c) -> t w c", t=self.n_steps, c=self.d_vars)

        return y


BatchedFNO1D = nn.vmap(
    FNO1D,
    in_axes=0,
    out_axes=0,
    variable_axes={"params": None},
    split_rngs={"params": False},
)

# %% ../../nbs/models/fno.ipynb 18
class SpectralConv2d(nn.Module):
    in_channels: int
    out_channels: int
    n_modes1: int  # modes along the columns
    n_modes2: int  # modes along the rows

    def setup(self):

        weight_shape = (
            self.in_channels,
            self.out_channels,
            self.n_modes1,
            self.n_modes2,
        )

        scale = 1 / (self.in_channels * self.out_channels)

        self.weight_1_real = self.param(
            "weight_1_real",
            uniform(scale=scale),
            weight_shape,
        )

        self.weight_1_imag = self.param(
            "weight_1_imag",
            uniform(scale=scale),
            weight_shape,
        )

        self.weight_2_real = self.param(
            "weight_2_real",
            uniform(scale=scale),
            weight_shape,
        )

        self.weight_2_imag = self.param(
            "weight_2_imag",
            uniform(scale=scale),
            weight_shape,
        )

        self.complex_weight_1 = self.weight_1_real + 1j * self.weight_1_imag
        self.complex_weight_2 = self.weight_2_real + 1j * self.weight_2_imag

    def __call__(
        self,
        x: jnp.ndarray,  # (H, W, C)
    ):
        """
        The input x is of shape (H, W, C), and we always perform a linear convolution
        """

        H, W, C = x.shape
        # get the fourier transform of the input
        # along the first two dimensions
        X = jnp.fft.rfft2(x, s=(H * 2 - 1, W * 2 - 1), axes=(0, 1), norm="ortho")

        # truncate the fourier transform
        # to the first n_modes1, n_modes2 modes
        # X -> (n_modes1, n_modes2, C)
        # X = X[:self.n_modes1, :self.n_modes2, :]

        # multiply the weights with the fourier transform
        # This is a bit tricky. In the original implementation
        # We multiply with two different weights
        # along the first dimension from -n_modes1:n_modes1
        # this is neccesary to cover the entire height
        # this differs from parker's implementation
        out_ft_up = jnp.einsum(
            "xyi,ioxy->xyo",
            X[: self.n_modes1, : self.n_modes2, :],
            self.complex_weight_1,
        )

        out_ft_down = jnp.einsum(
            "xyi,ioxy->xyo",
            X[-self.n_modes1 :, : self.n_modes2, :],
            self.complex_weight_2,
        )

        out_ft = jnp.concatenate((out_ft_up, out_ft_down), axis=0)

        # inverse fourier transform
        # along the first two dimensions
        x = jnp.fft.irfft2(out_ft, s=(H, W), axes=(0, 1))

        return x

# %% ../../nbs/models/fno.ipynb 20
class FNO2D(nn.Module):
    hidden_channels: int  # number of hidden channels
    n_modes: int  # number of fourier modes to keep
    d_vars: int = 1  # number of output channels
    linear_conv: bool = True  # whether to use linear convolution
    n_layers: int = 4  # number of layers
    n_steps: int = None  # number of steps to output
    activation: nn.Module = nn.gelu  # activation function
    d_model: Tuple[int, int] = (41, 37)  # (H, W) of the input for the grid
    use_positions: bool = False  # whether to use positions in the input
    norm: str = "layer"  # normalization layer
    training: bool = True

    def setup(self):
        self.conv_layers = [
            SpectralConv2d(
                in_channels=self.hidden_channels,
                out_channels=self.hidden_channels,
                n_modes1=self.n_modes,
                n_modes2=self.n_modes,
            )
            for _ in range(self.n_layers)
        ]

        # dense layers
        # we use conv so that we don't have to shuffle the dimensions
        self.w_layers = [
            nn.Conv(features=self.hidden_channels, kernel_size=(1,))
            for _ in range(self.n_layers)
        ]

        self.P = nn.Dense(
            features=self.hidden_channels,
        )

        # TODO: in the original implementation this is a tiny mlp
        # self.Q = nn.Dense(
        #     features=self.out_channels,
        # )
        self.Q = nn.Sequential(
            [
                nn.Dense(features=128),
                self.activation,
                nn.Dense(features=self.d_vars * self.n_steps),
            ]
        )

        if self.use_positions:
            self.grid = create_grid(self.d_model[1], self.d_model[0])

    def advance(
        self,
        x: jnp.ndarray,  # (h, w, (t c))
    ) -> jnp.ndarray:
        """
        The input x is of shape (H, W, C), and we always perform a linear convolution
        """
        if self.use_positions:
            x = jnp.concatenate((x, self.grid), axis=-1)

        # lifting layer works on the last dimension
        x = self.P(x)

        for conv, w in zip(self.conv_layers, self.w_layers):
            x1 = conv(x)
            x2 = w(x)
            x = self.activation(x1 + x2)

        x = self.Q(x)

        return x

    def __call__(
        self,
        x,  # (t, h, w, c)
    ) -> jnp.ndarray:
        """
        The input x is of shape (T, H, W, C).
        We always map from a single timestep to one or more timesteps.
        The FNO2D can map from many-to-many timesteps, in which case these
        are concatenated along the channel dimension.
        """
        # we need to rearrange the dimensions
        # will work only with 1 variable
        # this is equivalent to the temporal bundling trick
        x = rearrange(x, "t h w c -> h w (t c)")

        x = self.advance(x)

        x = rearrange(x, "h w (t c) -> t h w c", t=self.n_steps, c=self.d_vars)

        return x


BatchedFNO2D = nn.vmap(
    FNO2D,
    in_axes=0,
    out_axes=0,
    variable_axes={"params": None},
    split_rngs={"params": False},
)