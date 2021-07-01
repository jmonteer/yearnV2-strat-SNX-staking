from brownie import chain, Contract
from eth_abi import encode_single


def accumulate_fees(strategy):
    resolver = Contract(strategy.resolver())
    # We don't have any reward because the period is not over yet
    fee_pool = Contract(resolver.getAddress(encode_single("bytes32", b"FeePool")))

    # We sleep for the period time and end the cycle
    chain.sleep(fee_pool.feePeriodDuration())
    chain.mine(1)
    fee_pool.closeCurrentFeePeriod({"from": strategy.strategist()})

    return fee_pool.feesAvailable(strategy)[1]
