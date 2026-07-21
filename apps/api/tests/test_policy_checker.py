from app.services.policy_checker import PolicyConfig, PriceRecommendation, check

POLICY = PolicyConfig(
    band_width_percentage=5,
    pool_capacity_limit_kwh=10000,
    seller_uplift_percentage=15,
    operator_margin_percentage=5,
    feed_in_tariff_reference=0.10,
)


def test_price_within_band_auto_approved():
    result = check(
        PriceRecommendation(recommended_price=0.102, recommended_absorption_kwh=500),
        POLICY,
    )
    assert result.decision == "auto-approved"
    assert result.deviation_reason is None


def test_price_at_lower_bound_auto_approved():
    result = check(
        PriceRecommendation(recommended_price=0.095, recommended_absorption_kwh=500),
        POLICY,
    )
    assert result.decision == "auto-approved"


def test_price_at_upper_bound_auto_approved():
    result = check(
        PriceRecommendation(recommended_price=0.105, recommended_absorption_kwh=500),
        POLICY,
    )
    assert result.decision == "auto-approved"


def test_price_above_band_flagged():
    result = check(
        PriceRecommendation(recommended_price=0.12, recommended_absorption_kwh=500),
        POLICY,
    )
    assert result.decision == "needs_review"
    assert result.deviation_reason is not None
    assert "15.00%" in result.deviation_reason or "above" in result.deviation_reason


def test_price_below_band_flagged():
    result = check(
        PriceRecommendation(recommended_price=0.08, recommended_absorption_kwh=500),
        POLICY,
    )
    assert result.decision == "needs_review"
    assert result.deviation_reason is not None
    assert "15.00%" in result.deviation_reason or "below" in result.deviation_reason


def test_absorption_exceeds_capacity_flagged():
    result = check(
        PriceRecommendation(recommended_price=0.10, recommended_absorption_kwh=15000),
        POLICY,
    )
    assert result.decision == "needs_review"
    assert "capacity limit" in result.deviation_reason


def test_exact_boundary_price_at_lower_edge():
    result = check(
        PriceRecommendation(recommended_price=0.095, recommended_absorption_kwh=500),
        POLICY,
    )
    assert result.decision == "auto-approved"


def test_just_below_lower_bound_flagged():
    result = check(
        PriceRecommendation(recommended_price=0.0949, recommended_absorption_kwh=500),
        POLICY,
    )
    assert result.decision == "needs_review"
