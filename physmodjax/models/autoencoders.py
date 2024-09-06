# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/models/autoencoders.ipynb.

# %% auto 0
__all__ = ['BatchedFourierAutoencoder2D', 'BatchedDenseKoopmanAutoencoder2D', 'BatchedKoopmanAutoencoder2D',
           'BatchedKoopmanAutoencoder1D', 'BatchedKoopmanAutoencoder1DReal', 'FourierAutoencoder2D',
           'DenseKoopmanAutoencoder2D', 'KoopmanAutoencoder2D', 'KoopmanAutoencoder1D', 'KoopmanAutoencoder1DReal']

# %% ../../nbs/models/autoencoders.ipynb 2
import jax
import flax.linen as nn
import jax.numpy as jnp
from .conv import ConvEncoder, ConvDecoder
from .recurrent import LRUDynamics, LRUDynamicsVarying
from functools import partial
from einops import rearrange
from typing import Tuple
from ..utils.data import create_grid

# %% ../../nbs/models/autoencoders.ipynb 4
class FourierAutoencoder2D(nn.Module):

    dynamics_model: nn.Module
    d_vars: int
    d_model: Tuple[int, int]
    norm: str = "layer"
    training: bool = True
    use_positions: bool = False
    n_modes: int = 20

    def setup(self):
        self.dynamics = self.dynamics_model()
        if self.use_positions:
            self.grid = create_grid(self.d_model[1], self.d_model[0])

    def __call__(
        self,
        x: jnp.ndarray,  # (W, H, C) or (T, W, H, C)
    ) -> jnp.ndarray:

        z = self.encode(x)
        z = self.advance(z, x)
        return self.decode(z)

    def encode(
        self,
        x: jnp.ndarray,  # (W, H, C) or (T, W, H, C)
    ) -> jnp.ndarray:  # (hidden_dim) or (T, hidden_dim) complex
        """
        Spatial encoding of the input data.
        """

        if self.use_positions:
            x = jnp.concatenate([x, self.grid], axis=-1)

        *_, W, H, C = x.shape
        x = jnp.fft.rfft2(x, s=(W * 2 - 1, H * 2 - 1), axes=(-3, -2), norm="ortho")
        x = x[..., : self.n_modes, : self.n_modes, :]

        if len(x.shape) == 3:
            x = rearrange(x, "w h c -> (w h c)")
        elif len(x.shape) == 4:
            x = rearrange(x, "t w h c -> t (w h c)")

        return x

    def advance(
        self,
        z: jnp.ndarray,  # (hidden_dim,) complex
        steps: jnp.ndarray,  # (T,)
    ) -> jnp.ndarray:  # (T, hidden_dim,)
        # z = z[: z.shape[0] // 2] + 1j * z[z.shape[0] // 2 :]
        z = self.dynamics(z, steps.shape[0])
        # z = jnp.concatenate([z.real, z.imag], axis=-1)
        return z

    def decode(
        self,
        z: jnp.ndarray,  # (hidden_dim) or (T, hidden_dim) complex
    ) -> jnp.ndarray:  # (W, H, C) or (T, W, H, C) real

        w_modes = self.n_modes
        h_modes = self.n_modes
        if len(z.shape) == 1:
            z = rearrange(z, "(w h c) -> w h c", w=w_modes, h=h_modes, c=self.d_vars)
        elif len(z.shape) == 2:
            z = rearrange(
                z, "t (w h c) -> t w h c", w=w_modes, h=h_modes, c=self.d_vars
            )

        z = jnp.fft.irfft2(
            z, s=(self.d_model[0], self.d_model[1]), axes=(-3, -2), norm="ortho"
        )
        return z


BatchedFourierAutoencoder2D = nn.vmap(
    FourierAutoencoder2D,
    in_axes=0,
    out_axes=0,
    variable_axes={"params": None},
    split_rngs={"params": False},
    methods=["__call__", "decode", "encode", "advance"],
)

# %% ../../nbs/models/autoencoders.ipynb 6
class DenseKoopmanAutoencoder2D(nn.Module):
    """
    Koopman Dense Autoencoder
    """

    encoder_model: nn.Module
    decoder_model: nn.Module
    dynamics_model: nn.Module
    d_vars: int
    d_model: Tuple[int, int]
    n_steps: int
    norm: str = "layer"
    training: bool = True
    use_positions: bool = False

    def setup(self):
        self.encoder = self.encoder_model()
        self.decoder = self.decoder_model()
        self.dynamics = self.dynamics_model()
        if self.use_positions:
            self.grid = create_grid(self.d_model[1], self.d_model[0])

    def __call__(
        self,
        x: jnp.ndarray,  # (W, H, C)
    ) -> jnp.ndarray:
        z = self.encode(x[0])
        z = self.advance(z)
        return self.decode(z)

    def encode(
        self,
        x: jnp.ndarray,  # (W, H, C) or (T, W, H, C)
    ) -> jnp.ndarray:  # (hidden_dim) or (T, hidden_dim)

        if self.use_positions:
            x = jnp.concatenate([x, self.grid], axis=-1)

        if len(x.shape) == 3:
            x = rearrange(x, "w h c -> (w h c)")
        elif len(x.shape) == 4:
            x = rearrange(x, "t w h c -> t (w h c)")
        return self.encoder(x)

    def advance(
        self,
        z: jnp.ndarray,  # (hidden_dim,)
    ) -> jnp.ndarray:  # (T, hidden_dim,)
        z = z[: z.shape[0] // 2] + 1j * z[z.shape[0] // 2 :]
        z = self.dynamics(z, self.n_steps)
        z = jnp.concatenate([z.real, z.imag], axis=-1)
        return z

    def decode(
        self,
        z: jnp.ndarray,  # (hidden_dim) or (T, hidden_dim)
    ) -> jnp.ndarray:  # (W, H, C) or (T, W, H, C)
        z = self.decoder(z)
        if len(z.shape) == 1:
            z = rearrange(
                z,
                "(w h c) -> w h c",
                w=self.d_model[0],
                h=self.d_model[1],
                c=self.d_vars,
            )
        elif len(z.shape) == 2:
            z = rearrange(
                z,
                "t (w h c) -> t w h c",
                w=self.d_model[0],
                h=self.d_model[1],
                c=self.d_vars,
            )
        return z


BatchedDenseKoopmanAutoencoder2D = nn.vmap(
    DenseKoopmanAutoencoder2D,
    in_axes=0,
    out_axes=0,
    variable_axes={"params": None},
    split_rngs={"params": False},
    methods=["__call__", "decode", "encode", "advance"],
)

# %% ../../nbs/models/autoencoders.ipynb 9
class KoopmanAutoencoder2D(nn.Module):
    """
    Koopman Autoencoder
    """

    encoder_model: ConvEncoder
    decoder_model: ConvDecoder
    dynamics_model: LRUDynamics
    d_latent_channels: int
    d_latent_dims: Tuple[int, int]
    n_steps: int
    norm: str = "layer"
    training: bool = True

    def setup(self):
        self.encoder = self.encoder_model(training=self.training, norm=self.norm)
        self.decoder = self.decoder_model(training=self.training, norm=self.norm)
        self.dynamics = self.dynamics_model()

    def __call__(
        self,
        x: jnp.ndarray,  # (H, W, C)
    ) -> jnp.ndarray:  # (T, H, W, C)

        z = self.encode(x[0])
        z = self.advance(z)
        x_hat = self.decode(z)
        return x_hat

    def encode(
        self,
        x: jnp.ndarray,  # (H, W, C) or (T, H, W, C)
    ) -> jnp.ndarray:  # (hidden_dim,) or (T, hidden_dim)
        z = self.encoder(x)
        if len(z.shape) == 4:
            z = rearrange(z, "t h w c -> t (h w c)")
        elif len(z.shape) == 3:
            z = rearrange(z, "h w c -> (h w c)")
        return z

    def decode(
        self,
        z: jnp.ndarray,  # (hidden_dim,)  or (T, hidden_dim)
    ) -> jnp.ndarray:  # (H, W, C) or (T, H, W, C)
        if len(z.shape) == 2:
            z = rearrange(
                z,
                "t (h w c) -> t h w c",
                h=self.d_latent_dims[0],
                w=self.d_latent_dims[1],
                c=self.d_latent_channels,
            )
        elif len(z.shape) == 1:
            z = rearrange(
                z,
                "(h w c) -> h w c",
                h=self.d_latent_dims[0],
                w=self.d_latent_dims[1],
                c=self.d_latent_channels,
            )
        return self.decoder(z)

    def advance(
        self,
        z: jnp.ndarray,  # (hidden_dim,)
    ) -> jnp.ndarray:
        # convert to complex and back
        z = z[: z.shape[0] // 2] + 1j * z[z.shape[0] // 2 :]
        z = self.dynamics(z, self.n_steps)
        z = jnp.concatenate([z.real, z.imag], axis=-1)
        return z


BatchedKoopmanAutoencoder2D = nn.vmap(
    KoopmanAutoencoder2D,
    in_axes=0,  # map over the first axis of the first input not the second
    out_axes=0,
    variable_axes={"params": None, "batch_stats": None, "cache": 0, "prime": None},
    split_rngs={"params": False},
    methods=["__call__", "decode", "encode", "advance"],
    axis_name="batch",
)

# %% ../../nbs/models/autoencoders.ipynb 13
class KoopmanAutoencoder1D(nn.Module):
    """
    Koopman Autoencoder
    """

    encoder_model: nn.Module
    decoder_model: nn.Module
    dynamics_model: nn.Module
    d_vars: int
    d_model: int
    n_steps: int
    norm: str = "layer"
    training: bool = True

    def setup(self):
        self.encoder = self.encoder_model()
        self.decoder = self.decoder_model()
        self.dynamics = self.dynamics_model()

    def __call__(
        self,
        x: jnp.ndarray,  # (T, W, C)
    ) -> jnp.ndarray:

        z = self.encode(x[0])
        z = self.advance(z)
        x_hat = self.decode(z)
        return x_hat

    def encode(
        self,
        x: jnp.ndarray,  # (W, C) or (T, W, C)
    ) -> jnp.ndarray:  # (T, hidden_dim)
        if len(x.shape) == 2:
            x = rearrange(x, "w c -> (w c)")
        elif len(x.shape) == 3:
            x = rearrange(x, "t w c -> t (w c)")
        return self.encoder(x)

    def decode(
        self,
        z: jnp.ndarray,  # (hidden_dim,) or (T, hidden_dim)
    ) -> jnp.ndarray:  # (W, C) or (T, W, C)
        z = self.decoder(z)
        if len(z.shape) == 2:
            z = rearrange(z, "t (w c) -> t w c", w=self.d_model, c=self.d_vars)
        elif len(z.shape) == 1:
            z = rearrange(z, "(w c) -> w c", w=self.d_model, c=self.d_vars)
        return z

    def advance(
        self,
        z: jnp.ndarray,  # (hidden_dim,)
    ) -> jnp.ndarray:  # (T, hidden_dim)
        # convert to complex and back
        z = z[: z.shape[0] // 2] + 1j * z[z.shape[0] // 2 :]
        z = self.dynamics(z, self.n_steps)
        z = jnp.concatenate([z.real, z.imag], axis=-1)
        return z


BatchedKoopmanAutoencoder1D = nn.vmap(
    KoopmanAutoencoder1D,
    in_axes=0,
    out_axes=0,
    variable_axes={"params": None},
    split_rngs={"params": False},
    methods=["__call__", "decode", "encode", "advance"],
)

# %% ../../nbs/models/autoencoders.ipynb 16
class KoopmanAutoencoder1DReal(nn.Module):
    """
    Koopman Autoencoder but with real encoding and decoding
    """

    encoder_model: nn.Module
    decoder_model: nn.Module
    dynamics_model: nn.Module
    d_vars: int
    d_model: int
    n_steps: int
    norm: str = "layer"
    training: bool = True

    def setup(self):
        self.encoder = self.encoder_model()
        self.decoder = self.decoder_model()
        self.dynamics = self.dynamics_model()

    def __call__(
        self,
        x: jnp.ndarray,  # (T, W, C)
    ) -> jnp.ndarray:

        z = self.encode(x[0])
        z = self.advance(z)
        x_hat = self.decode(z)
        return x_hat

    def encode(
        self,
        x: jnp.ndarray,  # (W, C) or (T, W, C)
    ) -> jnp.ndarray:  # (T, hidden_dim)
        if len(x.shape) == 2:
            x = rearrange(x, "w c -> (w c)")
        elif len(x.shape) == 3:
            x = rearrange(x, "t w c -> t (w c)")
        return self.encoder(x)

    def decode(
        self,
        z: jnp.ndarray,  # (hidden_dim,) or (T, hidden_dim)
    ) -> jnp.ndarray:  # (W, C) or (T, W, C)
        z = self.decoder(z)
        if len(z.shape) == 2:
            z = rearrange(z, "t (w c) -> t w c", w=self.d_model, c=self.d_vars)
        elif len(z.shape) == 1:
            z = rearrange(z, "(w c) -> w c", w=self.d_model, c=self.d_vars)
        return z

    def advance(
        self,
        z: jnp.ndarray,  # (hidden_dim,)
    ) -> jnp.ndarray:  # (T, hidden_dim)
        # convert to complex and back
        z = z + 1j * 0.0
        z = self.dynamics(z, self.n_steps).real
        return z


BatchedKoopmanAutoencoder1DReal = nn.vmap(
    KoopmanAutoencoder1DReal,
    in_axes=0,
    out_axes=0,
    variable_axes={"params": None},
    split_rngs={"params": False},
    methods=["__call__", "decode", "encode", "advance"],
)
