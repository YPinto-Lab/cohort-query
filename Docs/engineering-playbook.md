# Ask-SLM Working Playbook

This playbook is optimized for fast, high-quality delivery in this repository.

## 1) Change Workflow

1. Define acceptance criteria before coding.
2. Implement in the smallest safe slice.
3. Run targeted validation commands.
4. Commit in focused batches.
5. Run final sanity checks before push.

## 2) Acceptance Criteria Template

Use this block before each change:

- Problem:
- Expected behavior:
- Backward compatibility expectations:
- Validation commands:
- Output artifacts to verify:

Example:

- Problem: `metadata-overview` fails for workspace-native path usage.
- Expected behavior: `--workspace ABX` works without explicit path flags.
- Backward compatibility: legacy `Inputs/<workspace>` usage still works.
- Validation commands: see section 4.
- Artifacts: CSV files under `Workspaces/ABX/results/metadata_overview/`.

## 3) Commit Message Template

Use this exact structure:

```
type(scope): short summary

Why:
- ...

What changed:
- ...

Compatibility:
- ...

Validation:
- <command 1>
- <command 2>
```

### Shell-safe commit message pattern

Avoid shell interpretation issues from backticks by using a file-based commit message:

```bash
cat > /tmp/commit-msg.txt <<'EOF'
type(scope): short summary

Why:
- ...

What changed:
- ...

Compatibility:
- ...

Validation:
- ...
EOF

git commit -F /tmp/commit-msg.txt
```

## 4) Validation Command Matrix

Run only the relevant subset for your change.

### CLI path resolution and workspace defaults

```bash
python askslm.py metadata-overview --workspace ABX
python askslm.py metadata-overview --workspace ABX --inputs-dir Workspaces/ABX/inputs --config-dir Workspaces/ABX/mapping_configs --output-dir Workspaces/ABX/results
```

### Metadata overview artifacts

```bash
python askslm.py metadata-overview --workspace ABX
ls -1 Workspaces/ABX/results/metadata_overview/
```

Expected files:

- `metadata_overview_summary.csv`
- `metadata_overview_projects.csv`
- `metadata_overview_discovered_keys_by_project.csv`
- `metadata_overview_discovered_keys_unique.csv`

### Taxon abundance flows

```bash
python askslm.py taxonomic-abundance --workspace ABX --rank genus --taxon Prevotella
python askslm.py single-taxon-abundance --workspace ABX --taxon Viruses --source-keys day_run host_subject_id_sam
```

### Matrix and diversity

```bash
python askslm.py abundance-matrix --workspace ABX
python askslm.py alpha-diversity --workspace ABX --rank genus
```

### Quick Python diagnostics

```bash
python -m py_compile askslm.py cli.py
```

## 5) Pre-Push Checklist

- [ ] Change is scoped to the requested behavior.
- [ ] Backward compatibility is verified (if applicable).
- [ ] At least one success-path command was executed.
- [ ] Outputs are generated in expected location.
- [ ] Commit message explains Why + What + Compatibility + Validation.
- [ ] Notebook execution noise is either excluded or committed separately.
- [ ] `git status --short` is clean or intentionally dirty.

## 6) Commit Slicing Rules

Prefer separate commits for:

1. Core behavior change.
2. UX/formatting improvements.
3. Documentation updates.
4. Notebook outputs (if needed).

Avoid mixing notebook output deltas with engine/CLI logic unless explicitly required.

## 7) Quality Gates by Change Type

### CLI behavior changes

- Must validate default and explicit-path modes.
- Must verify output path structure.
- Must verify non-zero error messages are informative.

### Metadata reporting changes

- Verify source categories (`from_jattr`, `from_attributes`, `metadata`).
- Verify row counts change as expected.
- Verify top values formatting and truncation rules.

### Notebook changes

- Keep a dedicated setup cell.
- Keep side-effect cells explicit and independently runnable.
- Avoid hidden global state assumptions.

## 8) Suggested Next Test Additions

1. E2E test: workspace-native `--workspace` defaults for all core commands.
2. Unit test: `_resolve_view_input_dir` path resolution behavior.
3. Unit test: top-values adaptive truncation and count formatting.
4. E2E test: metadata fields included in discovered reports.
