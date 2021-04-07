from brownie import Wei, Contract
from eth_abi import encode_single

def test_snx_rewards(
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
    # Move stale period to 30 days
    resolver = Contract(strategy.resolver())
    settings = Contract(
        resolver.getAddress(encode_single("bytes32", b"SystemSettings"))
    )
    settings.setRateStalePeriod(24 * 3600 * 30, {"from": settings.owner()})
    settings.setDebtSnapshotStaleTime(24 * 3600 * 30, {"from": settings.owner()})

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
    initial_debt = strategy.balanceOfDebt()

    # We don't have any reward because the period is not over yet
    fee_pool = Contract(resolver.getAddress(encode_single("bytes32", b"FeePool")))
    assert fee_pool.feesAvailable(strategy)[1] == 0

    # We sleep for the period time and end the cycle
    chain.sleep(fee_pool.feePeriodDuration())
    chain.mine(1)
    fee_pool.closeCurrentFeePeriod({"from": gov})
    assert fee_pool.feesAvailable(strategy)[1] > 0

    strategy.harvest({"from": gov})
    chain.sleep(60 * 60 * 8)  # Sleep 8 hours
    chain.mine(1)

    # After a second harvest we should get fees from trades which means profit
    assert vault.strategies(strategy).dict()["totalGain"] > 0

    strategy.harvest({"from": gov})

    # Since we got snx rewards, we have more collateral, hence more susd should be issue
    assert strategy.balanceOfDebt() > initial_debt

    # test vesting rewards
    chain.sleep(366 * 24 * 3600)  # a bit over 1 year
    chain.mine()

    previous_snx_balance = snx.balanceOf(vault)

    strategy.harvest({"from": gov})

    assert previous_snx_balance < snx.balanceOf(vault)
