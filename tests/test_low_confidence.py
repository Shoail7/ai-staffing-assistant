import pytest
from app.ranking import rank_candidates
from app.config import settings

def make_candidate(cid: str, score=3.0, skill_conf=0.85, burnout_prob=0.15, burnout_conf=0.85, cost=100.0, alloc=30.0):
    return {
        "resource_id": cid,
        "full_name": f"Candidate {cid}",
        "email": f"{cid.lower()}@example.com",
        "role": "Backend Dev",
        "seniority": "Senior",
        "years_experience": 7.0,
        "location": "NY",
        "timezone": "EST",
        "primary_domain": "fintech",
        "hourly_cost": cost,
        "available_capacity": 100.0 - alloc,
        "current_allocation_pct": alloc,
        "concurrent_projects_count": 1,
        "hours_last_4_weeks": 140.0,
        "recent_overtime_hours": 0.0,
        "skill_score": score,
        "skill_confidence": skill_conf,
        "burnout_prob": burnout_prob,
        "burnout_confidence": burnout_conf,
    }

def test_case_1_single_low_confidence():
    """Case 1: Mark candidate LOW CONFIDENCE if either confidence < MIN_CONFIDENCE (0.60)."""
    cand = make_candidate("C1", skill_conf=0.52, burnout_conf=0.85)
    results, is_tie, all_low = rank_candidates([cand])
    assert len(results) == 1
    assert results[0].is_low_confidence is True
    assert results[0].confidence_level == "LOW"
    assert results[0].needs_pm_review is True

def test_case_2_tie_margin():
    """Case 2: If top-2 final scores differ by less than TIE_MARGIN (0.05), mark group TOO CLOSE TO CALL."""
    c1 = make_candidate("C1", score=3.0, cost=100.0, alloc=30.0)
    c2 = make_candidate("C2", score=3.01, cost=100.5, alloc=30.0)
    results, is_tie, all_low = rank_candidates([c1, c2])

    assert is_tie is True
    assert results[0].is_tie is True
    assert results[1].is_tie is True
    assert results[0].needs_pm_review is True
    assert results[1].needs_pm_review is True

def test_case_3_all_top_3_low_confidence():
    """Case 3: If ALL of top 3 are low confidence, trigger all_top3_low flag."""
    c1 = make_candidate("C1", skill_conf=0.50)
    c2 = make_candidate("C2", skill_conf=0.48)
    c3 = make_candidate("C3", burnout_conf=0.45)
    c4 = make_candidate("C4", skill_conf=0.90) # 4th is high conf, but top 3 are low

    results, is_tie, all_low = rank_candidates([c1, c2, c3, c4])
    assert all_low is True
    assert results[0].is_low_confidence is True
    assert results[1].is_low_confidence is True
    assert results[2].is_low_confidence is True

def test_case_4_high_burnout_workload_risk():
    """Case 4: If burnout_prob >= HIGH_BURNOUT_PROB (0.70), show workload risk warning."""
    cand = make_candidate("C1", burnout_prob=0.78, burnout_conf=0.85)
    results, is_tie, all_low = rank_candidates([cand])

    assert results[0].workload_risk is True
    assert results[0].needs_pm_review is True
