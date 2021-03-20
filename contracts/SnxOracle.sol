// SPDX-License-Identifier: AGPL-3.0
pragma solidity 0.6.12;
pragma experimental ABIEncoderV2;

import {
    SafeERC20,
    SafeMath,
    IERC20,
    Address
} from "@openzeppelin/contracts/token/ERC20/SafeERC20.sol";
import "@openzeppelin/contracts/math/Math.sol";

interface IER {
    function updateRates(
        bytes32[] calldata currencyKeys,
        uint256[] calldata newRates,
        uint256 timeSent
    ) external returns (bool);
}

contract SnxOracle {
    IER public exchangeRate;

    constructor(address _exchangeRates) public {
        exchangeRate = IER(_exchangeRates);
    }

    function updateSnxPrice(uint256 _price) external {
        bytes32[] memory keys = new bytes32[](1);
        keys[0] = "SNX";
        uint256[] memory rates = new uint256[](1);
        rates[0] = _price;
        exchangeRate.updateRates(keys, rates, now);
    }
}
