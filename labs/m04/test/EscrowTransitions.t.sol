// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {MilestoneEscrow} from "../src/MilestoneEscrow.sol";

interface VmEscrowTransitions {
    function warp(uint256 timestamp) external;
    function deal(address who, uint256 newBalance) external;
    function prank(address sender) external;
    function expectRevert(bytes4 selector) external;
    function expectEmit(bool topic1, bool topic2, bool topic3, bool data, address emitter) external;
}

contract EscrowTransitionsTest {
    VmEscrowTransitions private constant vm =
        VmEscrowTransitions(address(uint160(uint256(keccak256("hevm cheat code")))));

    address private constant A = address(0xa140);
    address private constant B = address(0xb140);
    uint256 private constant T0 = 1_700_000_000;
    uint256 private constant D = T0 + 60;
    uint256 private constant AMOUNT = 12_500 wei;
    MilestoneEscrow private escrow;

    // Test instrumentation, not part of the escrow's public event stream.
    event Ledger(string step, uint8 state, uint256 heldWei, uint256 creditAWei, uint256 creditBWei);

    function setUp() public {
        vm.warp(T0);
        vm.deal(A, 2 * AMOUNT);
        vm.deal(B, AMOUNT);
        vm.prank(A);
        escrow = new MilestoneEscrow(B, D);
        assert(escrow.payer() == A && escrow.payee() == B && escrow.deadline() == D);
    }

    function _row(string memory step, MilestoneEscrow.State expected, uint256 held, uint256 a, uint256 b) private {
        MilestoneEscrow.State state = escrow.state();
        uint256 heldWei = address(escrow).balance;
        uint256 creditA = escrow.credit(A);
        uint256 creditB = escrow.credit(B);
        require(state == expected && heldWei == held && creditA == a && creditB == b, step);
        emit Ledger(step, uint8(state), heldWei, creditA, creditB);
    }

    function _lock() private {
        _row("awaiting", MilestoneEscrow.State.Awaiting, 0, 0, 0);
        vm.expectEmit(true, false, false, true, address(escrow));
        emit MilestoneEscrow.Locked(A, AMOUNT);
        vm.prank(A);
        escrow.lock{value: AMOUNT}();
        _row("locked", MilestoneEscrow.State.Locked, AMOUNT, 0, 0);
    }

    function _settle() private {
        vm.expectEmit(true, false, false, true, address(escrow));
        emit MilestoneEscrow.Settled(B, AMOUNT);
        vm.prank(A);
        escrow.settle();
        _row("settled", MilestoneEscrow.State.Settled, AMOUNT, 0, AMOUNT);
    }

    function _withdraw(address recipient, MilestoneEscrow.State terminal) private {
        uint256 beforeBalance = recipient.balance;
        vm.expectEmit(true, false, false, true, address(escrow));
        emit MilestoneEscrow.Withdrawn(recipient, AMOUNT);
        vm.prank(recipient);
        escrow.withdraw();
        assert(recipient.balance == beforeBalance + AMOUNT);
        _row("withdrawn", terminal, 0, 0, 0);
    }

    function testSettleAtDMinusOne() public {
        _lock();
        vm.warp(D - 1);
        vm.expectRevert(MilestoneEscrow.TooEarly.selector);
        vm.prank(A);
        escrow.refund();
        _row("early-refund-rejected", MilestoneEscrow.State.Locked, AMOUNT, 0, 0);
        _settle();
        _withdraw(B, MilestoneEscrow.State.Settled);
    }

    function testRefundAtD() public {
        _lock();
        vm.warp(D);
        _row("deadline-without-call", MilestoneEscrow.State.Locked, AMOUNT, 0, 0);
        vm.expectRevert(MilestoneEscrow.DeadlineReached.selector);
        vm.prank(A);
        escrow.settle();
        _row("late-settle-rejected", MilestoneEscrow.State.Locked, AMOUNT, 0, 0);
        vm.expectEmit(true, false, false, true, address(escrow));
        emit MilestoneEscrow.Refunded(A, AMOUNT);
        vm.prank(A);
        escrow.refund();
        _row("refunded", MilestoneEscrow.State.Refunded, AMOUNT, AMOUNT, 0);
        _withdraw(A, MilestoneEscrow.State.Refunded);
    }

    function testRejectBadLocks() public {
        vm.expectRevert(MilestoneEscrow.ZeroDeposit.selector);
        vm.prank(A);
        escrow.lock();
        _row("zero-deposit", MilestoneEscrow.State.Awaiting, 0, 0, 0);
        vm.expectRevert(MilestoneEscrow.PayerOnly.selector);
        vm.prank(B);
        escrow.lock{value: AMOUNT}();
        _row("wrong-locker", MilestoneEscrow.State.Awaiting, 0, 0, 0);
        vm.warp(D);
        vm.expectRevert(MilestoneEscrow.DeadlineReached.selector);
        vm.prank(A);
        escrow.lock{value: AMOUNT}();
        _row("late-lock", MilestoneEscrow.State.Awaiting, 0, 0, 0);
    }

    function testRejectWrongDecisionMaker() public {
        _lock();
        vm.warp(D - 1);
        vm.expectRevert(MilestoneEscrow.PayerOnly.selector);
        vm.prank(B);
        escrow.settle();
        _row("wrong-settler", MilestoneEscrow.State.Locked, AMOUNT, 0, 0);
        vm.warp(D);
        vm.expectRevert(MilestoneEscrow.PayerOnly.selector);
        vm.prank(B);
        escrow.refund();
        _row("wrong-refunder", MilestoneEscrow.State.Locked, AMOUNT, 0, 0);
    }

    function testRejectSecondSettlement() public {
        _lock();
        vm.warp(D - 1);
        _settle();
        vm.expectRevert(MilestoneEscrow.WrongState.selector);
        vm.prank(A);
        escrow.settle();
        _row("second-settle", MilestoneEscrow.State.Settled, AMOUNT, 0, AMOUNT);
        vm.expectRevert(MilestoneEscrow.NoCredit.selector);
        vm.prank(A);
        escrow.withdraw();
        _row("payer-cannot-claim", MilestoneEscrow.State.Settled, AMOUNT, 0, AMOUNT);
        _withdraw(B, MilestoneEscrow.State.Settled);
        vm.expectRevert(MilestoneEscrow.NoCredit.selector);
        vm.prank(B);
        escrow.withdraw();
        vm.expectRevert(MilestoneEscrow.WrongState.selector);
        vm.prank(A);
        escrow.lock{value: AMOUNT}();
        _row("still-terminal", MilestoneEscrow.State.Settled, 0, 0, 0);
    }

    function testRejectInvalidTerms() public {
        vm.expectRevert(MilestoneEscrow.InvalidPayee.selector);
        vm.prank(A);
        new MilestoneEscrow(address(0), D);
        vm.expectRevert(MilestoneEscrow.InvalidPayee.selector);
        vm.prank(A);
        new MilestoneEscrow(A, D);
        vm.expectRevert(MilestoneEscrow.DeadlineNotFuture.selector);
        vm.prank(A);
        new MilestoneEscrow(B, T0);
    }
}
