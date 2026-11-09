# Pilot annotation results (9 Nov 2026)

Purpose: test whether the rulebook wording is clear before it is frozen. Sites (all outside the 30-site corpus): oxymon.co, tekedia.com, slot.ng. Annotators: Stephanie (annotator 1) and Monalisa (annotator 2). Both used the pilot workbook (17 rules per site, 51 labels each). Capture date on the sheet: 8 Nov 2026.

## Result
- Both labelled all 51 items. Identical labels on all 51 (Cohen's kappa 1.0; Wilson 95% interval for 51 of 51: 0.930 to 1.000). Their notes and evidence references were written separately (no identical notes).
- Label counts for each annotator: 24 Non-Compliant, 14 Not Applicable, 13 Compliant.

| Rule | oxymon.co | slot.ng | tekedia.com |
|---|---|---|---|
| CK-01 | NA | NC | NC |
| CK-02 | NA | NA | NC |
| CN-01 | NA | NC | NC |
| CN-02 | NA | NC | NC |
| CN-03 | NA | NC | NC |
| CN-04 | NA | C | NA |
| CN-05 | NA | NC | NA |
| TR-02 | NA | NC | NC |
| SB-01 | NA | NC | NC |
| SB-02 | NA | NC | NC |
| SB-03 | NA | NC | NC |
| PP-01 | C | C | C |
| PP-02 | C | C | C |
| PP-03 | C | C | NC |
| PP-04 | C | C | C |
| PP-05 | NC | NC | C |
| PP-06 | NC | NC | NC |

(C Compliant, NC Non-Compliant, NA Not Applicable.)

## What the three sites were
- oxymon.co: no banner, no cookies and no tracker, so no consent trigger. The consent and script rules are Not Applicable.
- slot.ng: a bottom banner with an Accept button only. A consent flag was already set to true before any click, and Meta and Google measurement cookies were present before the click. Both annotators judged CN-02 Non-Compliant ("a pre-existing consent=true cannot substitute for affirmative action") and CN-04 Compliant.
- tekedia.com: no banner and no settings, with Google advertising trackers contacted before any choice.

## What it does and does not show
- No disagreement, so the pilot did not expose unclear rule wording. No rule text is changed because of it.
- Three sites and 51 items are few. The lower bound of agreement is 0.93, not 1.0.
- None of the three sites had a Reject button or a Close-only banner, so the wording for the Reject run, the Close reading and CN-05 withdrawal is untested. A fourth pilot site with a full banner (Accept, Reject, settings) is planned (B-53).
- Chrome version was not recorded on any site and the capture date is missing for oxymon.co. Register R6 requires both (B-52).
- Notes and Site context show the annotators used the frozen lists (R8, R10 and R1 are cited in their notes).

## Next
Run the tool on the three pilot sites and compare with these labels. That is a dry run of the whole evaluation and will show the first real tool-versus-human differences before the freeze.
