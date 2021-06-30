import brownie
from brownie import Contract, Wei
from eth_abi import encode_single


def test_lossy_vault(chain,
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
    settings.setRateStalePeriod(24 * 3600 * 30, {"from": settings.owner()})
    settings.setDebtSnapshotStaleTime(24 * 3600 * 30, {"from": settings.owner()})

    # Do the first deposit
    snx.transfer(bob, Wei("1000 ether"), {"from": snx_whale})
    snx.approve(vault, 2 ** 256 - 1, {"from": bob})
    vault.deposit({"from": bob})
    # Invest with an SNX price of 20
    snx_oracle.updateSnxPrice(Wei("20 ether"), {"from": gov})
    strategy.harvest({"from": gov})
    strategy.setDoHealthCheck(False, {'from': vault.governance()})
    chain.sleep(24 * 3600)
    chain.mine()

    susd_router = Contract(susd_vault.withdrawalQueue(0))
    susd_router.harvest({'from': susd_router.strategist()})
    susd042 = Contract(susd_router.yVault())
    susd.transfer(susd_whale, Wei("1000 ether"), {'from': susd042})

    susd.transfer(susd_whale, Wei("100 ether"), {'from': susd_vault})
    # to force reducing debt
    vault.updateStrategyDebtRatio(strategy, 5_000, {'from': vault.governance()})
    strategy.setMaxLoss(0, {'from': gov})
    with brownie.reverts():
        strategy.harvest({'from': gov})

    chain.sleep(24 * 3600)
    chain.mine()
    strategy.setMaxLoss(10_000, {'from': gov})
    strategy.harvest({'from': gov})
    assert False