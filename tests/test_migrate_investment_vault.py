import brownie
from brownie import Wei, Contract, config
from eth_abi import encode_single


def test_migrate_investment_vault(
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
    guardian,
    pm,
    rewards,
    management,
    debt_cache
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
    vault.deposit({"from": bob})

    # Invest with an SNX price of 20
    snx_oracle.updateSnxPrice(Wei("20 ether"), {"from": gov})
    strategy.harvest({"from": gov})
    debt_cache.takeDebtSnapshot({'from': debt_cache.owner()})
    chain.sleep(86400 + 1)  # just over 24h
    chain.mine()

    assert strategy.balanceOfWant() == Wei("1000 ether")
    assert strategy.balanceOfSusd() == 0
    assert strategy.balanceOfSusdInVault() > 0

    Vault = pm(config["dependencies"][0]).Vault
    new_vault = guardian.deploy(Vault)
    new_vault.initialize(susd, gov, rewards, "", "", guardian)
    new_vault.setDepositLimit(2 ** 256 - 1, {"from": gov})
    new_vault.setManagement(management, {"from": gov})
    new_vault.setPerformanceFee(0, {"from": gov})
    new_vault.setManagementFee(0, {"from": gov})

    previous_balance = strategy.balanceOfSusdInVault()

    strategy.migrateSusdVault(new_vault, 10_000, {"from": gov})

    assert previous_balance == new_vault.totalAssets()
    assert previous_balance == strategy.balanceOfSusdInVault()

    vault.withdraw({"from": bob})

    assert snx.balanceOf(vault) == 0
    assert vault.balanceOf(bob) == 0
    assert snx.balanceOf(bob) == Wei("1000 ether")
    chain.revert()
