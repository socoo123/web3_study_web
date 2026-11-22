// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// Single-order teaching contract. Only the payer decides acceptance before the deadline.
contract MilestoneEscrow {
    enum State { Awaiting, Locked, Settled, Refunded }

    address public immutable payer;
    address public immutable payee;
    uint256 public immutable deadline;
    State public state;
    uint256 private deposit; // Original value of this order, not the current contract balance.
    mapping(address => uint256) public credit;

    event Locked(address indexed payer, uint256 amount);
    event Settled(address indexed payee, uint256 amount);
    event Refunded(address indexed payer, uint256 amount);
    event Withdrawn(address indexed recipient, uint256 amount);

    error InvalidPayee();
    error DeadlineNotFuture();
    error PayerOnly();
    error WrongState();
    error DeadlineReached();
    error TooEarly();
    error ZeroDeposit();
    error NoCredit();
    error WithdrawalFailed();

    constructor(address payee_, uint256 deadline_) {
        if (payee_ == address(0) || payee_ == msg.sender) revert InvalidPayee();
        if (deadline_ <= block.timestamp) revert DeadlineNotFuture();
        payer = msg.sender;
        payee = payee_;
        deadline = deadline_;
    }

    modifier onlyPayer() {
        if (msg.sender != payer) revert PayerOnly();
        _;
    }

    function lock() external payable onlyPayer {
        if (state != State.Awaiting) revert WrongState();
        if (block.timestamp >= deadline) revert DeadlineReached();
        if (msg.value == 0) revert ZeroDeposit();
        deposit = msg.value;
        state = State.Locked;
        emit Locked(payer, msg.value);
    }

    function settle() external onlyPayer {
        if (state != State.Locked) revert WrongState();
        if (block.timestamp >= deadline) revert DeadlineReached();
        state = State.Settled;
        uint256 amount = deposit;
        credit[payee] = amount;
        emit Settled(payee, amount);
    }

    function refund() external onlyPayer {
        if (state != State.Locked) revert WrongState();
        if (block.timestamp < deadline) revert TooEarly();
        state = State.Refunded;
        uint256 amount = deposit;
        credit[payer] = amount;
        emit Refunded(payer, amount);
    }

    function withdraw() external {
        uint256 amount = credit[msg.sender];
        if (amount == 0) revert NoCredit();
        credit[msg.sender] = 0;
        (bool sent,) = payable(msg.sender).call{value: amount}("");
        if (!sent) revert WithdrawalFailed();
        emit Withdrawn(msg.sender, amount);
    }
}
