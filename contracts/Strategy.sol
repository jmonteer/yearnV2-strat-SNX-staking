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
import "../interfaces/IRewardEscrowV2.sol";

import "../interfaces/IVault.sol";
import "../interfaces/ISushiRouter.sol";

contract Strategy is BaseStrategy {
    using SafeERC20 for IERC20;
    using Address for address;
    using SafeMath for uint256;

    uint256 public constant MIN_ISSUE = 50 * 1e18; // TODO: update this to avoid constant new issues of synths
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

    uint256 public targetRatioMultiplier = 15_000;
    IVault public immutable susdVault;

    // to keep track of next entry to vest
    uint256 public entryIDIndex = 0;
    uint256[] public entryIDs; // entryIDs that have been claimed by the strategy

    bytes32 private constant CONTRACT_SYNTHETIX = "Synthetix";
    bytes32 private constant CONTRACT_EXRATES = "ExchangeRates";
    bytes32 private constant CONTRACT_REWARDESCROW_V2 = "RewardEscrowV2";
    bytes32 private constant CONTRACT_ISSUER = "Issuer";
    bytes32 private constant CONTRACT_FEEPOOL = "FeePool";

    constructor(address _vault, address _susdVault)
        public
        BaseStrategy(_vault)
    {
        susdVault = IVault(_susdVault);

        // To deposit susd in the susd vault
        IERC20(susd).safeApprove(address(_susdVault), type(uint256).max);
        // To exchange sUSD for snx
        IERC20(susd).safeApprove(address(sushi), type(uint256).max);
        // To exchange SNX for sUSD
        IERC20(want).safeApprove(address(sushi), type(uint256).max);
    }

    // ********************** SETTERS **********************
    function setTargetRatioMultiplier(uint256 _targetRatioMultiplier)
        external
        onlyGovernance
    {
        targetRatioMultiplier = _targetRatioMultiplier;
    }

    // ********************** YEARN STRATEGY **********************

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
        vestNextRewardsEntry();

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
        // NOTE: target ratio is under 500% to maximize APY
        uint256 _targetRatio = getTargetRatio();
        // burn debt (sUSD) if the ratio is too high
        // collateralisation_ratio = debt / collat

        if (_currentRatio > _targetRatio) {
            // current debt ratio might be unhealthy
            // we need to repay some debt to get back to the optimal range
            uint256 _debtToRepay =
                balanceOfDebt().sub(getTargetDebt(balanceOfWant()));
            repayDebt(_debtToRepay);
        } else if (_targetRatio.sub(_currentRatio) > 1e16) {
            // min threshold to act on differences = 1e16
            // if there is enough collateral to issue Synth, issue it
            // this should put the c-ratio around 500%
            if (_synthetix().maxIssuableSynths(address(this)) >= MIN_ISSUE) {
                _synthetix().issueMaxSynths();
            }
        }

        // If there is susd in the strategy, send it to the susd vault
        if (balanceOfSusd() > 0) {
            susdVault.deposit();
        }
    }

    function liquidatePosition(uint256 _amountNeeded)
        internal
        override
        returns (uint256 _liquidatedAmount, uint256 _loss)
    {
        // if unlocked collateral balance is not enough, repay debt to unlock
        // enough `want` to repay debt.
        // unlocked collateral includes profit just claimed in `prepareReturn`
        uint256 unlockedWant = _unlockedWant();
        if (unlockedWant < _amountNeeded) {
            // NOTE: we use _unlockedWant because `want` balance is the total amount of staked + unstaked want (SNX)
            reduceLockedCollateral(_amountNeeded.sub(unlockedWant));
        }

        // Fetch the unlocked collateral for a second time
        // to update after repaying debt
        unlockedWant = _unlockedWant();
        // if not enough want in balance, it means the strategy lost `want`
        if (_amountNeeded > unlockedWant) {
            _liquidatedAmount = unlockedWant;
            _loss = _amountNeeded.sub(unlockedWant);
        } else {
            _liquidatedAmount = _amountNeeded;
        }
    }

    function prepareMigration(address _newStrategy) internal override {
        liquidatePosition(vault.strategies(_newStrategy).totalDebt);
    }

    // ********************** OPERATIONS FUNCTIONS **********************

    function reduceLockedCollateral(uint256 amountToFree) internal {
        // amountToFree cannot be higher than the amount that is unlockable
        amountToFree = Math.min(amountToFree, _unlockableWant());

        if (amountToFree == 0) {
            return;
        }

        uint256 _currentDebt = balanceOfDebt();
        uint256 _newCollateral = _lockedCollateral().sub(amountToFree);
        uint256 _targetDebt = _newCollateral.mul(getIssuanceRatio()).div(1e18);
        // NOTE: _newCollateral will always be < _lockedCollateral() so _targetDebt will always be < _currentDebt
        uint256 _amountToRepay = _currentDebt.sub(_targetDebt);

        repayDebt(_amountToRepay);
    }

    function repayDebt(uint256 amountToRepay) internal {
        // debt can grow over the amount of sUSD minted (see Synthetix docs)
        // if that happens, we might not have enough sUSD to repay debt
        // if we withdraw in this situation, we need to sell `want` to repay debt and would have losses
        // this can only be done if c-Ratio is over 272% (otherwise there is not enough unlocked)
        if (amountToRepay == 0) {
            return;
        }

        uint256 _debtBalance = balanceOfDebt();
        // max amount to be repaid is the total balanceOfDebt
        amountToRepay = Math.min(_debtBalance, amountToRepay);

        // in case the strategy is going to repay almost all debt, it should repay the total amount of debt
        // TODO: avoid strategy lock due to trying to repay a greater amount of debt than the amount it can serve
        if (_debtBalance.sub(amountToRepay) <= MIN_ISSUE) {
            amountToRepay = _debtBalance;
        }

        uint256 currentSusdBalance = balanceOfSusd();
        if (amountToRepay > currentSusdBalance) {
            // there is not enough balance in strategy to repay debt

            // we withdraw from susdvault
            uint256 _withdrawAmount = amountToRepay.sub(currentSusdBalance);
            withdrawFromSUSDVault(_withdrawAmount);
            // we fetch sUSD balance for a second time and check if now there is enough
            currentSusdBalance = balanceOfSusd();
            if (amountToRepay > currentSusdBalance) {
                // there was not enough balance in strategy and sUSDvault to repay debt

                // debt is too high to be repaid using current funds, the strategy should:
                // 1. repay max amount of debt
                // 2. sell unlocked want to buy required sUSD to pay remaining debt
                // 3. repay debt

                if (currentSusdBalance > 0) {
                    // we burn the full sUSD balance to unlock `want` (SNX) in order to sell
                    if (burnSusd(currentSusdBalance)) {
                        // subject to minimumStakePeriod
                        // if successful burnt, update remaining amountToRepay
                        amountToRepay = amountToRepay.sub(currentSusdBalance);
                    }
                }

                // buy enough sUSD to repay outstanding debt, selling `want` (SNX)
                if (_unlockedWant() > 0) {
                    buySusdWithWant(amountToRepay);
                }
                // amountToRepay should equal balanceOfSusd() (we just bought `amountToRepay` sUSD)
            }
        }

        // repay sUSD debt by burning the synth
        if (amountToRepay > 0) {
            burnSusd(amountToRepay); // this method is subject to minimumStakePeriod (see Synthetix docs)
        }
    }

    function claimProfits() internal returns (bool) {
        // two profit sources: Synthetix protocol and Yearn sUSD Vault
        uint256 feesAvailable;
        uint256 rewardsAvailable;
        (feesAvailable, rewardsAvailable) = _getFeesAvailable();
        if (feesAvailable > 0 || rewardsAvailable > 0) {
            // claim fees from Synthetix
            // claim fees (in sUSD) and rewards (in want (SNX))
            // Synthetix protocol requires issuers to have a c-ratio above 500% to be able to claim fees
            // so we need to burn some sUSD

            // TODO: check if estimatedProfit is high enough for it to be worth it to go back to 500% and realise losses
            // jmonteer: first approach: only claim (i.e. burnToTarget) if the amount to repay required debt is less than 30% of cash
            uint256 _requiredPayment =
                balanceOfDebt().sub(getTargetDebt(_collateral()));
            uint256 _maxCash =
                balanceOfSusd().add(balanceOfSusdInVault()).mul(30).div(100);
            bool _claim = _requiredPayment > _maxCash ? false : true;
            if (_claim) {
                // we need to burn sUSD to target
                burnSusdToTarget(); // this might not be possible (if debt >> cash to repay)

                // if a vesting entry is going to be created, we save its ID to keep track of its vesting
                if (rewardsAvailable > 0) {
                    entryIDs.push(_rewardEscrowV2().nextEntryId());
                }

                _feePool().claimFees();
            }
        }

        // claim profits from Yearn sUSD Vault
        // TODO: Update this taking into account that debt is not always == sUSD issued
        // jmonteer: I would not withdraw profits until the balanceOfDebt is lower than balanceOfSusdInVault
        // jmonteer: even if it is technically in profits because amount deposited is lower than amount to withdraw
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

    function vestNextRewardsEntry() internal {
        // Synthetix protocol sends SNX staking rewards to a escrow contract that keeps them 52 weeks, until they vest
        // each time we claim the SNX rewards, a VestingEntry is created in the escrow contract for the amount that was owed
        // we need to keep track of those VestingEntries to know when they vest and claim them
        // after they vest and we claim them, we will receive them in our balance (strategy's balance)
        if (entryIDs.length == 0) return;

        // The strategy keeps track of the next VestingEntry expected to vest and only when it has vested, it checks the next one
        // this works because the VestingEntries record has been saved in chronological order and they will vest in chronological order too
        IRewardEscrowV2 re = _rewardEscrowV2();
        uint256[] memory nextEntryID;
        uint256 index = entryIDIndex;
        nextEntryID[0] = entryIDs[index];
        uint256 _claimable =
            re.getVestingEntryClaimable(address(this), nextEntryID[0]);
        // check if we need to vest
        if (_claimable == 0) {
            return;
        }

        // vest entryID
        re.vest(nextEntryID);

        // we update the nextEntryID to point to the next VestingEntry
        entryIDIndex++;
    }

    function tendTrigger(uint256 callCost) public view override returns (bool) {
        uint256 _currentRatio = getCurrentRatio(); // debt / collateral
        uint256 _targetRatio = getTargetRatio(); // max debt ratio. over this number, we consider debt unhealthy
        uint256 _issuanceRatio = getIssuanceRatio(); // preferred c-ratio by Synthetix (See protocol docs)

        if (_currentRatio < _issuanceRatio) {
            // strategy needs to take more debt
            // only return true if the difference is greater than a threshold
            return _issuanceRatio.sub(_currentRatio) >= 1e16;
        }

        if (_currentRatio >= _targetRatio) {
            // strategy is in optimal range (a bit undercollateralised)
            return false;
        }

        // the strategy needs to repay debt to exit the danger zone
        // only return true if the difference is greater than a threshold
        return _currentRatio.sub(_targetRatio) >= 1e16;
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

    // ********************** SUPPORT FUNCTIONS  **********************

    function burnSusd(uint256 _amount) internal returns (bool) {
        // returns false if unsuccessful
        if (_issuer().canBurnSynths(address(this))) {
            _synthetix().burnSynths(_amount);
            return true;
        } else {
            return false;
        }
    }

    function burnSusdToTarget() internal returns (uint256) {
        // we use this method to be able to avoid the waiting period
        // (see Synthetix Protocol)
        // it burns enough Synths to get back to 500% c-ratio
        // we need to have enough sUSD to burn to target
        uint256 _debtBalance = balanceOfDebt();
        uint256 _maxSynths = _synthetix().maxIssuableSynths(address(this)); // returns amount of synths at 500% c-ratio (with current collateral)
        if (_debtBalance <= _maxSynths) {
            // we are over the 500% c-ratio, we don't need to burn sUSD
            return 0;
        }
        uint256 _amountToBurn = _debtBalance.sub(_maxSynths);
        uint256 _balance = balanceOfSusd();
        if (_balance < _amountToBurn) {
            // if we do not have enough in balance, we withdraw funds from sUSD vault
            withdrawFromSUSDVault(_amountToBurn.sub(_balance));
        }

        _synthetix().burnSynthsToTarget();
        return _amountToBurn;
    }

    function withdrawFromSUSDVault(uint256 _amount) internal {
        // Don't leave less than MIN_ISSUE sUSD in the vault
        if (
            _amount > balanceOfSusdInVault() ||
            balanceOfSusdInVault().sub(_amount) <= MIN_ISSUE
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

    function buySusdWithWant(uint256 _amount) internal {
        if (_amount == 0) {
            return;
        }

        address[] memory path = new address[](3);
        path[0] = address(want);
        path[1] = address(WETH);
        path[2] = address(susd);

        // we use swapTokensForExactTokens because we need an exact sUSD amount
        sushi.swapTokensForExactTokens(
            _amount,
            type(uint256).max,
            path,
            address(this),
            now
        );
    }

    // ********************** CALCS **********************

    function estimatedProfit() public view returns (uint256) {
        uint256 availableFees; // in sUSD
        uint256 availableRewards; // in `want` (SNX)

        (availableFees, availableRewards) = _getFeesAvailable();

        return availableRewards.add(sUSDToWant(availableFees));
    }

    function getTargetDebt(uint256 _targetCollateral)
        internal
        returns (uint256)
    {
        uint256 _targetRatio = getTargetRatio();
        uint256 _collateralInSUSD = wantToSUSD(_targetCollateral);
        return _targetRatio.mul(_collateralInSUSD).div(1e18);
    }

    function sUSDToWant(uint256 _amount) internal view returns (uint256) {
        if (_amount == 0) {
            return 0;
        }

        return _amount.mul(1e18).div(_exchangeRates().rateForCurrency("SNX"));
    }

    function wantToSUSD(uint256 _amount) internal view returns (uint256) {
        if (_amount == 0) {
            return 0;
        }

        return _amount.mul(_exchangeRates().rateForCurrency("SNX")).div(1e18);
    }

    // ********************** BALANCES & RATIOS **********************
    // TODO: make these functions internal
    function _lockedCollateral() internal view returns (uint256) {
        // collateral includes `want` balance (both locked and unlocked) AND escrowed balance
        uint256 _collateral = _synthetix().collateral(address(this));
        return _collateral.sub(_unlockedWant());
    }

    // amount of `want` (SNX) that can be transferred, sold, ...
    function _unlockedWant() internal view returns (uint256) {
        return _synthetix().transferableSynthetix(address(this));
    }

    function _unlockableWant() internal view returns (uint256) {
        // collateral includes escrowed SNX, we may not be able to unlock the full
        // we can only unlock this by repaying debt
        return balanceOfWant().sub(_unlockedWant());
    }

    function _collateral() internal view returns (uint256) {
        return _synthetix().collateral(address(this));
    }

    function _getFeesAvailable() internal view returns (uint256, uint256) {
        // returns fees and rewards
        // fees in sUSD
        // rewards in `want` (SNX)

        return _feePool().feesAvailable(address(this));
    }

    function getCurrentRatio() public view returns (uint256) {
        // ratio = debt / collateral
        // i.e. ratio is 0 if debt is 0
        return _issuer().collateralisationRatio(address(this));
    }

    function getIssuanceRatio() public view returns (uint256) {
        return _issuer().issuanceRatio();
    }

    function getTargetRatio() public view returns (uint256) {
        return
            _issuer().issuanceRatio().mul(targetRatioMultiplier).div(MAX_BPS);
    }

    function balanceOfEscrowedWant() public view returns (uint256) {
        return _rewardEscrowV2().balanceOf(address(this));
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

    // ********************** ADDRESS RESOLVER SHORTCUTS **********************

    function _synthetix() internal view returns (ISynthetix) {
        return
            ISynthetix(
                IAddressResolver(resolver).getAddress(CONTRACT_SYNTHETIX)
            );
    }

    function _feePool() internal view returns (IFeePool) {
        return
            IFeePool(IAddressResolver(resolver).getAddress(CONTRACT_FEEPOOL));
    }

    function _issuer() internal view returns (IIssuer) {
        return IIssuer(IAddressResolver(resolver).getAddress(CONTRACT_ISSUER));
    }

    function _exchangeRates() internal view returns (IExchangeRates) {
        return
            IExchangeRates(
                IAddressResolver(resolver).getAddress(CONTRACT_EXRATES)
            );
    }

    function _rewardEscrowV2() internal view returns (IRewardEscrowV2) {
        return
            IRewardEscrowV2(
                IAddressResolver(resolver).getAddress(CONTRACT_REWARDESCROW_V2)
            );
    }
}
