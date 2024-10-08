"""An script to train a generic RNN model."""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/scripts/train_rnn.ipynb.

# %% auto 0
__all__ = ['create_train_state', 'train', 'train_rnn']

# %% ../../nbs/scripts/train_rnn.ipynb 2
import os
from pathlib import Path
from typing import Dict, Tuple, Any, List
import pprint
from functools import partial
from absl import logging
import logging as pylogging
import hydra
import jax
import jax.numpy as jnp
import matplotlib
from matplotlib import pyplot as plt
import optax
from omegaconf import DictConfig, OmegaConf
from tqdm import tqdm
import wandb
from math import ceil

from flax import traverse_util
from flax import linen as nn
from flax.training import train_state, orbax_utils, early_stopping
import orbax.checkpoint as obc
from einops import rearrange
from physmodjax.utils.metrics import (
    mse,
    mae,
    mse_relative,
    mae_relative,
    accumulate_metrics,
)
from ..utils.plot import plot_solution, plot_solution_2d
from hydra.core.hydra_config import HydraConfig

# %% ../../nbs/scripts/train_rnn.ipynb 3
def create_train_state(
    model: nn.Module,
    rng: jnp.ndarray,
    x_shape: Tuple[
        int, int, int, int
    ],  # (batch_size, time_steps, grid_size, num_channels):
    num_steps: int,  # number of training steps
    norm: str = "layer",  # "layer" or "batch"
    learning_rate: float = 1e-3,
    grad_clip: optax.GradientTransformation = optax.clip_by_global_norm(1.0),
    components_to_freeze: List[str] = [],
    schedule_type: str = "constant",  # "cosine" or "constant"
    debug: bool = False,  # print debug information
) -> train_state.TrainState:

    logging.info(f"Initalizing model with shape {x_shape}.")
    init_key, dropout_key = jax.random.split(rng, num=2)
    variables = model.init(
        {"params": init_key, "dropout": dropout_key},
        jnp.empty(shape=x_shape),
    )

    # print model parameters
    logging.info(
        model.tabulate(
            init_key,
            jnp.empty(shape=x_shape),
            column_kwargs={"no_wrap": True},
            table_kwargs={"expand": True},
            console_kwargs={"width": 120},
            depth=1,
        )
    )

    if norm in ["batch"]:
        params = variables["params"]
        batch_stats = variables["batch_stats"]
    else:
        params = variables["params"]

    ssm_params = ["nu_log", "theta_log", "gamma_log", "B_re", "B_im", "C_re", "C_im"]
    param_labels = traverse_util.path_aware_map(
        lambda path, _: (
            "ssm" if any(part in path for part in ssm_params) else "regular"
        ),
        params,
    )

    # freeze parameters if necessary
    param_labels = traverse_util.path_aware_map(
        lambda path, label: (
            "frozen" if any(part in path for part in components_to_freeze) else label
        ),
        param_labels,
    )

    if debug:
        pp = pprint.PrettyPrinter(depth=4)
        pp.pprint(traverse_util.flatten_dict(param_labels))

    logging.info(f"Scheduling for {num_steps} steps.")
    if schedule_type in ["cosine"]:
        schedule_regular = optax.cosine_decay_schedule(
            decay_steps=num_steps,
            init_value=learning_rate,
        )
        schedule_ssm = optax.cosine_decay_schedule(
            decay_steps=num_steps,
            init_value=learning_rate / 4,
        )
    elif schedule_type in ["constant"]:
        schedule_regular = optax.constant_schedule(learning_rate)
        schedule_ssm = optax.constant_schedule(learning_rate / 4)
    else:
        raise ValueError("schedule_type must be 'cosine' or 'constant'")

    gradient_transform = optax.multi_transform(
        {
            "ssm": optax.adam(schedule_ssm),
            "regular": optax.chain(grad_clip, optax.adamw(schedule_regular)),
            "frozen": optax.set_to_zero(),
        },
        param_labels,
    )

    if norm in ["layer"]:

        class TrainState(train_state.TrainState):
            key: jax.Array

        return TrainState.create(
            apply_fn=model.apply,
            params=params,
            key=dropout_key,
            tx=gradient_transform,
        )
    else:

        class TrainState(train_state.TrainState):
            key: jax.Array
            batch_stats: Any

        return TrainState.create(
            apply_fn=model.apply,
            params=params,
            tx=gradient_transform,
            key=dropout_key,
            batch_stats=batch_stats,
        )

# %% ../../nbs/scripts/train_rnn.ipynb 4
def train(
    model_cls,
    datamodule,
    cfg: DictConfig,
    checkpoint_manager: obc.CheckpointManager,
):
    # unpack dataloader
    train_dataloader = datamodule.train_dataloader
    val_dataloader = datamodule.val_dataloader
    test_dataloader = datamodule.test_dataloader

    data_shape = datamodule.get_info()

    epochs_val = getattr(cfg, "epochs_val", 1)

    # hydra multirun flag
    hydra_multirun = (
        hydra.core.hydra_config.HydraConfig.get().mode == hydra.types.RunMode.MULTIRUN
    )

    # generate zeros for input
    x_shape = [datamodule.train_batch_size, *data_shape]

    # initialise rng
    rng = jax.random.PRNGKey(cfg.seed)

    # Initialize optimiser, clipping and loss function
    optimiser = hydra.utils.instantiate(cfg.optimiser)
    grad_clip = hydra.utils.instantiate(cfg.gradient_clip)
    loss_fn = hydra.utils.instantiate(cfg.loss)

    # initialise train state
    total_batches = datamodule.train_batch_size * len(train_dataloader)
    state = create_train_state(
        model_cls(n_steps=datamodule.num_steps_target_train),
        rng,
        x_shape,
        num_steps=cfg.epochs * total_batches + cfg.epochs,
        learning_rate=cfg.optimiser.learning_rate,
        grad_clip=grad_clip,
        components_to_freeze=cfg.frozen,
        norm=cfg.model.norm,
        schedule_type=cfg.schedule_type,
    )

    early_stop = early_stopping.EarlyStopping(min_delta=1e-3, patience=10)

    # train step
    @partial(jax.jit, static_argnames=("norm"))
    def train_step(
        state: train_state.TrainState,
        x: jnp.ndarray,  # pde solution from t=0(batch, timesteps, grid_size, channels)
        y: jnp.ndarray,  # pde solution from t+1(batch, timesteps, grid_size, channels)
        dropout_key: jnp.ndarray = None,
        norm: str = "layer",
    ) -> Tuple[train_state.TrainState, Dict[str, float], jnp.ndarray]:

        gradient_fn = jax.value_and_grad(loss_fn, has_aux=True)
        dropout_train_key = jax.random.fold_in(key=dropout_key, data=state.step)

        (loss, (pred, vars)), grads = gradient_fn(
            state.params,
            state,
            x=x,
            y=y,
            dropout_key=dropout_train_key,
            norm=norm,
        )

        if norm in ["batch"]:
            state = state.apply_gradients(grads=grads, batch_stats=vars["batch_stats"])
        else:
            state = state.apply_gradients(grads=grads)

        metrics = {
            "loss": loss,
            "mse": mse(y, pred),
            "mae": mae(y, pred),
            "mse_rel": mse_relative(y, pred),
            "mae_rel": mae_relative(y, pred),
        }
        return state, metrics, pred

    # val step
    @partial(jax.jit, static_argnames=("model", "norm"))
    def val_step(
        state: train_state.TrainState,
        x: jnp.ndarray,  # pde solution from t=0(batch, timesteps, grid_size, channels)
        y: jnp.ndarray,  # pde solution from t+1(batch, timesteps, grid_size, channels)
        model: nn.Module,  # model to use for prediction
        norm: str = "layer",
    ):
        if norm in ["batch"]:
            pred = model.apply(
                {"params": state.params, "batch_stats": state.batch_stats}, x
            )
        else:
            pred = model.apply({"params": state.params}, x)

        metrics = {
            "mse": mse(y, pred),
            "mae": mae(y, pred),
            "mse_rel": mse_relative(y, pred),
            "mae_rel": mae_relative(y, pred),
        }
        return metrics, pred

    @partial(jax.jit, static_argnames=("model", "norm"))
    def test_step(
        state: train_state.TrainState,
        x: jnp.ndarray,  # pde solution (batch, timesteps, grid_size, c)
        model: nn.Module,  # model to use for predictio
        norm: str = "layer",
    ):

        # We only need the first time step for the input
        # but the models expect a sequence with length num_steps
        init_x = x[:, : datamodule.num_steps_input_train, ...]

        def step(carry, _):
            if norm == "batch":
                pred = model.apply(
                    {"params": state.params, "batch_stats": state.batch_stats}, carry
                )
            else:
                pred = model.apply({"params": state.params}, carry)

            return (
                pred[
                    :, -datamodule.num_steps_input_train :, ...
                ],  # Update carry (with the last step) and output with the new prediction
                pred,
            )  # Update carry (with the last step) and output with the new prediction

        # if not evenly divisible, we need to ceil the length to account the the missing input steps
        length = ceil(x.shape[1] / datamodule.num_steps_target_train) + 1

        _, preds = jax.lax.scan(step, init_x, None, length=length)

        preds = rearrange(preds, "n b s ... c -> b (n s) ... c")

        # Concatenate the initial input with the predictions
        # WARNING for the rnn the input is always only the first time step! do not include the rest!
        # otherwise we stack a duplicate at the start
        full_preds = jnp.concatenate([init_x, preds], axis=1)

        # we need to slice the predictions to match the input
        full_preds = full_preds[:, : x.shape[1], ...]

        metrics = {
            "mse": mse(x, full_preds),
            "mae": mae(x, full_preds),
            "mse_rel": mse_relative(x, full_preds),
            "mae_rel": mae_relative(x, full_preds),
        }
        return metrics, full_preds

    # If hydra mode is RUN print the mode
    if hydra_multirun:
        logger = pylogging.getLogger("tqdm_logger")
        logger.setLevel(pylogging.INFO)
        progress_bar = tqdm(range(1, cfg.epochs + 1), file=open(os.devnull, "w"))
    else:
        progress_bar = tqdm(range(1, cfg.epochs + 1))

    for epoch in progress_bar:
        """Training."""
        train_batch_metrics = []
        for x, y in train_dataloader:

            state, metrics, pred = train_step(
                state,
                x=x,
                y=y,
                dropout_key=rng,
                norm=cfg.model.norm,
            )
            train_batch_metrics.append(metrics)
        train_batch_metrics = accumulate_metrics(train_batch_metrics)

        # Validation
        if ((epoch - 1) % epochs_val == 0) or (epoch == cfg.epochs):
            """Validation."""
            val_batch_metrics = []
            for x, y in val_dataloader:

                metrics, pred = val_step(
                    state,
                    x=x,
                    y=y,
                    model=model_cls(
                        training=False,
                        n_steps=datamodule.num_steps_target_val,
                    ),  # use model with dropout off
                    norm=cfg.model.norm,
                )
                val_batch_metrics.append(metrics)
            val_batch_metrics = accumulate_metrics(val_batch_metrics)
            early_stop = early_stop.update(val_batch_metrics["mae_rel"])

            test_batch_metrics = []
            for test_x in test_dataloader:
                # the test step is always autoregressive
                metrics, test_pred = test_step(
                    state,
                    x=test_x,
                    model=model_cls(
                        training=False,
                        n_steps=datamodule.num_steps_target_train,
                    ),  # use model with dropout off
                    norm=cfg.model.norm,
                )
                test_batch_metrics.append(metrics)
            test_batch_metrics = accumulate_metrics(test_batch_metrics)

            if early_stop.should_stop:
                logging.info("Met early stopping criteria, breaking...")
                break

            # Log Metrics to Weights & Biases
            metrics_to_log = {
                "train/loss": float(train_batch_metrics["loss"]),
                "train/mse": float(train_batch_metrics["mse"]),
                "train/mae": float(train_batch_metrics["mae"]),
                "train/mse_rel": float(train_batch_metrics["mse_rel"]),
                "train/mae_rel": float(train_batch_metrics["mae_rel"]),
                "val/mse": float(val_batch_metrics["mse"]),
                "val/mae": float(val_batch_metrics["mae"]),
                "val/mse_rel": float(val_batch_metrics["mse_rel"]),
                "val/mae_rel": float(val_batch_metrics["mae_rel"]),
                "test/mse_rel": float(test_batch_metrics["mse_rel"]),
                "test/mae_rel": float(test_batch_metrics["mae_rel"]),
            }

            wandb.log(
                metrics_to_log,
                step=epoch,
            )

            # log images
            single_y = y[0, ..., 0]  # single entry, only last channel
            single_pred = pred[0, ..., 0]  # single entry, only last channel

            if len(data_shape) == 4:
                fig = plot_solution_2d(
                    gt=single_y,
                    pred=single_pred,
                    # ar_pred=ar_pred[..., 0] if datamodule.mode == "many_to_many" else None,
                )
            elif len(data_shape) == 3:
                fig = plot_solution(
                    gt=single_y,
                    pred=single_pred,
                    ar_gt=test_x[0, ..., 0],  # single entry, only last channel
                    ar_pred=test_pred[0, ..., 0],  # single entry, only last channel
                )

            else:
                raise ValueError("Invalid training data shape")

            images = wandb.Image(
                fig,
            )
            plt.close(fig)
            wandb.log({"end train epoch": images})

            # Save checkpoint
            checkpoint_manager.save(
                step=epoch,
                args=obc.args.Composite(
                    state=obc.args.PyTreeSave(state),
                ),
                metrics=metrics_to_log,
            )
        else:
            # # Log Metrics to Weights & Biases
            wandb.log(
                {
                    "train/loss": train_batch_metrics["loss"],
                    "train/mse": train_batch_metrics["mse"],
                    "train/mae": train_batch_metrics["mae"],
                    "train/mse_rel": train_batch_metrics["mse_rel"],
                    "train/mae_rel": train_batch_metrics["mae_rel"],
                },
                step=epoch,
            )
        progress_bar.set_postfix({"loss": float(train_batch_metrics["loss"])})

        if hydra_multirun:
            logger.info(str(progress_bar))

    return state

# %% ../../nbs/scripts/train_rnn.ipynb 5
@hydra.main(version_base=None, config_path="../../conf", config_name="train_rnn")
def train_rnn(cfg: DictConfig) -> None:
    """
    Train RNN model
    """
    OmegaConf.register_new_resolver(
        "eval",
        eval,
        replace=True,
    )

    logging.debug(OmegaConf.to_yaml(cfg, resolve=True))

    jax.config.update("jax_platform_name", cfg.jax.platform_name)
    logging.debug("jax devices: ", jax.devices())

    # Set matplotlib backend to Agg when running on cluster
    matplotlib.use("Agg")

    # Initialise logging
    output_dir = Path(HydraConfig.get().run.dir).absolute()

    wandb.require("core")
    run = wandb.init(
        dir=output_dir,
        config=OmegaConf.to_container(
            cfg,
            resolve=True,
            throw_on_missing=False,
        ),
        **cfg.wandb,
    )

    model_cls = hydra.utils.instantiate(cfg.model)
    datamodule = hydra.utils.instantiate(cfg.datamodule)

    # Log data info
    wandb.config.update({"output_dir": output_dir})
    wandb.config.update({"data_info": datamodule.get_info()})
    wandb.config.update(
        {"data_std": datamodule.std if hasattr(datamodule, "std") else None}
    )
    wandb.config.update(
        {"data_mean": datamodule.mean if hasattr(datamodule, "mean") else None}
    )

    options = obc.CheckpointManagerOptions(
        max_to_keep=1,
        create=True,
        best_fn=lambda x: float(x["val/mse"]),
        best_mode="min",
    )

    with obc.CheckpointManager(
        directory=Path(output_dir) / "checkpoints",
        options=options,
        item_handlers={"state": obc.PyTreeCheckpointHandler()},
    ) as checkpoint_manager:

        state = train(
            model_cls=model_cls,
            datamodule=datamodule,
            cfg=cfg,
            checkpoint_manager=checkpoint_manager,
        )

        checkpoint_manager.wait_until_finished()

    logging.info(
        f"Checkpoint best step {checkpoint_manager.best_step()}, number of steps: {checkpoint_manager.all_steps()}"
    )

    # Save model to wandb
    artifact = wandb.Artifact(
        name=f"checkpoints_{wandb.run.id}",
        type="model",
    )
    artifact.add_dir(checkpoint_manager.directory, name="checkpoints")
    run.log_artifact(artifact)

    wandb.finish()
