import pandas as pd

from ecoops.generator import generate
from ecoops.ingest import SCHEMAS, infer_period, load_csv_dir, save_csv_dir, validate
from ecoops.models import IMPACT_KEYS, PROVENANCE


def test_generator_is_deterministic():
    a, b = generate(7), generate(7)
    for name in a:
        pd.testing.assert_frame_equal(a[name], b[name])


def test_generator_satisfies_input_contract(data):
    issues = validate(data)
    # Only the deliberately planted telemetry gaps are reported.
    assert all("missing values" in i for i in issues)
    assert set(SCHEMAS) <= set(data)


def test_period_inference(data):
    start, end, days = infer_period(data)
    assert str(start.date()) == "2026-09-01"
    assert days == 30


def test_csv_round_trip(tmp_path, data, settings):
    from ecoops.pipeline import run

    save_csv_dir(data, tmp_path)
    loaded = load_csv_dir(tmp_path)
    r1, r2 = run(data, settings), run(loaded, settings)
    assert [o.id for o in r1.opportunities] == [o.id for o in r2.opportunities]


def test_measures_preserve_source_period_unit_provenance_confidence(result):
    m = result.measures
    for col in ("source", "entity", "period_start", "period_end", "metric", "value", "unit", "provenance", "confidence"):
        assert col in m.columns
    assert set(m.provenance) <= set(PROVENANCE)
    assert m.confidence.between(0, 1).all()


def test_footprint_covers_every_asset(result, data):
    assert set(data["assets"].entity) == set(result.footprint.entity)
    for k in IMPACT_KEYS:
        assert (result.footprint[f"annual_{k}"] >= 0).all()
