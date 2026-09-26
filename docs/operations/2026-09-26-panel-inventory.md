# Keep verified inventory visible after a worker restart

The Live tab now has a fixed inventory balance and verification timestamp
above the current stage. The existing scrolling statistics remain available.

Current-worker readings retain their existing checks: two native My Horizon
samples, same goal and observed account, matching worker PID/run identifier,
and an observation timestamp between worker start and now.

After a restart, a prior verified reading can appear as **LAST VERIFIED**,
with its timestamp and a statement that the current balance has not been
reread. This display fallback additionally requires the saved goal's credit
account to match the observed account. It rejects future or timezone-free
timestamps, missing proof, wrong accounts/goals and invalid counts. It is
display-only and does not authorize game inputs or modify purchase accounting.

Verification: 16 focused public tests pass for current and prior worker
readings, timestamp validation, account/goal isolation and missing evidence.
The source workspace's two bridge tests also pass. Layout positions were
checked statically; the panel was not launched or visually revalidated while
the farming worker was active. The UI loads on the next normal panel reload.
