# Hermes-Agent + AutoAgent Leverage Report For Trading Assistant

Date: 2026-04-22

## Executive Summary

`trading_assistant` already has a stronger domain-specific learning substrate than either reference project in one important sense: it has structured trading events, deterministic routing, outcome measurement, calibration, hypothesis tracking, transfer tracking, parameter search, and a weekly learning cycle tied to actual market data. The repo is not missing "learning features" in the abstract. It is missing a few specific leverage points that would make the existing learning machinery compound faster and more reliably into better trading decisions.

The highest-value conclusion from reading `_references/hermes-agent/`, `_references/autoagent/`, and the current repo is this:

- `AutoAgent` and `Hermes` should not be treated as competing blueprints.
- `AutoAgent` is best used here as an **offline outer loop** that improves the analysis harness itself.
- `Hermes` is best used here as an **online inner loop** that improves how each analysis run recalls and reuses prior evidence.
- The best outcome for this repo is a **hybrid system**: AutoAgent offline, Hermes online.

One correction after a stricter second pass through the code: the repo already has more replay, evaluation, and retrieval infrastructure than the first version of this report gave it credit for. The highest-value opportunities remain the same, but several recommendations are better framed as **extensions of existing foundations** rather than greenfield additions.

The most material opportunities are not "port Hermes wholesale" or "let the system rewrite itself indefinitely." The most material opportunities are:

1. Build a **failure-to-benchmark compiler** that turns measured misses, blocked suggestions, transfer failures, spurious outcomes, and bad predictions into frozen offline evaluation cases.
2. Use those cases to run an **AutoAgent-style harness improvement loop** over prompt assembly, retrieval, validator policy, provider routing, and workflow tuning.
3. Replace broad bulk context loading with a **query-aware decision-memory router** built on learning cards, run search, and outcome-aware retrieval feedback.
4. Make provider/model selection **outcome-conditioned**, not just preference-based or cooldown-based.
5. Adapt Hermes skill generation into **controlled trading playbook generation**, not generic autonomous code or skill sprawl.

If implemented well, these five changes have a realistic path to improving:

- suggestion precision
- prediction calibration
- transfer proposal quality
- repeatability of high-quality analysis
- speed at which the system stops repeating known bad ideas
- eventual live trading performance through better upstream decisions

## Scope And Evidence

This report is based on direct reading of:

### Reference projects

- `_references/autoagent/README.md`
- `_references/autoagent/program.md`
- `_references/autoagent/agent.py`
- `_references/autoagent/agent-claude.py`
- `_references/hermes-agent/agent/prompt_builder.py`
- `_references/hermes-agent/agent/memory_manager.py`
- `_references/hermes-agent/agent/skill_commands.py`
- `_references/hermes-agent/agent/skill_utils.py`
- `_references/hermes-agent/tools/memory_tool.py`
- `_references/hermes-agent/tools/session_search_tool.py`
- `_references/hermes-agent/tools/skill_manager_tool.py`
- `_references/hermes-agent/website/docs/user-guide/features/memory.md`
- `_references/hermes-agent/website/docs/user-guide/features/skills.md`
- `_references/hermes-agent/website/docs/guides/work-with-skills.md`
- `_references/hermes-agent/website/docs/developer-guide/creating-skills.md`

### Current repo

- `analysis/context_builder.py`
- `analysis/prompt_assembler.py`
- `analysis/weekly_prompt_assembler.py`
- `analysis/outcome_reasoning_prompt.py`
- `analysis/response_validator.py`
- `orchestrator/agent_runner.py`
- `orchestrator/invocation_builder.py`
- `orchestrator/agent_preferences.py`
- `orchestrator/provider_cooldown.py`
- `orchestrator/run_index.py`
- `orchestrator/session_store.py`
- `orchestrator/app.py`
- `orchestrator/handlers.py`
- `skills/learning_cycle.py`
- `skills/learning_card_store.py`
- `skills/learning_ledger.py`
- `skills/retrospective_builder.py`
- `skills/suggestion_tracker.py`
- `skills/auto_outcome_measurer.py`
- `skills/forecast_tracker.py`
- `skills/prediction_tracker.py`
- `skills/hypothesis_library.py`
- `skills/transfer_proposal_builder.py`
- `skills/autonomous_pipeline.py`
- `skills/parameter_searcher.py`
- `skills/suggestion_backtester.py`

I also checked the current internal assessments under `docs/`, especially the recent Hermes-port and learning-loop audits, to avoid re-reporting already-implemented work as if it were still missing.

## The Two Reference Families

The user's distinction between `AutoAgent` and `Hermes` is correct and important.

### 1. AutoAgent

`AutoAgent` is a mechanism for improving the **agent harness itself**. Its core pattern is:

1. define the intended system behavior in `program.md`
2. let the agent edit the harness or supporting scripts
3. run an evaluation suite
4. compare against a baseline
5. keep or discard the change
6. repeat

This is not primarily a runtime memory system. It is much closer to benchmark-driven harness optimization.

The most valuable AutoAgent ideas for this repo are:

- explicit benchmark suites
- baseline-vs-candidate scoring
- keep/discard discipline
- improvement of the harness rather than the trading logic itself
- optimization of prompts, scripts, routing, and workflow mechanics based on evidence

### 2. Hermes-Agent

`Hermes` is primarily about **runtime learning and memory reuse**. Its most valuable ideas are:

- bounded persistent memory for durable facts
- searchable conversation/session history
- agent-managed skills and patches
- continuous memory maintenance
- continuous skill maintenance
- safety scanning for generated skills

Its goal is not to produce a frozen improved harness. Its goal is to make the agent behave more intelligently the longer it is used.

The most valuable Hermes ideas for this repo are:

- better task-aware retrieval
- better recall of prior failures and successful investigation paths
- converting non-trivial repeated procedures into reusable playbooks
- guarding generated procedural knowledge so it does not become a liability

## Current State Of Trading Assistant

The repo is already far beyond a simple "LLM writes reports" system.

### What is already strong

- The repo has a real suggestion lifecycle: `SuggestionTracker`, outcome measurement, deployment states, and retrospective synthesis.
- It already measures consequences: `AutoOutcomeMeasurer`, `ForecastTracker`, `PredictionTracker`, transfer outcome measurement, recalibrations, and spurious outcome handling.
- It already has an autonomous learning cadence: `LearningCycle`, weekly retrospectives, category scoring, experiment selection, and learning ledgers.
- It already has memory primitives: `LearningCardStore`, structured findings, `RunIndex`, prompt-side learning-card injection, and run directories that persist prompt-side artifacts and outputs.
- It already has deterministic validation pressure: `ResponseValidator`, category scorecards, calibration adjustments, and portfolio guardrails.
- It already has an inner optimization loop for parameter proposals: `ParameterSearcher`, `BacktestSimulator`, robustness testing, approval routing, and experiment routing.
- It already has several replay/evaluation components below the whole-harness level: `SuggestionValidator`, `CounterfactualSimulator`, `BacktestSimulator`, `ExperimentManager`, structural experiment evaluation, and `LearningLedger` as a `results.tsv`-style weekly log.
- It already has multi-provider plumbing: `AgentPreferencesManager`, fallback chains, workflow tuning, and cooldown tracking.

### What is already Hermes-like

Several Hermes-inspired capabilities are already present:

- prompt assembly now injects instructions, corrections, skill context, and learning cards through `InvocationBuilder.build_full_prompt()`
- structured learning memories exist as `LearningCard`s
- searchable run memory exists in `RunIndex`
- workflow-aware context priorities, adaptive budget expansion, and a context-budget manifest already exist in `ContextBuilder`
- learning-card retrieval is bot-aware, workflow-aware, and records `retrieval_count`
- outcome reasoning and learning writes are already part of scheduled operations

This matters because it changes the recommendation. The repo does **not** need a naive "port Hermes" project. It needs targeted tightening of the parts that directly improve decision quality.

### Second-pass corrections

The first version of this report understated several implemented capabilities.

- The learning-card layer is more complete than implied. `LearningCardStore.ingest_from_existing()` already ingests `transfer_outcomes.jsonl`, `retrospective_synthesis.jsonl`, outcome reasoning, recalibrations, spurious outcomes, and expands `validation_log.jsonl` into individual cards instead of only handling corrections and outcomes.
- The context layer is more advanced than "static bulk loading" alone. `ContextBuilder.base_package()` already has workflow-specific priority orders, adaptive item-budget expansion, optional token budgeting, a `_context_budget_manifest`, and bot-aware learning-card retrieval with `_learning_card_ids` in metadata.
- The repo already has several evaluation primitives that should be treated as building blocks for an AutoAgent-style outer loop, not ignored. Those include `SuggestionValidator` backtest replay, `CounterfactualSimulator`, `BacktestSimulator`, `ParameterSearcher`, `ExperimentManager`, structural experiment evaluation in `orchestrator/app.py`, and `LearningLedger` as an autoresearch-style weekly ledger.
- The replay/history substrate is stronger than just session summaries. `AgentRunner._write_run_files()` persists prompt-side data, instructions, corrections, skill context, and `metadata.json` into each run directory, while `RunIndex` builds FTS over responses, instructions, validator notes, and structured output. The weaker part is not storage; it is the absence of a mature retrieval and replay loop using those assets.

### What is still missing or underpowered

Despite the strong substrate, several high-value gaps remain:

1. There is no generalized AutoAgent-style **offline evaluation suite for the whole analysis harness**. The repo has many workflow-specific evaluators, but not a unified benchmark-and-compare loop for prompts, retrieval, routing, and validators.
2. There is no systematic **compiler from failures into benchmark cases**.
3. `ContextBuilder` still behaves mostly like **broad structured loading plus prioritization/pruning**, not a precise decision-memory router that ranks all evidence sources against the current problem.
4. `RunIndex` and run snapshots exist, but there is not yet a strong **trajectory replay and similar-case retrieval loop** on top of them.
5. Provider selection is still **configured**, not **learned from downstream quality and outcomes**.
6. The repo has memory cards and retrieval counters, but not yet a strong **feedback loop telling the retrieval layer which memories actually helped**. `record_feedback()` exists in the schema layer, but is not operationalized in the runtime paths.
7. There is no controlled equivalent of Hermes autonomous skill generation for **trading investigation playbooks**.

These are precisely the areas where the references still have leverage.

## High-Value Leverage Opportunities

The table below ranks the highest-value imports from the references by expected impact on the repo's actual goal: improved trading performance over time through better upstream analysis and better learning.

| Priority | Opportunity | Reference family | Expected value | Why it matters |
|---|---|---|---|---|
| 1 | Failure-to-benchmark compiler | AutoAgent + Hermes | Very high | Converts scattered learning signals into a reusable harness-improvement asset |
| 2 | Offline harness improvement loop | AutoAgent | Very high | Improves the analysis system itself with evidence, not opinion |
| 3 | Query-aware decision-memory router | Hermes | Very high | Reduces prompt noise and surfaces the most decision-relevant prior evidence |
| 4 | Outcome-conditioned provider/model routing | AutoAgent-style evaluation | High | Lets the repo learn which runtime works best for which workflow and context |
| 5 | Controlled playbook generation | Hermes adapted | High | Makes repeated complex investigations more consistent without unsafe self-modification |
| 6 | Run/session trajectory search and replay | Hermes | Medium-high | Gives the system access to prior similar cases and debugging evidence |
| 7 | Bounded hot memory for operator/project facts | Hermes | Medium-low | Useful ergonomically, but lower direct trading impact than the items above |

## Recommendation 1: Build A Failure-To-Benchmark Compiler

This is the single highest-value bridge between the two reference families.

### Core idea

Take the repo's existing negative and positive learning artifacts and compile them into a frozen benchmark corpus of "cases the harness should learn to handle better."

### Why this is the highest-value move

Right now, the repo already records a lot of valuable evidence:

- blocked suggestions in `validation_log.jsonl`
- measured outcomes in `outcomes.jsonl`
- outcome reasonings in `outcome_reasonings.jsonl`
- recalibrations in `recalibrations.jsonl`
- retrospective keep/discard decisions
- transfer outcomes
- prediction verdicts
- search approve/discard signals

The important nuance after re-review is that the repo already has several near-neighbor components:

- `RetrospectiveBuilder` already emits keep/discard synthesis
- `LearningLedger` already functions like a weekly `results.tsv`
- `SuggestionValidator`, `BacktestSimulator`, and `CounterfactualSimulator` already do replay-style evaluation
- `ExperimentManager` and structural experiment resolution already do controlled comparison at narrower scopes

But those artifacts and evaluators mostly stay attached to their local workflows. They do not yet become a disciplined offline test set for improving the harness itself.

That is a missed opportunity, because in this repo:

- tasks are structured
- data is archived
- downstream outcomes exist
- several workflows already have programmatic quality signals

That makes this project **unusually well suited** to an AutoAgent-style evaluation loop compared with most agent systems.

### What to compile into benchmark cases

Each benchmark case should capture:

- workflow: daily analysis, weekly analysis, triage, outcome reasoning, transfer proposal, structural proposal review
- input snapshot: exact prompt package inputs, relevant curated files, and retrieved memory
- expected properties: not a single gold answer, but measurable correctness constraints
- downstream evidence: blocked patterns, actual outcomes, later retrospective verdict, calibration truth, or transfer result
- scoring hooks: functions that can grade the run against the known later evidence

### Best sources for case generation

The best initial sources are:

- negative outcomes with good measurement quality
- spurious outcomes
- repeated validator blocks
- transfer failures
- predictions with clear calibration misses
- retrospective "what_failed" and "discard" entries

Positive cases should also be included:

- high-quality positive outcomes
- successful transfer cases
- strong retrospective "what_worked" cases
- stable high-value patterns that later generalized

### Suggested implementation shape

Add a new compiler layer, likely with artifacts such as:

- `schemas/benchmark_case.py`
- `skills/benchmark_case_compiler.py`
- `memory/findings/benchmark_cases.jsonl`
- `memory/findings/harness_eval_results.jsonl`

The compiler should run on a schedule, probably after outcome measurement and weekly retrospectives.

### Why this improves trading performance

It improves trading performance indirectly but materially by improving the upstream system that decides:

- what problems matter
- which proposals are plausible
- which categories to distrust
- how to calibrate confidence
- which prior lessons should be surfaced

Without a benchmark compiler, the learning loop stays mostly local and narrative. With it, the loop becomes cumulative and testable.

## Recommendation 2: Add An AutoAgent-Style Offline Harness Improvement Loop

Once benchmark cases exist, the next highest-value step is an explicit harness-optimization loop.

### What should be improved

The target should be the **analysis harness**, not the live trading bots and not unrestricted repo mutation.

The first candidates to optimize are:

- prompt assembly structure
- context retrieval strategy
- validator policy thresholds and heuristics
- provider/model choice by workflow
- workflow tuning such as turn limits or allowed tools
- report decomposition rules and required evidence formatting

### Why this is a natural fit for this repo

The repo already has many evaluation primitives that can be turned into harness scores:

- whether bad suggestions were blocked
- whether good suggestions were proposed at all
- whether predictions were calibrated
- whether the run matched later outcomes and retrospective verdicts
- whether transfer ideas generalized or failed
- whether the parser/validator path produced high-quality structured outputs

This should be treated as an extension of what already exists, not a greenfield evaluation project. The repo is missing the **unified harness-level comparison loop**, not the raw ingredients.

### What the score should optimize

Do not optimize for "reports that read better." Optimize for downstream proxies tied to the repo's actual objective.

A first-pass composite harness score should heavily weight:

- precision of approved suggestions
- recall on later-confirmed high-value issues
- prediction calibration quality
- reduction in repeated blocked suggestions
- transfer proposal precision
- structured-output reliability

It should lightly weight:

- latency
- token cost
- prompt length

Those matter, but they are secondary to decision quality.

### Keep/discard discipline

Every harness change should be logged and compared against the current baseline. A candidate should only be retained if it is:

- meaningfully better on the benchmark suite
- or equivalently good but materially simpler, cheaper, or safer

This keep/discard discipline is the most valuable AutoAgent idea in the references.

### Where it should plug in

The most natural implementation points are:

- `skills/learning_cycle.py` for scheduled evaluation summaries
- `analysis/*_prompt_assembler.py` for candidate prompt variants
- `analysis/response_validator.py` for validator-policy variants
- `orchestrator/agent_preferences.py` for routing variants
- `orchestrator/run_index.py` and the new benchmark corpus for replay

### Important constraint

Do **not** let this loop autonomously mutate live trading logic or approval gates.

The correct target is:

- prompting
- retrieval
- routing
- validation
- orchestration heuristics

That is where AutoAgent has high upside and acceptable risk in this system.

## Recommendation 3: Replace Broad Context Loading With A Query-Aware Decision-Memory Router

This is the most valuable Hermes-style import.

### Current state

`ContextBuilder.base_package()` already loads an impressive range of artifacts, and `LearningCardStore.ranked_for_prompt()` is a good foundation. But the current pattern is still largely:

- load many structured sources
- apply recency windows and budgets
- inject ranked cards on top

That is stronger than a naive system, but it is still not the same thing as precise decision-memory retrieval.

### Why this matters

In a trading-analysis context, broad loading has two costs:

- relevant evidence gets diluted by marginally related context
- the model is more likely to average across patterns instead of locking onto the most decision-relevant precedent

This is exactly where Hermes feels "smarter": not because it knows more facts in total, but because it surfaces the right prior procedure or lesson at the moment it matters.

### What the router should retrieve on

The retrieval query should be conditioned on:

- workflow
- bot
- strategy family
- regime
- suggestion category
- failure mode taxonomy
- metric under discussion
- recent direction of performance

The memory sources to rank together should include:

- learning cards
- retrospective synthesis
- transfer outcomes
- outcome reasonings
- recalibrations
- validator blocks
- similar historical runs from `RunIndex`
- targeted session summaries or richer run traces

### What is missing today

`LearningCard.relevance_score()` is useful but still simple. It uses:

- recency
- impact magnitude
- confidence
- retrieval feedback
- bot/workflow/tag match

That is a good start, but it is not yet a full decision router. It lacks richer notions of:

- regime match
- category match
- current problem type
- similar historical failure trajectories
- downstream helpfulness by workflow and outcome

### High-value refinement

The next step should not be embeddings-first. The next step should be **better structured retrieval keys** tied to the repo's own schemas.

For example:

- tag validator-block cards by blocked category and reason
- tag outcome reasonings by mechanism and transferability
- tag retrospective items by keep/discard class and affected subsystem
- tag transfer outcomes by source bot, target bot, and regime match
- tag runs by structured suggestion categories, predictions, validator results, and later measured outcomes

### Retrieval feedback loop

The `LearningCard` schema already supports:

- `retrieval_count`
- `helpful_count`
- `harmful_count`

That should be activated into a real loop. Right now, the runtime records retrievals, but not downstream helpfulness or harmfulness. After each run, the system should estimate which retrieved items were actually useful and which were noise or correlated with bad outputs. Even imperfect feedback will make the memory layer compound over time.

### Why this improves trading performance

Better retrieval improves the quality of every high-level judgment:

- which failure modes the model notices
- which proposal categories it trusts
- whether it repeats bad ideas
- whether it overgeneralizes from the wrong precedent

This is one of the few changes that can raise the quality of nearly every analysis run without changing the trading bots themselves.

## Recommendation 4: Make Provider And Model Selection Outcome-Conditioned

This is a high-value opportunity because the repo already has the machinery to support it.

### Current state

The current provider system is useful but static in spirit:

- explicit defaults
- workflow overrides
- fallback chains
- cooldown tracking

That is operationally solid, but it does not yet answer the most valuable question:

> Which provider/model combination actually produces better downstream outcomes for each workflow and context?

### What to learn from

The routing model should learn from:

- parse success and structured-output completeness
- validator blocked rate
- later outcome quality of approved suggestions
- calibration quality of predictions
- transfer proposal success
- cost and latency as secondary constraints

### What to route on

The initial routing dimensions should be:

- workflow
- bot or bot family
- category mix
- macro regime
- task complexity class

This does not need to start as a complex bandit or reinforcement learner. A simple scored routing table is enough for the first version.

### Where to integrate

Likely additions:

- new scored route registry under `memory/findings/`
- routing scorer layered on top of `AgentPreferencesManager`
- periodic recomputation from `RunIndex`, outcomes, validation logs, and retrospectives

### Why this is high value

This repo already supports multiple runtimes. If one runtime is better at:

- weekly synthesis
- triage
- structural proposals
- outcome reasoning

then failing to learn that mapping leaves value on the table every single day.

## Recommendation 5: Adapt Hermes Skill Generation Into Controlled Trading Playbook Generation

This is valuable, but only in a constrained form.

### What not to copy directly

Do not give the system broad authority to create arbitrary new skills or patch anything it wants in the codebase.

That would create too much sprawl, too much maintenance burden, and too much safety risk for a trading-adjacent system.

### What to adapt instead

Adapt the Hermes idea into generated **playbooks** or **investigation recipes** for repeated complex analysis tasks.

Examples:

- "investigate repeated slippage spikes"
- "evaluate whether a transfer proposal is real or regime-specific"
- "triage a recurring validator-block pattern"
- "review a negative outcome for spurious causality"
- "assess whether a category should be suppressed or only confidence-damped"

These playbooks should live in a tightly controlled area such as:

- `memory/skills/generated/`
- or a new `memory/playbooks/`

### When a playbook should be generated or patched

Trigger on evidence, not on raw turn count.

Good triggers would be:

- repeated multi-step investigations that converge on a stable procedure
- repeated validator blocks with the same root cause
- repeated positive outcomes from a consistent investigation pattern
- weekly retrospectives showing the same lesson several times

This is a better fit for this repo than Hermes's generic "after N steps" trigger, because the runs here are stateless and task-bounded.

### Guardrails

Every generated playbook should pass a safety scan similar in spirit to Hermes's skill guard, but adapted for this domain.

The guard should reject or quarantine playbooks that:

- recommend bypassing approval gates
- recommend changing live trading logic directly
- encode brittle one-off hacks
- contradict policy files
- cite no evidence or no provenance

### Why this helps

A good playbook layer improves repeatability in the exact areas where trading-analysis quality often drifts:

- causal review
- experimental discipline
- transfer skepticism
- validator reasoning
- diagnostic completeness

This can materially improve the learning loop without giving the system unsafe autonomy.

## Recommendation 6: Build A Richer Trajectory Search And Replay Layer

This is the other strong Hermes-like opportunity, though it ranks below the first five.

### Current state

The repo already has:

- `RunIndex` with FTS over responses, instructions, validator notes, and structured output
- `SessionStore` with compact recent-session summaries
- run directories that persist prompt-side JSON, instructions, system prompt, corrections, skill context, responses, and metadata

That is a meaningful base.

### What is still missing

The repo does not yet fully exploit those assets for:

- similar-case retrieval during analysis
- harness debugging after a bad run
- benchmark construction
- provider comparison by task archetype
- replaying prior trajectories against current harness variants

### Recommended direction

Treat `RunIndex` as the nucleus of a replay/search system:

- enrich run metadata with more structured tags
- connect runs to later outcomes and retrospective verdicts
- allow searches like "find daily analyses for bot X in similar regime that later produced negative outcomes"
- allow searches like "find runs where category Y was proposed and later blocked or discarded"

The gap here is mainly usage, not capture. The repo already stores much of what a replay system needs; it just does not yet feed that back into prompt assembly, harness evaluation, or provider routing.

This makes the system less forgetful in a way that directly helps both the Hermes-style inner loop and the AutoAgent-style outer loop.

## What Not To Port Directly

Some parts of the references are lower value or actively risky in this repo.

### 1. Do not port AutoAgent as an infinite self-editing live loop

The repo should not continuously rewrite itself against live workflows without a tightly scoped target and a benchmark gate.

Use AutoAgent ideas for:

- offline harness optimization
- benchmark discipline
- keep/discard logging

Do not use them for:

- autonomous mutation of live trading logic
- autonomous mutation of approval gates
- unrestricted repo self-editing

### 2. Do not treat Hermes user-preference memory as a top trading priority

Hermes's `user.md` and `memory.md` patterns are useful for agent ergonomics, but they are not the highest-value path to better trading performance here.

They are worth having eventually for:

- operator preferences
- notification style
- workflow preferences

But they should stay below:

- benchmark cases
- retrieval quality
- provider routing
- playbook generation

### 3. Do not add a generic semantic memory layer first

The repo already has rich structured artifacts. The next value is not a vector database for everything. The next value is:

- better labels
- better retrieval keys
- better outcome linkage
- better evaluation discipline

Semantic retrieval can be added later if the structured router proves insufficient.

### 4. Do not let autonomous skill generation create procedural debt

Skills or playbooks that are not evidence-backed, maintained, and guarded become liabilities fast. Hermes is correct about that.

This repo should require generated playbooks to be:

- evidence-linked
- source-tagged
- reviewable
- easy to supersede or deactivate

## Recommended Target Architecture

The best hybrid architecture for this repo looks like this:

```text
Observed outcomes / validator blocks / retrospectives / transfer results
    -> BenchmarkCaseCompiler
    -> benchmark_cases.jsonl
    -> HarnessEvalRunner
    -> keep/discard results for prompt/retrieval/routing variants

Observed outcomes / reflective lessons / stable successful procedures
    -> LearningCardStore + PlaybookReviewer
    -> ranked memory + guarded playbooks
    -> injected into future runs through a decision-memory router

Historical runs + structured outputs + later outcomes
    -> RunIndex + replay search
    -> similar-case retrieval and offline harness evaluation
```

This architecture maps the references cleanly:

- AutoAgent improves the harness offline.
- Hermes improves recall and procedural reuse online.
- The existing repo provides the domain-specific evaluation and outcome substrate that both approaches need.

## Suggested Implementation Roadmap

### Phase 1: Highest-confidence, highest-value foundations

1. Add benchmark case schemas and a benchmark compiler.
2. Extend run metadata and run-to-outcome linkage.
3. Add a first outcome-aware retrieval router in front of broad context injection.
4. Start recording retrieval helpfulness and harmfulness.

Expected result:

- the repo begins turning learning artifacts into reusable evaluation and retrieval assets

### Phase 2: Harness optimization

1. Build an offline harness evaluator that replays benchmark cases.
2. Compare prompt/retrieval/validator/provider variants against baseline.
3. Start logging keep/discard results in a dedicated harness-results ledger.

Expected result:

- the repo can improve the analysis system itself without touching live trading logic

### Phase 3: Controlled procedural learning

1. Add a playbook reviewer that proposes new or updated playbooks from repeated successful investigations.
2. Add a guard for generated playbooks.
3. Inject playbooks on demand through the same router used for learning cards.

Expected result:

- repeated hard analysis tasks become more stable and less dependent on the model rediscovering the method

### Phase 4: Outcome-conditioned runtime selection

1. Score provider/model performance by workflow and context.
2. Route with learned priors plus fallback safety.
3. Recompute scores periodically and keep cost as a secondary constraint.

Expected result:

- better analysis quality at the same or lower runtime cost

## Concrete Success Metrics

These changes should be judged by trading-aligned metrics, not by whether the docs look more sophisticated.

### Primary metrics

- positive outcome rate of deployed suggestions
- average measured effect size of deployed suggestions
- reduction in repeated blocked or later-discarded suggestions
- prediction calibration improvement
- transfer proposal precision
- share of weekly retrospectives that identify genuinely new, useful lessons

### Secondary metrics

- structured-output success rate
- validator block rate by category
- retrieval hit quality and helpfulness ratio
- provider quality by workflow
- time-to-suppress a repeatedly bad proposal class
- context size and token efficiency

## Bottom Line

The best parts of `AutoAgent` and `Hermes` can materially improve `trading_assistant`, but only if they are imported in the right role.

The correct synthesis is:

- use `AutoAgent` to improve the harness offline through benchmarked keep/discard loops
- use `Hermes` to improve online recall through query-aware memory, search, and guarded playbook generation
- do not port either project wholesale

If only one new initiative is funded, it should be:

**Build a failure-to-benchmark compiler and use it to drive offline harness optimization.**

That is the highest-leverage move because it converts the repo's existing learning artifacts from "useful context" into "compounding evidence for system improvement."

If two initiatives are funded, the second should be:

**Build a decision-memory router that retrieves the most relevant prior evidence and playbooks for each analysis task.**

Those two together are the most credible path from the current strong-but-partially-integrated learning system to a system that more reliably improves trading performance over time.
