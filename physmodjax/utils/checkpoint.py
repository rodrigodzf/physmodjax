# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/utils/checkpoint.ipynb.

# %% auto 0
__all__ = ['restore_experiment_state', 'download_ckpt_single_run']

# %% ../../nbs/utils/checkpoint.ipynb 2
from pathlib import Path
from flax.training import train_state
import orbax.checkpoint as obc
import hydra
import jax
from ..scripts.train_rnn import create_train_state
import flax.linen as nn
from omegaconf import OmegaConf
from typing import Tuple
from wandb.apis import public
import wandb

# %% ../../nbs/utils/checkpoint.ipynb 3
def restore_experiment_state(
    run_path: Path,  # Path to the run directory (e.g. "outputs/2024-01-23/22-15-11")
    best: bool = True,  # If True, restore the best checkpoint instead of the latest
    step_to_restore: int = None,  # If not None, restore the checkpoint at this step
    x0_shape: Tuple[int] = (1, 101, 1),  # Shape of the initial condition
    x_shape: Tuple[int] = (1, 1, 101, 1),  # Shape of the input data
    kwargs: dict = {},  # Additional arguments to pass to the model
) -> Tuple[train_state.TrainState, nn.Module, obc.CheckpointManager]:
    """
    Restores the train state from a run.

    Args:
        run_path (Path): Path to the run directory (e.g. "outputs/2024-01-23/22-15-11")

    Returns:
    -------
        train_state.TrainState: The train state of the experiment
        nn.Module: The model used in the experiment
        CheckpointManager: The checkpoint manager
    """

    # Make sure the path is a Path object
    run_path = Path(run_path)

    # These are hardcoded, do not change
    ckpt_path = run_path / "checkpoints"
    config_path = run_path / ".hydra" / "config.yaml"

    options = obc.CheckpointManagerOptions(
        max_to_keep=1,
        create=True,
        best_fn=lambda x: float(x["val/mse"]),
        best_mode="min",
    )
    with obc.CheckpointManager(
        ckpt_path,
        options=options,
        item_handlers={"state": obc.PyTreeCheckpointHandler()},
    ) as checkpoint_manager:

        # Load the config
        cfg = OmegaConf.load(config_path)

        model_cls: nn.Module = hydra.utils.instantiate(cfg.model)
        grad_clip = hydra.utils.instantiate(cfg.gradient_clip)

        # initialise train state
        # try to get this information from the config
        if hasattr(cfg, "data_info"):
            print(f"Using data_info from config: {cfg.data_info}")
            x_shape = [1] + cfg.data_info
        rng = jax.random.PRNGKey(cfg.seed)

        empty_state = create_train_state(
            model_cls(training=False, **kwargs),
            rng=rng,
            x_shape=x_shape,
            num_steps=666,
            learning_rate=cfg.optimiser.learning_rate,
            grad_clip=grad_clip,
            components_to_freeze=cfg.frozen,
            norm=cfg.model.norm,
            schedule_type=cfg.schedule_type,
        )

        step = (
            checkpoint_manager.latest_step()
            if not best
            else checkpoint_manager.best_step()
        )
        step = step_to_restore if step_to_restore is not None else step
        print(f"Restoring checkpoint from step {step}...")
        state = checkpoint_manager.restore(
            step=step,
            args=obc.args.Composite(
                state=obc.args.PyTreeRestore(empty_state),
            ),
        )["state"]

        return state, model_cls(training=False, **kwargs), checkpoint_manager

# %% ../../nbs/utils/checkpoint.ipynb 4
def download_ckpt_single_run(
    run_name: str,
    project: str,
    tmp_dir: Path = Path("/tmp/physmodjax"),
    overwrite: bool = False,
) -> Tuple[Path, OmegaConf]:
    filter_dict = {
        "display_name": run_name,
    }

    if wandb.run is None:
        wandb.init()
        api: public.Api = wandb.Api()

    runs: public.Runs = api.runs(project, filter_dict)

    assert len(runs) > 0, f"No runs found with name {run_name}"
    assert len(runs) == 1, f"More than one run found with name {run_name}"

    run: public.Run = runs[0]
    conf = OmegaConf.create(run.config)

    artifacts: public.RunArtifacts = run.logged_artifacts()

    artifact: wandb.Artifact

    # check if no artifacts
    if len(artifacts) == 0:
        raise ValueError(f"No artifacts found for run {run_name}")

    for artifact in artifacts:
        if artifact.type == "model":
            checkpoint_path = tmp_dir / artifact.name
            if checkpoint_path.exists() and not overwrite:
                print(f"Checkpoint already exists at {checkpoint_path}, skipping")
                return checkpoint_path, conf
            else:
                artifact.download(checkpoint_path)

    # save config next to checkpoint
    conf_path = checkpoint_path / ".hydra" / "config.yaml"
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    OmegaConf.save(conf, conf_path)

    print(f"Downloaded checkpoint to {checkpoint_path}")
    return checkpoint_path, conf
