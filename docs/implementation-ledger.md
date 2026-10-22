# Implementation ledger

- Approved spec: docs/spec.md; execution authorized by user with "terapkan".
- Isolated clone at original main ac864c78a2b5a86ac8b56fedf874761b9242b14b.
- Remote backup branch created before replacing legacy code.
- Task 1: tests first, then SQLite store; 6 tests passed.
- Task 2: tests first, then delivery/expiry; 13 tests passed.
- Task 3: tests first, lifecycle and menu implementation; 19 tests passed.
- Final suite: 29 tests passed, byte compilation and git diff --check passed.
- Review found premature recovery notices after file-copy failures; separated
  file and membership incident scopes from admin-access incidents, with regression.
- Additional regression caught regrant allowing master toggle without redeploy;
  added durable redeploy_required flag, cleared only by successful redeployment.
- Ruling: use Bot API for ongoing operations and Telethon for deployment auth —
  numeric private channel IDs need reliable bot access without MTProto access-hash
  cache. Cost: two Telegram client libraries rather than one.
- Ruling: bound expiry to 2879 minutes — Telegram's deletion window is under 48h.
  Longer outages can still prevent deletion; this is documented in README.
- Ruling: preserve legacy implementation in Git history and backup branch rather
  than loading old plugins alongside a new multi-bot ownership model. Old links
  and PostgreSQL data require a separate migration; no automatic conversion claimed.
