# Plan 5b: Mark Sent + Follow-up Lifecycle

> **For agentic workers:** Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement spec §5.1 steps 19-26 — operator marks a proposal as sent, a `FollowUp` is scheduled +3d, the worker fires a reminder to the operator, and the operator records the client's response.

**Architecture:** Reuses Plan 5a infrastructure (scheduler, worker, registry, repositories). No new infra; only domain logic + bot wiring.

---

## Branch

```powershell
cd C:\Repos\reyzbikh_buro_crm
git checkout main
git pull --ff-only origin main
git checkout -b plan-5b-mark-sent-and-followup
```

Tag at the end: `plan-5b-mark-sent-and-followup`.

---

## Prerequisites (already in place from Plan 5a)

- `enqueue_job`, `apply_backoff`, `LEASE_TIMEOUT` in `crm.scheduler.jobs`.
- `JOB_HANDLERS`, `register_handler` in `crm.scheduler.handlers`.
- `run_worker` poll loop with reclaim, pick, finalize_done/reschedule/terminal.
- Worker entrypoint with `_register_all_handlers`.
- `FollowUpRepository` with `list_due` (Plan 2).
- 96 tests passing.

---

## File Structure (created/modified)

```
src/crm/
  use_cases/
    mark_proposal_sent.py       NEW
    send_follow_up.py           NEW
    record_follow_up_result.py  NEW
  entrypoints/
    bot.py                      MODIFY (mark_sent + 3 outcome callbacks)
    worker.py                   MODIFY (register send_follow_up handler)
  db/repositories/
    follow_ups.py               MODIFY (add get_by_id - optional helper)

tests/
  unit/
    test_mark_proposal_sent_unit.py
    test_send_follow_up_unit.py
    test_record_follow_up_result_unit.py
  integration/
    test_mark_proposal_sent.py
    test_send_follow_up.py
    test_record_follow_up_result.py
    test_bot_mark_sent_callback.py
    test_bot_follow_up_outcome.py
    test_worker_send_follow_up.py     # end-to-end via worker

README.md                       MODIFY
```

---

## Domain decisions

### `mark_proposal_sent`
- Accepts: `container, proposal_id, operator_user_id`.
- Rejects if `proposal.status != draft` (idempotency via UI gate — button removed after success).
- Single TX:
  - `Proposal.status=sent, sent_at=now`
  - `Lead.status=proposal_sent`
  - `INSERT FollowUp(proposal_id, kind=status_check, scheduled_for=now+3d, channel=telegram, status=pending, message_template=<rendered text>)`
  - `enqueue_job("send_follow_up", payload={"follow_up_id": <id>}, run_at=scheduled_for, idempotency_key=f"send_follow_up:{follow_up_id}", max_attempts=5)`
  - Events: `proposal.sent`, `follow_up.scheduled`.

Follow-up text (hardcoded f-string in v1):
```
⏰ 3 дня назад отправили Proposal #{proposal_id} (lead #{lead_id}). Клиент откликнулся?
```

### `send_follow_up`
- Accepts: `container, follow_up_id`.
- Reads FollowUp; **idempotent** — if `status != pending`, no-op and return.
- Outside TX: `telegram_sender.send_message(chat_id=operator[0], text=follow_up.message_template, reply_markup=<outcome keyboard>)`. The outcome keyboard has 3 buttons:
  - `follow_up_outcome:{id}:accepted`
  - `follow_up_outcome:{id}:declined`
  - `follow_up_outcome:{id}:waiting`
- TX: `UPDATE FollowUp(status=sent, sent_at=now)`. Event `follow_up.sent`.
- Bot `Bot.send_message` is the underlying call but in tests we pass keyboard via `reply_markup` kwarg into the mocked sender. The real sender accepts `reply_markup`.

### Worker handler `handle_send_follow_up`
Thin shim: `await send_follow_up(container, follow_up_id=job.payload["follow_up_id"])`.

### `record_follow_up_result`
- Accepts: `container, follow_up_id, outcome (FollowUpOutcome), notes (str), operator_user_id`.
- `FollowUpOutcome` enum: `accepted, declined, waiting`.
- Rejects if `follow_up.status != sent`.
- TX:
  - `FollowUp.result_notes = notes` (always).
  - If `outcome == accepted`: `Proposal.status=accepted, responded_at=now`, `Lead.status=accepted`. Event `proposal.accepted`.
  - If `outcome == declined`: `Proposal.status=declined, responded_at=now`, `Lead.status=declined`. Event `proposal.declined`.
  - If `outcome == waiting`: only `follow_up.result_recorded` event.
- Always emit `follow_up.result_recorded`.

### Bot callbacks (added to `bot.py`)
- `MARK_SENT_PREFIX = "mark_sent:"` — calls `mark_proposal_sent`, replies with "Proposal отправлен. Напоминание через 3 дня."
- `FOLLOW_UP_PREFIX = "follow_up_outcome:"` — parses `{id}:{outcome}`, calls `record_follow_up_result(notes="(via inline button)")`.

### GDocs handler notification (modify `_send_operator_link`)
After publication, attach an inline keyboard with the "✅ Отправлено клиенту" button. Worker can send `reply_markup` via the telegram_sender — the real `aiogram.Bot.send_message` accepts it; the test fakes capture it.

---

## Task list (7 tasks)

### T1: `mark_proposal_sent` use case
- Create `src/crm/use_cases/mark_proposal_sent.py` with `ProposalNotInDraftError`.
- Unit tests (mock UoW): happy path inserts FollowUp + enqueues job + updates Proposal/Lead; error path for non-draft.
- Integration test: end-to-end with real DB.
- Expected: 92 → ~97 passed (3-4 unit + 3-4 integration).
- Commit: `feat(use_cases): mark_proposal_sent transitions proposal + schedules follow-up`

### T2: GDocs notification keyboard + bot `on_mark_sent` callback
- Modify `_send_operator_link` in `publish_proposal_to_gdoc.py` to attach an inline keyboard with `mark_sent:{proposal_id}` button.
- Add `MARK_SENT_PREFIX` constant + `on_mark_sent` callback in `bot.py`.
- Integration test for the bot callback (replicates pattern from `test_bot_publish_callback`).
- Update `test_worker_publish_gdoc.py` if it asserts the captured notification has no `reply_markup` (likely doesn't but verify).
- Commit: `feat(bot): mark_sent callback transitions proposal sent + schedules reminder`

### T3: `send_follow_up` use case
- Create `src/crm/use_cases/send_follow_up.py` with `FollowUpNotPendingError`.
- Inline rendering of the outcome keyboard (define helper `_outcome_keyboard(follow_up_id)`) — keyboard built using `aiogram.types.InlineKeyboardMarkup`/`InlineKeyboardButton`.
- Unit tests: pending → sends + marks sent; non-pending → no-op.
- Integration test.
- Commit: `feat(use_cases): send_follow_up sends reminder + marks follow-up sent`

### T4: Worker handler for `send_follow_up`
- In `src/crm/use_cases/send_follow_up.py`, add `JOB_TYPE_SEND_FOLLOW_UP = "send_follow_up"` and `handle_send_follow_up(container, job)` shim.
- Modify `src/crm/entrypoints/worker.py` to register it alongside `publish_proposal_to_gdoc`.
- End-to-end integration test `test_worker_send_follow_up.py`: mark_proposal_sent → pick job → worker runs handler → FollowUp marked sent + Telegram captured.
- Commit: `feat(scheduler): send_follow_up worker handler + registration`

### T5: `record_follow_up_result` use case + `FollowUpOutcome` enum
- Create `src/crm/use_cases/record_follow_up_result.py`.
- Define `FollowUpOutcome(StrEnum): accepted, declined, waiting`.
- `FollowUpNotSentError` for invalid transitions.
- 3 unit tests (one per outcome) + 3 integration tests.
- Commit: `feat(use_cases): record_follow_up_result transitions proposal/lead based on outcome`

### T6: Bot 3 outcome callbacks
- Add `FOLLOW_UP_PREFIX = "follow_up_outcome:"` constant + `on_follow_up_outcome` callback in `bot.py`.
- Callback parses `{id}:{outcome}`, calls `record_follow_up_result`, replies with confirmation.
- Integration test that exercises all 3 outcomes.
- Commit: `feat(bot): follow_up_outcome callback records client response`

### T7: README + tag
- Update README status (mark Plan 5b complete) and add `mark_proposal_sent`, `send_follow_up`, `record_follow_up_result` to the use case list, plus `send_follow_up` to worker handlers.
- Final pytest + ruff verification.
- Tag `plan-5b-mark-sent-and-followup`.
- Commit: `docs(domain): README — Plan 5b complete (follow-up lifecycle)`

---

## Definition of Done

- [ ] All 7 tasks committed on branch `plan-5b-mark-sent-and-followup`.
- [ ] Tag exists at branch tip.
- [ ] `uv run pytest -v` is green (target: ~110+ passed).
- [ ] `uv run ruff check .` is green.
- [ ] Operator can: receive GDoc URL → click "✅ Отправлено клиенту" → 3 days later get a reminder → click ✅/❌/💬 → see state in DB.

---

## Self-review checklist (during/after implementation)

- AI/IO calls outside DB transactions.
- No `assert` as runtime guard.
- All state changes recorded in `events`.
- Idempotency: re-enqueue via `idempotency_key`, re-run handler is no-op via status guard.
- Telegram send failures swallowed (do NOT crash worker / bot handler).
- Event payloads truncate long strings.

---

## Backlog (for Plan 6+)

- Free-text result notes (today: hardcoded "(via inline button)"; tomorrow: prompt operator for a follow-up text).
- Cancel a pending FollowUp if proposal is reverted to draft (today: no rollback path).
- Multi-operator alerts (`ids[0]` everywhere).
- Concurrent-enqueue race on `idempotency_key` (Plan 5a backlog, still open).
- Real Google Docs adapter (Plan 6).
