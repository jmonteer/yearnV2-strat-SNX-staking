// SPDX-License-Identifier: MIT
pragma solidity 0.6.12;

interface ISynthetix {
    // Views
    function collateral(address account) external view returns (uint256);

    function collateralisationRatio(address issuer)
        external
        view
        returns (uint256);

    function debtBalanceOf(address issuer, bytes32 currencyKey)
        external
        view
        returns (uint256);

    function isWaitingPeriod(bytes32 currencyKey) external view returns (bool);

    function maxIssuableSynths(address issuer)
        external
        view
        returns (uint256 maxIssuable);

    function remainingIssuableSynths(address issuer)
        external
        view
        returns (
            uint256 maxIssuable,
            uint256 alreadyIssued,
            uint256 totalSystemDebt
        );

    // Mutative Functions
    function burnSynths(uint256 amount) external;

    function burnSynthsOnBehalf(address burnForAddress, uint256 amount)
        external;

    function burnSynthsToTarget() external;

    function burnSynthsToTargetOnBehalf(address burnForAddress) external;

    function exchange(
        bytes32 sourceCurrencyKey,
        uint256 sourceAmount,
        bytes32 destinationCurrencyKey
    ) external returns (uint256 amountReceived);

    function exchangeOnBehalf(
        address exchangeForAddress,
        bytes32 sourceCurrencyKey,
        uint256 sourceAmount,
        bytes32 destinationCurrencyKey
    ) external returns (uint256 amountReceived);

    function issueMaxSynths() external;

    function issueMaxSynthsOnBehalf(address issueForAddress) external;

    function issueSynths(uint256 amount) external;

    function issueSynthsOnBehalf(address issueForAddress, uint256 amount)
        external;

    function mint() external returns (bool);

    function settle(bytes32 currencyKey)
        external
        returns (
            uint256 reclaimed,
            uint256 refunded,
            uint256 numEntries
        );
}
