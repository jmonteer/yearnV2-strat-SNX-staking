import brownie
from brownie import Wei, Contract
from eth_abi import encode_single


def test_emergency_exit(
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
    debt_cache,
):
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
    # to avoid bug
    debtCache = Contract(resolver.getAddress(encode_single("bytes32", b"DebtCache")))
    debtCache.takeDebtSnapshot({"from": debtCache.owner()})
    assert strategy.balanceOfWant() == Wei("1000 ether")
    assert strategy.balanceOfSusd() == 0
    assert strategy.balanceOfSusdInVault() > 0

    # We need to wait 24hs to be able to burn synths
    # Always takeDebtSnapshot after moving time.
    chain.sleep(86401)
    chain.mine(1)

    strategy.setEmergencyExit({"from": gov})
    strategy.harvest({"from": gov})
    assert strategy.estimatedTotalAssets() == 0
    assert snx.balanceOf(vault) == Wei("1000 ether")
    assert vault.strategies(strategy).dict()["totalDebt"] == 0
