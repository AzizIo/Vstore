# Notification outbox operations

The Telegram notification outbox is written in the same database transaction as the corresponding order/delivery state change. The bot process runs the worker that claims due rows, sends Telegram messages and schedules retries.

Use the read-only diagnostic from the backend directory:

```bash
python -m scripts.notification_outbox_health
```

For machine-readable output:

```bash
python -m scripts.notification_outbox_health --json
```

The oldest due message age can be given a different alert threshold (default: 300 seconds):

```bash
python -m scripts.notification_outbox_health --max-due-age-seconds 600
```

The command opens the configured database connection and executes one aggregate SELECT. It does not claim, retry, update, lock or delete rows; it does not contact Telegram. Output contains aggregate counts and durations only. It never prints recipient identifiers, message content, order IDs, raw provider errors or connection settings.

## Interpreting the result

- `healthy`: no permanently failed rows, no processing rows with an absent/expired lease, and the oldest due pending row is at or below the configured age threshold.
- `degraded`: at least one of those conditions is present. Inspect the bot/worker logs and database state before taking manual action.
- Future-scheduled pending rows are expected during retry backoff and are not counted as due.
- Active processing leases are expected while a worker is sending a message.
- The diagnostic cannot prove that Telegram delivered a message to a person; `delivered` means the Telegram API accepted the send request.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Healthy |
| 1 | Degraded queue health |
| 2 | Diagnostic/configuration/database error |

A database error is never reported as healthy. The script intentionally emits a generic error instead of an exception string because database-driver errors can contain connection details.

## JSON contract

The JSON document contains:

- `status`: `healthy` or `degraded`;
- `sampled_at`: UTC timestamp;
- `thresholds.max_due_age_seconds`;
- `counts`: total and counts by outbox status;
- `due_pending_count` and `expired_processing_lease_count`;
- `oldest_due_pending_age_seconds` and `oldest_failed_age_seconds` (null when absent);
- `degraded_reasons`: stable reason codes.

This command is operational visibility only. It does not introduce an automatic retry, manual redrive, message deletion or payment behavior.
