// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

// A single public exercise register. No funds, accounts or payment authorization.
contract AmountRegister {
    uint256 private amountWei;

    function set(uint256 nextWei) external returns (uint256) {
        amountWei = nextWei;
        return nextWei;
    }

    function get() external view returns (uint256) {
        return amountWei;
    }
}
