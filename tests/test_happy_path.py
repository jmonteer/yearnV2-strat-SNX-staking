import brownie
from brownie import Wei, Contract
from eth_abi import encode_single


def test_happy_path(
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
    snx.transfer(bob, Wei("1000 ether"), {"from": snx_whale})
    snx.approve(vault, 2 ** 256 - 1, {"from": bob})
    vault.deposit({"from": bob})

    # Invest with an SNX price of 21
    snx_oracle.updateSnxPrice(Wei("20 ether"), {"from": gov})
    strategy.harvest({"from": gov})
    assert strategy.balanceOfWant() == Wei("1000 ether")
    assert strategy.balanceOfSusd() == 0
    assert strategy.balanceOfSusdInVault() > 0

    # Donate some sUSD to the susd_vault to mock earnings and harvest profit
    susd.transfer(susd_vault, Wei("1000 ether"), {"from": susd_whale})

    # Sleep for 10hs
    chain.sleep(36000)
    chain.mine(1)
    er = Contract(strategy._exchangeRates())
    snx_oracle.updateSnxPrice(Wei("20 ether"), {"from": gov})
    tx = strategy.harvest({"from": gov})
    assert 1 == 2
    er.rateAndInvalid(encode_single("bytes32", b"SNX"))
    snx_oracle.updateSnxPrice(Wei("20 ether"), {"from": gov})
