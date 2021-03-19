// SPDX-License-Identifier: AGPL-3.0
pragma solidity 0.6.12;
pragma experimental ABIEncoderV2;

// These are the core Yearn libraries
import {BaseStrategy} from "@yearnvaults/contracts/BaseStrategy.sol";
import {
    SafeERC20,
    SafeMath,
    IERC20,
    Address
} from "@openzeppelin/contracts/token/ERC20/SafeERC20.sol";

import "../interfaces/ISynthetix.sol";
import "../interfaces/IIssuer.sol";
import "../interfaces/IFeePool.sol";
import "../interfaces/IAddressResolver.sol";
import "../interfaces/IVault.sol";

contract Strategy is BaseStrategy {
    using SafeERC20 for IERC20;
    using Address for address;
    using SafeMath for uint256;

    uint256 public MAX_RATIO = uint256(-1);

    address public constant susd =
        address(0x57Ab1ec28D129707052df4dF418D58a2D46d5f51);
    address public constant resolver =
        address(0x823bE81bbF96BEc0e25CA13170F5AaCb5B79ba83);

    IVault public susdVault;

    constructor(address _vault, address _susdVault)
        public
        BaseStrategy(_vault)
    {
        susdVault = IVault(_susdVault);

        // To deposit susd in the susd vault
        IERC20(susd).safeApprove(address(susdVault), type(uint256).max);
    }

    function name() external view override returns (string memory) {
        return "StrategySynthetixSusdMinter";
    }

    function estimatedTotalAssets() public view override returns (uint256) {
        return
            balanceOfWant()
                .add(wantFutureProfit())
                .add(balanceOfSusdVaultInWant())
                .sub(debtInWant());
    }

    function prepareReturn(uint256 _debtOutstanding)
        internal
        override
        returns (
            uint256 _profit,
            uint256 _loss,
            uint256 _debtPayment
        )
    {}

    function adjustPosition(uint256 _debtOutstanding) internal override {}

    function liquidatePosition(uint256 _amountNeeded)
        internal
        override
        returns (uint256 _liquidatedAmount, uint256 _loss)
    {
        if (balanceOfWant() < _amountNeeded) {
            reduceCollateral(_amountNeeded.sub(balanceOfWant()));
        }

        uint256 totalAssets = balanceOfWant();
        if (_amountNeeded > totalAssets) {
            _liquidatedAmount = totalAssets;
            _loss = _amountNeeded.sub(totalAssets);
        } else {
            _liquidatedAmount = _amountNeeded;
        }
    }

    function prepareMigration(address _newStrategy) internal override {
        liquidatePosition(vault.strategies(_newStrategy).totalDebt);
    }

    function protectedTokens()
        internal
        view
        override
        returns (address[] memory)
    {
        address[] memory protected = new address[](1);
        protected[0] = susd;
        return protected;
    }

    function tendTrigger(uint256 callCost) public view override returns (bool) {
        uint256 _currentRatio = getCurrentRatio();
        uint256 _targetRatio = getTargetRatio();

        if (_currentRatio >= _targetRatio) {
            return false;
        }

        return _currentRatio.sub(_targetRatio) < 30000;
    }

    function getCurrentRatio() public view returns (uint256) {
        uint256 debt = balanceOfDebt();
        // If we don't have debt, we have unlimited ratio
        if (debt == 0) {
            return MAX_RATIO;
        }

        uint256 ratio = this.issuer().collateralisationRatio(address(this));
        return ratio;
    }

    function getTargetRatio() public view returns (uint256) {
        return this.issuer().issuanceRatio();
    }

    function reduceCollateral(uint256 _amount) internal {
        //require(balanceOfCollateral() >= _amount, "Not enough collateral");
    }

    function balanceOfWant() public view returns (uint256) {
        return IERC20(want).balanceOf(address(this));
    }

    function balanceOfDebt() public view returns (uint256) {
        return this.synthetix().debtBalanceOf(address(this), "sUSD");
    }

    function balanceOfSusdInVault() public view returns (uint256) {
        return
            susdVault
                .balanceOf(address(this))
                .mul(susdVault.pricePerShare())
                .div(1e18);
    }

    function balanceOfSusdVaultInWant() public view returns (uint256) {
        uint256 _balance = balanceOfSusdInVault();
        if (_balance == 0) {
            return 0;
        }

        // TODO FIX THIS
        //return _balance.mul(1e18).div(fMint.getPrice(address(want)));
        return 1;
    }

    function debtInWant() public view returns (uint256) {
        // TODO fix
        return 0;
    }

    function wantFutureProfit() public view returns (uint256) {
        uint256 availableFees;
        uint256 availableRewards;
        (availableFees, availableRewards) = this.feePool().feesAvailable(
            address(this)
        );

        // TODO convert availableFees from susd to snx
        return availableRewards.add(availableFees);
    }

    // TODO: make internal
    function synthetix() external view returns (ISynthetix) {
        return ISynthetix(IAddressResolver(resolver).getAddress("Synthetix"));
    }

    // TODO: make internal
    function feePool() external view returns (IFeePool) {
        return IFeePool(IAddressResolver(resolver).getAddress("FeePool"));
    }

    // TODO: make internal
    function issuer() external view returns (IIssuer) {
        return IIssuer(IAddressResolver(resolver).getAddress("Issuer"));
    }
}
