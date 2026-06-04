# Ask-SLM

A workbench for reproducible metagenomic analysis. The user works through a web UI, chatting with
an LLM agent that builds and analyzes a study as a workspace of phase scripts — exactly like
`Workspaces/ABX_new`. The toolbox is the `askslm` package plus established libraries
(biom, ete3, scikit-bio, scipy, pandas).

## Install

```bash
pip install -r Docs/requirements.txt
pip install -e .
```
Python 3.12+. The ete3 NCBI database (`~/.etetoolkit/taxa.sqlite`) must be built locally.

## A workspace

A study is a folder of phases handed off through files on disk:
`0_inputs/ → 1_build/feature_table.biom → 2_transform/<exploration>/result/ → 3_analyze/<exploration>/<analysis>/`.

Scaffold with the CLI, never by hand:

```bash
askslm workspace new my_study
askslm transform add my_study no-control_bacteria
askslm analysis add my_study no-control_bacteria braycurtis
```

Every phase script starts `from askslm import workspace` then `ws = workspace.phase(__file__)`.
See `Workspaces/ABX_new` for a complete example and `Docs/feature-table-and-library-palette.html`
for the model.

## Tests

```bash
python -m pytest Tests -q
```
