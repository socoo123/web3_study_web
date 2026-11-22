package course.m05;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.Locale;
import java.util.regex.Pattern;

/** Operator CLI, not a callback endpoint. A scenario's price and asset never change. */
public final class OrderIntent {
    static final Pattern ID = Pattern.compile("[A-Za-z0-9][A-Za-z0-9_-]{0,63}");
    record Release(long chainId, String contractAddress, long deployHeight, String deployHash, String payee) {
        static Release load() throws IOException {
            JsonNode m = Lab.manifest();
            if (!"m04-escrow-release/1".equals(m.path("format").asText()) || m.required("chainId").asLong() != 31337)
                throw new IOException("expected M04 release on chain 31337");
            return new Release(31337, lower(m.required("contractAddress")), m.required("deploymentBlockNumber").asLong(),
                lower(m.required("deploymentBlockHash")), lower(m.required("constructor").required("payee")));
        }
        private static String lower(JsonNode n) { return n.asText().toLowerCase(Locale.ROOT); }
    }
    record Terms(String id, Release release, String asset, String expectedUnits, int minDepth, boolean active) {}

    static Terms lock(Connection db, String id) throws SQLException {
        try (var q = db.prepareStatement("SELECT * FROM payment_intent WHERE id=? FOR UPDATE")) {
            q.setString(1, id);
            try (var r = q.executeQuery()) {
                if (!r.next()) return null;
                var rel = new Release(r.getLong("chain_id"), r.getString("contract_address"), r.getLong("deploy_height"),
                    r.getString("deploy_hash"), r.getString("payee"));
                return new Terms(id, rel, r.getString("asset"), r.getBigDecimal("expected_units").toPlainString(),
                    r.getInt("min_depth"), r.getBoolean("active"));
            }
        }
    }

    private static void create(Connection db, String[] args, Release rel) throws SQLException {
        String asset = args[2];
        if (!asset.equals("native:31337") && !asset.equals("invoice:USD"))
            throw new IllegalArgumentException("use native:31337 (wei) or invoice:USD (cents)");
        BigInteger units = new BigInteger(args[3]);
        int depth = Integer.parseInt(args[4]);
        if (units.signum() <= 0 || units.bitLength() > 256 || depth < 1) throw new IllegalArgumentException("invalid units or depth");
        try (var q = db.prepareStatement("""
            INSERT INTO payment_intent(id,chain_id,contract_address,deploy_height,deploy_hash,payee,asset,expected_units,min_depth)
            SELECT ?,chain_id,contract_address,deploy_height,deploy_hash,?,?,?,? FROM scan_cursor
            WHERE id=1 AND chain_id=? AND contract_address=? AND deploy_height=? AND deploy_hash=?
            """)) {
            q.setString(1, args[1]); q.setString(2, rel.payee()); q.setString(3, asset);
            q.setBigDecimal(4, new BigDecimal(units)); q.setInt(5, depth); q.setLong(6, rel.chainId());
            q.setString(7, rel.contractAddress()); q.setLong(8, rel.deployHeight()); q.setString(9, rel.deployHash());
            if (q.executeUpdate() != 1) throw new SQLException("scan the trusted deployment into this database first");
        }
    }

    public static void main(String[] args) throws Exception {
        boolean creating = args.length == 5 && args[0].equals("create");
        if (!(creating || (args.length == 2 && args[0].equals("retire"))) || !ID.matcher(args[1]).matches())
            throw new IllegalArgumentException("OrderIntent create ID ASSET EXPECTED_UNITS MIN_DEPTH | retire ID");
        Release rel = Release.load();
        try (Connection db = Lab.db()) {
            db.setAutoCommit(false);
            if (creating) create(db, args, rel);
            else {
                Terms order = lock(db, args[1]); // Serialize retirement against accounting callbacks.
                if (order == null || !order.active() || !order.release().equals(rel)) throw new SQLException("not an active order of this release");
                try (var q = db.prepareStatement("""
                    UPDATE payment_intent SET active=false WHERE id=? AND NOT EXISTS (SELECT FROM order_booking WHERE order_id=?)
                    """)) {
                    q.setString(1, args[1]); q.setString(2, args[1]);
                    if (q.executeUpdate() != 1) throw new SQLException("a booked order cannot be retired or reassigned");
                }
            }
            db.commit();
            System.out.println(args[0] + " " + args[1]);
        }
    }
}
