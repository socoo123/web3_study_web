package course.m05;

import com.fasterxml.jackson.databind.JsonNode;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.Locale;
import org.web3j.protocol.Web3j;
import org.web3j.protocol.core.methods.response.EthBlock;

/** Repair the SQL view of one deployment, never the chain or the raw log. */
public final class Recover {
    private record Header(long height, String hash, String parent) {}
    private record Cursor(long chain, String address, long deploy, String deployHash, long height, String hash) {}

    private static void require(boolean ok, String message) {
        if (!ok) throw new IllegalStateException(message);
    }

    private static Header header(Web3j w, long height) throws Exception {
        EthBlock.Block b = Lab.block(w, height);
        require(b != null && b.getNumber().longValueExact() == height, "missing canonical header at " + height);
        return new Header(height, b.getHash().toLowerCase(Locale.ROOT), b.getParentHash().toLowerCase(Locale.ROOT));
    }

    private static Cursor lockCursor(Connection c) throws Exception {
        try (var st = c.createStatement(); var rs = st.executeQuery("""
                SELECT chain_id, contract_address, deploy_height, deploy_hash, height, block_hash
                FROM scan_cursor WHERE id=1 FOR UPDATE
                """)) {
            return rs.next() ? new Cursor(rs.getLong(1), rs.getString(2), rs.getLong(3), rs.getString(4),
                                          rs.getLong(5), rs.getString(6)) : null;
        }
    }

    private static Header stored(PreparedStatement query, long h) throws Exception {
        query.setLong(2, h);
        try (ResultSet r = query.executeQuery()) {
            require(r.next(), "gap in stored canonical chain at " + h);
            return new Header(h, r.getString(1), r.getString(2));
        }
    }

    private static String repair(Connection c, Web3j w, boolean interrupt) throws Exception {
        Cursor old = lockCursor(c);
        JsonNode m = Lab.manifest();
        long chain = m.required("chainId").longValue(), deploy = m.required("deploymentBlockNumber").longValue();
        String address = m.required("contractAddress").asText().toLowerCase(Locale.ROOT);
        String deployHash = m.required("deploymentBlockHash").asText().toLowerCase(Locale.ROOT);
        var id = w.ethChainId().send();
        require(!id.hasError() && chain == 31337 && id.getChainId().longValueExact() == chain, "chain ID mismatch");
        require(header(w, deploy).hash.equals(deployHash), "deployment block mismatch; refusing rewind");
        if (old != null) {
            require(old.chain == chain && old.address.equals(address) && old.deploy == deploy
                    && old.deployHash.equals(deployHash) && old.height >= deploy, "cursor deployment mismatch");
        }
        try (var st = c.createStatement()) {
            st.execute("""
                    CREATE TABLE IF NOT EXISTS reorg_audit (
                      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, repaired_at timestamptz NOT NULL DEFAULT now(),
                      chain_id bigint NOT NULL, contract_address text NOT NULL,
                      old_height bigint NOT NULL, old_hash text NOT NULL, observed_height bigint NOT NULL,
                      observed_hash text NOT NULL, ancestor_height bigint NOT NULL, ancestor_hash text NOT NULL,
                      orphan_blocks bigint NOT NULL CHECK (orphan_blocks = old_height - ancestor_height AND orphan_blocks > 0))
                    """);
        }
        if (old == null) return "EMPTY: Scan will initialize the deployment anchor";
        try (var query = c.prepareStatement("SELECT hash,parent_hash FROM chain_block WHERE chain_id=? AND height=? AND canonical")) {
            query.setLong(1, chain);
            require(stored(query, deploy).hash.equals(deployHash), "stored deployment block mismatch");
            var head = w.ethBlockNumber().send();
            require(!head.hasError(), "cannot read chain height");
            long at = Math.min(old.height, head.getBlockNumber().longValueExact());
            require(at >= deploy, "node is behind the deployment anchor");
            Header observed = header(w, at), current = observed;
            String oldHash = old.hash;
            for (long h = old.height; h >= deploy; h--) {
                Header db = stored(query, h);
                require(db.hash.equals(oldHash), "broken stored parent link at " + h);
                oldHash = db.parent;
                if (h > at) continue;  // This RPC endpoint has no block yet at that height.
                if (h < at) {
                    Header previous = header(w, h);
                    require(previous.hash.equals(current.parent), "RPC branch changed during walk; retry recovery");
                    current = previous;
                }
                if (!db.hash.equals(current.hash)) continue;
                if (h == old.height) return "UNCHANGED height=" + h;
                require(h != at, "shorter matching prefix; wait for the node, no contradictory block observed");
                try (var mark = c.prepareStatement("UPDATE chain_block SET canonical=false WHERE chain_id=? AND height>? AND canonical");
                     var audit = c.prepareStatement("""
                         INSERT INTO reorg_audit(chain_id,contract_address,old_height,old_hash,observed_height,
                             observed_hash,ancestor_height,ancestor_hash,orphan_blocks) VALUES (?,?,?,?,?,?,?,?,?)
                         """);
                     var rewind = c.prepareStatement("UPDATE scan_cursor SET height=?,block_hash=? WHERE id=1")) {
                    mark.setLong(1, chain); mark.setLong(2, h);
                    long dropped = mark.executeLargeUpdate();
                    require(dropped == old.height - h, "canonical row count disagrees with old path");
                    audit.setLong(1, chain); audit.setString(2, address);
                    audit.setLong(3, old.height); audit.setString(4, old.hash);
                    audit.setLong(5, at); audit.setString(6, observed.hash);
                    audit.setLong(7, h); audit.setString(8, db.hash); audit.setLong(9, dropped);
                    audit.executeUpdate();
                    rewind.setLong(1, h); rewind.setString(2, db.hash);
                    require(rewind.executeUpdate() == 1, "missing locked cursor");
                    require(header(w, at).hash.equals(observed.hash), "RPC branch changed before commit; retry recovery");
                    if (interrupt) throw new IllegalStateException("LAB_INTERRUPT_BEFORE_COMMIT");
                    return "REWIND old=" + old.height + " ancestor=" + h + " observed=" + at + " orphanBlocks=" + dropped;
                }
            }
            throw new IllegalStateException("no common deployment ancestor; quarantine this deployment");
        }
    }

    public static void main(String[] args) throws Exception {
        String mode = args.length == 0 ? "" : args[0];
        if (args.length > 1 || !(mode.isEmpty() || mode.equals("--interrupt-before-commit") || mode.equals("--rewind-only")))
            throw new IllegalArgumentException("Recover [--interrupt-before-commit|--rewind-only]");
        Web3j w = Lab.web3();
        try (Connection c = Lab.db()) {
            c.setAutoCommit(false);
            try {
                String result = repair(c, w, mode.equals("--interrupt-before-commit"));
                c.commit();
                System.out.println(result);
            } catch (Exception e) {
                c.rollback();
                throw e;
            }
        } finally {
            w.shutdown();
        }
        if (mode.isEmpty()) Scan.main(new String[0]);
    }
}
