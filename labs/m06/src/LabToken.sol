// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// Fixed supply, exact transfers, finite allowances. For the local course chain only.
contract LabToken {
    string public symbol;
    uint8 public immutable decimals;
    uint256 public immutable totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    error InsufficientAllowance();
    error InsufficientBalance();
    error ZeroRecipient();

    constructor(string memory symbol_, uint8 decimals_, uint256 supply_) {
        symbol = symbol_;
        decimals = decimals_;
        totalSupply = supply_;
        balanceOf[msg.sender] = supply_;
        emit Transfer(address(0), msg.sender, supply_);
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transfer(address to, uint256 value) external returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 available = allowance[from][msg.sender];
        if (value > available) revert InsufficientAllowance();
        unchecked { allowance[from][msg.sender] = available - value; }
        _transfer(from, to, value);
        return true;
    }

    function _transfer(address from, address to, uint256 value) private {
        if (to == address(0)) revert ZeroRecipient();
        uint256 balance = balanceOf[from];
        if (value > balance) revert InsufficientBalance();
        // Debit first, including for self-transfers. The fixed supply bounds the credit.
        unchecked {
            balanceOf[from] = balance - value;
            balanceOf[to] += value;
        }
        emit Transfer(from, to, value);
    }
}
