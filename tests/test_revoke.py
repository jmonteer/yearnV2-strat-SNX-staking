import brownie
from brownie import Wei, Contract
from eth_abi import encode_single


def test_revoke(
    chain,
    gov,
    vault,
    strategy,
    snx,
    susd,
    susd_vault,
    susd_whale,
    snx_whale,
    bob,
    snx_oracle,
):
    chain.snapshot()
    # Move stale period to 6 days
    resolver = Contract(strategy.resolver())
    settings = Contract(
        resolver.getAddress(encode_single("bytes32", b"SystemSettings"))
    )
    settings.setRateStalePeriod(24 * 3600 * 6, {"from": settings.owner()})
    settings.setDebtSnapshotStaleTime(24 * 3600 * 6, {"from": settings.owner()})

    # Do the first deposit
    snx.transfer(bob, Wei("1000 ether"), {"from": snx_whale})
    snx.approve(vault, 2 ** 256 - 1, {"from": bob})
    vault.deposit({"from": bob})

    # Invest with an SNX price of 20
    snx_oracle.updateSnxPrice(Wei("20 ether"), {"from": gov})
    strategy.harvest({"from": gov})
    assert strategy.balanceOfWant() == Wei("1000 ether")
    assert strategy.balanceOfSusd() == 0
    assert strategy.balanceOfSusdInVault() > 0

    # We need to wait 24hs to be able to burn synths
    # Always takeDebtSnapshot after moving time.
    chain.sleep(86401)
    chain.mine(1)

    # Donate some sUSD to the susd_vault to mock earnings and harvest profit
    susd.transfer(susd_vault, Wei("1000 ether"), {"from": susd_whale})
    strategy.harvest({"from": gov})
    assert vault.strategies(strategy).dict()["totalGain"] > 0

    # Sleep 8 hours to get the full profit
    chain.sleep(60 * 60 * 8)
    chain.mine(1)

    # Sleep 24 hours to allow the minimumStakePeriod to pass
    chain.sleep(60 * 60 * 24)
    chain.mine(1)

    # Revoke + harvest
    vault.revokeStrategy(strategy, {"from": gov})
    strategy.harvest({"from": gov})

    assert strategy.balanceOfWant() == 0
    assert strategy.balanceOfDebt() == 0
    assert strategy.balanceOfSusdInVault() == 0
    # There might be some dust from the susd price per share calculations
    assert strategy.balanceOfSusd() < Wei("0.1 ether")
    assert vault.strategies(strategy).dict()["totalDebt"] == 0
    assert vault.strategies(strategy).dict()["debtRatio"] == 0
    assert (
        snx.balanceOf(vault)
        == Wei("1000 ether") + vault.strategies(strategy).dict()["totalGain"]
    )
    chain.revert()