import brownie
from utils import accumulate_fees


def test_target_multiplier(vault, strategy, bob):

    # Strategist can't call it
    with brownie.reverts():
        strategy.setTargetRatioMultiplier(100, {"from": strategy.strategist()})

    # Randos either
    with brownie.reverts():
        strategy.setTargetRatioMultiplier(100, {"from": bob})

    # Can be set my management
    strategy.setTargetRatioMultiplier(123, {"from": vault.management()})
    assert strategy.targetRatioMultiplier() == 123

    # and can be set by gov
    strategy.setTargetRatioMultiplier(12345, {"from": vault.governance()})
    assert strategy.targetRatioMultiplier() == 12345
