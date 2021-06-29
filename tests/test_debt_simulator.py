import brownie
import pytest
from brownie import Contract, chain, Wei
from eth_abi import encode_single
import datetime


def test_debt_simulator(snx, susd, susd_whale, snx_whale, snx_oracle, bob, gov):
    chain.snapshot()
    beginning = datetime.datetime.now()
    print(datetime.datetime.now())
    resolver = Contract("0x823bE81bbF96BEc0e25CA13170F5AaCb5B79ba83")
    synthetix = Contract("0x97767D7D04Fd0dB0A1a2478DCd4BA85290556B48")
    settings = Contract(
        resolver.getAddress(encode_single("bytes32", b"SystemSettings"))
    )
    settings.setRateStalePeriod(24 * 3600 * 6, {"from": settings.owner()})
    settings.setDebtSnapshotStaleTime(24 * 3600 * 6, {"from": settings.owner()})

    # bob receives snx
    snx.transfer(bob, Wei("1000 ether"), {"from": snx_whale})
    # price of ether is $20
    snx_oracle.updateSnxPrice(Wei("20 ether"), {"from": gov})

    debtCache = Contract(resolver.getAddress(encode_single("bytes32", b"DebtCache")))
    try:
        print("Taking Debt Snapshot, this will take a while...")
        debtCache.takeDebtSnapshot({"from": debtCache.owner()})
    except:
        print(
            "Failed. This is expected due to timeout but it is useful to cache, next call will go through"
        )

    # set up:
    snx_oracle.updateBTCPrice(Wei("30000 ether"), {"from": gov})
    snx_oracle.updateETHPrice(Wei("1500 ether"), {"from": gov})
    debtCache.takeDebtSnapshot({"from": debtCache.owner()})

    # issue some debt
    synthetix.issueMaxSynths({"from": bob})
    # solving bug
    debtCache.takeDebtSnapshot({"from": debtCache.owner()})
    print("Issued debt when BTC @ 30,000 and ETH @ 1500")
    print(susd.balanceOf(bob))
    print(synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD")))
    print()
    # change price of ETH (up 10%)
    prev_debt = synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    snx_oracle.updateETHPrice(Wei("1650 ether"), {"from": gov})
    debtCache.takeDebtSnapshot({"from": debtCache.owner()})
    post_debt = synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    print("BTC @ 30,000 and ETH @ 1,650 (+10%)")
    print(susd.balanceOf(bob))  # should not change
    print(
        synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    )  # should be down
    print(f"Debt changed a {post_debt/prev_debt*100-100}%")
    print()
    # reset ETH price
    prev_debt = synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    snx_oracle.updateETHPrice(Wei("1500 ether"), {"from": gov})
    debtCache.takeDebtSnapshot({"from": debtCache.owner()})
    post_debt = synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    print("BTC @ 30,000 and ETH @ 1,500 (0%)")
    print(susd.balanceOf(bob))  # should not change
    print(
        synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    )  # should be down
    print(f"Debt changed a {post_debt/prev_debt*100-100}%")
    print()
    # change price of ETH (down 10%)
    prev_debt = synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    snx_oracle.updateETHPrice(Wei("1350 ether"), {"from": gov})
    debtCache.takeDebtSnapshot({"from": debtCache.owner()})
    post_debt = synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    print("BTC @ 30,000 and ETH @ 1,350 (-10%)")
    print(susd.balanceOf(bob))  # should not change
    print(
        synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    )  # should be down
    print(f"Debt changed a {post_debt/prev_debt*100-100}%")
    print()
    # reset ETH price
    prev_debt = synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    snx_oracle.updateETHPrice(Wei("1500 ether"), {"from": gov})
    debtCache.takeDebtSnapshot({"from": debtCache.owner()})
    post_debt = synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    print("BTC @ 30,000 and ETH @ 1,500 (0%)")
    print(susd.balanceOf(bob))  # should not change
    print(
        synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    )  # should be down
    print(f"Debt changed a {post_debt/prev_debt*100-100}%")
    print()
    # change price of BTC (up 10%)
    prev_debt = synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    snx_oracle.updateBTCPrice(Wei("33000 ether"), {"from": gov})
    debtCache.takeDebtSnapshot({"from": debtCache.owner()})
    post_debt = synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    print("BTC @ 33,000 (+10%) and ETH @ 1,500")
    print(susd.balanceOf(bob))  # should not change
    print(
        synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    )  # should be down
    print(f"Debt changed a {post_debt/prev_debt*100-100}%")
    print()
    # reset BTC price
    prev_debt = synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    snx_oracle.updateBTCPrice(Wei("30000 ether"), {"from": gov})
    snx_oracle.updateETHPrice(Wei("1500 ether"), {"from": gov})
    debtCache.takeDebtSnapshot({"from": debtCache.owner()})
    post_debt = synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    print("BTC @ 30,000 and ETH @ 1,500 (0%)")
    print(susd.balanceOf(bob))  # should not change
    print(
        synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    )  # should be down
    print(f"Debt changed a {post_debt/prev_debt*100-100}%")
    print()
    # change price of BTC and ETH(up 10%)
    prev_debt = synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    snx_oracle.updateBTCPrice(Wei("33000 ether"), {"from": gov})
    snx_oracle.updateETHPrice(Wei("1650 ether"), {"from": gov})
    debtCache.takeDebtSnapshot({"from": debtCache.owner()})
    post_debt = synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    print("BTC @ 33,000 (+10%) and ETH @ 1,650 (+10%)")
    print(susd.balanceOf(bob))  # should not change
    print(
        synthetix.debtBalanceOf(bob, encode_single("bytes32", b"sUSD"))
    )  # should be down
    print(f"Debt changed a {post_debt/prev_debt*100-100}%")
    print()
    print(datetime.datetime.now())
    print(datetime.datetime.now() - beginning)
    chain.revert()
