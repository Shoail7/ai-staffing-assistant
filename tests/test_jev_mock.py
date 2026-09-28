import asyncio
import pytest
from app.jev_client import MockDecisionEngine

def test_mock_jev_output_shape():
    async def _run():
        mock_engine = MockDecisionEngine(model_version="jev-1.13.0")
        project_spec = {
            "role": "Backend Dev",
            "skills": ["Python", "SQL"],
            "domain": "fintech",
            "min_experience_years": 5.0
        }
        candidates = [
            {
                "resource_id": "RES-001",
                "full_name": "Alice Fin",
                "role": "Backend Dev",
                "seniority": "Senior",
                "years_experience": 6.5,
                "primary_domain": "fintech",
                "matched_skills_count": 2,
                "avg_proficiency": 4.5,
                "current_allocation_pct": 30.0,
                "concurrent_projects_count": 1,
                "recent_overtime_hours": 0.0
            },
            {
                "resource_id": "RES-002",
                "full_name": "Bob Overworked",
                "role": "Backend Dev",
                "seniority": "Mid",
                "years_experience": 4.0,
                "primary_domain": "retail",
                "matched_skills_count": 1,
                "avg_proficiency": 3.0,
                "current_allocation_pct": 110.0,
                "concurrent_projects_count": 4,
                "recent_overtime_hours": 24.0
            }
        ]

        scores, tokens, model_name, is_mock, is_fallback = await mock_engine.score_candidates(
            project_spec, candidates
        )

        assert is_mock is True
        assert is_fallback is False
        assert "jev-1.13.0 (MOCK)" in model_name
        assert tokens > 0
        assert len(scores) == 2

        # Check Alice
        s1 = scores["RES-001"]
        assert 0.0 <= s1["skill_score"] <= 4.0
        assert 0.0 <= s1["skill_confidence"] <= 1.0
        assert 0.0 <= s1["burnout_prob"] <= 1.0
        assert 0.0 <= s1["burnout_confidence"] <= 1.0
        assert "skill_probabilities" in s1
        assert set(s1["skill_probabilities"].keys()) == {"0", "1", "2", "3", "4"}
        assert s1["burnout_prob"] < 0.40  # Alice has low workload

        # Check Bob (overworked)
        s2 = scores["RES-002"]
        assert s2["burnout_prob"] >= 0.70  # Bob is over-allocated with overtime

    asyncio.run(_run())
