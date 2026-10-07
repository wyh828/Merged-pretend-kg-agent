# Predictive Agents - Codex Working Agreement

This repository is a long-term undergraduate research project for building and evaluating a self-designed agent that forecasts cross-domain technology trends. The project root is `F:\Predictive agents`.

Chinese explanations are welcome in documentation. File names, directory names, code identifiers, configuration keys, and dataset names must use English.

## 1. Before Making Changes

1. Inspect the complete relevant directory structure before changing code.
2. Read the root `README.md` and the applicable documentation under `Resources/`, `Data/`, and `Attempt/`.
3. For code changes, read the relevant modules and trace their callers, inputs, outputs, configuration, and data flow before editing.
4. Summarize the current architecture, the proposed change, affected files, risks, and verification plan.
5. Ask for user review before architectural changes, new dependencies, new data sources, public interface changes, destructive operations, file moves, or large-scale rewrites.
6. Do not modify files while requirements or the intended architecture are materially unclear.

## 2. Engineering Design Rules

1. Keep data collection, storage, preprocessing, trend scoring, forecasting, and report generation separate.
2. Reuse existing interfaces and utilities when possible. Do not introduce duplicate abstractions without explaining the reason.
3. Frequently changed experiment parameters must be exposed through configuration files, command-line arguments, or environment variables.
4. Do not hard-code model names, API endpoints, prompts, thresholds, time windows, file paths, or data-source settings inside business logic.
5. New functions must have clear inputs, outputs, side effects, failure behavior, and a narrow responsibility.
6. Keep secrets out of source code, documentation, Git history, and example configuration files. Use `.env` locally and update `.env.example` when a new variable is required.
7. Prefer transparent, reproducible, and low-compute methods. Every non-trivial scoring or forecasting decision must be documented.

## 3. Project Organization

- `Resources/`: papers, external research, project descriptions, technical documentation, reading notes, and historical progress.
- `Data/`: crawler results, API data, downloaded data, raw data, intermediate data, processed data, metadata, schemas, and reports.
- `Attempt/`: all code, environment files, experiment configurations, notebooks, tests, scripts, and experiment records.
- `Attempt/Memory_Design/`: memory and historical-information experiments.
- `Attempt/Reasoning_Architecture/`: reasoning and agent-architecture experiments.
- `Attempt/Reproduction/`: reproductions of published or existing experiments.
- `Attempt/Baselines/`: simple baselines and comparison implementations.
- `Attempt/Sandbox/`: temporary exploratory work that is not yet a formal experiment.

Do not mix raw data, processed data, source code, and research notes. Do not overwrite raw data or previous experiment outputs.

## 4. Versioning and Reproducibility

1. Independent experiments, datasets, reports, and generated artifacts use suffixes `_00`, `_01`, `_02`, and so on.
2. The first experimental version is `_00`; later versions must use the next appropriate suffix and must not overwrite earlier versions.
3. Every independent version must have a matching explanation document describing its goal, assumptions, changes, data sources, model and configuration, commands, results, problems, and next steps.
4. Stable project files such as `README.md`, `.gitignore`, `AGENTS.md`, and environment definition files keep stable names. Git records their history.
5. Before a risky or major change, create a Git checkpoint. Commit meaningful, reproducible states rather than every keystroke.
6. Do not claim that an experiment is reproducible unless the code, configuration, data provenance, environment, and run command are recorded.

## 5. Data and Research Integrity

1. Record source URL or API, collection time, query parameters, license or access conditions, schema, and processing steps in metadata.
2. Preserve original data whenever permitted. Store derived data separately and record the transformation from source to derived data.
3. Do not commit API keys, passwords, access tokens, private data, or large generated datasets without explicit approval.
4. Separate observations, measurements, model outputs, assumptions, interpretations, and forecasts in reports.
5. State uncertainty, missing data, selection bias, and known limitations. Do not present an LLM-generated claim as evidence without a traceable source.

## 6. Verification and Reporting

After modifying code:

1. Run the smallest relevant tests or validation scripts.
2. Check formatting, imports, configuration loading, and data paths when applicable.
3. Report changed files, commands executed, results, warnings, unresolved issues, and suggested next steps.
4. If verification could not be run, explain why instead of claiming success.

## 7. User Review and Stop Rule

1. Ask focused questions when a decision would materially change the research direction, architecture, data scope, or evaluation method.
2. Present a plan and affected-file list before a material change that requires review.
3. If the user says `不对`, `停下`, or otherwise indicates disagreement, stop modifying files immediately.
4. After stopping, report what has already changed and wait for revised instructions.

## 8. Communication Style

Use concise Chinese explanations unless English is needed for code, commands, filenames, APIs, or technical terms. Prefer evidence, explicit assumptions, and reproducible commands over unsupported conclusions.

## 9. Function-by-Function Revision Gate

1. Before merging or implementing new functionality, read the complete project source, function interfaces, configuration, callers, data flow, and target plans, including `Resources/plans/PROJECT_PLAN.md`, `Resources/reports/COMPARISON_REPORT.md`, `Resources/plans/MERGE_PLAN.md`, and `Resources/reports/REPORT_OUTLINE.md`.
2. Maintain a function inventory and distinguish syntax/import checks, unit tests, offline integration checks, and external-service validation. Inventory coverage does not mean every function is behaviorally verified.
3. Reproduce one failure, specify the expected interface behavior, make one focused revision, and run its relevant checks before starting the next revision. Stop advancing when a required check fails.
4. Reuse and improve the existing dashboard in `techtrend/viz/`; integrate analysis documents with the dashboard using the same generated artifacts and explicitly identify missing data and unverified results.
5. Record each stage's blockers, merged results, verification commands/results, and subsequent optimization in the current checkout's root `README.md` (`F:\Predictive agents\README.md` on this computer).
6. Do not carry upstream historical benchmark numbers forward as local validation results. Changes to forecast targets or evaluation protocols still require user review.

## 10. GitHub Account and Upload Destination

1. The user requires local project conversations to use the machine's GitHub account `LisaZhao0709`. Use the local Git credential manager and verify the authenticated identity before remote mutations; never print or persist tokens in project files.
2. Do not use a connector authenticated as another account to upload, create repositories, releases, or pull requests for this project.
3. Upload this project's updates to `https://github.com/wyh828/Merged-pretend-kg-agent`, as authorized by the user after granting write access. Preserve the existing fork.
4. Use the original repository remote for uploads. Preserve other remotes, avoid force pushes, and keep data packages in versioned Release attachments with provenance and validation records.
