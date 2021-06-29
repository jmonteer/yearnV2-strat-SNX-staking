import brownie
from brownie import Wei, Contract
from eth_abi import encode_single


def test_snx_price_decreases(
    snx,
    chain,
    gov,
    vault,
    strategy,
    susd,
    susd_vault,
    susd_whale,
    snx_whale,
    bob,
    snx_oracle,
    debt_cache,
):
    chain.snapshot()
    # Move stale period to 6 days
    resolver = Contract(strategy.resolver())
    settings = Contract(
        resolver.getAddress(encode_single("bytes32", b"SystemSettings"))
    )
    settings.setRateStalePeriod(24 * 3600 * 16, {"from": settings.owner()})
    settings.setDebtSnapshotStaleTime(24 * 3600 * 16, {"from": settings.owner()})

    snx.transfer(bob, Wei("1000 ether"), {"from": snx_whale})
    snx.approve(vault, 2 ** 256 - 1, {"from": bob})
    vault.deposit({"from": bob})

    # Invest with an SNX price of 20
    snx_oracle.updateSnxPrice(Wei("20 ether"), {"from": gov})
    strategy.harvest({"from": gov})
    debt_cache.takeDebtSnapshot({"from": debt_cache.owner()})
    chain.sleep(86400 + 1)  # just over 24h
    chain.mine()

    assert strategy.balanceOfWant() == Wei("1000 ether")
    assert strategy.balanceOfSusd() == 0
    assert strategy.balanceOfSusdInVault() > 0
    previous_want = strategy.balanceOfWant()

    snx_oracle.updateSnxPrice(Wei("18 ether"), {"from": gov})

    assert strategy.balanceOfWant() == previous_want

    # check that debt ratio is higher than issuance ratio but smaller than target ratio
    assert strategy.getCurrentRatio() > strategy.getIssuanceRatio()
    assert strategy.getCurrentRatio() < strategy.getTargetRatio()

    # harvesting should not do anything (nor minting nor repaying), as it is within the healthy range
    previous_ratio = strategy.getCurrentRatio()
    previous_debt = strategy.balanceOfDebt()
    previous_vault_balance = strategy.balanceOfSusdInVault()

    strategy.harvest({"from": gov})
    debt_cache.takeDebtSnapshot({"from": debt_cache.owner()})
    chain.sleep(86400 + 1)  # just over 24h
    chain.mine()

    assert previous_ratio == strategy.getCurrentRatio()
    assert previous_debt == strategy.balanceOfDebt()
    assert previous_vault_balance == strategy.balanceOfSusdInVault()

    # decrease collateral value down to the point that debt ratio is unhealthy
    snx_oracle.updateSnxPrice(Wei("15 ether"), {"from": gov})

    # the strategy should repay debt and get to targetRatio without selling
    previous_snx = snx.balanceOf(strategy)
    previous_ratio = strategy.getCurrentRatio()
    previous_debt = strategy.balanceOfDebt()

    strategy.harvest({"from": gov})
    debt_cache.takeDebtSnapshot({"from": debt_cache.owner()})
    chain.sleep(86400 + 1)  # just over 24h
    chain.mine()
    assert previous_debt > strategy.balanceOfDebt()
    assert previous_snx == snx.balanceOf(strategy)

    # check that ratios are expected
    assert strategy.getCurrentRatio() < previous_ratio
    assert strategy.getCurrentRatio() > strategy.getIssuanceRatio()
    assert strategy.getCurrentRatio() == strategy.getTargetRatio()

    # withdrawal should be ok (no losses, it will just repay sUSD debt)
    vault.withdraw({"from": bob})

    assert snx.balanceOf(bob) > 0
    assert vault.balanceOf(bob) == 0
    assert snx.balanceOf(vault) == 0
    assert snx.balanceOf(strategy) == 0

    # bob did not lose SNX
    assert snx.balanceOf(bob) == Wei("1000 ether")
    chain.revert()


def test_snx_price_increases(
    snx,
    chain,
    gov,
    vault,
    strategy,
    susd,
    susd_vault,
    susd_whale,
    snx_whale,
    bob,
    snx_oracle,
    debt_cache,
):
    chain.snapshot()
    # Move stale period to 6 days
    resolver = Contract(strategy.resolver())
    settings = Contract(
        resolver.getAddress(encode_single("bytes32", b"SystemSettings"))
    )
    settings.setRateStalePeriod(24 * 3600 * 6, {"from": settings.owner()})
    settings.setDebtSnapshotStaleTime(24 * 3600 * 6, {"from": settings.owner()})

    snx.transfer(bob, Wei("1000 ether"), {"from": snx_whale})
    snx.approve(vault, 2 ** 256 - 1, {"from": bob})
    vault.deposit({"from": bob})

    # Invest with an SNX price of 20
    snx_oracle.updateSnxPrice(Wei("20 ether"), {"from": gov})
    strategy.harvest({"from": gov})
    debt_cache.takeDebtSnapshot({"from": debt_cache.owner()})
    chain.sleep(86400 + 1)  # just over 24h
    chain.mine()

    assert strategy.balanceOfWant() == Wei("1000 ether")
    assert strategy.balanceOfSusd() == 0
    assert strategy.balanceOfSusdInVault() == Wei("4000 ether")

    previous_want = strategy.balanceOfWant()

    snx_oracle.updateSnxPrice(Wei("25 ether"), {"from": gov})

    assert strategy.balanceOfWant() == previous_want

    # check that debt ratio is lower than issuance ratio and lower than target ratio
    assert strategy.getCurrentRatio() < strategy.getIssuanceRatio()
    assert strategy.getCurrentRatio() < strategy.getTargetRatio()

    # harvesting should issue more debt and invest it in the sUSD vault
    previous_ratio = strategy.getCurrentRatio()
    previous_debt = strategy.balanceOfDebt()
    previous_vault_balance = strategy.balanceOfSusdInVault()

    strategy.harvest({"from": gov})
    debt_cache.takeDebtSnapshot({"from": debt_cache.owner()})
    chain.sleep(86400 + 1)  # just over 24h
    chain.mine()

    assert previous_ratio < strategy.getCurrentRatio()
    assert previous_debt < strategy.balanceOfDebt()
    assert previous_vault_balance < strategy.balanceOfSusdInVault()

    # withdrawal should be ok and report gains
    vault.withdraw({"from": bob})

    assert snx.balanceOf(bob) > 0
    assert vault.balanceOf(bob) == 0
    assert snx.balanceOf(vault) == 0
    assert snx.balanceOf(strategy) == 0

    assert snx.balanceOf(bob) == Wei("1000 ether")
    chain.revert()
