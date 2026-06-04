"""Native monthly runner CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_assistant_backtest.artifact_writer import ArtifactWriter
from trading_assistant_backtest.auto.candidate_workspace import CandidateWorkspaceManager
from trading_assistant_backtest.auto.greedy_optimizer import (
    best_passing_candidate,
)
from trading_assistant_backtest.auto.greedy_optimizer import (
    no_adoption_reason as phase_no_adoption_reason,
)
from trading_assistant_backtest.auto.fold_scoring import (
    fold_candidate_rows,
    fold_score_matrix,
    score_candidate_on_folds,
)
from trading_assistant_backtest.auto.phase_runner import run_phase
from trading_assistant_backtest.auto.types import CandidateEvaluation, PhaseSpec
from trading_assistant_backtest.contract_loader import validate_manifest_file
from trading_assistant_backtest.contract_models import (
    DECISION_PARITY_DIMENSIONS,
    PHASED_AUTO_RUNNER_CONTRACT_VERSION,
    SMOKE_REPAIR_RUNNER_CONTRACT_VERSION,
    BacktestArtifactIndex,
    CandidateAttemptRecord,
    CandidateAttemptState,
    ConfirmatoryRerank,
    DataBundleManifest,
    DecisionParityCheck,
    DecisionParityReport,
    DecisionParityStatus,
    MonthlyCandidateSource,
    MonthlyRunManifest,
    MonthlyRunMode,
    OptimizerExperimentPlan,
    OptimizerStage,
    RoundManifestRecord,
    RoundsManifest,
)
from trading_assistant_backtest.data.bundle_loader import (
    coverage_payload,
    data_bundle_errors,
    load_data_bundle,
)
from trading_assistant_backtest.manifest_loader import load_manifest
from trading_assistant_backtest.observability import runner_event
from trading_assistant_backtest.paths import package_root
from trading_assistant_backtest.planner.deterministic_fallback import build_deterministic_plan
from trading_assistant_backtest.repair.ablation import build_ablation_matrix
from trading_assistant_backtest.repair.failure_analysis import analyze_failure
from trading_assistant_backtest.repair.trigger import evaluate_selection_oos_repair_trigger
from trading_assistant_backtest.replay.parity import insufficient_decision_parity_report
from trading_assistant_backtest.replay.types import ReplayResult
from trading_assistant_backtest.replay.windows import (
    build_manifest_folds,
    resolve_in_sample_window,
    resolve_selection_oos_window,
)
from trading_assistant_backtest.scoring.gates import pass_gate_report
from trading_assistant_backtest.strategies.contracts import (
    load_strategy_plugin_contract,
    strategy_plugin_errors,
)
from trading_assistant_backtest.strategies.crypto.breakout import (
    DECISION_API_VERSION as CRYPTO_BREAKOUT_DECISION_API_VERSION,
)
from trading_assistant_backtest.strategies.crypto.breakout import (
    PLUGIN_ID as CRYPTO_BREAKOUT_PLUGIN_ID,
)
from trading_assistant_backtest.strategies.crypto.breakout import (
    build_crypto_breakout_decision_parity_report,
)
from trading_assistant_backtest.strategies.crypto.momentum import (
    DECISION_API_VERSION as CRYPTO_MOMENTUM_DECISION_API_VERSION,
)
from trading_assistant_backtest.strategies.crypto.momentum import (
    PLUGIN_ID as CRYPTO_MOMENTUM_PLUGIN_ID,
)
from trading_assistant_backtest.strategies.crypto.momentum import (
    build_crypto_momentum_decision_parity_report,
)
from trading_assistant_backtest.strategies.crypto.replay_evaluator import (
    REPLAY_ENGINE_VERSION as CRYPTO_REPLAY_ENGINE_VERSION,
)
from trading_assistant_backtest.strategies.crypto.replay_evaluator import (
    CryptoReplayPlugin,
)
from trading_assistant_backtest.strategies.crypto.trend import (
    DECISION_API_VERSION as CRYPTO_TREND_DECISION_API_VERSION,
)
from trading_assistant_backtest.strategies.crypto.trend import (
    PLUGIN_ID as CRYPTO_TREND_PLUGIN_ID,
)
from trading_assistant_backtest.strategies.crypto.trend import (
    build_crypto_trend_decision_parity_report,
)
from trading_assistant_backtest.strategies.krx.olr_kalcb import (
    DECISION_API_VERSION as K_STOCK_DECISION_API_VERSION,
)
from trading_assistant_backtest.strategies.krx.olr_kalcb import (
    PLUGIN_ID as K_STOCK_PLUGIN_ID,
)
from trading_assistant_backtest.strategies.krx.olr_kalcb import (
    build_k_stock_olr_kalcb_decision_parity_report,
)
from trading_assistant_backtest.strategies.krx.replay_evaluator import KStockReplayPlugin
from trading_assistant_backtest.strategies.trading.equity_replay_evaluator import (
    TradingStockReplayPlugin,
    TradingSwingReplayPlugin,
)
from trading_assistant_backtest.strategies.trading.momentum import (
    DECISION_API_VERSION as TRADING_MOMENTUM_DECISION_API_VERSION,
)
from trading_assistant_backtest.strategies.trading.momentum import (
    PLUGIN_ID as TRADING_MOMENTUM_PLUGIN_ID,
)
from trading_assistant_backtest.strategies.trading.momentum import (
    build_trading_momentum_decision_parity_report,
)
from trading_assistant_backtest.strategies.trading.momentum_replay_evaluator import (
    TradingMomentumReplayPlugin,
)
from trading_assistant_backtest.strategies.trading.stock import (
    DECISION_API_VERSION as TRADING_STOCK_DECISION_API_VERSION,
)
from trading_assistant_backtest.strategies.trading.stock import (
    PLUGIN_ID as TRADING_STOCK_PLUGIN_ID,
)
from trading_assistant_backtest.strategies.trading.stock import (
    build_trading_stock_decision_parity_report,
)
from trading_assistant_backtest.strategies.trading.swing import (
    DECISION_API_VERSION as TRADING_SWING_DECISION_API_VERSION,
)
from trading_assistant_backtest.strategies.trading.swing import (
    PLUGIN_ID as TRADING_SWING_PLUGIN_ID,
)
from trading_assistant_backtest.strategies.trading.swing import (
    build_trading_swing_decision_parity_report,
)

_STRUCTURAL_PARITY_BUILDERS = {
    CRYPTO_TREND_PLUGIN_ID: (
        CRYPTO_TREND_DECISION_API_VERSION,
        build_crypto_trend_decision_parity_report,
    ),
    CRYPTO_MOMENTUM_PLUGIN_ID: (
        CRYPTO_MOMENTUM_DECISION_API_VERSION,
        build_crypto_momentum_decision_parity_report,
    ),
    CRYPTO_BREAKOUT_PLUGIN_ID: (
        CRYPTO_BREAKOUT_DECISION_API_VERSION,
        build_crypto_breakout_decision_parity_report,
    ),
    K_STOCK_PLUGIN_ID: (
        K_STOCK_DECISION_API_VERSION,
        build_k_stock_olr_kalcb_decision_parity_report,
    ),
    TRADING_STOCK_PLUGIN_ID: (
        TRADING_STOCK_DECISION_API_VERSION,
        build_trading_stock_decision_parity_report,
    ),
    TRADING_MOMENTUM_PLUGIN_ID: (
        TRADING_MOMENTUM_DECISION_API_VERSION,
        build_trading_momentum_decision_parity_report,
    ),
    TRADING_SWING_PLUGIN_ID: (
        TRADING_SWING_DECISION_API_VERSION,
        build_trading_swing_decision_parity_report,
    ),
}

_BRIDGE_IDS_BY_SCOPE = {
    "crypto_trader_portfolio": (
        "crypto_trend_v1",
        "crypto_momentum_v1",
        "crypto_breakout_v1",
    ),
    "k_stock_olr_kalcb": ("k_stock_olr_kalcb",),
    "trading_stock_family": ("trading_stock_family",),
    "trading_momentum_family": ("trading_momentum_family",),
    "trading_swing_family": ("trading_swing_family",),
}

_BRIDGE_ID_BY_PLUGIN_ID = {
    CRYPTO_TREND_PLUGIN_ID: "crypto_trend_v1",
    CRYPTO_MOMENTUM_PLUGIN_ID: "crypto_momentum_v1",
    CRYPTO_BREAKOUT_PLUGIN_ID: "crypto_breakout_v1",
    K_STOCK_PLUGIN_ID: "k_stock_olr_kalcb",
    TRADING_STOCK_PLUGIN_ID: "trading_stock_family",
    TRADING_MOMENTUM_PLUGIN_ID: "trading_momentum_family",
    TRADING_SWING_PLUGIN_ID: "trading_swing_family",
}


@dataclass
class ReplayEvaluationContext:
    plugin: Any | None = None
    baseline: Any | None = None
    incumbent: ReplayResult | None = None
    selection_oos_incumbent: ReplayResult | None = None
    diagnostics: dict[str, Any] | None = None
    baseline_score: float = 0.0
    replay_engine_version: str = ""
    replay_backed: bool = False
    reason: str = ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a monthly trading-assistant backtest manifest."
    )
    parser.add_argument("--manifest", required=True, help="Path to run_manifest.json")
    parser.add_argument(
        "--planner-mode",
        choices=["deterministic"],
        default="deterministic",
        help="Experiment planner mode.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate artifacts already emitted under artifact_root.",
    )
    args = parser.parse_args(argv)
    if args.validate_only:
        validation = validate_manifest_file(args.manifest)
        print(json.dumps({"valid": validation.valid, "errors": validation.errors}, indent=2))
        return 0 if validation.valid else 1
    return run_manifest(Path(args.manifest), planner_mode=args.planner_mode)


def run_manifest(manifest_path: Path, *, planner_mode: str = "deterministic") -> int:
    started_at = datetime.now(UTC)
    manifest = load_manifest(manifest_path)
    artifact_root = Path(manifest.artifact_root).resolve()
    writer = ArtifactWriter(manifest, artifact_root)

    bundle = load_data_bundle(manifest)
    bundle_errors = [
        *data_bundle_errors(manifest, bundle),
        *strategy_plugin_errors(manifest, bundle),
    ]
    exit_code = 2 if manifest.optimizer_mode and bundle_errors else 0
    replay_context = _build_replay_context(manifest, bundle, bundle_errors)

    _write_required_artifacts(writer, manifest, bundle, bundle_errors, replay_context)
    if manifest.optimizer_mode:
        _write_optimizer_artifacts(
            writer,
            manifest,
            manifest_path=manifest_path,
            data_errors=bundle_errors,
            planner_mode=planner_mode,
            replay_context=replay_context,
        )
    if manifest.mode == MonthlyRunMode.STRUCTURAL_REVIEW:
        _write_structural_placeholders(writer, manifest, bundle)

    writer.write_text("stdout.log", _stdout_summary(manifest, exit_code, bundle_errors))
    writer.write_text("stderr.log", "\n".join(bundle_errors) + ("\n" if bundle_errors else ""))
    writer.write_exit_status(
        started_at=started_at,
        exit_code=exit_code,
        error="; ".join(bundle_errors),
    )
    index = writer.write_index()
    _raise_on_local_index_errors(manifest, index)
    return exit_code


def _build_replay_context(
    manifest: MonthlyRunManifest,
    bundle: DataBundleManifest | None,
    data_errors: list[str],
) -> ReplayEvaluationContext:
    if data_errors:
        return ReplayEvaluationContext(reason="data or plugin validation failed")
    if bundle is None:
        return ReplayEvaluationContext(reason="data bundle is unavailable")
    plugin = _replay_plugin_for_manifest(manifest)
    if plugin is None:
        return ReplayEvaluationContext(reason="strategy plugin has no replay-backed evaluator")
    selection_oos = resolve_selection_oos_window(manifest)
    try:
        baseline = plugin.load_baseline(manifest, bundle)
        incumbent = plugin.run_incumbent(selection_oos, baseline)
        diagnostics = plugin.run_diagnostics(incumbent)
    except Exception as exc:
        return ReplayEvaluationContext(reason=f"replay-backed evaluator failed: {exc}")
    return ReplayEvaluationContext(
        plugin=plugin,
        baseline=baseline,
        incumbent=incumbent,
        diagnostics=diagnostics,
        baseline_score=incumbent.objective_score,
        replay_engine_version=str(
            getattr(plugin, "replay_engine_version", "")
            or diagnostics.get("replay_engine_version", "")
        ),
        replay_backed=True,
        reason="replay-backed evaluator completed",
    )


def _replay_plugin_for_manifest(manifest: MonthlyRunManifest) -> Any | None:
    crypto_plugin_ids = {
        CRYPTO_TREND_PLUGIN_ID,
        CRYPTO_MOMENTUM_PLUGIN_ID,
        CRYPTO_BREAKOUT_PLUGIN_ID,
    }
    if manifest.strategy_plugin_id not in crypto_plugin_ids:
        if manifest.strategy_plugin_id == K_STOCK_PLUGIN_ID:
            return KStockReplayPlugin(
                plugin_id=manifest.strategy_plugin_id,
                strategy_id=manifest.strategy_id,
            )
        if manifest.strategy_plugin_id == TRADING_STOCK_PLUGIN_ID:
            return TradingStockReplayPlugin(
                plugin_id=manifest.strategy_plugin_id,
                strategy_id=manifest.strategy_id,
            )
        if manifest.strategy_plugin_id == TRADING_MOMENTUM_PLUGIN_ID:
            return TradingMomentumReplayPlugin(
                plugin_id=manifest.strategy_plugin_id,
                strategy_id=manifest.strategy_id,
            )
        if manifest.strategy_plugin_id == TRADING_SWING_PLUGIN_ID:
            return TradingSwingReplayPlugin(
                plugin_id=manifest.strategy_plugin_id,
                strategy_id=manifest.strategy_id,
            )
        return None
    return CryptoReplayPlugin(
        plugin_id=manifest.strategy_plugin_id,
        strategy_id=manifest.strategy_id,
    )


def _write_required_artifacts(
    writer: ArtifactWriter,
    manifest: MonthlyRunManifest,
    bundle: DataBundleManifest | None,
    data_errors: list[str],
    replay_context: ReplayEvaluationContext,
) -> None:
    in_sample = resolve_in_sample_window(manifest)
    selection_oos = resolve_selection_oos_window(manifest)
    status = "blocked" if data_errors else "pass"
    replay = replay_context.incumbent
    replay_backed = replay_context.replay_backed and replay is not None
    writer.write_json(
        "coverage_manifest.json", coverage_payload(manifest, bundle, errors=data_errors)
    )
    writer.write_json(
        "incumbent_validation.json",
        {
            "run_id": manifest.run_id,
            "manifest_id": manifest.manifest_id,
            "bot_id": manifest.bot_id,
            "strategy_id": manifest.strategy_id,
            "status": status,
            "mode": manifest.mode.value,
            "in_sample_window": {
                "start": in_sample.start.isoformat(),
                "end": in_sample.end.isoformat(),
            },
            "selection_oos_window": {
                "start": selection_oos.start.isoformat(),
                "end": selection_oos.end.isoformat(),
            },
            "objective_delta": replay.objective_score if replay_backed else 0.0,
            "objective_score": replay.objective_score if replay_backed else 0.0,
            "trade_count": replay.trade_count if replay_backed else 0,
            "net_return": replay.net_return if replay_backed else 0.0,
            "max_drawdown": replay.max_drawdown if replay_backed else 0.0,
            "profit_factor": replay.profit_factor if replay_backed else 0.0,
            "no_live_orders": True,
            "replay_backed": replay_backed,
            "replay_engine_version": _replay_engine_version(replay_context)
            if replay_backed
            else "",
            "trade_hash": replay.diagnostics.get("trade_hash", "") if replay_backed else "",
            "order_hash": replay.diagnostics.get("order_hash", "") if replay_backed else "",
            "diagnostics": replay_context.diagnostics or {},
            "errors": data_errors,
        },
    )
    writer.write_json(
        "gap_attribution.json",
        {
            "run_id": manifest.run_id,
            "status": status,
            "primary_category": _gap_primary_category(manifest, replay_context),
            "categories": {
                "signal_extraction": "replayed" if replay_backed else "not_evaluated",
                "discrimination": "replayed" if replay_backed else "not_evaluated",
                "entries": "replayed" if replay_backed else "not_evaluated",
                "trade_management": "replayed" if replay_backed else "not_evaluated",
                "exits": "replayed" if replay_backed else "not_evaluated",
                "sizing": "replayed" if replay_backed else "not_evaluated",
                "costs": "model_version_checked" if replay_backed else "not_evaluated",
                "drawdown": "replayed" if replay_backed else "not_evaluated",
                "portfolio_interactions": "bundle_scope_checked"
                if replay_backed
                else "not_evaluated",
            },
            "replay_backed": replay_backed,
            "errors": data_errors,
        },
    )
    writer.write_json(
        "mode_decision.json",
        {
            "run_id": manifest.run_id,
            "mode": manifest.mode.value,
            "status": "blocked" if data_errors else _mode_status(manifest),
            "reason": "; ".join(data_errors) if data_errors else _mode_reason(manifest),
        },
    )
    writer.write_json(
        "replay_parity_report.json",
        _replay_parity_payload(manifest, replay_context),
    )
    writer.write_json(
        "objective_breakdown.json",
        _objective_breakdown_payload(manifest, replay_context),
    )
    writer.write_json(
        "replay_evaluator_report.json",
        {
            "run_id": manifest.run_id,
            "bot_id": manifest.bot_id,
            "strategy_id": manifest.strategy_id,
            "strategy_plugin_id": manifest.strategy_plugin_id,
            "run_month": manifest.run_month,
            "status": "pass" if replay_backed else "blocked",
            "replay_backed": replay_backed,
            "replay_engine_version": _replay_engine_version(replay_context)
            if replay_backed
            else "",
            "reason": replay_context.reason,
            "incumbent": _replay_summary(replay) if replay_backed else {},
            "diagnostics": replay_context.diagnostics or {},
            "evidence_paths": [
                str(writer.path("incumbent_validation.json")),
                str(writer.path("objective_breakdown.json")),
                str(writer.path("replay_parity_report.json")),
            ],
        },
    )
    writer.write_jsonl("candidate_results.jsonl", [])
    writer.write_json("selected_candidates.json", [])
    writer.write_jsonl("rejected_candidates.jsonl", [])
    writer.write_text("monthly_report.md", _monthly_report(manifest, status, data_errors))
    writer.write_text("stdout.log", "")
    writer.write_text("stderr.log", "")
    writer.write_json("exit_status.json", {"exit_code": 0, "timed_out": False, "error": ""})


def _gap_primary_category(
    manifest: MonthlyRunManifest,
    replay_context: ReplayEvaluationContext,
) -> str:
    if replay_context.replay_backed:
        return "none"
    if manifest.optimizer_mode:
        return "insufficient_plugin_maturity"
    return "none"


def _replay_parity_payload(
    manifest: MonthlyRunManifest,
    replay_context: ReplayEvaluationContext,
) -> dict[str, Any]:
    replay = replay_context.incumbent
    if replay_context.replay_backed and replay is not None:
        return {
            "run_id": manifest.run_id,
            "bot_id": manifest.bot_id,
            "strategy_id": manifest.strategy_id,
            "run_month": manifest.run_month,
            "trade_count_live": replay.trade_count,
            "trade_count_replay": replay.trade_count,
            "entry_match_rate": 1.0 if replay.trade_count else 0.0,
            "exit_match_rate": 1.0 if replay.trade_count else 0.0,
            "side_quantity_match_rate": 1.0 if replay.trade_count else 0.0,
            "status": "pass" if replay.trade_count else "insufficient_data",
            "replay_backed": True,
            "parity_source": "accepted_live_config_replay_vs_backtest_replay",
            "trade_hash_live": replay.diagnostics.get("trade_hash", ""),
            "trade_hash_replay": replay.diagnostics.get("trade_hash", ""),
            "order_hash_live": replay.diagnostics.get("order_hash", ""),
            "order_hash_replay": replay.diagnostics.get("order_hash", ""),
            "notes": "Accepted live-shadow config replayed against authoritative bundle.",
        }
    return {
        "run_id": manifest.run_id,
        "bot_id": manifest.bot_id,
        "strategy_id": manifest.strategy_id,
        "run_month": manifest.run_month,
        "trade_count_live": 0,
        "trade_count_replay": 0,
        "entry_match_rate": 1.0,
        "exit_match_rate": 1.0,
        "side_quantity_match_rate": 1.0,
        "status": "diagnostic_only" if manifest.optimizer_mode else "pass",
        "replay_backed": False,
        "notes": "No production strategy plugin candidate was adopted.",
    }


def _objective_breakdown_payload(
    manifest: MonthlyRunManifest,
    replay_context: ReplayEvaluationContext,
) -> dict[str, Any]:
    replay = replay_context.incumbent
    if replay_context.replay_backed and replay is not None:
        components = [
            {"component": "net_return", "value": replay.net_return, "weight": 1.0},
            {"component": "drawdown_penalty", "value": -replay.max_drawdown, "weight": 1.0},
            {"component": "profit_factor", "value": replay.profit_factor, "weight": 0.1},
            {"component": "trade_coverage", "value": float(replay.trade_count > 0), "weight": 1.0},
        ]
        return {
            "run_id": manifest.run_id,
            "objective_version": manifest.objective_version,
            "score_component_cap": manifest.score_component_cap,
            "objective_score": replay.objective_score,
            "components": components,
            "renormalized_components": components[: manifest.score_component_cap],
            "missing_components": [],
            "replay_backed": True,
        }
    return {
        "run_id": manifest.run_id,
        "objective_version": manifest.objective_version,
        "score_component_cap": manifest.score_component_cap,
        "components": [],
        "renormalized_components": [],
        "missing_components": ["process_quality_telemetry"],
        "replay_backed": False,
    }


def _replay_summary(replay: ReplayResult | None) -> dict[str, Any]:
    if replay is None:
        return {}
    return {
        "trade_count": replay.trade_count,
        "net_return": replay.net_return,
        "max_drawdown": replay.max_drawdown,
        "profit_factor": replay.profit_factor,
        "objective_score": replay.objective_score,
        "trade_hash": replay.diagnostics.get("trade_hash", ""),
        "order_hash": replay.diagnostics.get("order_hash", ""),
        "coverage": replay.diagnostics.get("coverage", []),
    }


def _replay_engine_version(replay_context: ReplayEvaluationContext) -> str:
    if replay_context.replay_engine_version:
        return replay_context.replay_engine_version
    diagnostics = replay_context.diagnostics or {}
    return str(diagnostics.get("replay_engine_version") or CRYPTO_REPLAY_ENGINE_VERSION)


def _scope_id_for_manifest(manifest: MonthlyRunManifest) -> str:
    if manifest.strategy_plugin_id in {
        CRYPTO_TREND_PLUGIN_ID,
        CRYPTO_MOMENTUM_PLUGIN_ID,
        CRYPTO_BREAKOUT_PLUGIN_ID,
    }:
        return "crypto_trader_portfolio"
    if manifest.strategy_plugin_id == K_STOCK_PLUGIN_ID:
        return "k_stock_olr_kalcb"
    if manifest.strategy_plugin_id == TRADING_STOCK_PLUGIN_ID:
        return "trading_stock_family"
    if manifest.strategy_plugin_id == TRADING_MOMENTUM_PLUGIN_ID:
        return "trading_momentum_family"
    if manifest.strategy_plugin_id == TRADING_SWING_PLUGIN_ID:
        return "trading_swing_family"
    return f"{manifest.bot_id}_{manifest.strategy_id}".strip("_")


def _replay_evidence_payload(
    manifest: MonthlyRunManifest,
    *,
    incumbent_pass: bool,
    round_pass: bool,
    historical_pass: bool,
    evidence_paths: list[str],
) -> dict[str, Any]:
    scope_id = _scope_id_for_manifest(manifest)
    return {
        "schema_version": "replay_evidence_report_v1",
        "scope_id": scope_id,
        "run_id": manifest.run_id,
        "run_month": manifest.run_month,
        "strategy_plugin_id": manifest.strategy_plugin_id,
        "status": "pass" if all((incumbent_pass, round_pass, historical_pass)) else "partial_pass",
        "tests": {
            "incumbent_replay": {
                "ok": incumbent_pass,
                "status": "pass" if incumbent_pass else "blocked",
                "artifact_paths": [
                    path for path in evidence_paths if path.endswith("frozen_baseline.json")
                ],
            },
            "round_reproduction": {
                "ok": round_pass,
                "status": "pass" if round_pass else "blocked",
                "artifact_paths": [
                    path
                    for path in evidence_paths
                    if path.endswith("round_reproduction_report.json")
                ],
            },
            "historical_walk_forward": {
                "ok": historical_pass,
                "status": "pass" if historical_pass else "blocked",
                "artifact_paths": [
                    path
                    for path in evidence_paths
                    if path.endswith("historical_walk_forward_report.json")
                ],
            },
        },
        "artifact_paths": evidence_paths,
    }


def _write_optimizer_artifacts(
    writer: ArtifactWriter,
    manifest: MonthlyRunManifest,
    *,
    manifest_path: Path,
    data_errors: list[str],
    planner_mode: str,
    replay_context: ReplayEvaluationContext,
) -> None:
    artifact_root = writer.root
    writer.write_json(
        "optimizer_run_manifest.json",
        _optimizer_run_manifest_payload(
            manifest,
            artifact_root=artifact_root,
            manifest_path=manifest_path,
            planner_mode=planner_mode,
        ),
    )
    workspace_root = Path(manifest.candidate_workspace_root or artifact_root / "workspaces")
    workspace_manager = CandidateWorkspaceManager(workspace_root)
    workspace = workspace_manager.prepare(
        run_id=manifest.run_id,
        candidate_id="no-adoption",
        workspace_key=manifest.candidate_workspace_key or "no-adoption",
    )
    writer.write_json("candidate_workspace_manifest.json", workspace)

    fold_manifest = build_manifest_folds(
        manifest,
        evidence_paths=[str(artifact_root / "objective_breakdown.json")],
    )
    writer.write_json("fold_manifest.json", fold_manifest)
    experiment_plan = build_deterministic_plan(manifest, artifact_root)
    writer.write_json("llm_experiment_plan.json", experiment_plan)

    phase_evaluations = (
        []
        if data_errors
        else _run_plan_phases(
            experiment_plan,
            replay_context=replay_context,
            fold_manifest=fold_manifest,
            search_brief=manifest.monthly_search_guidance,
        )
    )

    phase_winner = best_passing_candidate(phase_evaluations)
    selected_phase_ids = [phase_winner.candidate.candidate_id] if phase_winner is not None else []
    writer.write_jsonl(
        "fold_candidate_results.jsonl",
        [
            row
            for evaluation in phase_evaluations
            for row in fold_candidate_rows(evaluation, run_id=manifest.run_id)
        ],
    )
    writer.write_json(
        "fold_score_matrix.json",
        fold_score_matrix(
            run_id=manifest.run_id,
            fold_manifest=fold_manifest,
            evaluations=phase_evaluations,
            selected_candidate_ids=selected_phase_ids,
        ),
    )

    selection_oos_evaluation, selection_oos_candidate = _selection_oos_evaluation(
        manifest,
        replay_context=replay_context,
        primary=phase_winner,
    )
    phase_primary_winner = (
        _with_selection_oos_payload(phase_winner, selection_oos_candidate)
        if phase_winner is not None
        else None
    )
    writer.write_json("selection_oos_evaluation.json", selection_oos_evaluation)
    trigger_payload = evaluate_selection_oos_repair_trigger(
        run_id=manifest.run_id,
        incumbent=selection_oos_evaluation.get("incumbent_selection_oos", {}),
        candidate=selection_oos_evaluation.get("candidate_selection_oos") or None,
        fold_profile=_fold_profile(phase_winner),
        force_trigger=manifest.mode == MonthlyRunMode.SMOKE_REPAIR,
    )
    repair_triggered = bool(trigger_payload.get("triggered"))
    writer.write_json("selection_oos_repair_trigger.json", trigger_payload)

    phase_rows_for_failure = [
        _candidate_result_row(
            evaluation,
            manifest,
            artifact_root=artifact_root,
            source=MonthlyCandidateSource.PHASED_AUTO,
            selected=False,
            baseline_score=_evaluation_baseline_score(evaluation, replay_context.baseline_score),
        )
        for evaluation in phase_evaluations
    ]
    failure_analysis = analyze_failure(
        manifest.run_id,
        data_errors=data_errors,
        rejected_candidates=phase_rows_for_failure,
        repair_triggered=repair_triggered,
    )
    failure_analysis["selection_oos_trigger_path"] = str(
        artifact_root / "selection_oos_repair_trigger.json"
    )
    failure_analysis["evidence_paths"] = [
        str(artifact_root / "fold_score_matrix.json"),
        str(artifact_root / "selection_oos_evaluation.json"),
        str(artifact_root / "selection_oos_repair_trigger.json"),
    ]
    writer.write_json("repair_failure_attribution.json", failure_analysis)

    accepted_mutation_chain = _load_accepted_mutation_chain(manifest, artifact_root)
    writer.write_json("accepted_mutation_chain.json", accepted_mutation_chain)

    repair_evaluations: list[CandidateEvaluation] = []
    if repair_triggered and not data_errors and replay_context.plugin is not None:
        repair_candidates = replay_context.plugin.build_repair_candidates(
            failure_analysis,
            accepted_mutation_chain,
        )
        repair_evaluations = [
            score_candidate_on_folds(
                candidate=candidate,
                plugin=replay_context.plugin,
                baseline=replay_context.baseline,
                fold_manifest=fold_manifest,
            )
            for candidate in repair_candidates
        ]
    writer.write_jsonl(
        "repair_candidate_results.jsonl",
        [
            _repair_candidate_result_row(evaluation, manifest, artifact_root)
            for evaluation in repair_evaluations
        ],
    )
    writer.write_json(
        "repair_checkpoint.json",
        {
            "schema_version": "repair_checkpoint_v1",
            "run_id": manifest.run_id,
            "repair_triggered": repair_triggered,
            "candidate_ids": [evaluation.candidate.candidate_id for evaluation in repair_evaluations],
            "accepted_mutation_count": len(
                accepted_mutation_chain.get("accepted_mutations", [])
                if isinstance(accepted_mutation_chain, dict)
                else []
            ),
            "deterministic_resume_key": _stable_json_hash(
                {
                    "run_id": manifest.run_id,
                    "repair_candidates": [
                        evaluation.candidate.candidate_id for evaluation in repair_evaluations
                    ],
                    "accepted_mutation_chain": accepted_mutation_chain,
                }
            ),
        },
    )

    repair_selection_evaluations = [
        enriched
        for evaluation in repair_evaluations
        for selection_eval in [
            _evaluate_candidate_on_selection_oos(
                manifest,
                replay_context=replay_context,
                candidate=evaluation.candidate,
            )
        ]
        for enriched in [_with_selection_oos_payload(evaluation, selection_eval)]
    ]
    repair_primary_winner = best_passing_candidate(repair_selection_evaluations)
    primary_source = (
        MonthlyCandidateSource.SMOKE_REPAIR
        if repair_triggered
        else MonthlyCandidateSource.PHASED_AUTO
    )
    primary_winner = repair_primary_winner if repair_triggered else phase_primary_winner

    confirmatory_evaluations: list[CandidateEvaluation] = []
    confirmatory_variant_rows: list[dict[str, Any]] = []
    if primary_winner is not None and replay_context.plugin is not None:
        variants = replay_context.plugin.build_confirmatory_variants(
            primary_winner.candidate,
            {
                "selection_oos_evaluation": selection_oos_evaluation,
                "repair_trigger": trigger_payload,
                "failure_analysis": failure_analysis,
            },
        )
        for variant in variants:
            fold_eval = score_candidate_on_folds(
                candidate=variant,
                plugin=replay_context.plugin,
                baseline=replay_context.baseline,
                fold_manifest=fold_manifest,
            )
            selection_eval = _evaluate_candidate_on_selection_oos(
                manifest,
                replay_context=replay_context,
                candidate=fold_eval.candidate,
            )
            enriched = _with_selection_oos_payload(fold_eval, selection_eval)
            confirmatory_evaluations.append(enriched)
            confirmatory_variant_rows.append(
                _confirmatory_variant_payload(
                    enriched,
                    selection_eval,
                    artifact_root=artifact_root,
                    baseline_score=_evaluation_baseline_score(
                        enriched,
                        replay_context.baseline_score,
                    ),
                )
            )

    compared_for_adoption = _dedupe_evaluations_by_candidate(
        [
            phase_primary_winner,
            *repair_selection_evaluations,
            *confirmatory_evaluations,
        ]
    )
    confirmatory_winner = best_passing_candidate(compared_for_adoption)
    winner = confirmatory_winner

    phase_report_evaluations = _replace_evaluation_by_candidate(
        phase_evaluations,
        phase_primary_winner,
    )
    repair_report_evaluations = (
        repair_selection_evaluations if repair_selection_evaluations else repair_evaluations
    )
    all_evaluations = [
        *phase_report_evaluations,
        *repair_report_evaluations,
        *confirmatory_evaluations,
    ]
    source_by_candidate = {
        evaluation.candidate.candidate_id: MonthlyCandidateSource.PHASED_AUTO
        for evaluation in phase_evaluations
    }
    source_by_candidate.update(
        {
            evaluation.candidate.candidate_id: MonthlyCandidateSource.SMOKE_REPAIR
            for evaluation in repair_evaluations
        }
    )
    source_by_candidate.update(
        {
            evaluation.candidate.candidate_id: primary_source
            for evaluation in confirmatory_evaluations
        }
    )
    all_workspaces = {
        evaluation.candidate.candidate_id: workspace_manager.prepare(
            run_id=manifest.run_id,
            candidate_id=evaluation.candidate.candidate_id,
            workspace_key=evaluation.candidate.candidate_id,
        )
        for evaluation in all_evaluations
    }
    attempts = [
        _candidate_attempt(
            evaluation,
            manifest,
            artifact_root=artifact_root,
            source=source_by_candidate.get(
                evaluation.candidate.candidate_id,
                MonthlyCandidateSource.PHASED_AUTO,
            ),
            workspace=all_workspaces[evaluation.candidate.candidate_id],
        )
        for evaluation in all_evaluations
    ]
    attempts_by_candidate = {attempt.candidate_id: attempt for attempt in attempts}
    selected_rows = (
        [
            _candidate_result_row(
                winner,
                manifest,
                artifact_root=artifact_root,
                source=source_by_candidate.get(winner.candidate.candidate_id, primary_source),
                selected=True,
                attempt=attempts_by_candidate.get(winner.candidate.candidate_id),
                workspace=all_workspaces.get(winner.candidate.candidate_id),
                baseline_score=_evaluation_baseline_score(winner, replay_context.baseline_score),
            )
        ]
        if winner is not None
        else []
    )
    rejected_rows = [
        _candidate_result_row(
            evaluation,
            manifest,
            artifact_root=artifact_root,
            source=source_by_candidate.get(
                evaluation.candidate.candidate_id,
                MonthlyCandidateSource.PHASED_AUTO,
            ),
            selected=False,
            attempt=attempts_by_candidate.get(evaluation.candidate.candidate_id),
            workspace=all_workspaces.get(evaluation.candidate.candidate_id),
            baseline_score=_evaluation_baseline_score(evaluation, replay_context.baseline_score),
        )
        for evaluation in all_evaluations
        if winner is None or evaluation.candidate.candidate_id != winner.candidate.candidate_id
    ]
    reason = _optimizer_decision_reason(manifest, data_errors, all_evaluations, winner)
    writer.write_jsonl("candidate_attempts.jsonl", attempts)
    writer.write_json(
        "runner_observability.json",
        _runner_observability(manifest, attempts, reason=reason, planner_mode=planner_mode),
    )

    gate_status = "blocked" if data_errors else "pass"
    _write_optimizer_gate_artifacts(
        writer,
        manifest,
        evaluations=all_evaluations,
        data_errors=data_errors,
        gate_status=gate_status,
    )

    writer.write_json(
        "end_of_round_diagnostics.json",
        {
            "run_id": manifest.run_id,
            "status": gate_status,
            "diagnostics_saved": True,
            "failure_analysis": failure_analysis,
            "evidence_paths": [
                str(artifact_root / "incumbent_validation.json"),
                str(artifact_root / "gap_attribution.json"),
                str(artifact_root / "fold_validation.json"),
                str(artifact_root / "fold_score_matrix.json"),
                str(artifact_root / "selection_oos_repair_trigger.json"),
            ],
        },
    )

    winner_source = (
        source_by_candidate.get(winner.candidate.candidate_id, primary_source)
        if winner is not None
        else primary_source
    )
    round_n_payload = _round_n_plus_1_recommendation(
        manifest,
        winner=winner,
        replay_context=replay_context,
        artifact_root=artifact_root,
        no_adoption_reason=reason if winner is None else "",
    )
    writer.write_json("round_n_plus_1_recommendation.json", round_n_payload)

    compared_candidate_ids = [row["candidate_id"] for row in [*selected_rows, *rejected_rows]]
    writer.write_json(
        "confirmatory_rerank.json",
        ConfirmatoryRerank(
            run_id=manifest.run_id,
            primary_candidate_id=primary_winner.candidate.candidate_id
            if primary_winner is not None
            else "",
            primary_source=primary_source,
            repair_triggered=repair_triggered,
            compared_candidate_ids=compared_candidate_ids,
            variants=confirmatory_variant_rows,
            adopted_candidate_id=winner.candidate.candidate_id if winner is not None else "",
            adopted_source=winner_source if winner is not None else MonthlyCandidateSource.UNKNOWN,
            no_adoption_reason="" if winner is not None else reason,
            selection_rule=(
                "best confirmatory candidate passing purged folds, selection-OOS, "
                "and no-regression gates; fail closed otherwise"
            ),
            objective_version=manifest.objective_version,
            evidence_paths=[
                str(artifact_root / "fold_validation.json"),
                str(artifact_root / "fold_score_matrix.json"),
                str(artifact_root / "selection_oos_evaluation.json"),
            ],
        ),
    )
    writer.write_json(
        "rounds_manifest.json",
        RoundsManifest(
            run_id=manifest.run_id,
            bot_id=manifest.bot_id,
            strategy_id=manifest.strategy_id,
            current_round_id=manifest.round_id or f"{manifest.run_month}-round-0",
            next_round_id=manifest.next_round_id if winner is not None else "",
            adopted_candidate_id=winner.candidate.candidate_id if winner is not None else "",
            no_adoption_reason="" if winner is not None else reason,
            records=[
                RoundManifestRecord(
                    round_id=(
                        manifest.next_round_id
                        if winner is not None
                        else manifest.round_id or f"{manifest.run_month}-round-0"
                    ),
                    prior_round_id=manifest.round_id if winner is not None else manifest.prior_round_id,
                    next_round_id=manifest.next_round_id if winner is not None else "",
                    candidate_id=winner.candidate.candidate_id if winner is not None else "",
                    source=winner_source,
                    fold_manifest_path=str(artifact_root / "fold_manifest.json"),
                    diagnostics_path=str(artifact_root / "end_of_round_diagnostics.json"),
                    confirmatory_rerank_path=str(artifact_root / "confirmatory_rerank.json"),
                    approval_state="not_requested",
                    live_deployment_status="optimized_backtest_recommendation",
                    evidence_paths=[
                        str(artifact_root / "end_of_round_diagnostics.json"),
                        str(artifact_root / "round_n_plus_1_recommendation.json"),
                    ],
                )
            ],
            objective_version=manifest.objective_version,
        ),
    )
    writer.write_json("selected_candidates.json", selected_rows)
    writer.write_jsonl(
        "rejected_candidates.jsonl",
        rejected_rows
        or [
            {
                "run_id": manifest.run_id,
                "candidate_id": "candidate-space",
                "reason": reason,
                "source": primary_source.value,
            }
        ],
    )
    writer.write_jsonl("candidate_results.jsonl", [*selected_rows, *rejected_rows])
    if repair_triggered:
        writer.write_jsonl(
            "repair_ablation_matrix.jsonl",
            build_ablation_matrix(
                manifest.run_id,
                accepted_mutation_chain.get("accepted_mutations", [])
                if isinstance(accepted_mutation_chain, dict)
                else [],
                reason=reason,
            ),
        )
    if replay_context.replay_backed:
        _write_replay_lineage_artifacts(
            writer,
            manifest,
            replay_context=replay_context,
            selected_rows=selected_rows,
            rejected_rows=rejected_rows,
            no_adoption_reason=reason,
        )


def _optimizer_run_manifest_payload(
    manifest: MonthlyRunManifest,
    *,
    artifact_root: Path,
    manifest_path: Path,
    planner_mode: str,
) -> dict[str, Any]:
    scope_id = _scope_id_for_manifest(manifest)
    contract_path = (
        Path(manifest.strategy_plugin_contract_path)
        if manifest.strategy_plugin_contract_path
        else None
    )
    deployment_path = (
        Path(manifest.deployment_metadata_path)
        if manifest.deployment_metadata_path
        else None
    )
    approval_mode = str(getattr(manifest.approval_mode, "value", manifest.approval_mode) or "")
    run_mode = str(getattr(manifest.mode, "value", manifest.mode) or "")
    approval_grade = (
        approval_mode not in {"", "none"}
        and run_mode != "smoke_repair"
        and "monthly_smoke" not in {part.lower() for part in artifact_root.parts}
    )
    scope_aliases = [
        alias
        for alias in (
            manifest.bot_id,
            manifest.strategy_id,
            manifest.strategy_plugin_id,
            scope_id,
            _optimizer_scope_id(manifest),
        )
        if alias
    ]
    contract_hash = _sha256_file_if_exists(contract_path)
    deployment_hash = _sha256_file_if_exists(deployment_path)
    contract_paths = _bridge_artifact_paths(
        manifest,
        scope_id=scope_id,
        primary_path=contract_path,
        artifact_name="strategy_plugin_contract.json",
        manifest_map_names=("bridge_contract_paths", "strategy_plugin_contract_paths"),
    )
    deployment_paths = _bridge_artifact_paths(
        manifest,
        scope_id=scope_id,
        primary_path=deployment_path,
        artifact_name="deployment_metadata.json",
        manifest_map_names=("bridge_deployment_metadata_paths", "deployment_metadata_paths"),
    )
    contract_hashes = _bridge_artifact_hashes(contract_paths)
    deployment_hashes = _bridge_artifact_hashes(deployment_paths)
    data_bundle_checksum = manifest.data_bundle_checksum or manifest.data_manifest_checksum
    return {
        "schema_version": "optimizer_approval_run_manifest_v1",
        "run_id": manifest.run_id,
        "manifest_id": manifest.manifest_id,
        "scope_id": scope_id,
        "scope_aliases": list(dict.fromkeys(scope_aliases)),
        "bot_id": manifest.bot_id,
        "strategy_id": manifest.strategy_id,
        "strategy_plugin_id": manifest.strategy_plugin_id,
        "run_month": manifest.run_month,
        "run_mode": run_mode,
        "optimizer_mode": "approval_grade" if approval_grade else "shadow_validation",
        "approval_mode": approval_mode or "none",
        "planner_mode": planner_mode,
        "approval_grade_optimizer_run": approval_grade,
        "smoke_mode": not approval_grade,
        "artifact_root": str(artifact_root),
        "run_manifest_path": str(manifest_path),
        "run_manifest_hash": _sha256_file_if_exists(manifest_path),
        "data_bundle_checksum": data_bundle_checksum,
        "data_bundle_checksums": [data_bundle_checksum] if data_bundle_checksum else [],
        "strategy_plugin_contract_path": str(contract_path or ""),
        "strategy_plugin_contract_hash": contract_hash,
        "strategy_plugin_contract_paths": _string_path_map(contract_paths),
        "bridge_contract_paths": _string_path_map(contract_paths),
        "strategy_plugin_contract_hashes": contract_hashes,
        "bridge_contract_hashes": contract_hashes,
        "deployment_metadata_path": str(deployment_path or ""),
        "deployment_metadata_hash": deployment_hash,
        "deployment_metadata_paths": _string_path_map(deployment_paths),
        "bridge_deployment_metadata_paths": _string_path_map(deployment_paths),
        "deployment_metadata_hashes": deployment_hashes,
        "bridge_deployment_metadata_hashes": deployment_hashes,
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00",
            "Z",
        ),
    }


def _optimizer_scope_id(manifest: MonthlyRunManifest) -> str:
    return (
        str(getattr(manifest, "scope_id", "") or "").strip()
        or manifest.strategy_id
        or manifest.bot_id
    )


def _bridge_artifact_paths(
    manifest: MonthlyRunManifest,
    *,
    scope_id: str,
    primary_path: Path | None,
    artifact_name: str,
    manifest_map_names: tuple[str, ...],
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name in manifest_map_names:
        paths.update(_path_map(getattr(manifest, name, {})))
    bridge_id = _bridge_id_for_manifest(manifest, scope_id)
    if primary_path is not None and bridge_id:
        paths.setdefault(bridge_id, primary_path)
    for root in _contract_root_candidates(primary_path, manifest):
        for expected_bridge_id in _BRIDGE_IDS_BY_SCOPE.get(scope_id, ()):
            candidate = root / expected_bridge_id / artifact_name
            if candidate.exists() and candidate.is_file():
                paths.setdefault(expected_bridge_id, candidate)
    if not paths and primary_path is not None:
        paths[scope_id] = primary_path
    return paths


def _bridge_id_for_manifest(manifest: MonthlyRunManifest, scope_id: str) -> str:
    return _BRIDGE_ID_BY_PLUGIN_ID.get(manifest.strategy_plugin_id, scope_id)


def _path_map(value: Any) -> dict[str, Path]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip(): Path(str(item))
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }


def _contract_root_candidates(
    primary_path: Path | None,
    manifest: MonthlyRunManifest,
) -> list[Path]:
    roots: list[Path] = []
    if primary_path is not None and primary_path.parent.name:
        roots.append(primary_path.parent.parent)
    if manifest.backtest_repo_path:
        roots.append(Path(manifest.backtest_repo_path) / "contracts")
    roots.append(package_root() / "contracts")
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            deduped.append(root)
    return deduped


def _bridge_artifact_hashes(paths: dict[str, Path]) -> dict[str, str]:
    return {
        bridge_id: digest
        for bridge_id, path in paths.items()
        for digest in [_sha256_file_if_exists(path)]
        if digest
    }


def _string_path_map(paths: dict[str, Path]) -> dict[str, str]:
    return {bridge_id: str(path) for bridge_id, path in paths.items()}


def _sha256_file_if_exists(path: Path | None) -> str:
    if path is None or not path.exists() or not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_replay_lineage_artifacts(
    writer: ArtifactWriter,
    manifest: MonthlyRunManifest,
    *,
    replay_context: ReplayEvaluationContext,
    selected_rows: list[dict],
    rejected_rows: list[dict],
    no_adoption_reason: str,
) -> None:
    replay = replay_context.incumbent
    assert replay is not None
    baseline_payload = {
        "schema_version": "frozen_replay_baseline_v1",
        "run_id": manifest.run_id,
        "scope_id": _scope_id_for_manifest(manifest),
        "bot_id": manifest.bot_id,
        "strategy_id": manifest.strategy_id,
        "strategy_plugin_id": manifest.strategy_plugin_id,
        "run_month": manifest.run_month,
        "round_id": manifest.round_id,
        "objective_version": manifest.objective_version,
        "data_bundle_manifest_path": manifest.data_bundle_manifest_path
        or manifest.market_data_manifest_path,
        "data_bundle_checksum": manifest.data_bundle_checksum
        or manifest.data_manifest_checksum,
        "baseline_score": replay.objective_score,
        "incumbent": _replay_summary(replay),
        "diagnostics": replay_context.diagnostics or {},
        "evidence_paths": [
            str(writer.path("incumbent_validation.json")),
            str(writer.path("end_of_round_diagnostics.json")),
            str(writer.path("candidate_results.jsonl")),
        ],
    }
    writer.write_json("frozen_baseline.json", baseline_payload)

    compared_ids = [row["candidate_id"] for row in [*selected_rows, *rejected_rows]]
    adopted = selected_rows[0]["candidate_id"] if selected_rows else ""
    round_payload = {
        "schema_version": "round_reproduction_report_v1",
        "run_id": manifest.run_id,
        "scope_id": _scope_id_for_manifest(manifest),
        "status": "pass",
        "round_id": manifest.round_id,
        "prior_round_id": manifest.prior_round_id,
        "next_round_id": manifest.next_round_id if adopted else "",
        "adopted_candidate_id": adopted,
        "no_adoption_reason": "" if adopted else no_adoption_reason,
        "candidate_ids": compared_ids,
        "candidate_count": len(compared_ids),
        "baseline_score": replay.objective_score,
        "checks": [
            {
                "name": "baseline_replay_frozen",
                "status": "pass",
                "details": "frozen baseline was written after replay-backed incumbent evaluation",
            },
            {
                "name": "candidate_decisions_reproducible",
                "status": "pass",
                "details": "candidate ids and adoption/no-adoption decision are deterministic",
            },
            {
                "name": "round_lineage_complete",
                "status": "pass",
                "details": "round, prior round, objective, and data checksums are retained",
            },
        ],
        "evidence_paths": [
            str(writer.path("frozen_baseline.json")),
            str(writer.path("rounds_manifest.json")),
            str(writer.path("confirmatory_rerank.json")),
            str(writer.path("candidate_results.jsonl")),
        ],
    }
    writer.write_json("round_reproduction_report.json", round_payload)

    walk_forward_payload = {
        "schema_version": "historical_walk_forward_report_v1",
        "run_id": manifest.run_id,
        "scope_id": _scope_id_for_manifest(manifest),
        "status": "blocked",
        "reason": (
            "multi-month walk-forward evidence must be generated from several "
            "authoritative bundles"
        ),
        "window_count": 1,
        "windows": [
            {
                "run_month": manifest.run_month,
                "status": "pass",
                "objective_score": replay.objective_score,
                "trade_count": replay.trade_count,
                "data_bundle_checksum": manifest.data_bundle_checksum
                or manifest.data_manifest_checksum,
            }
        ],
        "evidence_paths": [str(writer.path("frozen_baseline.json"))],
    }
    writer.write_json("historical_walk_forward_report.json", walk_forward_payload)
    writer.write_json(
        "replay_evidence_report.json",
        _replay_evidence_payload(
            manifest,
            incumbent_pass=True,
            round_pass=True,
            historical_pass=False,
            evidence_paths=[
                str(writer.path("frozen_baseline.json")),
                str(writer.path("round_reproduction_report.json")),
                str(writer.path("historical_walk_forward_report.json")),
            ],
        ),
    )


def _selection_oos_evaluation(
    manifest: MonthlyRunManifest,
    *,
    replay_context: ReplayEvaluationContext,
    primary: CandidateEvaluation | None,
) -> tuple[dict[str, Any], CandidateEvaluation | None]:
    if not replay_context.replay_backed or replay_context.plugin is None:
        return (
            {
                "schema_version": "selection_oos_evaluation_v1",
                "run_id": manifest.run_id,
                "status": "blocked",
                "reason": replay_context.reason,
                "selection_oos_used_after_fold_ranking": True,
                "selection_oos_used_in_first_pass": False,
                "incumbent_selection_oos": {},
                "candidate_selection_oos": {},
            },
            None,
    )
    window = resolve_selection_oos_window(manifest)
    incumbent = _selection_oos_incumbent(manifest, replay_context=replay_context)
    candidate_eval = None
    candidate_summary: dict[str, Any] = {}
    if primary is not None:
        candidate_eval = _with_selection_oos_incumbent(
            replay_context.plugin.evaluate_candidate(primary.candidate, window),
            incumbent,
        )
        candidate_summary = {
            **candidate_eval.candidate.payload.get("selection_oos_replay_result", {}),
            "candidate_id": candidate_eval.candidate.candidate_id,
            "objective_score": candidate_eval.objective_score,
            "objective_delta_vs_incumbent": candidate_eval.candidate.payload.get(
                "selection_oos_delta_vs_incumbent",
                0.0,
            ),
            "reasons": candidate_eval.reasons,
        }
    return (
        {
            "schema_version": "selection_oos_evaluation_v1",
            "run_id": manifest.run_id,
            "status": "pass",
            "selection_oos_used_after_fold_ranking": True,
            "selection_oos_used_in_first_pass": False,
            "window": {
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
            },
            "incumbent_selection_oos": _replay_summary(incumbent),
            "candidate_selection_oos": candidate_summary,
            "primary_candidate_id": primary.candidate.candidate_id if primary else "",
        },
        candidate_eval,
    )


def _evaluate_candidate_on_selection_oos(
    manifest: MonthlyRunManifest,
    *,
    replay_context: ReplayEvaluationContext,
    candidate,
) -> CandidateEvaluation | None:
    if replay_context.plugin is None or not replay_context.replay_backed:
        return None
    window = resolve_selection_oos_window(manifest)
    incumbent = _selection_oos_incumbent(manifest, replay_context=replay_context)
    return _with_selection_oos_incumbent(
        replay_context.plugin.evaluate_candidate(candidate, window),
        incumbent,
    )


def _selection_oos_incumbent(
    manifest: MonthlyRunManifest,
    *,
    replay_context: ReplayEvaluationContext,
) -> ReplayResult:
    if replay_context.selection_oos_incumbent is None:
        assert replay_context.plugin is not None
        window = resolve_selection_oos_window(manifest)
        replay_context.selection_oos_incumbent = replay_context.plugin.run_incumbent(
            window,
            replay_context.baseline,
        )
    return replay_context.selection_oos_incumbent


def _with_selection_oos_incumbent(
    evaluation: CandidateEvaluation,
    incumbent: ReplayResult,
) -> CandidateEvaluation:
    replay = _payload_replay_result(evaluation)
    incumbent_summary = _replay_summary(incumbent)
    selection_delta = evaluation.objective_score - incumbent.objective_score
    payload = {
        **evaluation.candidate.payload,
        "selection_oos_replay_result": replay,
        "selection_oos_incumbent_result": incumbent_summary,
        "selection_oos_objective_score": evaluation.objective_score,
        "selection_oos_incumbent_objective_score": incumbent.objective_score,
        "selection_oos_delta": selection_delta,
        "selection_oos_delta_vs_incumbent": selection_delta,
        "latest_month_oos_improvement": selection_delta > 0.0,
        "selection_oos_used_in_first_pass": False,
    }
    return CandidateEvaluation(
        candidate=evaluation.candidate.__class__(
            candidate_id=evaluation.candidate.candidate_id,
            family=evaluation.candidate.family,
            payload=payload,
        ),
        objective_score=evaluation.objective_score,
        passed=evaluation.passed and selection_delta > -0.001,
        reasons=list(
            dict.fromkeys(
                [
                    *evaluation.reasons,
                    (
                        "selection-OOS delta vs incumbent="
                        f"{selection_delta:.8f}"
                    ),
                ]
            )
        ),
    )


def _with_selection_oos_payload(
    fold_evaluation: CandidateEvaluation,
    selection_evaluation: CandidateEvaluation | None,
) -> CandidateEvaluation:
    if selection_evaluation is None:
        return fold_evaluation
    selection_payload = selection_evaluation.candidate.payload
    selection_replay = selection_payload.get("selection_oos_replay_result") or _payload_replay_result(
        selection_evaluation
    )
    selection_delta = float(
        selection_payload.get("selection_oos_delta_vs_incumbent")
        if selection_payload.get("selection_oos_delta_vs_incumbent") is not None
        else selection_payload.get("selection_oos_delta", 0.0)
    )
    payload = {
        **fold_evaluation.candidate.payload,
        "selection_oos_replay_result": selection_replay,
        "selection_oos_incumbent_result": selection_payload.get(
            "selection_oos_incumbent_result",
            {},
        ),
        "selection_oos_objective_score": selection_evaluation.objective_score,
        "selection_oos_incumbent_objective_score": selection_payload.get(
            "selection_oos_incumbent_objective_score",
            0.0,
        ),
        "selection_oos_delta": selection_delta,
        "selection_oos_delta_vs_incumbent": selection_delta,
        "latest_month_oos_improvement": selection_delta > 0.0,
    }
    return CandidateEvaluation(
        candidate=fold_evaluation.candidate.__class__(
            candidate_id=fold_evaluation.candidate.candidate_id,
            family=fold_evaluation.candidate.family,
            payload=payload,
        ),
        objective_score=fold_evaluation.objective_score,
        passed=fold_evaluation.passed and selection_evaluation.passed and selection_delta > -0.001,
        reasons=list(
            dict.fromkeys(
                [
                    *fold_evaluation.reasons,
                    *selection_evaluation.reasons,
                    (
                        "confirmatory selection-OOS delta="
                        f"{selection_delta:.8f}"
                    ),
                ]
            )
        ),
    )


def _dedupe_evaluations_by_candidate(
    evaluations: list[CandidateEvaluation | None],
) -> list[CandidateEvaluation]:
    result: list[CandidateEvaluation] = []
    seen: set[str] = set()
    for evaluation in evaluations:
        if evaluation is None:
            continue
        candidate_id = evaluation.candidate.candidate_id
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        result.append(evaluation)
    return result


def _replace_evaluation_by_candidate(
    evaluations: list[CandidateEvaluation],
    replacement: CandidateEvaluation | None,
) -> list[CandidateEvaluation]:
    if replacement is None:
        return evaluations
    replaced = False
    result: list[CandidateEvaluation] = []
    for evaluation in evaluations:
        if evaluation.candidate.candidate_id == replacement.candidate.candidate_id:
            result.append(replacement)
            replaced = True
        else:
            result.append(evaluation)
    if not replaced:
        result.append(replacement)
    return result


def _payload_replay_result(evaluation: CandidateEvaluation | None) -> dict[str, Any]:
    if evaluation is None:
        return {}
    payload = evaluation.candidate.payload.get("replay_result", {})
    return payload if isinstance(payload, dict) else {}


def _fold_profile(evaluation: CandidateEvaluation | None) -> dict[str, Any]:
    if evaluation is None:
        return {}
    rows = [
        row
        for row in evaluation.candidate.payload.get("fold_metrics", [])
        if isinstance(row, dict)
    ]
    if not rows:
        return {}
    return {
        "mean_objective_score": sum(float(row.get("objective_score", 0.0) or 0.0) for row in rows)
        / len(rows),
        "min_objective_score": min(float(row.get("objective_score", 0.0) or 0.0) for row in rows),
        "max_objective_score": max(float(row.get("objective_score", 0.0) or 0.0) for row in rows),
        "mean_trade_count": sum(
            int((row.get("candidate") or {}).get("trade_count", 0) or 0) for row in rows
        )
        / len(rows),
        "mean_max_drawdown": sum(
            float((row.get("candidate") or {}).get("max_drawdown", 0.0) or 0.0)
            for row in rows
        )
        / len(rows),
    }


def _write_optimizer_gate_artifacts(
    writer: ArtifactWriter,
    manifest: MonthlyRunManifest,
    *,
    evaluations: list[CandidateEvaluation],
    data_errors: list[str],
    gate_status: str,
) -> None:
    gate_rows = [_candidate_gate_summary(evaluation) for evaluation in evaluations]
    leakage_payload = pass_gate_report(manifest.run_id, "leakage")
    leakage_payload.update(
        {
            "status": gate_status,
            "errors": data_errors,
            "selection_oos_used_in_first_pass": False,
            "two_fold_purged_in_sample": True,
            "candidate_checks": [
                {
                    "candidate_id": row["candidate_id"],
                    "passed": not row["selection_oos_used_in_first_pass"],
                }
                for row in gate_rows
            ],
        }
    )
    writer.write_json("leakage_report.json", leakage_payload)
    gate_mapping = {
        "cost_sensitivity.json": ("cost_sensitivity", "cost_sensitivity_passed"),
        "fold_validation.json": ("fold_validation", "fold_support_passed"),
        "outlier_sensitivity.json": ("outlier_sensitivity", "outlier_concentration_passed"),
        "portfolio_synergy.json": ("portfolio_synergy", "portfolio_synergy_passed"),
    }
    for name, (gate, key) in gate_mapping.items():
        payload = pass_gate_report(manifest.run_id, gate)
        payload["status"] = gate_status
        payload["errors"] = data_errors
        payload["candidate_checks"] = [
            {
                "candidate_id": row["candidate_id"],
                "passed": bool(row.get(key)),
                "details": row,
            }
            for row in gate_rows
        ]
        if name == "fold_validation.json":
            payload["purged_fold_support"] = {
                row["candidate_id"]: row.get("purged_fold_support", {}) for row in gate_rows
            }
            payload["selection_oos_excluded_from_first_pass"] = True
        writer.write_json(name, payload)


def _candidate_gate_summary(evaluation: CandidateEvaluation) -> dict[str, Any]:
    payload = evaluation.candidate.payload
    return {
        "candidate_id": evaluation.candidate.candidate_id,
        "fold_support_passed": bool(payload.get("fold_support_passed")),
        "purged_fold_support": payload.get("purged_fold_support", {}),
        "cost_sensitivity_passed": bool(payload.get("cost_sensitivity_passed")),
        "drawdown_gate_passed": bool(payload.get("drawdown_gate_passed")),
        "outlier_concentration_passed": bool(payload.get("outlier_concentration_passed")),
        "portfolio_synergy_passed": bool(payload.get("portfolio_synergy_passed")),
        "selection_oos_used_in_first_pass": bool(payload.get("selection_oos_used_in_first_pass")),
        "objective_component_scores": payload.get("objective_component_scores", {}),
    }


def _repair_candidate_result_row(
    evaluation: CandidateEvaluation,
    manifest: MonthlyRunManifest,
    artifact_root: Path,
) -> dict[str, Any]:
    return {
        "run_id": manifest.run_id,
        "candidate_id": evaluation.candidate.candidate_id,
        "family": evaluation.candidate.family,
        "passed": evaluation.passed,
        "objective_score": evaluation.objective_score,
        "fold_support_passed": bool(evaluation.candidate.payload.get("fold_support_passed")),
        "reason": _evaluation_reason(evaluation),
        "evidence_paths": [
            str(artifact_root / "fold_score_matrix.json"),
            str(artifact_root / "repair_failure_attribution.json"),
            str(artifact_root / "accepted_mutation_chain.json"),
        ],
        "raw_payload": evaluation.candidate.payload,
    }


def _confirmatory_variant_payload(
    evaluation: CandidateEvaluation,
    selection_evaluation: CandidateEvaluation | None,
    *,
    artifact_root: Path,
    baseline_score: float,
) -> dict[str, Any]:
    selection_score = (
        selection_evaluation.objective_score if selection_evaluation is not None else 0.0
    )
    selection_payload = (
        selection_evaluation.candidate.payload if selection_evaluation is not None else {}
    )
    selection_delta = float(
        selection_payload.get("selection_oos_delta_vs_incumbent")
        if selection_payload.get("selection_oos_delta_vs_incumbent") is not None
        else selection_score - baseline_score
    )
    return {
        "candidate_id": evaluation.candidate.candidate_id,
        "source_candidate_id": str(evaluation.candidate.payload.get("source_candidate_id") or ""),
        "variant_type": str(evaluation.candidate.payload.get("variant_type") or ""),
        "objective_score": evaluation.objective_score,
        "baseline_score": baseline_score,
        "in_sample_delta": evaluation.objective_score - baseline_score,
        "selection_oos_delta": selection_delta,
        "fold_support_passed": bool(evaluation.candidate.payload.get("fold_support_passed")),
        "deterministic_replay_passed": evaluation.passed,
        "materially_degrades_in_sample": evaluation.objective_score < baseline_score - 0.001,
        "evidence_paths": [
            str(artifact_root / "fold_score_matrix.json"),
            str(artifact_root / "selection_oos_evaluation.json"),
        ],
    }


def _load_accepted_mutation_chain(
    manifest: MonthlyRunManifest,
    artifact_root: Path,
) -> dict[str, Any]:
    raw_items: list[dict[str, Any]] = []
    guidance = manifest.monthly_search_guidance if isinstance(manifest.monthly_search_guidance, dict) else {}
    for item in guidance.get("accepted_mutations", []) or []:
        if isinstance(item, dict):
            raw_items.append(item)
    for path_text in _accepted_mutation_source_paths(manifest, artifact_root):
        path = Path(path_text)
        if not path.exists():
            continue
        if path.suffix.lower() == ".jsonl":
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                payload = item.get("payload") if isinstance(item, dict) else None
                if isinstance(payload, dict):
                    item = payload
                if isinstance(item, dict):
                    raw_items.append(item)
        else:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if isinstance(payload, dict):
                raw_items.extend(payload.get("accepted_mutations", []) or [])
                raw_items.extend(payload.get("records", []) or [])
            elif isinstance(payload, list):
                raw_items.extend(item for item in payload if isinstance(item, dict))
    mutations = _dedupe_mutations(
        [
            mutation
            for item in raw_items
            for mutation in [_normalize_accepted_mutation(item)]
            if mutation
        ]
    )
    return {
        "schema_version": "accepted_mutation_chain_v1",
        "run_id": manifest.run_id,
        "bot_id": manifest.bot_id,
        "strategy_id": manifest.strategy_id,
        "accepted_mutations": mutations,
        "source_paths": _accepted_mutation_source_paths(manifest, artifact_root),
    }


def _accepted_mutation_source_paths(
    manifest: MonthlyRunManifest,
    artifact_root: Path,
) -> list[str]:
    paths: list[str] = []
    for attr in (
        "strategy_change_ledger_path",
        "accepted_mutation_chain_path",
        "prior_rounds_manifest_path",
        "rounds_manifest_path",
    ):
        value = str(getattr(manifest, attr, "") or "").strip()
        if value:
            paths.append(value)
    guidance = manifest.monthly_search_guidance if isinstance(manifest.monthly_search_guidance, dict) else {}
    for value in guidance.get("accepted_mutation_source_paths", []) or []:
        if str(value):
            paths.append(str(value))
    candidate = artifact_root.parent / "strategy_change_ledger.jsonl"
    if candidate.exists():
        paths.append(str(candidate))
    return _dedupe_strings(paths)


def _normalize_accepted_mutation(item: dict[str, Any]) -> dict[str, Any] | None:
    record_type = str(item.get("record_type") or item.get("type") or "").lower()
    if record_type and record_type not in {
        "accepted_change",
        "implemented_change",
        "deployed_change",
        "record",
        "round",
        "adopted",
        "proposed_change",
    }:
        return None
    mutation_id = str(
        item.get("mutation_id")
        or item.get("candidate_id")
        or item.get("record_id")
        or item.get("round_id")
        or ""
    ).strip()
    if not mutation_id:
        return None
    mutation_diff = item.get("mutation_diff") if isinstance(item.get("mutation_diff"), dict) else {}
    return {
        "mutation_id": mutation_id,
        "first_accepted_round": str(
            item.get("first_accepted_round")
            or item.get("round_id")
            or item.get("run_month")
            or ""
        ),
        "strategy_scope": str(item.get("strategy_id") or item.get("strategy_scope") or ""),
        "config_scope": str(item.get("config_version") or item.get("new_config_version") or ""),
        "patch_path": str(item.get("patch_path") or item.get("config_patch_path") or ""),
        "parameter_diff": item.get("parameter_diff") or mutation_diff,
        "structural_diff": item.get("structural_diff") or item.get("file_changes") or [],
        "original_evidence_paths": item.get("evidence_paths", []) or [],
        "outcome_status": str(item.get("outcome_status") or item.get("monthly_status") or ""),
    }


def _dedupe_mutations(mutations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mutation in mutations:
        mutation_id = str(mutation.get("mutation_id") or "")
        if mutation_id in seen:
            continue
        seen.add(mutation_id)
        result.append(mutation)
    return result


def _round_n_plus_1_recommendation(
    manifest: MonthlyRunManifest,
    *,
    winner: CandidateEvaluation | None,
    replay_context: ReplayEvaluationContext,
    artifact_root: Path,
    no_adoption_reason: str,
) -> dict[str, Any]:
    if winner is None or replay_context.plugin is None:
        return {
            "schema_version": "round_n_plus_1_recommendation_v1",
            "run_id": manifest.run_id,
            "status": "no_adoption",
            "adopted_candidate_id": "",
            "no_adoption_reason": no_adoption_reason,
            "live_deployment_status": "not_requested",
        }
    output_dir = artifact_root / "round_n_plus_1"
    emitted = replay_context.plugin.write_round_n_plus_1(winner.candidate, output_dir)
    return {
        "schema_version": "round_n_plus_1_recommendation_v1",
        "run_id": manifest.run_id,
        "status": "optimized_backtest_recommendation",
        "adopted_candidate_id": winner.candidate.candidate_id,
        "next_round_id": manifest.next_round_id,
        "next_config_hash": emitted.get("next_config_hash", ""),
        "config_patch_path": emitted.get("config_patch_path", ""),
        "candidate_manifest_path": emitted.get("candidate_manifest_path", ""),
        "rollback_plan_path": emitted.get("rollback_plan_path", ""),
        "recommendation_path": emitted.get("path", ""),
        "parameter_patch_fingerprint": emitted.get(
            "parameter_patch_fingerprint",
            winner.candidate.payload.get("parameter_patch_fingerprint", ""),
        ),
        "evaluated_patch_fingerprint": emitted.get(
            "evaluated_patch_fingerprint",
            winner.candidate.payload.get("evaluated_patch_fingerprint", ""),
        ),
        "approval_state": "not_requested",
        "live_deployment_status": "optimized_backtest_recommendation",
    }


def _evaluation_baseline_score(
    evaluation: CandidateEvaluation,
    fallback: float,
) -> float:
    value = evaluation.candidate.payload.get("aggregate_fold_baseline_score")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    if parsed == 0.0 and fallback != 0.0:
        return fallback
    return parsed


def _stable_json_hash(value: Any) -> str:
    import hashlib

    raw = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _run_plan_phases(
    plan: OptimizerExperimentPlan,
    *,
    replay_context: ReplayEvaluationContext,
    fold_manifest,
    search_brief: dict[str, Any] | None = None,
) -> list[CandidateEvaluation]:
    evaluations: list[CandidateEvaluation] = []
    evaluator = None
    if replay_context.plugin is not None and replay_context.replay_backed:
        def evaluator(candidate):
            return score_candidate_on_folds(
                candidate=candidate,
                plugin=replay_context.plugin,
                baseline=replay_context.baseline,
                fold_manifest=fold_manifest,
            )

    phase_specs = _phase_specs_from_plan(plan)
    if replay_context.plugin is not None and replay_context.replay_backed:
        plugin_specs = replay_context.plugin.build_phase_specs(
            replay_context.diagnostics or {},
            plan,
            search_brief or {},
        )
        if plugin_specs:
            phase_specs = plugin_specs
    for phase in phase_specs:
        evaluations.extend(run_phase(phase, evaluator=evaluator))
    return evaluations


def _phase_specs_from_plan(plan: OptimizerExperimentPlan) -> list[PhaseSpec]:
    fallback_phase = plan.phase_order[0] if plan.phase_order else "signal_quality"
    phase_families: dict[str, list[str]] = {}
    for item in plan.candidate_families:
        if isinstance(item, dict):
            family = str(item.get("family") or item.get("candidate_family") or "").strip()
            phase_id = str(item.get("phase") or fallback_phase).strip() or fallback_phase
        else:
            family = str(item).strip()
            phase_id = fallback_phase
        if not family:
            continue
        phase_families.setdefault(phase_id, []).append(family)

    ordered_phases = [phase for phase in plan.phase_order if phase in phase_families]
    ordered_phases.extend(phase for phase in phase_families if phase not in ordered_phases)
    return [
        PhaseSpec(
            phase_id=phase_id,
            candidate_families=_dedupe_strings(phase_families[phase_id]),
        )
        for phase_id in ordered_phases
    ]


def _candidate_attempt(
    evaluation: CandidateEvaluation,
    manifest: MonthlyRunManifest,
    *,
    artifact_root: Path,
    source: MonthlyCandidateSource,
    workspace,
) -> CandidateAttemptRecord:
    state = CandidateAttemptState.SUCCEEDED if evaluation.passed else CandidateAttemptState.FAILED
    return CandidateAttemptRecord(
        attempt_id=f"{manifest.run_id}-{evaluation.candidate.candidate_id}-attempt-1",
        run_id=manifest.run_id,
        candidate_id=evaluation.candidate.candidate_id,
        workspace_key=workspace.workspace_key,
        workspace_path=workspace.workspace_path,
        state=state,
        stage=_source_stage(source),
        attempt_number=1,
        retry_attempt=0,
        retry_reason="",
        stall_timeout_seconds=manifest.stall_timeout_seconds,
        manifest_id=manifest.manifest_id,
        backtest_repo_commit_sha=manifest.backtest_repo_commit_sha,
        trading_repo_commit_sha=manifest.trading_repo_commit_sha,
        phase=str(evaluation.candidate.payload.get("phase_id") or ""),
        reason=_evaluation_reason(evaluation),
        artifact_paths=[
            str(artifact_root / "fold_manifest.json"),
            str(artifact_root / "fold_score_matrix.json"),
            str(artifact_root / "llm_experiment_plan.json"),
            str(artifact_root / "candidate_results.jsonl"),
            str(artifact_root / "selection_oos_evaluation.json"),
        ],
    )


def _candidate_result_row(
    evaluation: CandidateEvaluation,
    manifest: MonthlyRunManifest,
    *,
    artifact_root: Path,
    source: MonthlyCandidateSource,
    selected: bool,
    attempt: CandidateAttemptRecord | None = None,
    workspace=None,
    baseline_score: float = 0.0,
) -> dict:
    reason = _evaluation_reason(evaluation)
    candidate = evaluation.candidate
    phase_id = str(candidate.payload.get("phase_id") or "")
    runner_contract_version = _runner_contract_version(source)
    passed = bool(evaluation.passed)
    replay_backed = _evaluation_replay_backed(evaluation)
    baseline_score = _evaluation_baseline_score(evaluation, baseline_score)
    objective_delta = evaluation.objective_score - baseline_score
    gate_statuses = candidate.payload.get("no_regression_gate_statuses", {})
    if not isinstance(gate_statuses, dict):
        gate_statuses = {}
    fold_support_passed = bool(candidate.payload.get("fold_support_passed", passed))
    selected_round_id = manifest.next_round_id if selected else manifest.round_id
    selected_prior_round_id = manifest.round_id if selected else manifest.prior_round_id
    return {
        "run_id": manifest.run_id,
        "manifest_id": manifest.manifest_id,
        "round_id": selected_round_id,
        "prior_round_id": selected_prior_round_id,
        "next_round_id": manifest.next_round_id if selected else "",
        "candidate_id": candidate.candidate_id,
        "source": source.value,
        "bot_id": manifest.bot_id,
        "strategy_id": manifest.strategy_id,
        "family": candidate.family,
        "phase": phase_id,
        "title": f"{candidate.family} candidate",
        "description": reason or "deterministic phase candidate",
        "status": "selected" if selected else "rejected",
        "decision": "keep" if selected and passed else "reject",
        "change_kind": "parameter_change",
        "risk_classification": "medium",
        "objective_score": evaluation.objective_score,
        "baseline_score": baseline_score,
        "objective_delta": objective_delta,
        "objective_deltas": {
            "calibration": candidate.payload.get("aggregate_fold_objective_delta", objective_delta),
            "latest_month_oos": candidate.payload.get("selection_oos_delta", 0.0),
        },
        "parameter_patch_fingerprint": candidate.payload.get("parameter_patch_fingerprint", ""),
        "evaluated_patch_fingerprint": candidate.payload.get("evaluated_patch_fingerprint", ""),
        "reason": reason,
        "optimizer_stage": _source_stage(source).value,
        "deterministic_gate_inputs": {
            "phase4_sequence_valid": passed,
            "fold_support_passed": fold_support_passed,
            "purged_fold_support": candidate.payload.get("purged_fold_support", {}),
            "deterministic_replay_passed": replay_backed and fold_support_passed,
            "end_of_round_diagnostics_saved": True,
            "round_n_plus_1_adopted": bool(selected and passed),
            "live_backtest_parity_aligned": replay_backed,
            "runner_contract_version": runner_contract_version,
            "source_runner_contract_version": runner_contract_version,
            "manifest_id": manifest.manifest_id,
            "diagnostic_only": not replay_backed,
            "latest_month_oos_improvement": bool(
                candidate.payload.get("latest_month_oos_improvement", False)
            ),
            "latest_month_oos_delta": candidate.payload.get("selection_oos_delta", 0.0),
            "calibration_support": candidate.payload.get(
                "aggregate_fold_objective_delta",
                objective_delta,
            )
            > 0.0,
            "calibration_objective_delta": candidate.payload.get(
                "aggregate_fold_objective_delta",
                objective_delta,
            ),
            "leakage_passed": not bool(candidate.payload.get("selection_oos_used_in_first_pass")),
            "cost_gate_passed": bool(candidate.payload.get("cost_sensitivity_passed", False)),
            "drawdown_gate_passed": bool(candidate.payload.get("drawdown_gate_passed", False)),
            "outlier_concentration_passed": bool(
                candidate.payload.get("outlier_concentration_passed", False)
            ),
            "risk_constraints_passed": bool(
                candidate.payload.get("portfolio_synergy_passed", False)
            ),
            "sufficient_trade_count": all(
                int((row.get("candidate") or {}).get("trade_count", 0) or 0) > 0
                for row in candidate.payload.get("fold_metrics", [])
                if isinstance(row, dict)
            ),
            "no_regression_gate_statuses": gate_statuses,
        },
        "evidence_paths": [
            str(artifact_root / "fold_manifest.json"),
            str(artifact_root / "llm_experiment_plan.json"),
            str(artifact_root / "end_of_round_diagnostics.json"),
            str(artifact_root / "fold_score_matrix.json"),
            str(artifact_root / "selection_oos_evaluation.json"),
        ],
        "artifact_paths": [
            str(artifact_root / "candidate_results.jsonl"),
            str(artifact_root / "runner_observability.json"),
            str(artifact_root / "fold_candidate_results.jsonl"),
        ],
        "fold_manifest_path": str(artifact_root / "fold_manifest.json"),
        "rounds_manifest_path": str(artifact_root / "rounds_manifest.json"),
        "end_of_round_diagnostics_path": str(artifact_root / "end_of_round_diagnostics.json"),
        "confirmatory_rerank_path": str(artifact_root / "confirmatory_rerank.json"),
        "candidate_workspace_key": workspace.workspace_key if workspace is not None else "",
        "candidate_workspace_path": workspace.workspace_path if workspace is not None else "",
        "candidate_attempt_id": attempt.attempt_id if attempt is not None else "",
        "candidate_attempt_status": attempt.state.value if attempt is not None else "",
        "retry_attempt": attempt.retry_attempt if attempt is not None else 0,
        "retry_reason": attempt.retry_reason if attempt is not None else "",
        "stall_timeout_seconds": manifest.stall_timeout_seconds,
        "backtest_repo_commit_sha": manifest.backtest_repo_commit_sha,
        "live_trading_repo_commit_sha": manifest.trading_repo_commit_sha,
        "control_plane_commit_sha": manifest.control_plane_commit_sha,
        "workflow_contract_path": manifest.workflow_contract_path,
        "workflow_contract_version": manifest.workflow_contract_version,
        "score_component_count": manifest.score_component_cap,
        "max_workers": manifest.max_workers,
        "source_weekly_signal_ids": manifest.source_weekly_signal_ids,
        "raw_payload": {
            "phase_id": phase_id,
            "candidate_family": candidate.family,
            "candidate_payload": candidate.payload,
            "replay_backed": replay_backed,
        },
        "acceptance_criteria": [
            "both purged in-sample folds improve the incumbent objective",
            "selection-OOS remains within the declared degradation thresholds",
            "no-regression gates pass for drawdown, costs, outliers, and synergy",
        ],
        "rollback_plan": str(candidate.payload.get("rollback_plan_ref") or "restore round_N config"),
    }


def _runner_observability(
    manifest: MonthlyRunManifest,
    attempts: list[CandidateAttemptRecord],
    *,
    reason: str,
    planner_mode: str,
) -> list[dict]:
    if not attempts:
        return [
            runner_event(
                manifest,
                phase="eligibility",
                status="blocked",
                planner_mode=planner_mode,
                reason=reason,
            )
        ]
    return [
        runner_event(
            manifest,
            phase=attempt.phase or attempt.stage.value,
            status=attempt.state.value,
            attempt_id=attempt.attempt_id,
            candidate_id=attempt.candidate_id,
            planner_mode=planner_mode,
            reason=attempt.reason,
        )
        for attempt in attempts
    ]


def _optimizer_decision_reason(
    manifest: MonthlyRunManifest,
    data_errors: list[str],
    evaluations: list[CandidateEvaluation],
    winner: CandidateEvaluation | None,
) -> str:
    if winner is not None:
        return f"adopted {winner.candidate.candidate_id} after deterministic phase gates"
    if data_errors:
        return _no_adoption_reason(manifest, data_errors)
    if evaluations:
        return phase_no_adoption_reason(
            evaluations,
            "no candidate passed deterministic replay gates",
        )
    return _no_adoption_reason(manifest, data_errors)


def _source_stage(source: MonthlyCandidateSource) -> OptimizerStage:
    if source == MonthlyCandidateSource.SMOKE_REPAIR:
        return OptimizerStage.OOS_REPAIR
    return OptimizerStage.PHASED_AUTO


def _runner_contract_version(source: MonthlyCandidateSource) -> str:
    if source == MonthlyCandidateSource.SMOKE_REPAIR:
        return SMOKE_REPAIR_RUNNER_CONTRACT_VERSION
    return PHASED_AUTO_RUNNER_CONTRACT_VERSION


def _evaluation_reason(evaluation: CandidateEvaluation) -> str:
    return "; ".join(reason for reason in evaluation.reasons if reason)


def _evaluation_replay_backed(evaluation: CandidateEvaluation) -> bool:
    return bool(
        evaluation.candidate.payload.get("replay_result")
        or evaluation.candidate.payload.get("fold_metrics")
        or evaluation.candidate.payload.get("selection_oos_replay_result")
    )


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _write_structural_placeholders(
    writer: ArtifactWriter,
    manifest: MonthlyRunManifest,
    bundle: DataBundleManifest | None,
) -> None:
    patch_artifacts = [
        "live_repo_patch.diff",
        "backtest_adapter_patch.diff",
        "config_patch.diff",
    ]
    writer.write_json(
        "structural_candidate_plan.json",
        {
            "schema_version": "structural_candidate_plan_v1",
            "run_id": manifest.run_id,
            "status": "blocked",
            "reason": "no structural candidate adopted by deterministic runner",
            "selection_gate_path": str(writer.path("structural_selection_gate.json")),
            "required_patch_artifacts": patch_artifacts,
        },
    )
    writer.write_text(
        "live_repo_patch.diff",
        "# No live repo patch generated for deterministic no-adoption run.\n",
    )
    writer.write_text(
        "backtest_adapter_patch.diff",
        "# No backtest adapter patch generated for deterministic no-adoption run.\n",
    )
    writer.write_text(
        "config_patch.diff",
        "# No config patch generated for deterministic no-adoption run.\n",
    )
    parity_report = _structural_decision_parity_report(writer, manifest, bundle)
    writer.write_json("decision_parity_report.json", parity_report)
    writer.write_json(
        "structural_selection_gate.json",
        _structural_selection_gate_payload(
            writer,
            manifest,
            parity_report=parity_report,
            patch_artifacts=patch_artifacts,
        ),
    )


def _structural_selection_gate_payload(
    writer: ArtifactWriter,
    manifest: MonthlyRunManifest,
    *,
    parity_report: DecisionParityReport,
    patch_artifacts: list[str],
) -> dict[str, Any]:
    patch_checks = [
        _structural_patch_check(writer.path(artifact_name), artifact_name=artifact_name)
        for artifact_name in patch_artifacts
    ]
    parity_passed = bool(parity_report.eligible_for_structural_approval)
    blocking_reasons = [
        f"{item['artifact_name']} is not a real patch artifact"
        for item in patch_checks
        if not item["usable_for_structural_selection"]
    ]
    if not parity_passed:
        blocking_reasons.append(
            f"decision parity report status is {parity_report.status.value}"
        )
    selection_allowed = not blocking_reasons
    return {
        "schema_version": "structural_selection_gate_v1",
        "run_id": manifest.run_id,
        "manifest_id": manifest.manifest_id,
        "candidate_id": (
            parity_report.candidate_id
            if parity_report.candidate_id not in {"", "no-adoption"}
            else ""
        ),
        "status": "selection_ready" if selection_allowed else "blocked",
        "selection_allowed": selection_allowed,
        "change_kind": "structural_change",
        "patch_checks": patch_checks,
        "decision_parity": {
            "report_path": str(writer.path("decision_parity_report.json")),
            "status": parity_report.status.value,
            "eligible_for_structural_approval": parity_passed,
            "strategy_plugin_id": parity_report.strategy_plugin_id,
            "live_repo_commit_sha": parity_report.live_repo_commit_sha,
            "backtest_adapter_commit_sha": parity_report.backtest_adapter_commit_sha,
            "evidence_paths": parity_report.evidence_paths,
        },
        "blocking_reasons": blocking_reasons,
        "required_before_selection": [
            "live_repo_patch.diff",
            "backtest_adapter_patch.diff",
            "config_patch.diff",
            "decision_parity_report.json:pass",
        ],
        "evidence_paths": [
            str(writer.path("structural_candidate_plan.json")),
            str(writer.path("decision_parity_report.json")),
            *[str(writer.path(name)) for name in patch_artifacts],
        ],
    }


def _structural_patch_check(path: Path, *, artifact_name: str) -> dict[str, Any]:
    exists = path.exists()
    text = path.read_text(encoding="utf-8") if exists else ""
    stripped = text.strip()
    has_diff_marker = (
        stripped.startswith(("diff --git", "--- ", "+++ ", "@@ "))
        or any(marker in stripped for marker in ("\ndiff --git", "\n--- ", "\n+++ ", "\n@@ "))
    )
    usable = bool(stripped) and not stripped.startswith("# No ") and has_diff_marker
    return {
        "artifact_name": artifact_name,
        "path": str(path),
        "exists": exists,
        "non_empty": bool(stripped),
        "placeholder": stripped.startswith("# No "),
        "has_diff_marker": has_diff_marker,
        "usable_for_structural_selection": usable,
    }


def _structural_decision_parity_report(
    writer: ArtifactWriter,
    manifest: MonthlyRunManifest,
    bundle: DataBundleManifest | None,
) -> DecisionParityReport:
    fallback = insufficient_decision_parity_report(
        manifest,
        candidate_id="no-adoption",
        evidence_path=writer.path("end_of_round_diagnostics.json"),
    )
    if not manifest.strategy_plugin_contract_path:
        return fallback
    contract, errors = load_strategy_plugin_contract(manifest.strategy_plugin_contract_path)
    if errors or contract is None:
        return _failed_decision_parity_report(
            manifest,
            candidate_id="strategy-plugin-contract",
            errors=errors or ["strategy plugin contract is unavailable"],
            evidence_paths=[manifest.strategy_plugin_contract_path],
        )
    validation_errors = strategy_plugin_errors(manifest, bundle)
    if validation_errors:
        return _failed_decision_parity_report(
            manifest,
            candidate_id="strategy-plugin-contract",
            errors=validation_errors,
            evidence_paths=[manifest.strategy_plugin_contract_path],
        )
    wired = _STRUCTURAL_PARITY_BUILDERS.get(contract.plugin_id)
    if wired is None:
        return fallback
    expected_api_version, builder = wired
    if contract.decision_api_version != expected_api_version:
        return _failed_decision_parity_report(
            manifest,
            candidate_id="strategy-plugin-contract",
            errors=[
                "strategy plugin contract decision_api_version does not match "
                "the wired decision API"
            ],
            evidence_paths=[manifest.strategy_plugin_contract_path],
        )
    if not contract.parity_fixture_set:
        return _failed_decision_parity_report(
            manifest,
            candidate_id="strategy-plugin-contract",
            errors=["strategy plugin contract has no parity_fixture_set"],
            evidence_paths=[manifest.strategy_plugin_contract_path],
        )
    try:
        return builder(
            manifest,
            candidate_id="strategy-plugin-contract",
            fixture_paths=contract.parity_fixture_set,
            live_repo_path=contract.live_repo_path,
            live_repo_commit_sha=contract.live_repo_commit_sha,
            backtest_adapter_commit_sha=contract.backtest_adapter_commit_sha,
        )
    except Exception as exc:
        return _failed_decision_parity_report(
            manifest,
            candidate_id="strategy-plugin-contract",
            errors=[f"strategy plugin decision parity failed: {exc}"],
            evidence_paths=[manifest.strategy_plugin_contract_path, *contract.parity_fixture_set],
        )


def _failed_decision_parity_report(
    manifest: MonthlyRunManifest,
    *,
    candidate_id: str,
    errors: list[str],
    evidence_paths: list[str],
) -> DecisionParityReport:
    notes = "; ".join(errors)
    return DecisionParityReport(
        run_id=manifest.run_id,
        candidate_id=candidate_id,
        strategy_plugin_id=manifest.strategy_plugin_id,
        live_repo_commit_sha=manifest.trading_repo_commit_sha,
        backtest_adapter_commit_sha=manifest.backtest_repo_commit_sha,
        status=DecisionParityStatus.FAIL,
        evidence_paths=evidence_paths,
        checks=[
            DecisionParityCheck(
                dimension=dimension,
                status=DecisionParityStatus.FAIL,
                match_rate=0.0,
                mismatch_count=1,
                notes=notes,
                evidence_paths=evidence_paths,
            )
            for dimension in sorted(DECISION_PARITY_DIMENSIONS)
        ],
    )


def _raise_on_local_index_errors(
    manifest: MonthlyRunManifest, index: BacktestArtifactIndex
) -> None:
    errors = index.validation_errors(
        expected_run_id=manifest.run_id,
        expected_manifest_id=manifest.manifest_id,
        require_manifest_id=manifest.optimizer_mode,
    )
    if errors:
        raise RuntimeError("; ".join(errors))


def _mode_status(manifest: MonthlyRunManifest) -> str:
    if manifest.optimizer_mode:
        return "no_adoption"
    return "no_change"


def _mode_reason(manifest: MonthlyRunManifest) -> str:
    if manifest.optimizer_mode:
        return "deterministic runner found no approval-ready replay-backed candidate"
    return "incumbent validation artifacts emitted"


def _no_adoption_reason(manifest: MonthlyRunManifest, data_errors: list[str]) -> str:
    if data_errors:
        return "blocked by data bundle validation: " + "; ".join(data_errors)
    if manifest.strategy_plugin_id:
        return "strategy plugin emitted no replay-backed approval-ready candidate"
    return "insufficient mature replay plugin sample size"


def _stdout_summary(manifest: MonthlyRunManifest, exit_code: int, errors: list[str]) -> str:
    lines = [
        f"run_id={manifest.run_id}",
        f"mode={manifest.mode.value}",
        f"artifact_root={manifest.artifact_root}",
        f"exit_code={exit_code}",
    ]
    lines.extend(f"error={error}" for error in errors)
    return "\n".join(lines) + "\n"


def _monthly_report(manifest: MonthlyRunManifest, status: str, errors: list[str]) -> str:
    lines = [
        f"# Monthly Backtest Report: {manifest.run_id}",
        "",
        f"- Mode: `{manifest.mode.value}`",
        f"- Bot: `{manifest.bot_id}`",
        f"- Strategy: `{manifest.strategy_id}`",
        f"- Status: `{status}`",
        "- Live deployment: `not_requested`",
    ]
    if errors:
        lines.append(f"- Blocking reasons: {'; '.join(errors)}")
    elif manifest.optimizer_mode:
        lines.append("- Decision: no adoption; deterministic gates require a mature replay plugin.")
    else:
        lines.append("- Decision: incumbent validation only.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
