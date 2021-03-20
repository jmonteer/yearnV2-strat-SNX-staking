import brownie
from brownie import Wei, Contract


def test_happy_path(
    gov, vault, strategy, snx, susd, susd_vault, susd_whale, snx_whale, bob
):
    snx.transfer(bob, Wei("1000 ether"), {"from": snx_whale})
    snx.approve(vault, 2 ** 256 - 1, {"from": bob})
    vault.deposit({"from": bob})

    # Invest
    strategy.harvest({"from": gov})
    assert strategy.balanceOfWant() == Wei("1000 ether")
    assert strategy.balanceOfSusd() == 0
    assert strategy.balanceOfSusdInVault() > 0

    assert 1 == 2
    # Donate some sUSD to the susd_vault to mock earnings and harvest profit
    susd.transfer(susd_vault, Wei("1000 ether"), {"from": susd_whale})
    strategy.harvest({"from": gov})

    assert 1 == 2
