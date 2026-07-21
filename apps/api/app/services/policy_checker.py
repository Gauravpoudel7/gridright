from dataclasses import dataclass


@dataclass
class PolicyConfig:
    band_width_percentage: float
    pool_capacity_limit_kwh: float
    seller_uplift_percentage: float
    operator_margin_percentage: float
    feed_in_tariff_reference: float


@dataclass
class PriceRecommendation:
    recommended_price: float
    recommended_absorption_kwh: float
    direction: str = "local_pool"


@dataclass
class PolicyCheckResult:
    decision: str
    deviation_reason: str | None = None


def check(recommendation: PriceRecommendation, policy: PolicyConfig) -> PolicyCheckResult:
    band = policy.band_width_percentage / 100
    tariff = policy.feed_in_tariff_reference
    lower_bound = tariff * (1 - band)
    upper_bound = tariff * (1 + band)

    price = recommendation.recommended_price
    absorption = recommendation.recommended_absorption_kwh

    if price < lower_bound or price > upper_bound:
        if price < lower_bound:
            deviation_pct = round(((lower_bound - price) / tariff) * 100, 2)
            return PolicyCheckResult(
                decision="needs_review",
                deviation_reason=(
                    f"Recommended price ${price:.4f}/kWh is {deviation_pct}% below "
                    f"the reference tariff ${tariff:.4f}/kWh; "
                    f"band allows ±{policy.band_width_percentage}% "
                    f"(lower bound ${lower_bound:.4f}/kWh)"
                ),
            )
        else:
            deviation_pct = round(((price - upper_bound) / tariff) * 100, 2)
            return PolicyCheckResult(
                decision="needs_review",
                deviation_reason=(
                    f"Recommended price ${price:.4f}/kWh is {deviation_pct}% above "
                    f"the reference tariff ${tariff:.4f}/kWh; "
                    f"band allows ±{policy.band_width_percentage}% "
                    f"(upper bound ${upper_bound:.4f}/kWh)"
                ),
            )

    if absorption > policy.pool_capacity_limit_kwh:
        deviation_amt = round(absorption - policy.pool_capacity_limit_kwh, 2)
        return PolicyCheckResult(
            decision="needs_review",
            deviation_reason=(
                f"Recommended absorption {absorption} kWh exceeds "
                f"pool capacity limit {policy.pool_capacity_limit_kwh} kWh "
                f"by {deviation_amt} kWh"
            ),
        )

    return PolicyCheckResult(decision="auto-approved")
