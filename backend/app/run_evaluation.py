from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter

from .benchmark import score_predictions
from .config import settings
from .evaluation_dataset import GOLD_CASES, dataset_summary
from .groq_triage import GroqTriageModel
from .schemas import CustomerContext, TriageRequest
from .service import _redacted_request
from .triage_policy import apply_operational_policy


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


async def run(
    limit: int | None,
    delay: float,
    case_ids: list[str] | None = None,
    checkpoint_path: Path | None = None,
    resume: bool = False,
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
    errors: list[dict] = []
    if resume and checkpoint_path and checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("model") != settings.groq_model:
            raise RuntimeError(
                "Checkpoint model does not match GROQ_MODEL; remove the checkpoint "
                "or resume with the same model."
            )
        predictions.update(checkpoint.get("predictions", {}))
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
        try:
            result = await model.classify(safe_request, [])
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
        except Exception as error:
            errors.append({"case_id": case.case_id, "error": str(error)})
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
            "model": settings.groq_model,
            "elapsed_seconds": round(perf_counter() - started, 2),
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
        "--resume",
        action="store_true",
        help="Resume successful predictions from the output checkpoint.",
    )
    args = parser.parse_args()
    checkpoint_path = (
        args.output.with_suffix(".checkpoint.json") if args.output else None
    )
    report = asyncio.run(
        run(
            args.limit,
            args.delay,
            args.case_id,
            checkpoint_path=checkpoint_path,
            resume=args.resume,
        )
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
