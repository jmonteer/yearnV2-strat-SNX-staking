from brownie import Contract
from eth_abi import encode_single


def test_migration(
    token,
    vault,
    strategy,
    amount,
    Strategy,
    strategist,
    gov,
    susd_vault,
    chain,
    debt_cache,
):
    # Move stale period to 6 days
    resolver = Contract(strategy.resolver())
    settings = Contract(
        resolver.getAddress(encode_single("bytes32", b"SystemSettings"))
    )
    settings.setRateStalePeriod(24 * 3600 * 6, {"from": settings.owner()})
    settings.setDebtSnapshotStaleTime(24 * 3600 * 6, {"from": settings.owner()})

    # Deposit to the vault and harvest
    token.approve(vault, amount, {"from": gov})
    vault.deposit(amount, {"from": gov})
    strategy.harvest({"from": gov})
    debt_cache.takeDebtSnapshot({"from": debt_cache.owner()})
    assert token.balanceOf(strategy) == amount

    # sleep for 24h to be able to burn synths
    chain.sleep(24 * 3600 + 1)
    chain.mine(1)

    # migrate to a new strategy
    new_strategy = strategist.deploy(Strategy, vault, susd_vault)
    vault.migrateStrategy(strategy, new_strategy, {"from": gov})
    assert token.balanceOf(new_strategy) == amount
