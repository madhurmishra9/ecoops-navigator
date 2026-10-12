from ecoops.generator import SIMULATABLE, generate
from ecoops.models import NEXT_STEPS
from ecoops.pipeline import run
from ecoops.verification import verify

PERSONAL_COLUMNS = {"employee", "employee_id", "person", "user", "user_id", "name", "email", "team_member", "performance"}


def test_scores_are_bounded_and_decomposable(result):
    for o in result.opportunities:
        assert 0 <= o.score <= 100
        bd = o.score_breakdown
        assert abs(bd["impact_points"] + bd["confidence_points"] + bd["ease_points"] - bd["raw_score"]) < 0.2
        assert abs(bd["raw_score"] * bd["constraint_multiplier"] - o.score) < 0.2


def test_ranking_is_descending(result):
    scores = [o.score for o in result.opportunities]
    assert scores == sorted(scores, reverse=True)


def test_next_steps_are_valid(result):
    assert {o.next_step for o in result.opportunities} <= set(NEXT_STEPS)


def test_three_pathways_without_blocked_or_duplicate_assets(result):
    assert [p.key for p in result.pathways] == ["quick_wins", "digital_first", "balanced"]
    blocked = {o.id for o in result.opportunities if o.constraint_status == "blocked"}
    for p in result.pathways:
        ids = [a["id"] for a in p.actions]
        assert not set(ids) & blocked
        entities = [a["entity"] for a in p.actions]
        assert len(entities) == len(set(entities))
        assert [a["wave"] for a in p.actions] == sorted(a["wave"] for a in p.actions)


def test_balanced_pathway_follows_digital_emphasis(result, settings):
    p = next(p for p in result.pathways if p.key == "balanced")
    share = p.totals["digital_actions"] / p.totals["actions"]
    assert abs(share - settings.scoring["pathways"]["balanced_digital_share"]) <= 0.1


def test_quick_wins_are_low_effort_and_unconstrained(result):
    p = next(p for p in result.pathways if p.key == "quick_wins")
    assert p.actions
    assert all(a["effort"] == "S" and a["constraint_status"] == "clear" for a in p.actions)


def test_no_people_or_team_performance_data(result):
    frame = result.opportunity_frame()
    assert not PERSONAL_COLUMNS & set(frame.columns)
    assert not PERSONAL_COLUMNS & set(result.measures.columns)


def test_assumption_overrides_change_estimates(data, settings):
    greener = settings.with_overrides(factors={"facilities": {"grid_intensity_kg_per_kwh": 0.05}})
    base = run(data, settings).get("occupancy_hvac:floor-4").annual_savings["co2e_kg"]
    low = run(data, greener).get("occupancy_hvac:floor-4").annual_savings["co2e_kg"]
    assert low < base


def test_post_change_verification():
    df = verify(list(SIMULATABLE), seed=42)
    assert len(df) > 0
    assert (df.realised_cost >= 0).all()
    ratios = df.realisation_cost.dropna()
    assert ((ratios > 0.3) & (ratios < 1.5)).all()
    assert set(df.verdict) <= {"on track", "under-delivered", "over-delivered", "n/a"}


def test_simulated_changes_remove_the_flag():
    after = run(generate(42, applied=["schedule_off:nonprod-gke-dev", "build_on_change:monolith-nightly"]))
    ids = {o.id for o in after.opportunities}
    assert "schedule_off:nonprod-gke-dev" not in ids
    assert "build_on_change:monolith-nightly" not in ids
