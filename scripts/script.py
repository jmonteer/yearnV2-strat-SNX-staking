from eth_abi import encode_single
import brownie
from brownie import Contract


def main():
    strat = Contract("0xFB5F4E0656ebfF31743e674d324554fd185e1c4b")
    ssc = Contract("0x74b3E5408B1c29E571BbFCd94B09D516A4d81f36")
    resolver = Contract("0x823bE81bbF96BEc0e25CA13170F5AaCb5B79ba83")
    synthetix = Contract("0x97767D7D04Fd0dB0A1a2478DCd4BA85290556B48")
    exchangeRates = Contract(
        resolver.getAddress(encode_single("bytes32", b"ExchangeRates"))
    )
    vault = Contract(strat.vault())
    yvault = Contract(strat.susdVault())

    strat.setTargetRatioMultiplier(1000, {"from": vault.management()})
    strat.harvest({"from": strat.strategist()})

    print(f"Balance of debt:{strat.balanceOfDebt()/1e18}")
    print(f"Balance of want:{strat.balanceOfWant()/1e18}")
    print(f"Transferrable SNX:{synthetix.transferableSynthetix(strat)/1e18}")
    print(f"Current ratio:{strat.getCurrentRatio()/1e18}")
    strat.setTargetRatioMultiplier(1000, {"from": vault.management()})  # 1_000/10_000
    strat.setEmergencyExit({"from": vault.management()})

    strat.manuallyRepayDebt(strat.balanceOfSusdInVault(), {"from": strat.strategist()})
    print(f"Balance of debt:{strat.balanceOfDebt()/1e18}")
    print(f"Balance of want:{strat.balanceOfWant()/1e18}")
    print(f"Transferrable SNX:{synthetix.transferableSynthetix(strat)/1e18}")

    # vault.updateStrategyDebtRatio(strat, 0, {'from': vault.management()})
    # dejamos la deuda del balanceOfEscrowedWant
    # debt = strat.balanceOfDebt()-exchangeRates.rateForCurrency(encode_single("bytes32", b"SNX"))/1e18*strat.balanceOfEscrowedWant()
    strat.manuallyRepayDebt(strat.balanceOfSusdInVault(), {"from": strat.strategist()})
    tx = strat.harvest({"from": strat.strategist()})
    assert tx.events["Harvested"]["profit"] > 0
    assert tx.events["Harvested"]["loss"] == 0
