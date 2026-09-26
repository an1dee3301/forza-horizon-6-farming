# Optional credit reserve

The saved-Super-Wheelspin production mode can stop before another 95,000-CR purchase would cross a chosen credit reserve. The option is disabled by default; it has no built-in reserve amount.

Pass `--credit-floor <whole-number-CR>` to the existing Runtime bridge CLI, together with its usual `--channel`, `--action run`, and saved-Super-Wheelspin `--mode` arguments. For example, `--credit-floor 5000000` preserves five million CR. Programmatic Controller configuration accepts `credit_floor: 5000000` in this mode.

The worker requires an identified game account and persists the setting against the current goal. Omitting the option on resume preserves that saved setting. A different value cannot silently replace the saved goal policy, and the option cannot reopen a completed goal.

Before a funded batch, the purchase allowance is capped using identified credit proof minus exact committed purchase receipts. An already-paid car finishes its reward and return checkpoint first. The worker stops even partway through a funded batch when no further whole purchase fits above the reserve. Before declaring the stop, it obtains fresh full-header native credit proof; a stale conservative estimate alone cannot declare completion. If the fresh read permits another purchase, production continues. If fresh proof is unavailable, no additional purchase is authorized.

At the reserve, the worker runs verified Mad Mike cleanup with the existing per-removal journal and protected-car rules, then saves permanent completion. It performs no terminal SP top-up and does not reopen automatically after credits increase. Interrupted final cleanup resumes before any further farming or purchases.

The local panel has no new credit-reserve input yet. This release exposes the CLI/Controller option; the existing saved goal policy remains effective when the panel resumes it. No private goal, account, balance history, or receipt data is bundled.

## Final-only cleanup

Add `--cleanup-policy final_only` alongside a credit floor to defer Mad Mike cleanup until the reserve stops production. Controller configuration uses `cleanup_policy: "final_only"`. This explicitly disables cleanup after each batch and periodic car/batch thresholds. Omitting the option on resume preserves the saved policy; the policy does not weaken protected-car or per-removal proof rules.

The worker finishes each already-paid car, allows further batches while the reserve funds purchases, then performs final verified cleanup once the credit floor stops buying. Existing interrupted cleanup operations retain their recovery checkpoints; this option does not discard them. The default cleanup behavior is unchanged without this explicit option.
