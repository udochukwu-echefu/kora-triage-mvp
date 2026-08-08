from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter

from .benchmark import score_predictions
from .config import settings
from .evaluation_dataset import GOLD_CASES, dataset_summary
from .groq_triage import GroqTriageModel
from .schemas import CustomerContext, TriageRequest
from .service import _redacted_request
from .triage_policy import apply_operational_policy


SMOKE_CASE_IDS = (
    "EVAL-TRANSFER-01-01",
    "EVAL-PAYMENT-01-03",
    "EVAL-DUPLICATE-01-01",
    "EVAL-FRAUD-01-03",
    "EVAL-DELAY-01-02",
    "EVAL-MISSING-01-02",
    "EVAL-CHANGE-01-03",
    "EVAL-ACCESS-01-01",
    "EVAL-VERIFY-01-02",
    "EVAL-REFUND-01-02",
    "EVAL-FEE-01-01",
)


def _prediction(result) -> dict:
    return {
        "intent": result.intent.value,
        "urgency": result.urgency.value,
        "route": result.route.value,
        "sentiment": result.sentiment.value,
        "confidence": result.confidence,
        "entities": {
            "amount": result.entities.amount,
            "transactionId": result.entities.transaction_id,
            "orderId": result.entities.order_id,
            "account": (
                f"••••••{result.entities.account_last4}"
                if result.entities.account_last4
                else None
            ),
            "card": (
                f"•••• {result.entities.card_last4}"
                if result.entities.card_last4
                else None
            ),
        },
    }


def _nearest_rank(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, round(percentile * len(ordered) + 0.499999))
    return ordered[min(rank - 1, len(ordered) - 1)]


def _measurement_summary(measurements: dict[str, dict]) -> dict:
    rows = list(measurements.values())
    latencies = [int(row["latency_ms"]) for row in rows]
    prompt_tokens = [row.get("prompt_tokens") for row in rows]
    completion_tokens = [row.get("completion_tokens") for row in rows]
    total_tokens = [row.get("total_tokens") for row in rows]

    def token_summary(values: list[int | None]) -> dict:
        known = [int(value) for value in values if value is not None]
        return {
            "measured_cases": len(known),
            "total": sum(known) if known else None,
            "average": round(sum(known) / len(known), 1) if known else None,
        }

    return {
        "latency_ms": {
            "measured_cases": len(latencies),
            "min": min(latencies) if latencies else None,
            "median": round(median(latencies), 1) if latencies else None,
            "p95": _nearest_rank(latencies, 0.95),
            "max": max(latencies) if latencies else None,
        },
        "tokens": {
            "prompt": token_summary(prompt_tokens),
            "completion": token_summary(completion_tokens),
            "total": token_summary(total_tokens),
        },
    }


def _git_sha() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_dirty() -> bool | None:
    try:
        return bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def _public_error(error: Exception) -> tuple[str, str]:
    detail = str(error).lower()
    if "rate_limit" in detail or "rate limit" in detail or "quota" in detail:
        return "provider_rate_limit", "Provider quota or rate limiting interrupted this case."
    if "json_validate_failed" in detail or "expected schema" in detail:
        return "structured_output_error", "The provider rejected model output that did not match the required schema."
    return "model_request_error", "The model request failed. Private provider details were removed from this public report."


async def run(
    limit: int | None,
    delay: float,
    case_ids: list[str] | None = None,
    checkpoint_path: Path | None = None,
    resume: bool = False,
    run_label: str = "live_gold_benchmark",
) -> dict:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is required to run the live gold-set evaluation.")
    cases = list(GOLD_CASES)
    if case_ids:
        selected = set(case_ids)
        cases = [
            case
            for case in cases
            if case.case_id in selected
            or case.case_id.rsplit("-", 1)[0] in selected
        ]
        matched = {
            value
            for case in cases
            for value in (case.case_id, case.case_id.rsplit("-", 1)[0])
        }
        missing = selected - matched
        if missing:
            raise RuntimeError(
                f"Unknown evaluation case or scenario: {', '.join(sorted(missing))}"
            )
    if limit:
        cases = cases[:limit]
    model = GroqTriageModel(settings.groq_api_key, settings.groq_model)
    predictions: dict[str, dict] = {}
    measurements: dict[str, dict] = {}
    errors: list[dict] = []
    if resume and checkpoint_path and checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("model") != settings.groq_model:
            raise RuntimeError(
                "Checkpoint model does not match GROQ_MODEL; remove the checkpoint "
                "or resume with the same model."
            )
        predictions.update(checkpoint.get("predictions", {}))
        measurements.update(checkpoint.get("measurements", {}))
    started_at = datetime.now(UTC).isoformat()
    started = perf_counter()

    for index, case in enumerate(cases, start=1):
        if case.case_id in predictions:
            print(
                f"[{index:03d}/{len(cases):03d}] {case.case_id} (checkpoint)",
                flush=True,
            )
            continue
        request = TriageRequest(
            case_id=case.case_id,
            channel=case.channel,
            subject=case.subject,
            message=case.message,
            customer=CustomerContext(
                customer_id=f"CUSTOMER-{case.case_id}",
                name="Evaluation Customer",
            ),
        )
        safe_request, deterministic = _redacted_request(request)
        case_started = perf_counter()
        try:
            result, usage = await model.classify_with_metadata(safe_request, [])
            result = apply_operational_policy(safe_request, result).triage
            if deterministic.get("account_last4") and not result.entities.account_last4:
                result = result.model_copy(
                    update={
                        "entities": result.entities.model_copy(
                            update={
                                "account_last4": deterministic["account_last4"]
                            }
                        )
                    }
                )
            predictions[case.case_id] = _prediction(result)
            measurements[case.case_id] = {
                "latency_ms": round((perf_counter() - case_started) * 1000),
                **usage,
            }
        except Exception as error:
            error_type, public_message = _public_error(error)
            errors.append(
                {
                    "case_id": case.case_id,
                    "latency_ms": round((perf_counter() - case_started) * 1000),
                    "error_type": error_type,
                    "error": public_message,
                }
            )
            if "rate_limit" in str(error).lower() or "rate limit" in str(error).lower():
                print(
                    f"[{index:03d}/{len(cases):03d}] {case.case_id} "
                    "(quota reached; checkpoint saved)",
                    flush=True,
                )
                if checkpoint_path:
                    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                    checkpoint_path.write_text(
                        json.dumps(
                            {
                                "model": settings.groq_model,
                                "predictions": predictions,
                                "measurements": measurements,
                            },
                            indent=2,
                            ensure_ascii=False,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                break
        print(
            f"[{index:03d}/{len(cases):03d}] {case.case_id}",
            flush=True,
        )
        if checkpoint_path:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_path.write_text(
                json.dumps(
                    {
                        "model": settings.groq_model,
                        "predictions": predictions,
                        "measurements": measurements,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
        if delay and index < len(cases):
            await asyncio.sleep(delay)

    report = score_predictions(cases, predictions)
    report.update(
        {
            "run": {
                "label": run_label,
                "started_at": started_at,
                "git_sha": _git_sha(),
                "git_dirty": _git_dirty(),
                "complete": len(predictions) == len(cases),
                "synthetic_data": True,
            },
            "model": settings.groq_model,
            "elapsed_seconds": round(perf_counter() - started, 2),
            "measurements": measurements,
            "measurement_summary": _measurement_summary(measurements),
            "errors": errors,
            "dataset": dataset_summary(cases),
        }
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Kora's labelled Groq benchmark.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--case-id",
        action="append",
        default=None,
        help=(
            "Run one exact case ID or all four variants in a scenario prefix. "
            "Repeat this option to select several cases."
        ),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.75,
        help="Seconds between requests to stay within Groq token limits.",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run the fixed 11-case synthetic smoke set covering every supported intent.",
    )
    parser.add_argument(
        "--run-label",
        default=None,
        help="Evidence label stored in the generated report.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume successful predictions from the output checkpoint.",
    )
    args = parser.parse_args()
    if args.smoke and (args.limit or args.case_id):
        parser.error("--smoke cannot be combined with --limit or --case-id")
    selected_case_ids = list(SMOKE_CASE_IDS) if args.smoke else args.case_id
    run_label = args.run_label or ("live_smoke" if args.smoke else "live_gold_benchmark")
    checkpoint_path = (
        args.output.with_suffix(".checkpoint.json") if args.output else None
    )
    report = asyncio.run(
        run(
            args.limit,
            args.delay,
            selected_case_ids,
            checkpoint_path=checkpoint_path,
            resume=args.resume,
            run_label=run_label,
        )
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
