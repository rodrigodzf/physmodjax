"""Script to generate the dataset for the project."""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/scripts/dataset_generation.ipynb.

# %% auto 0
__all__ = ['generate_run', 'generate_dataset', 'convert_to_single_file']

# %% ../../nbs/scripts/dataset_generation.ipynb 2
from pathlib import Path
from omegaconf import DictConfig, OmegaConf, open_dict
import hydra
import numpy as np
from tqdm import tqdm
from typing import Optional, List, Union
from physmodjax.solver.generator import (
    generate_initial_condition,
    Generator,
    Gaussian,
    SineMode,
)
import os
import logging

# %% ../../nbs/scripts/dataset_generation.ipynb 3
def generate_run(
    rng: np.random.Generator,
    solver,
    generator: Generator = Gaussian(),
    **ic_params,
):
    u0, v0 = generate_initial_condition(
        rng,
        generator,
        **ic_params,
    )
    # solve
    return solver.solve(u0=u0, v0=v0)


@hydra.main(version_base=None, config_path="../../conf", config_name="generate_data")
def generate_dataset(
    cfg: DictConfig,
):
    print(OmegaConf.to_yaml(cfg, resolve=True))
    ic_params = getattr(cfg, "ic_params", {})
    # print(ic_params)

    solver = hydra.utils.instantiate(cfg.solver)
    generator = hydra.utils.instantiate(cfg.ic_generator)

    # hydra multirun flag
    hydra_multirun = (
        hydra.core.hydra_config.HydraConfig.get().mode == hydra.types.RunMode.MULTIRUN
    )

    number_ics = cfg.number_ics
    # If the generator is SineMode, we need to make sure that we are not generating modes with a k higher
    # than the number of grid points in the solver minus 2. Otherwise, we will get aliasing. Print warning about changing number_ics.
    if isinstance(generator, SineMode):
        number_ics = min(number_ics, solver.n_max_modes)
        if number_ics < cfg.number_ics:
            print(
                f"Warning: number_ics was changed from {cfg.number_ics} to {number_ics} to avoid modes not used in the solver when using SineMode."
            )

    rng = np.random.default_rng(cfg.seed)

    # To preserve backwards compatibility, we need to check if the config has ic_type or ic_max_amplitude at the base level
    # and set ic_params accordingly. Before, ic_max_amplitude being a float was assumed to indicate randomized amplitude.
    if hasattr(cfg, "ic_type") and ("ic_type" not in ic_params):
        ic_params["ic_type"] = cfg.ic_type
    if hasattr(cfg, "ic_max_amplitude"):
        ic_params["ic_max_amplitude"] = cfg.ic_max_amplitude
        ic_params["ic_amplitude_random"] = True

    # If hydra mode is RUN print the mode
    if hydra_multirun:
        logger = logging.getLogger("tqdm_logger")
        logger.setLevel(logging.INFO)
        logger.info(OmegaConf.to_yaml(cfg))
        progress_bar = tqdm(range(1, number_ics + 1), file=open(os.devnull, "w"))
    else:
        progress_bar = tqdm(range(1, number_ics + 1))
    # create initial conditions
    for i in progress_bar:
        if isinstance(generator, SineMode):
            with open_dict(ic_params):
                ic_params["ic_sine_k"] = int(i)
        t, u, v = generate_run(rng, solver, generator, **ic_params)

        ic = np.stack([u, v], axis=-1)

        # save
        file_name = f"ic_{i:05d}.npy"
        progress_bar.set_postfix({"Saved file": f"{file_name}"})

        if hydra_multirun:
            logger.info(str(progress_bar))

        # The convention for the data is:
        # (timesteps, grid_points, statevars)
        np.save(Path(file_name), ic)

# %% ../../nbs/scripts/dataset_generation.ipynb 7
from fastcore.script import call_parse

# %% ../../nbs/scripts/dataset_generation.ipynb 8
@call_parse
def convert_to_single_file(
    data_dir: str,  # the directory where the files are
    output_file: str,  # the output file
    target_dtype: str = "np.float32",  # the dtype of the output file
):
    files = list(Path(data_dir).glob("*.npy"))
    files.sort(key=lambda x: x.stem)

    # load the first file to get the shape
    first_file = np.load(files[0])
    shape = (len(files), *first_file.shape)

    # convert the dtype to a numpy dtype
    target_dtype = eval(target_dtype)

    # create a memory-mapped file
    target = np.lib.format.open_memmap(
        output_file, mode="w+", shape=shape, dtype=target_dtype
    )

    for i, f in enumerate(files):
        target[i] = np.load(f).astype(target_dtype)

    print(
        f"Saved to {output_file}, has a size of {target.nbytes / 1e9} GB, and shape {target.shape}"
    )
