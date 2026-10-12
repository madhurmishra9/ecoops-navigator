"""Ground-truth tests: every planted scenario is found, no healthy control is flagged."""

import pytest

from ecoops.generator import CONTROLS, PLANTED

BLOCKED = {
    "lifecycle_delete:audit-logs-archive": "data_retention",
    "schedule_off:dr-standby-gke": "resilience",
    "consolidate_floor:floor-2": "accessibility",
    "region_shift:risk-features": "security",
}


def test_every_planted_scenario_is_detected(result):
    found = {o.id for o in result.opportunities}
    assert set(PLANTED) <= found


def test_no_false_positives_on_controls(result):
    flagged = {o.entity for o in result.opportunities}
    assert not flagged & set(CONTROLS)


def test_no_unexpected_flags(result):
    assert {o.id for o in result.opportunities} == set(PLANTED)


@pytest.mark.parametrize("opp_id,category", BLOCKED.items())
def test_attractive_but_constrained_actions_are_blocked(result, opp_id, category):
    o = result.get(opp_id)
    assert o.constraint_status == "blocked"
    assert category in {c.category for c in o.constraints}
    assert o.score == 0 and o.potential_score > 0
    assert o.next_step == "escalate"


def test_retention_block_has_compatible_alternative(result):
    assert result.get("storage_class_transition:audit-logs-archive").constraint_status == "clear"
    assert any(c.alternative for c in result.get("lifecycle_delete:audit-logs-archive").constraints)


def test_dataflow_rightsizing_requires_nft_evidence(result):
    o = result.get("rightsize:customer-ingest-daily")
    assert o.constraint_status == "conditional"
    assert o.next_step == "test"
    assert any("NFT" in p for p in o.prerequisites)
    assert any(e.provenance == "missing" for e in o.evidence)  # planted memory-telemetry gap


def test_every_flag_is_explained(result):
    for o in result.opportunities:
        provenances = {e.provenance for e in o.evidence}
        assert "observed" in provenances, o.id
        assert provenances & {"derived", "assumed"}, o.id
        assert o.missing_information, o.id
        assert o.assumptions, o.id
        assert o.confidence_reasons, o.id
        assert o.narrative and o.proposed_action and o.capacity_effect, o.id
        assert o.owner_role, o.id


def test_savings_are_reductions(result):
    for o in result.opportunities:
        assert all(v >= -1e-6 for v in o.annual_savings.values()), o.id
        assert sum(o.annual_savings.values()) > 0, o.id
