# Synthetic failure examples

These examples use synthetic messages. They document observed development failures and intentionally exercised safety paths, not customer incidents.

## Structured output omitted a required field

- **Input:** A synthetic failed-payment complaint with a transaction reference.
- **Expected:** A schema-valid classification and response draft.
- **Observed:** The provider rejected generated JSON because `draft_response` was missing.
- **System response:** The case was recorded as a model request failure instead of accepting partial output.
- **Status:** The strict schema remains intentional. The public benchmark reports this as `structured_output_error` without exposing provider account details.

## Provider quota interrupted the full benchmark

- **Input:** The 100-case synthetic gold dataset.
- **Expected:** All 100 cases processed in one resumable run.
- **Observed:** The provider quota stopped the run after 24 successful cases.
- **System response:** Successful predictions were checkpointed and the release gate remained failed because the run was incomplete.
- **Status:** The portfolio does not claim a completed 100-case live result.

## Unsafe credential request

- **Input:** A synthetic account-access complaint paired with a draft asking for an OTP and password.
- **Expected:** No request for authentication secrets.
- **Observed:** The deterministic guardrail identified the unsafe request.
- **System response:** Kora replaced the draft with a safe human-review response and explicitly warned the customer not to share credentials.
- **Test:** `test_sensitive_data_request_is_replaced`.

## Invented external action

- **Input:** A synthetic draft claiming that Kora generated a reset link, checked tracking, or contacted a courier.
- **Expected:** No claim about an action the system did not perform.
- **Observed:** The deterministic guardrail matched the unsupported action.
- **System response:** Kora replaced the claim with an inspectable review step.
- **Test:** `test_unverified_external_actions_are_replaced`.

## Label disagreement in the demonstration queue

- **Input:** Four of the 18 stored demonstration snapshots.
- **Expected:** The reference intent and urgency labels attached to the synthetic case.
- **Observed:** One intent and three urgency predictions differ from their references.
- **System response:** Insights display the disagreement instead of hiding it, producing 32 correct labels from 36 comparisons (89%).
- **Status:** This is a UI demonstration of correction and evaluation behavior, not a live model benchmark.
