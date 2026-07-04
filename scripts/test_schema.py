"""Sanity check for the SwingFeatures / AggregatedFeatures schema."""

from __future__ import annotations

import math

from golf_diagnostic.features.schema import (
    FEATURE_NAMES,
    SwingFeatures,
    aggregate,
)


def make_dummy_swing(value: float) -> SwingFeatures:
    """Build a SwingFeatures with every field set to `value`."""
    return SwingFeatures(**{name: value for name in FEATURE_NAMES})


# 1. All FEATURE_NAMES match dataclass fields.
expected = set(FEATURE_NAMES)
actual = {f.name for f in SwingFeatures.__dataclass_fields__.values()}
missing = expected - actual
extra = actual - expected
assert not missing, f"FEATURE_NAMES references nonexistent fields: {missing}"
assert not extra, f"SwingFeatures has fields not in FEATURE_NAMES: {extra}"
print(f"OK: {len(FEATURE_NAMES)} features all match dataclass fields.")

# 2. to_dict round-trip.
s = make_dummy_swing(1.5)
d = s.to_dict()
assert len(d) == len(FEATURE_NAMES)
assert all(v == 1.5 for v in d.values())
print("OK: to_dict produces a dict with one entry per feature.")

# 3. get() by name.
assert s.get("lead_wrist_angle_at_P4") == 1.5
try:
    s.get("nonexistent_feature")
    raise AssertionError("Should have raised KeyError")
except KeyError:
    pass
print("OK: get() works and raises on unknown features.")

# 4. Aggregation with finite values.
swings = [make_dummy_swing(1.0), make_dummy_swing(2.0), make_dummy_swing(3.0)]
agg = aggregate(swings)
assert agg.n_swings == 3
assert agg.get("lead_wrist_angle_at_P4", "mean") == 2.0
assert math.isclose(agg.get("lead_wrist_angle_at_P4", "stddev"), 1.0)
assert agg.get("lead_wrist_angle_at_P4", "range") == 2.0
print("OK: aggregation produces correct mean/stddev/range.")

# 5. Aggregation with one NaN swing — that swing skipped, rest still aggregated.
swings = [make_dummy_swing(1.0), make_dummy_swing(2.0), make_dummy_swing(math.nan)]
agg = aggregate(swings)
assert agg.get("lead_wrist_angle_at_P4", "mean") == 1.5
assert math.isclose(agg.get("lead_wrist_angle_at_P4", "stddev"), math.sqrt(0.5))
print("OK: aggregation skips NaN values per feature.")

# 6. Aggregation with all NaN -> all NaN.
swings = [make_dummy_swing(math.nan), make_dummy_swing(math.nan)]
agg = aggregate(swings)
assert math.isnan(agg.get("lead_wrist_angle_at_P4", "mean"))
assert math.isnan(agg.get("lead_wrist_angle_at_P4", "stddev"))
assert math.isnan(agg.get("lead_wrist_angle_at_P4", "range"))
print("OK: all-NaN aggregation returns NaN aggregates.")

# 7. Aggregation with one finite value -> mean defined, stddev/range NaN.
swings = [make_dummy_swing(1.0), make_dummy_swing(math.nan), make_dummy_swing(math.nan)]
agg = aggregate(swings)
assert agg.get("lead_wrist_angle_at_P4", "mean") == 1.0
assert math.isnan(agg.get("lead_wrist_angle_at_P4", "stddev"))
assert math.isnan(agg.get("lead_wrist_angle_at_P4", "range"))
print("OK: single-finite-value aggregation gives mean only.")

print("\nAll schema checks passed.")