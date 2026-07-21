from datetime import time

import pytest

from app.services.recommender import (
    PoolState,
    RecommendationInput,
    rules_estimator,
    recommend,
)


def _inp(
    surplus=50.0,
    hour=14,
    absorption=1000,
    limit=10000,
    consumption=500,
):
    return RecommendationInput(
        seller_surplus_kwh=surplus,
        time_of_day=time(hour, 0),
        pool=PoolState(
            current_absorption_kwh=absorption,
            absorption_limit_kwh=limit,
            current_consumption_kwh=consumption,
        ),
    )


def test_local_pool_normal():
    result = rules_estimator(_inp())
    assert result.direction == "local_pool"
    assert result.recommended_price == 0.115
    assert result.recommended_absorption_kwh == 50.0


def test_local_pool_respects_capacity():
    result = rules_estimator(_inp(surplus=500, absorption=8000, limit=10000, consumption=300))
    assert result.direction == "local_pool"
    assert result.recommended_absorption_kwh == 500.0


def test_import_on_shortfall():
    result = rules_estimator(_inp(surplus=50, absorption=100, limit=10000, consumption=500))
    assert result.direction == "import"
    assert result.recommended_absorption_kwh == 50.0


def test_export_on_surplus_overflow():
    result = rules_estimator(_inp(surplus=5000, absorption=8000, limit=10000, consumption=500))
    assert result.direction == "export"
    assert result.recommended_absorption_kwh == 2000.0


def test_export_price_is_feed_in_tariff():
    result = rules_estimator(_inp(surplus=5000, absorption=8000, limit=10000, consumption=500))
    assert result.direction == "export"
    assert result.recommended_price == 0.10


@pytest.mark.asyncio
async def test_recommend_falls_back_to_rules_without_groq_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    result = await recommend(_inp())
    assert result.model_used == "rules"
    assert result.recommended_price == 0.115
