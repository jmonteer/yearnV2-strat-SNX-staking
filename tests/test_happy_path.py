import brownie
from brownie import Wei, Contract


def test_happy_path(gov, vault, strategy, snx, susd, snx_whale, bob):

    snx.transfer(bob, Wei("1000 ether"), {"from": snx_whale})
    snx.approve(vault, 2 ** 256 - 1, {"from": bob})
    vault.deposit({"from": bob})

    strategy.harvest({"from": gov})

    s = Contract(strategy.synthetix())
    s.issueMaxSynths({"from": strategy})
    assert 1 == 2
