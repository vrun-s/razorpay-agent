# Test fixtures

## `real_subscription_halted.json` (ticket 20)

Not committed until captured. Drop a **real** Razorpay test-mode `subscription.halted`
webhook body here (the full JSON envelope, exactly as received) and
`test_real_subscription_halted.py` stops skipping and runs the real payload through the
ingestion path (`app/routers/webhooks.py::_extract_halted_subscription` ->
`create_case_from_halted_subscription` -> one decision cycle -> event-id dedupe).

How to capture it:

1. Run the local backend against real test mode + the `ssh -R` tunnel. The
   step-by-step is `scripts/ticket-20-halted-slice-wizard.sh` (run from the repo
   root).
2. Get the exact bytes one of two ways:
   - read the request body from the Razorpay dashboard's webhook delivery log, or
   - run the capture proxy the wizard starts
     (`test-scripts/capture_halted_webhook.py`, gitignored local tooling) in
     front of the backend -- it writes
     `test-scripts/captured/subscription-halted-<ts>.json`, and that file's
     `body_json` field is what goes here.
3. Sanitise: the payload carries no card data, but scrub `customer_id` / `email` /
   any `notes` if they identify a real person. Keep the structural shape intact.

The synthetic counterpart lives in `conftest.py::synthetic_subscription_halted_payload`;
the real fixture exists to catch a real-vs-synthetic field-shape drift.
