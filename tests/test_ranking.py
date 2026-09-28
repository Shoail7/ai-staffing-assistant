import pytest
from app.ranking import rank_candidates
from app.config import settings

def test_ranking_formula_weights():
    candidate = {
        "resource_id": "RES-TEST-1",
        "full_name": "Test Engineer",
        "email": "test@example.com",
        "role": "Backend Dev",
        "seniority": "Senior",
        "years_experience": 8.0,
        "location": "New York",
        "timezone": "EST",
        "primary_domain": "fintech",
        "hourly_cost": 100.0,
        "max_allocation_pct": 100.0,
        "current_allocation_pct": 20.0,
        "available_capacity": 80.0,
        "concurrent_projects_count": 1,
        "hours_last_4_weeks": 140.0,
        "recent_overtime_hours": 0.0,
        "skill_score": 4.0,  # Max 4.0 -> norm 1.0
        "skill_confidence": 0.90,
        "burnout_prob": 0.0,  # 1 - 0.0 = 1.0
        "burnout_confidence": 0.90,
        "skills": []
    }

    results, is_tie, all_low = rank_candidates([candidate], requested_seniority="Senior")
    assert len(results) == 1
    r = results[0]

    # Verify score components
    # w1 * 1.0 = 0.35
    # w2 * (80/100) = 0.25 * 0.8 = 0.20
    # w3 * 1.0 = 0.20
    # w4 * 1.0 = 0.15
    # w5 penalty with single cost = 0.0
    assert r.final_score >= 0.85
    assert r.final_score <= 1.0
    assert r.score_breakdown.w1_skill == round(settings.weight_skill * 1.0, 4)
    assert r.score_breakdown.w3_burnout == round(settings.weight_burnout * 1.0, 4)

def test_ranking_cost_penalty():
    cand_expensive = {
        "resource_id": "RES-EXP",
        "full_name": "Expensive Dev",
        "email": "exp@example.com",
        "role": "Backend Dev",
        "seniority": "Senior",
        "years_experience": 8.0,
        "location": "NY",
        "timezone": "EST",
        "primary_domain": "fintech",
        "hourly_cost": 220.0,
        "available_capacity": 50.0,
        "current_allocation_pct": 50.0,
        "concurrent_projects_count": 1,
        "hours_last_4_weeks": 160.0,
        "recent_overtime_hours": 0.0,
        "skill_score": 3.0,
        "skill_confidence": 0.80,
        "burnout_prob": 0.20,
        "burnout_confidence": 0.80,
    }
    cand_cheap = dict(cand_expensive)
    cand_cheap["resource_id"] = "RES-CHEAP"
    cand_cheap["full_name"] = "Cheap Dev"
    cand_cheap["hourly_cost"] = 60.0

    results, _, _ = rank_candidates([cand_expensive, cand_cheap])
    # The cheaper candidate should have lower penalty and higher final score
    cheap_res = [c for c in results if c.resource_id == "RES-CHEAP"][0]
    exp_res = [c for c in results if c.resource_id == "RES-EXP"][0]

    assert cheap_res.final_score > exp_res.final_score
    assert cheap_res.score_breakdown.w5_cost_penalty < exp_res.score_breakdown.w5_cost_penalty
