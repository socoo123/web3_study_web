module workshop::ticket;

/// A serial number labels the work order; Sui's UID identifies this particular object.
public struct Ticket has key {
    id: UID,
    number: u64,
}

public entry fun open(number: u64, ctx: &mut TxContext) {
    let ticket = Ticket { id: object::new(ctx), number };
    transfer::transfer(ticket, ctx.sender());
}

public entry fun handoff(ticket: Ticket, recipient: address) {
    transfer::transfer(ticket, recipient);
}
