import pytest
from brownie import config, Contract, Wei
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
def amount(accounts, token, snx_whale):
    amount = 10_000 * 10 ** token.decimals()
    # In order to get some funds for the token you are about to use,
    # it impersonate an exchange address to use it's funds.
    token.transfer(accounts[0], amount, {"from": snx_whale})
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
    yield accounts.at("0xF977814e90dA44bFA03b6295A0616a897441aceC", force=True)


@pytest.fixture
def snx_whale(accounts):
    yield accounts.at("0xA1d7b2d891e3A1f9ef4bBC5be20630C2FEB1c470", force=True)


@pytest.fixture
def snx_oracle(gov, accounts, SnxOracle, interface):
    exchange_rate = interface.IExchangeRates("0xd69b189020EF614796578AfE4d10378c5e7e1138")
    er_gov = accounts.at(exchange_rate.owner(), force=True)
    new_oracle = gov.deploy(SnxOracle, exchange_rate)
    exchange_rate.setOracle(new_oracle, {"from": er_gov})

    if (
        exchange_rate.aggregators(encode_single("bytes32", b"SNX"))
        != "0x0000000000000000000000000000000000000000"
    ):
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
    new_oracle.updateBTCPrice(Wei("30000 ether"), {"from": gov})
    new_oracle.updateETHPrice(Wei("2000 ether"), {"from": gov})
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
def resolver(strategy):
    yield Contract(strategy.resolver())


@pytest.fixture
def debt_cache(resolver):
    debtCache = Contract(resolver.getAddress(encode_single("bytes32", b"DebtCache")))
    try:
        print("Taking Debt Snapshot, this will take a while...")
        debtCache.takeDebtSnapshot({"from": debtCache.owner()})
    except:
        print(
            "Failed. This is expected due to timeout but it is useful to cache, next call will go through"
        )
    yield debtCache


@pytest.fixture
def strategy(strategist, keeper, vault, Strategy, gov, susd_vault):
    strategy = strategist.deploy(Strategy, vault, susd_vault)
    strategy.setKeeper(keeper)
    vault.addStrategy(strategy, 10_000, 0, 2 ** 256 - 1, 0, {"from": gov})
    yield strategy
