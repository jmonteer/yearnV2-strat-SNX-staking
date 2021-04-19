import brownie
from brownie import Wei, Contract
from eth_abi import encode_single


def test_debt_increases(
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

    chain.sleep(86400 + 1)  # just over 24h
    chain.mine()

    assert strategy.balanceOfWant() == Wei("1000 ether")
    assert strategy.balanceOfSusd() == 0
    assert strategy.balanceOfSusdInVault() > 0

    # debt pool value increases (main assets are ETH and WBTC so increasing its price increases debt pool value)
    debtCache = Contract(resolver.getAddress(encode_single("bytes32", b"DebtCache")))

    # done to cache from infura
    try:
        print("Taking Debt Snapshot, this will take a while...")
        debtCache.takeDebtSnapshot({"from": debtCache.owner()})
    except:
        print(
            "Failed. This is expected due to timeout but it is useful to cache, next call will go through"
        )

    previous_debt = strategy.balanceOfDebt()

    snx_oracle.updateBTCPrice(Wei("70000 ether"), {"from": gov})
    snx_oracle.updateETHPrice(Wei("2500 ether"), {"from": gov})
    debtCache.takeDebtSnapshot({"from": debtCache.owner()})

    # check that our debt has increased when debt pool value has increased
    assert strategy.balanceOfDebt() > previous_debt

    # check that debt ratio is higher than issuance ratio but smaller than target ratio
    assert strategy.getCurrentRatio() > strategy.getIssuanceRatio()
    assert strategy.getCurrentRatio() < strategy.getTargetRatio()

    # withdrawal with no losses accepted should fail
    with brownie.reverts():
        vault.withdraw({"from": bob})

    # harvesting should not issue more debt nor repay debt
    previous_ratio = strategy.getCurrentRatio()
    strategy.harvest({"from": gov})
    chain.sleep(86400 + 1)  # just over 24h
    chain.mine()
    assert previous_ratio == strategy.getCurrentRatio()

    # increase debt pool value up to the point that debt ratio is unhealthy
    snx_oracle.updateBTCPrice(Wei("120000 ether"), {"from": gov})
    snx_oracle.updateETHPrice(Wei("3500 ether"), {"from": gov})
    debtCache.takeDebtSnapshot({"from": debtCache.owner()})

    # the strategy should repay debt and get to targetRatio without selling
    previous_snx = snx.balanceOf(strategy)
    previous_ratio = strategy.getCurrentRatio()
    previous_debt = strategy.balanceOfDebt()

    strategy.harvest({"from": gov})
    chain.sleep(86400 + 1)  # just over 24h
    chain.mine()
    assert strategy.balanceOfDebt() < previous_debt
    assert previous_snx == snx.balanceOf(strategy)

    # check that ratios are expected
    assert strategy.getCurrentRatio() < previous_ratio
    assert strategy.getCurrentRatio() > strategy.getIssuanceRatio()
    assert strategy.getCurrentRatio() == strategy.getTargetRatio()

    # withdrawal with losses accepted should not fail
    vault.withdraw(vault.balanceOf(bob), bob, 10_000, {"from": bob})

    assert snx.balanceOf(bob) > 0
    assert vault.balanceOf(bob) == 0
    assert snx.balanceOf(vault) == 0
    assert snx.balanceOf(strategy) == 0

    # bob lost SNX
    assert snx.balanceOf(bob) < Wei("1000 ether")
    chain.revert()


def test_debt_decreases(
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

    chain.sleep(86400 + 1)  # just over 24h
    chain.mine()

    assert strategy.balanceOfWant() == Wei("1000 ether")
    assert strategy.balanceOfSusd() == 0
    assert strategy.balanceOfSusdInVault() == Wei("4000 ether")

    previous_debt = strategy.balanceOfDebt()

    # debt pool value decreases (main assets are ETH and WBTC so decreasing its price decreases debt pool value)
    debtCache = Contract(resolver.getAddress(encode_single("bytes32", b"DebtCache")))

    # done to cache from infura
    try:
        print("Taking Debt Snapshot, this will take a while...")
        debtCache.takeDebtSnapshot({"from": debtCache.owner()})
    except:
        print(
            "Failed. This is expected due to timeout but it is useful to cache, next call will go through"
        )

    snx_oracle.updateBTCPrice(Wei("30000 ether"), {"from": gov})
    snx_oracle.updateETHPrice(Wei("1500 ether"), {"from": gov})
    debtCache.takeDebtSnapshot({"from": debtCache.owner()})

    # check that our debt has decreased when debt pool value has increased
    assert strategy.balanceOfDebt() < previous_debt

    # check that debt ratio is higher than issuance ratio but smaller than target ratio
    assert strategy.getCurrentRatio() < strategy.getIssuanceRatio()
    assert strategy.getCurrentRatio() < strategy.getTargetRatio()

    # harvesting should issue more debt
    previous_ratio = strategy.getCurrentRatio()
    previous_debt = strategy.balanceOfDebt()
    previous_vault_balance = snx.balanceOf(vault)

    strategy.harvest({"from": gov})
    chain.sleep(86400 + 1)  # just over 24h
    chain.mine()

    assert previous_ratio < strategy.getCurrentRatio()
    assert previous_debt < strategy.balanceOfDebt()
    assert previous_vault_balance < snx.balanceOf(vault)

    # withdrawal should be ok and report gains
    vault.withdraw({"from": bob})

    assert snx.balanceOf(bob) > 0
    assert vault.balanceOf(bob) == 0
    assert snx.balanceOf(vault) == 0
    assert snx.balanceOf(strategy) == 0

    # bob earned SNX
    assert snx.balanceOf(bob) > Wei("1000 ether")
    chain.revert()
