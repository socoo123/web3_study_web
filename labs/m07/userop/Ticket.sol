// SPDX-License-Identifier: GPL-3.0
pragma solidity 0.8.28;

import {IPaymaster} from "interfaces/IPaymaster.sol";
import {PackedUserOperation} from "interfaces/PackedUserOperation.sol";

/// Local ticket desk; a held ticket fails at execution, not during gas sponsorship checks.
contract TicketDesk {
    address immutable account;
    bool immutable held;
    uint32 public recorded;
    error TicketHeld();

    constructor(address account_, bool held_) {
        account = account_;
        held = held_;
    }

    function record(uint32 ticket) external {
        require(msg.sender == account);
        if (held) revert TicketHeld();
        recorded = ticket;
    }
}

interface ISimpleExecute {
    function execute(address dest, uint256 value, bytes calldata func) external;
}

/// One voucher for (sender, full nonce 0, exact account call, maximum prefund).
contract TicketSponsor is IPaymaster {
    address immutable entryPoint;
    address immutable account;
    bytes32 immutable allowedCall;
    uint256 public constant CAP_WEI = 800_000_000_000_000;
    error OutsideVoucher();
    error NoPostOpContext();

    constructor(address ep, address account_, address desk) {
        entryPoint = ep;
        account = account_;
        bytes memory inner = abi.encodeCall(TicketDesk.record, (uint32(27)));
        allowedCall = keccak256(abi.encodeCall(ISimpleExecute.execute, (desk, 0, inner)));
    }

    function validatePaymasterUserOp(PackedUserOperation calldata op, bytes32, uint256 maxCost)
        external view override returns (bytes memory context, uint256 validationData)
    {
        require(msg.sender == entryPoint);
        if (op.sender != account || op.nonce != 0 || op.initCode.length != 0 ||
            op.paymasterAndData.length != 52 || keccak256(op.callData) != allowedCall || maxCost > CAP_WEI) {
            revert OutsideVoucher();
        }
        // No post-operation accounting: EntryPoint owns the deposit and refunds the unused prefund.
        return ("", 0);
    }

    function postOp(PostOpMode, bytes calldata, uint256, uint256) external pure override {
        revert NoPostOpContext();
    }
}
