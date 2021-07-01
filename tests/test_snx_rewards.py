from brownie import Wei, Contract
from eth_abi import encode_single
from utils import accumulate_fees


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
    debt_cache,
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
    debt_cache.takeDebtSnapshot({"from": debt_cache.owner()})
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

    rewards_to_be_claimed = fee_pool.feesAvailable(strategy)[1]
    previous_escrowed_want = strategy.balanceOfEscrowedWant()

    strategy.harvest({"from": gov})
    debt_cache.takeDebtSnapshot({"from": debt_cache.owner()})

    chain.sleep(60 * 60 * 8)  # Sleep 8 hours
    chain.mine(1)

    # we check we received escrowed want and sUSD
    assert (
        previous_escrowed_want + rewards_to_be_claimed
        == strategy.balanceOfEscrowedWant()
    )
    assert (
        vault.strategies(strategy).dict()["totalGain"] > 0
    )  # fees sold for Want and have been taken as gain

    strategy.harvest({"from": gov})
    debt_cache.takeDebtSnapshot({"from": debt_cache.owner()})

    chain.sleep(60 * 60 * 24)  # Sleep 24 hours
    chain.mine(1)

    vault.withdraw({"from": bob})
    assert strategy.balanceOfSusd() == 0
    assert strategy.balanceOfSusdInVault() == 0
    assert strategy.balanceOfWant() == 0
