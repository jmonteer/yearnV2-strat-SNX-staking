import brownie
from brownie import Wei, Contract
from eth_abi import encode_single


def test_liquidations_snx_price_change(
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
    settings.setRateStalePeriod(24 * 3600 * 16, {"from": settings.owner()})
    settings.setDebtSnapshotStaleTime(24 * 3600 * 16, {"from": settings.owner()})

    snx.transfer(bob, Wei("1000 ether"), {"from": snx_whale})
    snx.approve(vault, 2 ** 256 - 1, {"from": bob})
    # bob deposits and the price collapses
    vault.deposit({"from": bob})

    # Invest with an SNX price of 20
    snx_oracle.updateSnxPrice(Wei("20 ether"), {"from": gov})
    strategy.harvest({"from": gov})

    chain.sleep(86400 + 1)  # just over 24h
    chain.mine()

    assert strategy.balanceOfWant() == Wei("1000 ether")
    assert strategy.balanceOfSusd() == 0
    assert strategy.balanceOfSusdInVault() == Wei("4000 ether")

    # price collapses
    snx_oracle.updateSnxPrice(Wei("7 ether"), {"from": gov})

    # the strategy can now be liquidated
    synthetix = Contract(resolver.getAddress(encode_single("bytes32", b"Synthetix")))
    liquidations = Contract(
        resolver.getAddress(encode_single("bytes32", b"Liquidations"))
    )
    # flag account for liquidation, then wait three days to allow the account to repay
    liquidations.flagAccountForLiquidation(strategy, {"from": snx_whale})
    chain.sleep(3600 * 24 * 3 + 1)  # a bit over 3 days (see Synthetix docs)
    chain.mine()

    # repay debt
    amount_needed = liquidations.calculateAmountToFixCollateral(
        strategy.balanceOfDebt(), strategy.balanceOfWant() * 7
    )
    previous_whale_balance = snx.balanceOf(susd_whale)
    synthetix.liquidateDelinquentAccount(strategy, amount_needed, {"from": susd_whale})

    assert strategy.getCurrentRatio() == strategy.getIssuanceRatio()

    vault.withdraw(vault.balanceOf(bob), bob, 10_000, {"from": bob})

    assert snx.balanceOf(bob) < Wei("1000 ether")
    assert previous_whale_balance < snx.balanceOf(
        susd_whale
    )  # the whale receives SNX (debt paid + 10%) as reward for liquidating
    assert (
        amount_needed * 11 / 70 * 0.999
        < Wei("1000 ether") - snx.balanceOf(bob)
        < amount_needed * 11 / 70 * 1.001
    )  # the losses where correctly calculated
    chain.revert()

def test_liquidations_debt_changes(
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
    # Move stale period to 16 days
    resolver = Contract(strategy.resolver())
    settings = Contract(
        resolver.getAddress(encode_single("bytes32", b"SystemSettings"))
    )
    settings.setRateStalePeriod(24 * 3600 * 16, {"from": settings.owner()})
    settings.setDebtSnapshotStaleTime(24 * 3600 * 16, {"from": settings.owner()})

    snx.transfer(bob, Wei("1000 ether"), {"from": snx_whale})
    snx.approve(vault, 2 ** 256 - 1, {"from": bob})
    # bob deposits back and the debt pool skyrockets
    vault.deposit({"from": bob})

    # Invest with an SNX price of 20
    snx_oracle.updateSnxPrice(Wei("20 ether"), {"from": gov})
    strategy.harvest({"from": gov})

    chain.sleep(86400 + 1)  # just over 24h
    chain.mine()

    assert strategy.balanceOfWant() == Wei("1000 ether")
    assert strategy.balanceOfSusd() == 0
    assert strategy.balanceOfSusdInVault() == Wei("4000 ether")
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

    # debt pool goes up to the sky
    previous_debt = strategy.balanceOfDebt()

    snx_oracle.updateBTCPrice(Wei("250000 ether"), {"from": gov})
    snx_oracle.updateETHPrice(Wei("10000 ether"), {"from": gov})
    debtCache.takeDebtSnapshot({"from": debtCache.owner()})
    print("debt", strategy.balanceOfDebt())
    # check that our debt has increased when debt pool value has increased
    assert strategy.balanceOfDebt() > previous_debt
    # the strategy can now be liquidated
    synthetix = Contract(resolver.getAddress(encode_single("bytes32", b"Synthetix")))
    liquidations = Contract(
        resolver.getAddress(encode_single("bytes32", b"Liquidations"))
    )
    # flag account for liquidation, then wait three days to allow the account to repay
    liquidations.flagAccountForLiquidation(strategy, {"from": snx_whale})
    chain.sleep(3600 * 24 * 3 + 1)  # a bit over 3 days (see Synthetix docs)
    chain.mine()

    # repay debt
    amount_needed = liquidations.calculateAmountToFixCollateral(
        strategy.balanceOfDebt(), strategy.balanceOfWant() * 20
    )
    previous_whale_balance = snx.balanceOf(susd_whale)
    synthetix.liquidateDelinquentAccount(strategy, amount_needed, {"from": susd_whale})

    assert strategy.getCurrentRatio() == strategy.getIssuanceRatio()

    vault.withdraw(vault.balanceOf(bob), bob, 10_000, {"from": bob})

    assert snx.balanceOf(bob) < Wei("1000 ether")
    assert previous_whale_balance < snx.balanceOf(
        susd_whale
    )  # the whale receives SNX (debt paid + 10%) as reward for liquidating
    assert (
        amount_needed * 11 / 200 * 0.999
        < Wei("1000 ether") - snx.balanceOf(bob)
        < amount_needed * 11 / 200 * 1.001
    )  # the losses where correctly calculated

    chain.revert()
