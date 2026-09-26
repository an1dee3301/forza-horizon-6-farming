# Spaced cleanup navigation

Fast cleanup now places an 80 ms released interval after each of four Down
inputs, then waits 160 ms before proving the Remove Car From Garage target.
The original 60 ms key holds remain unchanged. Both visual and OCR entry
paths require Get In Car focus first. Two fresh target observations precede
the caller's confirmation input. A failed group falls back to the normal
OCR selector without replaying the pulse group.

## Live evidence

Three bounded trials took **4.027, 4.054, and 3.949 seconds**, averaging
**4.010 seconds** from opening the action menu to observing the resulting
garage grid. All three used four action-menu Down inputs. Ordinary tightly
packed pulses commonly needed three additional individually verified inputs.

The [deidentified interval data](../data/cleanup-spacing-2026-09-26.json)
includes comparison removals and retains slow outliers. This is a small,
within-session timing comparison, not a randomized experiment. Filtering,
between-removal gaps, final empty verification, farming and conversion are
excluded from these interval measurements. The results do not establish a
full-batch rate or the target of 33 saved Super Wheelspins per hour.

An earlier unspaced seven-Down attempt took 7.340 seconds and still required
three additional inputs. Increasing the count did not improve that trial;
the tested improvement changes the release spacing instead.

## Selective public implementation

Only the tested action-menu pacing and its fallback were ported from the
running development workspace. This public module has a different cleanup
interface; its existing selected-car checks, final confirmation flow and
per-removal journal are retained. No live configuration, account identifiers,
purchase receipts, screenshots or experiment-consumption files are published.

Targeted tests cover pulse spacing, target timeout, focus changes, both menu
entry paths, refusal to burst without start-focus proof, fallback without
replay, and single-removal accounting on the successful path.
