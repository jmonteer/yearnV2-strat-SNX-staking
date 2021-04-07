import pytest
from brownie import config, Contract
from eth_abi import encode_single


@pytest.fixture
def gov(accounts):
    yield accounts[0]


@pytest.fixture
def rewards(accounts):
    yield accounts[1]


@pytest.fixture
def guardian(accounts):
    yield accounts[2]


@pytest.fixture
def management(accounts):
    yield accounts[3]


@pytest.fixture
def strategist(accounts):
    yield accounts[4]


@pytest.fixture
def keeper(accounts):
    yield accounts[5]


@pytest.fixture
def alice(accounts):
    yield accounts[6]


@pytest.fixture
def bob(accounts):
    yield accounts[7]


@pytest.fixture
def token(snx):
    yield snx


@pytest.fixture
def amount(accounts, token):
    amount = 10_000 * 10 ** token.decimals()
    # In order to get some funds for the token you are about to use,
    # it impersonate an exchange address to use it's funds.
    reserve = accounts.at("0xd551234ae421e3bcba99a0da6d736074f22192ff", force=True)
    token.transfer(accounts[0], amount, {"from": reserve})
    yield amount


@pytest.fixture
def weth():
    yield Contract("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")


@pytest.fixture
def weth_amout(gov, weth):
    weth_amout = 10 ** weth.decimals()
    gov.transfer(weth, weth_amout)
    yield weth_amout


@pytest.fixture
def susd():
    yield Contract("0x57Ab1ec28D129707052df4dF418D58a2D46d5f51")


@pytest.fixture
def snx():
    yield Contract("0xc011a73ee8576fb46f5e1c5751ca3b9fe0af2a6f")


@pytest.fixture
def susd_whale(accounts):
    yield accounts.at("0x49BE88F0fcC3A8393a59d3688480d7D253C37D2A", force=True)


@pytest.fixture
def snx_whale(accounts):
    yield accounts.at("0xA1d7b2d891e3A1f9ef4bBC5be20630C2FEB1c470", force=True)


@pytest.fixture
def resolver(accounts):
    yield Contract("0x823bE81bbF96BEc0e25CA13170F5AaCb5B79ba83")


@pytest.fixture
def issuer(accounts, resolver):
    address = resolver.getAddress(encode_single("bytes32", b"Issuer"))
    yield Contract(address)


@pytest.fixture
def snx_oracle(gov, accounts, SnxOracle, issuer):
    exchange_rate = Contract("0xd69b189020EF614796578AfE4d10378c5e7e1138")
    er_gov = accounts.at(exchange_rate.owner(), force=True)
    new_oracle = gov.deploy(SnxOracle, "0xd69b189020EF614796578AfE4d10378c5e7e1138")
    exchange_rate.setOracle(new_oracle, {"from": er_gov})

    # accepted_synths = ["0xfE18be6b3Bd88A2D2A7f928d00292E7a9963CfC6", "0x5e74C9036fb86BD7eCdcb084a0673EFc32eA31cb", "0x57Ab1ec28D129707052df4dF418D58a2D46d5f51"]
    # symbols = [b"sBTC", b"sETH", b"sUSD"]
    # encoded_symbols = [encode_single("bytes32", x).hex() for x in symbols]
    # print("accepted", encoded_symbols)
    # count = issuer.availableSynthCount()
    # for i in range(0, count):
    #     addy = issuer.availableSynths(i)
    #     e_symbol = issuer.synthsByAddress(addy)
    #     if e_symbol.hex() in encoded_symbols:
    #         print(i, addy)
    #     else:
    #         print("removing", addy, e_symbol)
    #         issuer.removeSynth(e_symbol, {'from': er_gov})

    if (
        exchange_rate.aggregators(encode_single("bytes32", b"SNX"))
        == "0x0000000000000000000000000000000000000000"
    ):
        yield new_oracle
    else:
        # If we don't remove the aggregator prices update through oracle are not considered
        exchange_rate.removeAggregator(
            encode_single("bytes32", b"SNX"), {"from": er_gov}
        )
        exchange_rate.removeAggregator(
            encode_single("bytes32", b"sBTC"), {"from": er_gov}
        )
        exchange_rate.removeAggregator(
            encode_single("bytes32", b"sETH"), {"from": er_gov}
        )
        yield new_oracle


@pytest.fixture
def susd_vault(accounts):
    vault = Contract("0xa5cA62D95D24A4a350983D5B8ac4EB8638887396")
    susd_gov = accounts.at(vault.governance(), force=True)
    vault.setDepositLimit(2 ** 256 - 1, {"from": susd_gov})
    yield vault


@pytest.fixture
def vault(pm, gov, rewards, guardian, management, token):
    Vault = pm(config["dependencies"][0]).Vault
    vault = guardian.deploy(Vault)
    vault.initialize(token, gov, rewards, "", "", guardian)
    vault.setDepositLimit(2 ** 256 - 1, {"from": gov})
    vault.setManagement(management, {"from": gov})
    vault.setPerformanceFee(0, {"from": gov})
    vault.setManagementFee(0, {"from": gov})
    yield vault


@pytest.fixture
def strategy(strategist, keeper, vault, Strategy, gov, susd_vault):
    strategy = strategist.deploy(Strategy, vault, susd_vault)
    strategy.setKeeper(keeper)
    vault.addStrategy(strategy, 10_000, 0, 2 ** 256 - 1, 0, {"from": gov})
    yield strategy
