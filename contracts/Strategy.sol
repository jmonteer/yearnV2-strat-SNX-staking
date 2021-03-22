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
import "@openzeppelin/contracts/math/Math.sol";

import "../interfaces/ISynthetix.sol";
import "../interfaces/IIssuer.sol";
import "../interfaces/IFeePool.sol";
import "../interfaces/IAddressResolver.sol";
import "../interfaces/IExchangeRates.sol";

import "../interfaces/IVault.sol";
import "../interfaces/ISushiRouter.sol";

contract Strategy is BaseStrategy {
    using SafeERC20 for IERC20;
    using Address for address;
    using SafeMath for uint256;

    uint256 public constant MIN_ISSUE = 50 * 1e18;
    uint256 public constant MAX_RATIO = type(uint256).max;
    uint256 public constant MAX_BPS = 10_000;
    address public constant susd =
        address(0x57Ab1ec28D129707052df4dF418D58a2D46d5f51);
    address public constant resolver =
        address(0x823bE81bbF96BEc0e25CA13170F5AaCb5B79ba83);
    address public constant WETH =
        address(0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2);
    // ISushiRouter public constant sushi =
    //     ISushiRouter(address(0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F));

    ISushiRouter public constant sushi =
        ISushiRouter(address(0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D));

    uint256 public targetRatioMultiplier = 9_000;
    IVault public immutable susdVault;

    constructor(address _vault, address _susdVault)
        public
        BaseStrategy(_vault)
    {
        susdVault = IVault(_susdVault);

        // To deposit susd in the susd vault
        IERC20(susd).safeApprove(address(_susdVault), type(uint256).max);
        // To exchange sUSD for snx
        IERC20(susd).safeApprove(address(sushi), type(uint256).max);
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

    event PrepareReturn(uint256 profit, uint256 loss, uint256 debtPayment);
    event DebtState(
        uint256 balanceOfDebt,
        uint256 lockedCollateral,
        uint256 unlockedCollateral,
        uint256 currentRatio
    );

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
        if (_debtOutstanding > 0) {
            uint256 _amountFreed = 0;
            (_amountFreed, _loss) = liquidatePosition(_debtOutstanding);
            _debtPayment = Math.min(_debtOutstanding, _amountFreed);

            if (_loss > 0) {
                _profit = 0;
            }
        }

        emit PrepareReturn(_profit, _loss, _debtPayment);
        emit DebtState(
            balanceOfDebt(),
            _lockedCollateral(),
            _unlockedCollateral(),
            getCurrentRatio()
        );
    }

    function claimProfits() internal returns (bool) {
        if (estimatedProfit() > 0) {
            // claim fees from Synthetix
            // claim fees (in sUSD) and rewards (in want (SNX))
            _feePool().claimFees();
        }

        // claim profits from Yearn sUSD Vault
        // TODO: Update this taking into account that debt is not always == sUSD issued
        if (balanceOfDebt() < balanceOfSusdInVault()) {
            // balance
            uint256 _valueToWithdraw =
                balanceOfSusdInVault().sub(balanceOfDebt());
            withdrawFromSUSDVault(_valueToWithdraw);
        }

        // sell profits in sUSD for want (SNX) using sushiswap
        uint256 _balance = balanceOfSusd();
        if (_balance > 0) {
            buyWantWithSusd(_balance);
        }
    }

    function withdrawFromSUSDVault(uint256 _amount) internal {
        // Don't leave less than MIN_ISSUE sUSD in the vault
        if (
            _amount > balanceOfSusdInVault() ||
            balanceOfSusdInVault().sub(_amount) < MIN_ISSUE
        ) {
            susdVault.withdraw();
        } else {
            uint256 _sharesToWithdraw =
                _amount.mul(1e18).div(susdVault.pricePerShare());
            susdVault.withdraw(_sharesToWithdraw);
        }
    }

    function buyWantWithSusd(uint256 _amount) internal {
        if (_amount == 0) {
            return;
        }

        address[] memory path = new address[](3);
        path[0] = address(susd);
        path[1] = address(WETH);
        path[2] = address(want);

        sushi.swapExactTokensForTokens(_amount, 0, path, address(this), now);
    }

    function adjustPosition(uint256 _debtOutstanding) internal override {
        if (emergencyExit) {
            return;
        }

        if (_debtOutstanding > balanceOfWant()) {
            return;
        }

        // compare current ratio with target ratio
        uint256 _currentRatio = getCurrentRatio();
        uint256 _targetRatio = getTargetRatio();
        // burn debt (sUSD) if the ratio is too high
        // issue debt (sUSD) if the ratio is too low
        // collateralisation_ratio = debt / collat
        if (_currentRatio < _targetRatio) {
            // issue debt to reach 500% c-ratio
            _synthetix().issueMaxSynths();
        } else if (_currentRatio > _targetRatio) {
            // TODO: calculate debt to be repaid
            uint256 _debtToRepay = 0;
            repayDebt(_debtToRepay);
        }

        // If there is susd in the strategy, send it to the susd vault
        if (balanceOfSusd() > 0) {
            susdVault.deposit();
        }
    }

    function issueTargetSynths() internal {
        uint256 _toIssue = getAmountToIssue();
        if (_toIssue == 0) {
            return;
        }

        // NOTE: we issue the amount to reach target ratio even if we are not able to deposit it
        // in the yearn sUSD Vault because the rewards a
        _synthetix().issueSynths(_toIssue);
    }

    function getAmountToIssue() internal returns (uint256) {
        if (getCurrentRatio() >= getTargetRatio()) {
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

    function getTargetDebt(uint256 _collateral) internal returns (uint256) {
        uint256 _targetRatio = getTargetRatio();
        uint256 _collateralInSUSD = wantToSUSD(_collateral);
        return _targetRatio.mul(_collateralInSUSD);
    }

    event LiquidatePosition(uint256 amount);
    event ReduceCollateral(uint256 amount);

    function liquidatePosition(uint256 _amountNeeded)
        internal
        override
        returns (uint256 _liquidatedAmount, uint256 _loss)
    {
        emit LiquidatePosition(_amountNeeded);
        // if unlocked collateral balance is not enough, repay debt to unlock
        // enough `want` to repay debt.
        // unlocked collateral includes profit just claimed in `prepareReturn`
        uint unlockedWant = _unlockedCollateral();
        if (unlockedWant < _amountNeeded) {
            emit ReduceCollateral(_amountNeeded.sub(_unlockedCollateral()));
            // NOTE: we use _unlockedCollateral because want balance is always the total amount of staked + unstaked want (SNX)
            reduceCollateral(_amountNeeded.sub(unlockedWant));
        }

        // Fetch the unlocked collateral for a second time
        // to update after repaying debt
        unlockedWant = _unlockedCollateral();
        // if not enough want in balance, it means the strategy lost `want`
        if (_amountNeeded > unlockedWant) {
            _liquidatedAmount = unlockedWant;
            _loss = _amountNeeded.sub(unlockedWant);
        } else {
            _liquidatedAmount = _amountNeeded;
        }
    }

    // TODO change to internal
    function _unlockedCollateral() internal view returns (uint256) {
        return balanceOfWant().sub(_lockedCollateral());
    }

    event InsideReduceCollateral(
        uint256 newCollat,
        uint256 targetDebt,
        uint256 amountToRepay
    );

    function reduceCollateral(uint256 amountToFree) internal {
        // amountToFree cannot be higher than lockedCollateral
        // TODO: is it worth it to change this to a Math.min(amountToFree, _lockedCollateral()) ?
        // TODO: to avoid trying to unlock more than locked
        require(
            amountToFree <= _lockedCollateral(),
            "not enough collateral locked"
        );
        if (amountToFree == 0) {
            return;
        }

        uint256 _currentDebt = balanceOfDebt();
        uint256 _newCollateral = _lockedCollateral().sub(amountToFree);
        uint256 _targetDebt = _newCollateral.mul(getIssuanceRatio()).div(1e18);
        // NOTE: _newCollateral will always be < _lockedCollateral() so _targetDebt will always be < _currentDebt
        uint256 _amountToRepay = _currentDebt.sub(_targetDebt);

        emit InsideReduceCollateral(
            _newCollateral,
            _targetDebt,
            _amountToRepay
        );
        repayDebt(_amountToRepay);
    }

    function repayDebt(uint256 amountToRepay) internal {
        if (amountToRepay <= 0) {
            return;
        }

        uint _debtBalance = balanceOfDebt();
        // in case the strategy is going to repay almost all debt, it repays the total amount of debt
        if(_debtBalance.sub(amountToRepay) <= MIN_ISSUE) {
            amountToRepay = _debtBalance;
        }

        // TODO: should do Math.min() to repay max possible?
        require(amountToRepay <= balanceOfSusdInVault().add(balanceOfSusd()), "!not enough balance to repay debt");

        if(amountToRepay > balanceOfSusd()) {
            // there is not enough balance in strategy to repay debt
            // we withdraw from susdvault
            uint _withdrawAmount = amountToRepay.sub(balanceOfSusd());
            uint _withdrawShares = _withdrawAmount.mul(1e18).div(susdVault.pricePerShare());
            susdVault.withdraw(_withdrawShares);
            if(amountToRepay.sub(balanceOfSusd()) > balanceOfSusdInVault()) {
                // there is not enough balance in sUSDvault to repay required debt
                // if debt is too high to be repaid using current funds, the strategy should: 
                // 1. repay max amount of debt
                // 2. sell unlocked want to buy required sUSD to pay remaining debt
                // 3. repay debt
            }
        }

        // TODO: what to do in case of waitingPeriod?
        // TODO: confirm this is the right usage for waitingPeriod
        if (!_synthetix().isWaitingPeriod("sUSD")) {
            _synthetix().burnSynths(amountToRepay);
        }
    }

    function _lockedCollateral() public view returns (uint256) {
        // want (SNX) that is not transferable (to keep max 500% c-ratio)
        uint256 _debt = balanceOfDebt();
        // NOTE: issuanceRatio is returned as debt/collateral. This is, 500% c-ratio is 0.2 collateralisationRatio
        uint256 _collateralRequired = _debt.mul(1e18).div(getIssuanceRatio()); // collateral required to keep 500% c-ratio

        uint256 _wantBalance = balanceOfWant();
        // if the strategy's c-ratio is below 500%, the locked amount is the total SNX balance
        return Math.min(_wantBalance, _collateralRequired);
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

    function setTargetRatioMultiplier(uint256 _targetRatioMultiplier)
        external
        onlyGovernance
    {
        targetRatioMultiplier = _targetRatioMultiplier;
    }

    function getIssuanceRatio() public view returns (uint256) {
        return _issuer().issuanceRatio();
    }

    function getTargetRatio() public view returns (uint256) {
        return
            _issuer().issuanceRatio().mul(targetRatioMultiplier).div(MAX_BPS);
    }

    function repayToRatio(uint256 _amount) internal {
        // TODO
    }

    function balanceOfWant() public view returns (uint256) {
        return IERC20(want).balanceOf(address(this));
    }

    function balanceOfSusd() public view returns (uint256) {
        return IERC20(susd).balanceOf(address(this));
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
        if (_amount == 0) {
            return 0;
        }

        return _amount.mul(1e18).div(_exchangeRates().rateForCurrency("SNX"));
    }

    function wantToSUSD(uint256 _amount) internal returns (uint256) {
        if (_amount == 0) {
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

    // TODO make internal
    function _synthetix() public view returns (ISynthetix) {
        return ISynthetix(IAddressResolver(resolver).getAddress("Synthetix"));
    }

    function _feePool() public view returns (IFeePool) {
        return IFeePool(IAddressResolver(resolver).getAddress("FeePool"));
    }

    function _issuer() public view returns (IIssuer) {
        return IIssuer(IAddressResolver(resolver).getAddress("Issuer"));
    }

    function _exchangeRates() public view returns (IExchangeRates) {
        return
            IExchangeRates(
                IAddressResolver(resolver).getAddress("ExchangeRates")
            );
    }
}
