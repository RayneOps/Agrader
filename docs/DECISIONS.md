# Decisions

Product decisions that the original build brief did not settle. Newest answers win.

## Data model

- **SoilReading** has a required `farm` link and a nullable `season`, so a device reading that
  arrives with no open season is still stored against the farm and the wizard can pick it up.
- **One open season per farm.** A farm can have at most one `draft` season at a time (database
  constraint), so the device API always knows which season to attach a reading to.
- **Farmer language** is a fixed list (Hausa, Nupe, Gbagyi, English, Yoruba, Igbo, Other) so
  that filtering stays consistent.
- **Last visit** on the Farmers list is the most recent season created for any of the farmer's
  farms. From phase 4 it also counts soil readings.
- **Farmer duplicates.** Adding a farmer whose name and village match an existing farmer (ignoring
  case) shows a warning with links to the matches and a "Save anyway" button. It never blocks.
- **Recommendation snapshot (phase 6).** A Recommendation stores a snapshot of the farm's water
  source and size at the time it was made. Farms are editable, and old recommendations must stay
  reproducible.

## Crop knowledge and approval

- **Who approves.** A user may approve only if `can_approve_rules` is set. `seed_admins` sets the
  flag on the admin named by `RULE_APPROVER_EMAIL` and clears it on everyone else. If the variable
  is unset, nobody can approve, and the Crop knowledge screen says so.
- **No self-approval.** Nobody can approve a version they edited themselves, the approver
  included. Seed data has no editor, so the approver can approve it.
- **Score settings** follow the same rule, with "verify" in place of "approve".
- **Requirement versions are immutable.** Every edit creates the next version. Older versions,
  approved or not, stay as they were.
- **Which requirement the engine uses.** It uses the newest approved version. With
  `ALLOW_UNAPPROVED_RULES=true`, it uses the newest version whether or not it is approved.
- **Pair rules, rotation rules and score settings are edited in place.** An edit clears approval,
  and the audit log keeps the history. Recommendations will snapshot the rule text they used
  (phase 6).
- **Display fields only.** The Crop knowledge screen edits a crop's name, local names,
  scientific name and active flag. Family and nitrogen fixing feed the scoring, so they are not
  editable on screen.
- **Seed data.**
  - `seed_crops` only adds records that are missing. It never changes an existing record, so
    edits and approvals survive a re-run.
  - Pair rules are seeded with no reason, because the brief gave none and we do not invent
    agronomy.
  - Pairs with no rule are allowed in mixed cropping, with no bonus.
- **R2 and R6 are stored as several rows.** R2 is one row for each next family. R6 is one row for
  each direction.
- **Score settings seeded.**
  - The five weights, which must add up to 100. The screen warns if they don't.
  - The season calendar.
  - `seasonal_rainfall_mm`.
  - The N, P and K nutrient shares, each 1 and treated as relative.
  - Placeholder N, P and K thresholds in mg/kg (medium from 20, 10 and 80; high from 40, 25 and
    150). Every setting starts unverified.

## Recommendation logic

### Season length
- The season-length rule counts days from the Season's `planting_date`, never from today.
  Planting dates may be in the future, because planning next year's rainy season is normal.
- The rainy season ends 15 October of the planting year. The dry season ends 31 March. Both
  dates are ScoreSettings.
- The wizard warns if the planting date falls outside the labelled season.
- **Extra hard rule:** a dry season on a `rain_fed` farm removes every crop, with the reason
  "no water source in the dry season".

### Water fit (replaces "moisture fit", weight 10)
- The sensor's moisture % is stored, charted and passed to the LLM as context only. It is
  never scored.
- `irrigated` or `fadama`: full marks.
- `rain_fed`: `available_rain = seasonal_rainfall_mm × (days from planting to season end ÷
  season length)`. Full marks if `available_rain >= water_low_mm`, half marks if it is at
  least 75% of `water_low_mm`, otherwise zero.
- `seasonal_rainfall_mm` is seeded as 1200 and marked unverified.

### Nutrient fit
- N, P and K each count for a third of the nutrient weight. The split is stored as settings.
- If a reading has no value for a nutrient, that component is dropped, the remaining weights
  are scaled back up to 100%, and the recommendation says so.

### Mixed cropping and the options shown
- The mixed method ranks combinations only.
- If no valid combination exists (one survivor, or every pair is "avoid"), it falls back to
  ranking single crops, with a notice explaining why.
- If no crops survive, there is no LLM call and the screen shows the removal reasons.
- In every case only the top 5 options are sent to the LLM and shown. The validator checks
  the LLM's answer against those 5.

### Rotation
- All rotation rules look only at the season immediately before on that farm, whatever its
  label. R8 also looks one season further back.
- If the previous season had several crops, a match on any of them counts. Each matching rule
  is applied once, the effects are added up, and the total is clamped.
- A `block` match on any previous crop removes the crop.
- Free-text previous crops with no crop link are ignored by the rules and passed to the LLM as
  context.
- R8 is a special case in code. R6 is stored as two rules, one for each direction.
- With no history at all, rotation fit is 60%, and the LLM is told that history is missing.
  Previous crops typed in by the operator count as history.
