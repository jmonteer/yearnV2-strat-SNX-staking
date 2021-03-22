# TODO: Add tests that show proper migration of the strategy to a newer one
#       Use another copy of the strategy to simulate the migration
#       Show that nothing is lost!


def test_migration(
    token, vault, strategy, amount, Strategy, strategist, gov, susd_vault, chain
):
    # Deposit to the vault and harvest
    token.approve(vault.address, amount, {"from": gov})
    vault.deposit(amount, {"from": gov})
    strategy.harvest()
    assert token.balanceOf(strategy.address) == amount

    # sleep for 24h to be able to burn synths
    chain.sleep(24 * 3600 + 1)
    chain.mine(1)

    # migrate to a new strategy
    new_strategy = strategist.deploy(Strategy, vault, susd_vault)
    strategy.migrate(new_strategy.address, {"from": gov})
    assert token.balanceOf(new_strategy.address) == amount
