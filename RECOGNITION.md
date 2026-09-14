# Legacy command-line recognition and tests

The new desktop dashboard and full modular pipeline are documented in **README.md**.
Open **Start FH6 Auto.cmd** for the GUI. The commands below remain available for
individual checks; the old "next stage" section is historical.

`forza_cycle.py` provides read-only recognition, a single mastery sequence,
and a purchase loop. Mastery has passed the user's live retest.
The user has confirmed the purchase loop works. The current version also
returns to Car Collection after the last purchase. Removal and the combined
purchase/mastery/removal cycle are not yet implemented.
The original `mastery.py` is unchanged.

## Next stage: locate the recently added car

After purchasing, open **My Cars** manually and start:

```powershell
python forza_cycle.py --locate-car
```

Press F6 while the game is focused. The program opens Sort, selects
Recently Added, verifies the jump-shortcut hint, then presses Backspace
once. It stops on the resulting garage selection and saves three screenshots
in `garage_checks`: before sorting, after sorting, and after the jump.
F7 stops further inputs.

This is a navigation test. It does not yet establish that the selected
duplicate is the copy just purchased, and does not enter or remove a car.
Check which card the shortcut selects; these saved screens will guide the
next integration into mastery. No additional recording is needed for this
lookup test.

## Buy continuously or choose a quantity

For continuous purchases until you press F7 or a check fails:

```powershell
python forza_cycle.py --purchase --count 0
```

To buy a fixed quantity, for example ten cars:

```powershell
python forza_cycle.py --purchase --count 10
```

Each confirmed purchase costs 95,000 CR, so ten cars cost 950,000 CR.
The program verifies success, presses Enter once to dismiss the message,
waits for the collection grid, then locates and verifies the Mazda again
before purchasing the next copy. At a fixed limit it also dismisses the
final success message and verifies Car Collection before stopping. The
console displays confirmed purchases and total cost.

F6 starts/resumes; F7 stops further actions. Confirmed progress is retained
within the running program, so resuming does not reset a fixed limit. If
you stop within an unfinished menu sequence, return to the collection grid
before F6. An uncertain purchase must be resolved as described below.

For the original one-car test, omit the count (it defaults to one):

Restart the program with:

```powershell
python forza_cycle.py --purchase
```

Open Collection Journal → Car Collection and navigate to Mazda so the
blue 1974 #123 Mad Mike 808 Wagon FURSTY card is visible. Start on the
five-column collection grid, before opening any purchase dialog. Keep the
same 1920 x 1080 English layout used in the recording.

Press F6. The program finds the matching car image and year/manufacturer,
hovers its card, verifies focus, presses Space to open the purchase prompt,
selects Yes, checks the exact 95,000 CR offer, and selects Buy. It sends the
purchase Enter once, then waits up to 15 seconds for the car-added message.
The voucher button is not accepted as Buy. A different price, missing car,
multiple matches, focus loss, or unrecognized dialog stops the test.

With the default count of one, the run returns to Car Collection after
buying one car. A fixed limit applies for the lifetime of that process;
pressing F6 again cannot exceed it. This loop buys copies only; it does not
yet enter the purchased copy or connect to the mastery sequence.

Purchase screenshots and records are saved in `purchases`. If Enter was
about to be sent or was sent but success was not verified, a pending record
blocks another purchase even after restarting. Check the game yourself,
then record what happened with ONE of these commands:

```powershell
python forza_cycle.py --resolve-purchase bought
python forza_cycle.py --resolve-purchase not-bought
```

These commands record your finding; they do not operate the game. Do not
clear an uncertain result by guessing. Failure screenshots are in `failures`.

## Read-only recognition

Install requirements using your normal Python installation:

```powershell
python -m pip install -r requirements-recognition.txt
python forza_cycle.py --live
```

Use the same 1920 x 1080 English layout as the recording. Open the Mad Mike
mastery screen, keep the game focused, then press F6. Move between nodes
manually and watch the console report `unavailable`, `available`, and
`owned`. F7 stops observation; Ctrl+C exits. If your game window title
differs, pass its title with `--game-title "your title"`. Use `--monitor 2`
if the game is on your second captured monitor.

Recognition currently covers the mastery screen and seven observed collection, purchase,
sort, garage, and removal screens. Other menus and transitions report
`unknown`. After 45 seconds of an unrecognized screen, observation stops
and saves a screenshot and report in `failures`. Focus loss stops it too.
Read-only matches are diagnostic observations. They do not verify which
duplicate is selected. As requested, a claimed Super Wheelspin node now
satisfies the reward requirement; a saved-spin count is not required.

The node classifier reads only a 48 x 48 center square. It ignores focus
borders and uses the observed white/dark/pink interior colors. Animation
frames can report `unknown`; later input automation will need stable
observations and additional action-specific checks. The mastery test waits
for three consistent observations and verifies the selected node caption
before sending Enter. Claim flashes are allowed to settle without further
inputs for up to eight seconds. A persistent unknown screen or another
recognized menu stops the sequence.

The caption check now tolerates the recorded/live text-rendering difference
that caused the September 8 stops at nodes 3 and 5. It compares all six
names and requires a clear best match. Failure reports include caption
scores and the margin over the next candidate. The mastery regression tests pass,
including the actual failure screenshots and rejection of incorrect,
blank, and ambiguous captions. Restart the program to load this fix.

## Single mastery test after recognition passes locally

Manually enter the copy you intend to use and open its mastery screen:

```powershell
python forza_cycle.py --mastery
```

F6 starts one mastery sequence. This mode spends up to 21 skill points.
It hovers each required node, checks its selection caption, presses Enter
once, and verifies ownership before proceeding. An uncertain claim stops
without retrying Enter. F7 stops further actions; an already sent key cannot
be undone. It leaves you on the mastery screen and never removes the car.
There is no cycle limit yet because repeated cycles are not implemented.

Offline checks:

```powershell
python forza_cycle.py --video "Recording 2026-09-07 231512.mp4"
python -m unittest -v test_recognition test_purchase test_garage
```

The video report is saved to `video_review/recognition.jsonl`.
`video_review/observations.md` records the route, costs, and remaining
duplicate-identity requirements. All 32 offline tests pass. Purchase tests
use fake input methods and recorded screens, including wrong price, voucher
selection, missing or duplicate candidates, stop/focus loss, and restart
after an uncertain purchase. Loop tests additionally cover exact limits,
continuous buying stopped by F7, retained progress on resume, and failure
to return to the grid or find the car again. Garage tests cover the recorded
navigation route, stopping, and rejecting an incorrect sort or shortcut.
The final-return change and garage lookup still need local live verification.

The Sort-menu template was corrected after the three 13:26–13:27 failures:
its title crop now excludes the shadow from the highlighted Manufacturer
row. Regression tests start with those real failure screenshots, then
simulate selecting Recently Added and using the jump shortcut. Restart the
program to reload the corrected template.
