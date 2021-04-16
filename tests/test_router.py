import brownie
from brownie import Wei


def test_router(vault, strategy, susd, susd_whale):

    assert vault.strategies(strategy).dict()["totalGain"] == 0

    # Shouldn't be able to set the router to a random address
    with brownie.reverts():
        strategy.setRouter(5, {"from": strategy.strategist()})

    strategy.setRouter(0, {"from": strategy.strategist()})
    susd.transfer(strategy, Wei("1000 ether"), {"from": susd_whale})
    strategy.harvest({"from": strategy.strategist()})
    gain = vault.strategies(strategy).dict()["totalGain"]
    assert gain > 0

    strategy.setRouter(1, {"from": strategy.strategist()})
    susd.transfer(strategy, Wei("2000 ether"), {"from": susd_whale})
    strategy.harvest({"from": strategy.strategist()})
    new_gain = vault.strategies(strategy).dict()["totalGain"]
    assert new_gain - gain > 0
