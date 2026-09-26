# Durable garage-removal accounting

A removal now records its operation before confirmation, records submission, and waits for two fresh garage-grid observations before acknowledging it. The acknowledged event is durably appended with its unique operation ID before updating the aggregate count. Restart recovery reconciles a pending acknowledgement before sending Escape or rebuilding the filter, and repeated delivery of the same operation cannot increment the counter twice.

Unconfirmed attempts remain recorded as unresolved outcomes and do not count as removals. The existing exact car filter and keep-list checks still govern removal. This accounting evidence assumes the normal worker owns the input sequence; a return to the grid alone cannot distinguish an unobserved manual cancellation from successful removal.

## Live verification

One complete funded batch produced 33 purchases, 33 recorded rewards and 33 acknowledged removals. All 33 operation IDs were unique, aggregate totals were consecutive, every operation outcome was journaled and no pending operation remained. The final filtered manufacturer index showed no Mazda entry after all Mad Mike removals. Cleanup, including navigation and final verification, took 194.197 seconds.

This healthy-run verification does not exercise every crash cut point. Isolated tests cover interrupted prepared/submitted/acknowledged states, replay, unchanged confirmation, and changed process/goal handling. Public cleanup/journal and keep-list suites passed 95 tests.

The change fixes accounting and restart continuity; it does not prove 33 saved Super Wheelspins/hour. Rate qualification still requires two adjacent native-inventory windows of at least 100 new saved SW each, including farming, conversion, cleanup and all interruption/recovery time.
