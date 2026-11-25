import { Address, BigInt, ethereum } from '@graphprotocol/graph-ts'
import { Locked, Settled, Refunded, Withdrawn } from './generated/Escrow/Escrow'
import { Posting } from './generated/schema'

function post(event: ethereum.Event, kind: string, actor: Address, amount: BigInt): void {
  // A block hash plus the block-wide log index locates one occurrence (one chain per deployment).
  let row = new Posting(event.block.hash.concatI32(event.logIndex.toI32()))
  row.height = event.block.number
  row.blockHash = event.block.hash
  row.txHash = event.transaction.hash
  row.logIndex = event.logIndex
  row.address = event.address
  row.kind = kind
  row.actor = actor
  row.amountWei = amount
  row.save()
}

export function handleLocked(event: Locked): void {
  post(event, 'Locked', event.params.payer, event.params.amount)
}
export function handleSettled(event: Settled): void {
  post(event, 'Settled', event.params.payee, event.params.amount)
}
export function handleRefunded(event: Refunded): void {
  post(event, 'Refunded', event.params.payer, event.params.amount)
}
export function handleWithdrawn(event: Withdrawn): void {
  post(event, 'Withdrawn', event.params.recipient, event.params.amount)
}
