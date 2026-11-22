// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {MilestoneEscrow} from "../src/MilestoneEscrow.sol";

interface EscrowPropertyVm {
    function deal(address who, uint256 balance) external;
    function prank(address caller) external;
    function warp(uint256 timestamp) external;
    function getBlockTimestamp() external view returns (uint256);
}

EscrowPropertyVm constant PROPERTY_VM =
    EscrowPropertyVm(address(uint160(uint256(keccak256("hevm cheat code")))));

// A test driver and observation journal. Neither is deployed in the release.
contract EscrowLedgerHandler {
    address public constant PAYER = address(0x15001);
    address public constant PAYEE = address(0x15002);
    MilestoneEscrow public order;

    uint256 public totalIn;
    uint256 public totalPaid;
    uint256 private principal;
    address private recipient;
    bool private collected;
    bool public retryChecked;

    constructor() {
        PROPERTY_VM.deal(PAYER, 1 ether);
        _newOrder();
    }

    function _newOrder() private {
        uint256 cutoff = PROPERTY_VM.getBlockTimestamp() + 10;
        PROPERTY_VM.prank(PAYER);
        order = new MilestoneEscrow(PAYEE, cutoff);
        principal = 0;
        recipient = address(0);
        collected = false;
        retryChecked = false;
    }

    function lock(uint96 raw) external {
        if (retryChecked) {
            assertLedger(); // No money or claim may be left in the retired order.
            _newOrder();
        }
        if (principal != 0) return;
        uint256 amount = 1 + uint256(raw) % 1_000_000;
        uint256 beforePayer = PAYER.balance;
        PROPERTY_VM.prank(PAYER);
        order.lock{value: amount}();
        principal = beforePayer - PAYER.balance;
        require(principal == amount, "lock debit");
        totalIn += principal;
    }

    function resolve(bool atCutoff) external {
        if (principal == 0 || recipient != address(0)) return;
        uint256 cutoff = order.deadline();
        PROPERTY_VM.warp(atCutoff ? cutoff : cutoff - 1);
        PROPERTY_VM.prank(PAYER);
        if (atCutoff) {
            order.refund();
            recipient = PAYER;
        } else {
            order.settle();
            recipient = PAYEE;
        }
    }

    function collect() external {
        if (recipient == address(0)) return;
        uint256 beforeRecipient = recipient.balance;
        if (!collected) {
            PROPERTY_VM.prank(recipient);
            order.withdraw();
            uint256 gained = recipient.balance - beforeRecipient;
            require(gained == principal, "withdraw net gain");
            totalPaid += gained;
            collected = true;
        } else {
            // Catch only the expected rejection of an already-paid claim.
            PROPERTY_VM.prank(recipient);
            (bool ok,) = address(order).call(abi.encodeCall(MilestoneEscrow.withdraw, ()));
            require(!ok && recipient.balance == beforeRecipient, "second withdrawal");
            retryChecked = true;
        }
    }

    function assertLedger() public view {
        require(totalPaid <= totalIn, "overspent");
        require(address(order).balance == totalIn - totalPaid, "cash reconciliation");
        uint256 due = collected ? 0 : principal;
        require(order.credit(PAYER) == (recipient == PAYER ? due : 0), "payer claim");
        require(order.credit(PAYEE) == (recipient == PAYEE ? due : 0), "payee claim");
        MilestoneEscrow.State expected;
        if (recipient == PAYEE) expected = MilestoneEscrow.State.Settled;
        else if (recipient == PAYER) expected = MilestoneEscrow.State.Refunded;
        else if (principal != 0) expected = MilestoneEscrow.State.Locked;
        else expected = MilestoneEscrow.State.Awaiting;
        require(order.state() == expected, "order state");
    }
}

contract EscrowPropertiesTest {
    EscrowLedgerHandler private book;

    event Page(string step, uint256 inWei, uint256 paidWei, uint256 heldWei,
               uint256 payerCreditWei, uint256 payeeCreditWei);

    function setUp() public {
        PROPERTY_VM.warp(100);
        book = new EscrowLedgerHandler();
    }

    // Forge reads these two discovery functions; no forge-std dependency.
    struct SelectorSet { address addr; bytes4[] selectors; }

    function targetContracts() external view returns (address[] memory list) {
        list = new address[](1);
        list[0] = address(book);
    }

    function targetSelectors() external view returns (SelectorSet[] memory sets) {
        bytes4[] memory actions = new bytes4[](3);
        actions[0] = EscrowLedgerHandler.lock.selector;
        actions[1] = EscrowLedgerHandler.resolve.selector;
        actions[2] = EscrowLedgerHandler.collect.selector;
        sets = new SelectorSet[](1);
        sets[0] = SelectorSet(address(book), actions);
    }

    function invariant_cashAndClaimsAgree() public view {
        book.assertLedger();
    }

    function _page(string memory step) private {
        book.assertLedger();
        MilestoneEscrow e = book.order();
        emit Page(step, book.totalIn(), book.totalPaid(), address(e).balance,
                  e.credit(book.PAYER()), e.credit(book.PAYEE()));
    }

    function _runOrder(uint96 raw, bool atCutoff) private {
        book.lock(raw);
        _page("lock");
        MilestoneEscrow e = book.order();
        uint256 cutoff = e.deadline();
        book.resolve(atCutoff);
        _page("resolve");
        uint256 decidedAt = PROPERTY_VM.getBlockTimestamp();
        bool vendorDue = decidedAt < cutoff;
        uint256 amount = 1 + uint256(raw) % 1_000_000;
        require(e.credit(book.PAYEE()) == (vendorDue ? amount : 0), "posting at cutoff");
        book.collect();
        _page("withdraw");
        book.collect();
        require(book.retryChecked(), "missing retry");
        _page("retry");
    }

    function test_LastSecondSettles() public { _runOrder(40, false); }
    function test_CutoffRefunds() public { _runOrder(40, true); }
    function testFuzz_Posting(uint96 raw, bool atCutoff) public { _runOrder(raw, atCutoff); }

    function test_TwoOrdersOneJournal() public {
        _runOrder(40, false);
        MilestoneEscrow first = book.order();
        _runOrder(58, true);
        require(book.order() != first && first.state() == MilestoneEscrow.State.Settled, "old order");
        require(book.totalIn() == 100 && book.totalPaid() == 100, "two-order journal");
    }

    function test_PayeeCannotSettle() public {
        book.lock(40);
        MilestoneEscrow e = book.order();
        address payee = book.PAYEE();
        PROPERTY_VM.prank(payee);
        (bool ok,) = address(e).call(abi.encodeCall(MilestoneEscrow.settle, ()));
        require(!ok, "settled by payee");
        _page("role-rejected");
    }
}
