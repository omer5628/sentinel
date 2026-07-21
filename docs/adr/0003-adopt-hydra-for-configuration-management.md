# 3. Adopt Hydra for Configuration Management

## Status
Accepted

## Context
Project Sentinel requires reproducible and traceable training experiments. Hardcoded parameters such as batch size, learning rate, model type, dataset, and number of epochs make experiments difficult to reproduce and compare.

A dependency lock file records which packages were installed, but it does not record which runtime parameters were used to train a model. We need a structured configuration system that supports external configuration files, command-line overrides, and reusable configuration groups.

## Decision
We will adopt `Hydra` as the configuration management framework for model training and evaluation workflows.

Configuration files will be stored under the `conf/` directory. Training entry points will use the `@hydra.main` decorator and print the resolved configuration at startup.

Hydra will be installed and managed exclusively through `uv`:

```bash
uv add hydra-core