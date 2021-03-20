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
import "../interfaces/IExchangeRates.sol";

contract Strategy is BaseStrategy {
    using SafeERC20 for IERC20;
    using Address for address;
    using SafeMath for uint256;

    uint256 public constant MIN_ISSUE = 50 * 1e18;
    uint256 public constant MAX_RATIO = type(uint256).max;
    uint256 public constant MAX_BPS = 10_000;
    uint256 public targetRatioMultiplier = 9_000;
    address public constant susd =
        address(0x57Ab1ec28D129707052df4dF418D58a2D46d5f51);
    address public constant resolver =
        address(0x823bE81bbF96BEc0e25CA13170F5AaCb5B79ba83);
    address public constant WETH = 
        address(0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2);
    ISushiRouter public constant sushi = 
        ISushiRouter(0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f);

    IVault public immutable susdVault;

    constructor(address _vault, address _susdVault)
        public
        BaseStrategy(_vault)
    {
        susdVault = IVault(_susdVault);

        // To deposit susd in the susd vault
        IERC20(susd).safeApprove(address(_susdVault), type(uint256).max);
    }

    function name() external view override returns (string memory) {
        return "StrategySynthetixSusdMinter";
    }

    function estimatedTotalAssets() public view override returns (uint256) {
        return
            balanceOfWant()
                .add(estimatedProfit())
                .add(sUSDToWant(balanceOfSusdInVault()))
                .sub(sUSDToWant(balanceOfDebt()));
    }

    function prepareReturn(uint256 _debtOutstanding)
        internal
        override
        returns (
            uint256 _profit,
            uint256 _loss,
            uint256 _debtPayment
        )
    {
        uint256 balanceOfWantBefore = balanceOfWant();

        claimProfits();

        _profit = balanceOfWant().sub(balanceOfWantBefore);
        
        // if the vault is claiming repayment of debt 
        if(_debtOutstanding > 0) {
            uint256 _amountFreed = 0; 
            (_amountFreed, _loss) = liquidatePosition(_debtOutstanding);
            _debtPayment = Math.min(_debtOutstanding, _amountFreed);

            if(_loss > 0) {
                _profit = 0;
            }
        }
    }

    function claimProfits() internal returns (bool) {
        if(estimatedProfits() > 0){
            // claim fees from Synthetix
            // claim fees (in sUSD) and rewards (in want (SNX))
            _feePool().claimFees();
        }

        // claim profits from Yearn sUSD Vault
        // TODO: Update this taking into account that debt is not always == sUSD issued
        if(balanceOfDebt() < balanceOfSUSDInVault()){
            // balance
            uint256 _valueToWithdraw = balanceOfSUSDInVault().sub(balanceOfDebt());
            withdrawFromSUSDVault(_valueToWithdraw);
        }

        // sell profits in sUSD for want (SNX) using sushiswap
        uint256 _balance = balanceOfSUSD();
        if(_balance > 0) {
            buyWantWithSUSD(_balance);
        }
    }

    function withdrawFromSUSDVault(uint256 _amount) internal {
        // Don't leave less than MIN_ISSUE sUSD in the vault
        if (
            _amount > balanceOfFusdInVault() ||
            balanceOfSUSDInVault().sub(_amount) < MIN_ISSUE
        ) {
            susdVault.withdraw();
        } else {
            uint256 _sharesToWithdraw =
                _amount.mul(1e18).div(susdVault.pricePerShare());
            susdVault.withdraw(_sharesToWithdraw);
        }
    }

    function buyWantWithSUSD(uint256 _amount) internal {
        if (_amount == 0) {
            return;
        }

        address[] memory path = new address[](3);
        path[0] = address(sUSD);
        path[1] = address(WETH);
        path[2] = address(want);

        sushi.swapExactTokensForTokens(_amount, 0, path, address(this), now);
    }

    function adjustPosition(uint256 _debtOutstanding) internal override {
        if(emergencyExit){
            return;
        }

        if(_debtOutstanding > balanceOfWant()) {
            return; 
        }

        // compare current ratio with target ratio
        uint _currentRatio = getCurrentRatio();
        uint _targetRatio = getTargetRatio();
        // burn debt (sUSD) if the ratio is too high
        // issue debt (sUSD) if the ratio is too low
        // collateralisation_ratio = debt / collat
        if(_currentRatio < _targetRatio) {
            // issue debt to reach 500% c-ratio
            _synthetix().issueMaxSynths();
            //issueTargetSynths();
            
        } else if(_currentRatio > _targetRatio){
            // burn debt
            reduceDebtToTargetRatio();
        }

        // deposit sUSD in Yearn sUSD Vault
    }

    function issueTargetSynths() internal {
        uint256 _toIssue = getAmountToIssue();
        if(_toIssue == 0) {
            return;
        }

        // NOTE: we issue the amount to reach target ratio even if we are not able to deposit it
        // in the yearn sUSD Vault because the rewards a
        _synthetix().issueSynths(_toIssue);
    }

    function getAmountToIssue() internal {
        if(getCurrentRatio() >= getTargetRatio()){
            return 0;
        }

        uint256 _targetDebt = getTargetDebt(balanceOfWant());
        uint256 _debt = balanceOfDebt();
        uint256 _toIssue = _targetDebt < _debt ? 0 : _targetDebt.sub(_debt);

        if (_toIssue > MIN_ISSUE) {
            return _toIssue;
        } else {
            return 0;
        }
    }

    function getTargetDebt(uint _collateral) internal returns (uint256){
        uint256 _targetRatio = getTargetRatio();
        uint256 _collateralInSUSD = wantToSUSD(_collateral);
        return _targetRatio.mul(_collateralInSUSD);
    }

    function liquidatePosition(uint256 _amountNeeded)
        internal
        override
        returns (uint256 _liquidatedAmount, uint256 _loss)
    {
        // if want balance is not enough, repay debt to unlock enough `want` to repay debt
        // balanceOfWant includes profit just claimed in `prepareReturn`
        if (balanceOfWant() < _amountNeeded) {
            // NOTE: we use _unlockedCollateral because want balance is always the total amount of staked + unstaked want (SNX)
            reduceCollateral(_amountNeeded.sub(_unlockedCollateral()));
        }

        // 
        uint256 _unlockedWant = _unlockedCollateral();
        // if not enough want in balance, it means the strategy lost `want`
        if (_amountNeeded > _unlockedWant) {
            _liquidatedAmount = _unlockedWant;
            _loss = _amountNeeded.sub(_unlockedWant);
        } else {
            _liquidatedAmount = _amountNeeded;
        }
    }

    function _unlockedCollateral() internal returns (uint256) {
        return balanceOfWant().sub(_lockedCollateral());
    }

    function reduceCollateral(uint amountToFree) internal {
        // amountToFree cannot be higher than lockedCollateral
        // TODO: is it worth it to change this to a Math.min(amountToFree, _lockedCollateral()) ? 
        // CONT: to avoid trying to unlock more than locked
        require(amountToFree <= _lockedCollateral(), "not enough collateral locked");
        if(amountToFree == 0) {
            return;
        }

        uint256 _currentDebt = balanceOfDebt();
        uint256 _newCollateral = _lockedCollateral().sub(amountToFree);
        // NOTE: _newCollateral will always be < _lockedCollateral() so _targetDebt will always be < _currentDebt
        uint256 _targetDebt = _newCollateral.mul(getIssuanceRatio()).div(1e18);

        uint256 _amountToRepay = _currentDebt.sub(_targetDebt);

        repayDebt(_amountToRepay);
    }

    function repayDebt(uint256 _amountToRepay) internal {
        if(_amountToRepay <= 0) {
            return;
        }

        // TODO: what to do in case of waitingPeriod?
        // TODO: confirm this is the right usage for waitingPeriod
        if(!_synthetix().isWaitingPeriod("sUSD")){
            _synthetix().burnSynths(_amountToRepay);
        }
    }

    function _lockedCollateral() internal returns (uint256) {
        // want (SNX) that is not transferable (to keep max 500% c-ratio)
        uint256 _debt = balanceOfDebt();
        // NOTE: issuanceRatio is returned as debt/collateral. This is, 500% c-ratio is 0.2 collateralisationRatio 
        uint256 _collateralRequired = _debt.mul(1e18).div(getIssuanceRatio()); // collateral required to keep 500% c-ratio

        uint256 _balance = balanceOfWant();

        // Return the minimum value because in case the strategy's c-ratio is below 500%, the locked amount is the total SNX balance
        return Math.min(_balance, _collateralRequired);
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
        // ratio = debt / collateral
        // i.e. ratio is 0 if debt is 0
        return _issuer().collateralisationRatio(address(this));
    }

    // function setTargetRatioMultiplier(uint256 _targetRatioMultiplier) external onlyGovernance {
    //     targetRatioMultiplier = _targetRatioMultiplier;
    // }

    function getIssuanceRatio() public view returns (uint256) {
        return _issuer().issuanceRatio();
    }

    function getTargetRatio() public view returns (uint256) {
        return _issuer().issuanceRatio().mul(targetRatioMultiplier).div(MAX_BPS);
    }

    function repayToRatio(uint256 _amount) internal {
        
    }

    function balanceOfWant() public view returns (uint256) {
        return IERC20(want).balanceOf(address(this));
    }

    function balanceOfDebt() public view returns (uint256) {
        return _synthetix().debtBalanceOf(address(this), "sUSD");
    }

    function balanceOfSusdInVault() public view returns (uint256) {
        return
            susdVault
                .balanceOf(address(this))
                .mul(susdVault.pricePerShare())
                .div(1e18);
    }

    function sUSDToWant(uint256 _amount) public view returns (uint256) {
        if(_amount == 0) {
            return 0;
        } 

        return _amount.mul(1e18).div(_exchangeRates().rateForCurrency("SNX"));
    }

    function wantToSUSD(uint amount) internal returns (uint256) {
        if(_amount == 0) {
            return 0;
        } 

        return _amount.mul(_exchangeRates().rateForCurrency("SNX")).div(1e18);
    }

    function estimatedProfit() public view returns (uint256) {
        uint256 availableFees; // in sUSD
        uint256 availableRewards; // in `want` (SNX)

        (availableFees, availableRewards) = _feePool().feesAvailable(
            address(this)
        );

        return availableRewards.add(sUSDToWant(availableFees));
    }

    function _synthetix() internal view returns (ISynthetix) {
        return ISynthetix(IAddressResolver(resolver).getAddress("Synthetix"));
    }

    function _feePool() internal view returns (IFeePool) {
        return IFeePool(IAddressResolver(resolver).getAddress("FeePool"));
    }

    function _issuer() internal view returns (IIssuer) {
        return IIssuer(IAddressResolver(resolver).getAddress("Issuer"));
    }

    function _exchangeRates() internal view returns (IExchangeRates) {
        return IExchangeRates(IAddressResolver(resolver).getAddress("ExchangeRates"));
    }
}
