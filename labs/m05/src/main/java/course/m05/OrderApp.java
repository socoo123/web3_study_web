package course.m05;

import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.math.BigInteger;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.web3j.protocol.Web3j;
import org.web3j.protocol.core.DefaultBlockParameterName;

/** GET never books; the callback only asks us to reconcile our own records. */
@SpringBootConfiguration(proxyBeanMethods = false)
@EnableAutoConfiguration(exclude = DataSourceAutoConfiguration.class)
@RestController
public class OrderApp {
    private static final Logger LOG = LoggerFactory.getLogger(OrderApp.class);
    private final OrderIntent.Release release;
    private final Web3j node = Lab.web3();
    public OrderApp() throws IOException { release = OrderIntent.Release.load(); }
    @PreDestroy public void close() { node.shutdown(); }

    public static void main(String[] args) {
        SpringApplication.run(OrderApp.class, "--server.address=127.0.0.1", "--server.port=18020");
    }

    record Evidence(long chainId, long height, String blockHash, String txHash, long logIndex,
                    String address, String kind, String actor, String amountWei) {
        static Evidence read(ResultSet r) throws SQLException {
            return new Evidence(r.getLong("chain_id"), r.getLong("height"), r.getString("block_hash"),
                r.getString("tx_hash"), r.getLong("log_index"), r.getString("address"), r.getString("kind"),
                r.getString("actor"), r.getBigDecimal("amount_wei").toPlainString());
        }
    }

    private static Evidence booked(Connection db, String id) throws SQLException {
        // Historical evidence, intentionally NOT filtered by canonical. Never delete an old booking to force a match.
        try (var q = db.prepareStatement("""
            SELECT l.*, b.height FROM order_booking p JOIN escrow_log l USING(chain_id,block_hash,tx_hash,log_index)
            JOIN chain_block b ON (b.chain_id,b.hash)=(l.chain_id,l.block_hash) WHERE p.order_id=?
            """)) {
            q.setString(1, id);
            try (var r = q.executeQuery()) { return r.next() ? Evidence.read(r) : null; }
        }
    }

    private static void book(Connection db, String id, Evidence e) throws SQLException {
        try (var q = db.prepareStatement("INSERT INTO order_booking(order_id,chain_id,block_hash,tx_hash,log_index) VALUES(?,?,?,?,?)")) {
            q.setString(1, id); q.setLong(2, e.chainId()); q.setString(3, e.blockHash());
            q.setString(4, e.txHash()); q.setLong(5, e.logIndex()); q.executeUpdate();
        }
        try (var q = db.prepareStatement("INSERT INTO order_outbox(order_id,kind) VALUES(?,'ENTITLEMENT_RECORDED')")) {
            q.setString(1, id); q.executeUpdate();
        }
    }

    private String evaluate(Connection db, OrderIntent.Terms t, Evidence previous, boolean write,
                            Map<String,Object> report) throws IOException, SQLException {
        if (!release.equals(t.release())) return "HOLD_RELEASE";
        if (!t.active()) return "RETIRED";
        long cursor;
        String hash;
        // Scan/Recover lock this same singleton when they change the journal and cursor.
        try (var q = db.prepareStatement("SELECT * FROM scan_cursor WHERE id=1 FOR SHARE"); var r = q.executeQuery()) {
            if (!r.next()) return "HOLD_NO_CURSOR";
            if (r.getLong("chain_id") != release.chainId() || !r.getString("contract_address").equals(release.contractAddress())
                || r.getLong("deploy_height") != release.deployHeight() || !r.getString("deploy_hash").equals(release.deployHash()))
                return "HOLD_RELEASE";
            cursor = r.getLong("height"); hash = r.getString("block_hash");
            report.put("cursorHeight", cursor); report.put("cursorHash", hash);
        }
        var chain = node.ethChainId().send();
        if (chain.hasError() || chain.getResult() == null) throw new IOException("eth_chainId unavailable");
        if (!chain.getChainId().equals(BigInteger.valueOf(release.chainId()))) return "HOLD_RELEASE";
        var latest = node.ethGetBlockByNumber(DefaultBlockParameterName.LATEST, false).send();
        if (latest.hasError() || latest.getBlock() == null) throw new IOException("latest block unavailable");
        var tip = latest.getBlock(); long head = tip.getNumber().longValueExact();
        report.put("headHeight", head); report.put("headHash", tip.getHash()); report.put("lagBlocks", head - cursor);
        if (head < cursor) return "HOLD_REORG";
        var atCursor = head == cursor ? tip : Lab.block(node, cursor);
        if (atCursor == null || !hash.equals(atCursor.getHash())) return "HOLD_REORG";
        if (cursor != head) return "HOLD_LAG";

        Evidence event;
        try (var q = db.prepareStatement("SELECT * FROM canonical_log WHERE chain_id=? AND address=? AND kind='Settled' LIMIT 2")) {
            q.setLong(1, release.chainId()); q.setString(2, release.contractAddress());
            try (var r = q.executeQuery()) {
                event = r.next() ? Evidence.read(r) : null;
                if (event != null && r.next()) return "HOLD_AMBIGUOUS"; // Not a single-order escrow history.
            }
        }
        report.put("observed", event);
        if (previous != null && !previous.equals(event)) return "HOLD_ORPHAN";
        if (event == null) return "WAIT_SETTLED";
        if (!event.actor().equals(release.payee())) return "HOLD_PAYEE";
        long depth = head - event.height() + 1;
        report.put("confirmations", depth);
        if (!t.asset().equals("native:31337")) return "HOLD_ASSET"; // Never compare cents to wei.
        BigInteger delta = new BigInteger(t.expectedUnits()).subtract(new BigInteger(event.amountWei()));
        report.put("differenceWei", delta.toString());
        if (delta.signum() != 0) return "HOLD_AMOUNT";
        if (depth < t.minDepth()) return "HOLD_DEPTH";
        if (previous != null) return "BOOKED_AT_HEAD";
        if (!write) return "READY_TO_BOOK";
        book(db, t.id(), event); report.put("bookingEvidence", event);
        return "BOOKED_AT_HEAD";
    }

    private Map<String,Object> reconcile(String id, String key) throws IOException, SQLException {
        if (!OrderIntent.ID.matcher(id).matches() || (key != null && !OrderIntent.ID.matcher(key).matches()))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "invalid order id or callback key");
        try (Connection db = Lab.db()) {
            db.setAutoCommit(false);
            var t = OrderIntent.lock(db, id);
            if (t == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
            var report = new LinkedHashMap<String,Object>(); report.put("intent", t);
            if (key != null) {
                try (var q = db.prepareStatement("INSERT INTO callback_hint(order_id,hint_key) VALUES(?,?) ON CONFLICT DO NOTHING")) {
                    q.setString(1, id); q.setString(2, key);
                    report.put("newHint", q.executeUpdate() == 1);
                }
            }
            Evidence previous = booked(db, id); report.put("bookingEvidence", previous);
            String decision = evaluate(db, t, previous, key != null, report);
            report.put("decision", decision); report.put("mayNotifyAsOfHead", decision.equals("BOOKED_AT_HEAD"));
            db.commit(); // Hint + booking + outbox all succeed or none do; no network push in this transaction.
            return report;
        }
    }

    @GetMapping("/orders/{id}")
    public Map<String,Object> get(@PathVariable("id") String id) throws IOException, SQLException { return reconcile(id, null); }

    @PostMapping(value="/orders/{id}/callbacks/{key}", consumes="application/json")
    public Map<String,Object> callback(@PathVariable("id") String id, @PathVariable("key") String key) throws IOException, SQLException {
        return reconcile(id, key); // No @RequestBody: client-supplied amount, asset, address and hash are not ledger inputs.
    }

    @ExceptionHandler({IOException.class, SQLException.class})
    @ResponseStatus(HttpStatus.SERVICE_UNAVAILABLE)
    public Map<String,Object> unavailable(Exception e) {
        LOG.warn("Local reconciliation dependency failed", e);
        return Map.of("decision", "HOLD_UNAVAILABLE", "mayNotifyAsOfHead", false);
    }
}
