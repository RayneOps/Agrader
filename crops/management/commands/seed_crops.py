from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from crops import seed_data
from crops.models import Crop, CropPairRule, CropRequirement, RotationRule, ScoreSetting


class Command(BaseCommand):
    help = (
        "Load the draft crop knowledge (all unapproved). Safe to re-run: it only adds what is "
        "missing and never changes a record that already exists."
    )

    def handle(self, *args, **options):
        self.counts = {}
        with transaction.atomic():
            crops = self.seed_crops()
            self.seed_pairs(crops)
            self.seed_rotation(crops)
            self.seed_settings()
        for label, (added, kept) in self.counts.items():
            self.stdout.write(f"{label}: {added} added, {kept} already present (left unchanged)")
        self.stdout.write(self.style.WARNING("All seeded values are drafts awaiting the Crop Scientist's approval."))

    def tally(self, label, created):
        added, kept = self.counts.get(label, (0, 0))
        self.counts[label] = (added + created, kept + (not created))

    def seed_crops(self):
        crops = {}
        for (name, also, sci, family, fixes_n, ph_min, ph_lo, ph_hi, ph_max, n, p, k,
             w_lo, w_hi, d_min, d_max, t_lo, t_hi, window) in seed_data.CROPS:
            crop, created = Crop.objects.get_or_create(
                name=name,
                defaults={"also_called": also, "scientific_name": sci, "family": family, "fixes_nitrogen": fixes_n},
            )
            self.tally("Crops", created)
            crops[name] = crop
            has_version = crop.requirements.exists()
            if not has_version:
                requirement = CropRequirement(
                    crop=crop, ph_min=ph_min, ph_ideal_low=ph_lo, ph_ideal_high=ph_hi, ph_max=ph_max,
                    n_demand=n, p_demand=p, k_demand=k, water_low_mm=w_lo, water_high_mm=w_hi,
                    days_min=d_min, days_max=d_max, temp_low_c=t_lo, temp_high_c=t_hi, planting_window=window,
                    requires_standing_water=name in seed_data.REQUIRES_STANDING_WATER,
                    exempt_from_season_length=name in seed_data.EXEMPT_FROM_SEASON_LENGTH,
                    notes="Draft seed values, not yet verified by the Crop Scientist.",
                )
                requirement.full_clean(exclude=["version"])
                requirement.save()
            self.tally("Crop requirements", not has_version)
        return crops

    def seed_pairs(self, crops):
        verdicts = {}
        for verdict, pairs in (("good", seed_data.GOOD_PAIRS), ("avoid", seed_data.AVOID_PAIRS)):
            for first, second in pairs:
                key = frozenset((first, second))
                if verdicts.get(key, verdict) != verdict:
                    raise CommandError(f"Seed data lists {first} + {second} as both good and avoid.")
                verdicts[key] = verdict
        for key, verdict in verdicts.items():
            first, second = sorted(key)
            a, b = CropPairRule.ordered(crops[first], crops[second])
            # The brief gives no reasons for pairs; the Crop Scientist adds them, we never invent them.
            _, created = CropPairRule.objects.get_or_create(crop_a=a, crop_b=b, defaults={"verdict": verdict})
            self.tally("Pair rules", created)

    def seed_rotation(self, crops):
        def side(value):
            if value is None:
                return "", None
            if value in seed_data.FAMILIES:
                return value, None
            return "", crops[value]

        for code, previous, following, effect, reason in seed_data.ROTATION_RULES:
            prev_family, prev_crop = side(previous)
            next_family, next_crop = side(following)
            match = RotationRule.Match.REPEAT_THIRD_SEASON if previous is None else RotationRule.Match.PATTERN
            _, created = RotationRule.objects.get_or_create(
                code=code, match=match,
                previous_family=prev_family, previous_crop=prev_crop,
                next_family=next_family, next_crop=next_crop,
                defaults={"effect": effect, "reason": reason},
            )
            self.tally("Rotation rules", created)

    def seed_settings(self):
        for key, group, kind, value, description in seed_data.SCORE_SETTINGS:
            _, created = ScoreSetting.objects.get_or_create(
                key=key, defaults={"group": group, "kind": kind, "value": value, "description": description}
            )
            self.tally("Score settings", created)
