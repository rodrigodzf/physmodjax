"""Metrics and losses for training and evaluation."""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/utils/metrics.ipynb.

# %% auto 0
__all__ = ['squared_error', 'absolute_error', 'mse', 'mae', 'mse_relative', 'mae_relative', 'accumulate_metrics']

# %% ../../nbs/utils/metrics.ipynb 2
import jax
import jax.numpy as jnp
import numpy as np

# %% ../../nbs/utils/metrics.ipynb 3
def squared_error(y_true, y_pred):
    return (y_true - y_pred) ** 2


def absolute_error(y_true, y_pred):
    return jnp.abs(y_true - y_pred)


def mse(y_true, y_pred, axis=None):
    return jnp.mean((y_true - y_pred) ** 2, axis=axis)


def mae(y_true, y_pred, axis=None):
    return jnp.mean(jnp.abs(y_true - y_pred), axis=axis)


def mse_relative(y_true, y_pred, axis=None):
    return jnp.mean(((y_true - y_pred) ** 2), axis=axis) / jnp.mean(
        (y_true**2), axis=axis
    )


def mae_relative(y_true, y_pred, axis=None):
    return jnp.mean(jnp.abs(y_true - y_pred), axis=axis) / jnp.mean(
        jnp.abs(y_true), axis=axis
    )


def accumulate_metrics(metrics):
    metrics = jax.device_get(metrics)
    return {k: np.mean([metric[k] for metric in metrics]) for k in metrics[0]}
