import pytest
from app.db import filter_candidates_sql, init_db
from app.seed import seed_database

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    seed_database()

def test_sql_filtering_active_only():
    candidates = filter_candidates_sql(role="Backend Dev", max_results=40)
    assert len(candidates) > 0
    assert len(candidates) <= 40
    for c in candidates:
        assert c["status"] == "active"
        assert c["window_allocation_pct"] < 100.0

def test_sql_filtering_skills_overlap():
    candidates = filter_candidates_sql(skills=["Python", "SQL"], max_results=20)
    assert len(candidates) > 0
    for c in candidates:
        assert c["matched_skills_count"] >= 1
        assert c["avg_proficiency"] >= 1.0

def test_sql_filtering_burnout_facts_computed():
    candidates = filter_candidates_sql(role="Backend Dev", max_results=10)
    assert len(candidates) > 0
    for c in candidates:
        assert "current_allocation_pct" in c
        assert "concurrent_projects_count" in c
        assert "hours_last_4_weeks" in c
        assert "recent_overtime_hours" in c
        assert c["current_allocation_pct"] >= 0.0
        assert c["concurrent_projects_count"] >= 0
        assert c["hours_last_4_weeks"] >= 0.0
        assert c["recent_overtime_hours"] >= 0.0

def test_sql_filtering_cap_at_40():
    candidates = filter_candidates_sql(max_results=40)
    assert len(candidates) <= 40
