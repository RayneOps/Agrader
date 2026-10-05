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

## New season wizard (phase 4)

- **Step 1 records the season itself.** It asks for the season (rainy or dry) and the planned
  planting date as well as the history, because the draft Season is saved at the end of
  step 1. `year` is the planting date's year. `cropping_method` stays blank on the draft until
  step 2.
- **Progress comes from the saved data,** not a stored step number. Step 2 is done once the
  method and shortlist are saved, and step 3 once the season has a reading. "Start new season"
  on a farm with a draft opens the first unfinished step. Going back to an earlier step
  updates the existing rows instead of adding new ones.
- **Returning farm** means the farm has any earlier season.
  - Step 1 always asks "What was actually planted last season?" and never prefills it. It must
    be answered: crops, other text, fallow, or "the farmer does not know".
  - The farmer's shortlist from that season is shown as a reminder only.
  - Two and three seasons ago are prefilled from what was recorded on the last season, and
    the operator can correct them.
- **First-time farm:** up to three past seasons, all optional.
- **Fallow and "does not know"** are stored as PreviousCrop rows with free text and no crop
  link. The rules ignore them, and the LLM receives them as context.
- **Soil readings.**
  - Values are stored as floats, exactly as entered or received.
  - pH is required. N, P, K, moisture, temperature and EC are optional.
  - Values outside these ranges get a warning and a "Save anyway" button, never a refusal:

    | Value | Plausible range |
    | --- | --- |
    | pH | 3 to 10 |
    | N and P | 0 to 1000 mg/kg |
    | K | 0 to 2000 mg/kg |
    | Moisture | 0 to 100 % |
    | Temperature | 5 to 60 °C |
    | EC | 0 to 10000 µS/cm |

  - The EC unit is assumed to be µS/cm, because the sensor's units are unconfirmed.
  - A reading time more than 5 minutes in the future is rejected. That is a date check, not a
    value check.
  - Typing in a new reading adds another one, and the season's newest reading is used.
- **Sensor pickup:** step 3 offers the farm's newest sensor reading from the last 24 hours
  that is either unattached or already attached to this season.

## Crop knowledge and approval

- **Who approves.** A user may approve only if `can_approve_rules` is set. `seed_admins` sets the
  flag on the admin named by `RULE_APPROVER_EMAIL` and clears it on everyone else. If the variable
  is unset, nobody can approve, and the Crop knowledge screen says so.
- **Approving own edits.** The rule approver may approve their own edits, as a separate click.
  Saving an edit never approves it. Everyone else cannot approve anything.
- **Score settings** follow the same rule, with "verify" in place of "approve".
- **Requirement versions are immutable.** Every edit creates the next version. Older versions,
  approved or not, stay as they were.
- **Which requirement the engine uses.** It uses the newest approved version. With
  `ALLOW_UNAPPROVED_RULES=true`, it uses the newest version whether or not it is approved.
- **Pair rules, rotation rules and score settings are edited in place.** An edit clears approval,
  and the audit log keeps the history. Recommendations will snapshot the rule text they used
  (phase 6).
- **Adding crops.** "Add crop" sets the family and nitrogen fixing, which are locked after that.
  Editing a crop later only changes its name, local names, scientific name and active flag. A
  new crop has no requirements, so it cannot be recommended until a requirements version is
  added and approved.
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

### Engine details settled in phase 5
- **Unapproved pair and rotation rules are ignored completely,** including "avoid" pairs and
  "block" rotation rules. Until R5 and the avoid pairs are approved, nothing stops those
  crops. The ranking screen says how many rules were skipped.
- **No N, P or K measured at all:** nutrient fit is left out for every crop, and the other four
  weights are scaled up to 100. This applies the "drop and rescale" rule for a single missing
  nutrient one level up. *Needs confirmation.*
- **Weights that don't add up to 100** are scaled so that they do. The Score settings screen
  already warns about this.
- **All removal reasons are kept.** A crop that fails several hard rules lists every reason.
- **The third-season rule (R8)** applies when the same crop was grown in each of the last two
  seasons. If its effect is changed to "block", it removes the crop like any other block rule.
- **History.** A "does not know" answer is not history. Fallow and free-text crops are history
  (so the LLM is not told history is missing), but the rules ignore them.
- **Season fit is still scored for crops excused from the season-length rule** (yam, or an
  irrigated or fadama farm). It can score 0.
- **Water fit:** if planting falls before the season starts, the available rain is capped at
  the full season's rainfall.
- **Combinations.** A combination's breakdown is the average of each component across its
  crops, plus the good-pair bonus. The ranking screen also shows each crop's own breakdown.
- **Tie-break order:** higher score first, then fewer crops, then name.
- **Nothing is saved in phase 5.** The ranking is worked out each time the page opens, and
  phase 6 adds the Recommendation record.

### LLM and outcomes (phase 6)
- **Rules with no reason text.** When a pair or rotation rule has no reason, the LLM may only
  say it is "listed as a good pairing" or "listed as a pairing to avoid". It must not supply a
  reason of its own.
- **Outcome from the next season.** The step 1 answer "What was actually planted last season?"
  also fills the Outcome of the previous season's recommendation.
