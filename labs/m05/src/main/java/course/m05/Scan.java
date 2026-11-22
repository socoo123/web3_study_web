package course.m05;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;
import org.web3j.crypto.Hash;
import org.web3j.protocol.Web3j;
import org.web3j.protocol.core.DefaultBlockParameter;
import org.web3j.protocol.core.Response;
import org.web3j.protocol.core.methods.request.EthFilter;
import org.web3j.protocol.core.methods.response.EthBlock;
import org.web3j.protocol.core.methods.response.EthLog;
import org.web3j.protocol.core.methods.response.Log;

/** One bounded catch-up pass. No subscriptions, signing keys or business-side effects. */
public final class Scan {
    private static final int WINDOW = 3;
    private static final long CHAIN = 31337;
    private static final Pattern ADDRESS = Pattern.compile("0x[0-9a-fA-F]{40}");
    private static final Pattern WORD = Pattern.compile("0x[0-9a-fA-F]{64}");
    private static final Map<String, String> KINDS = Map.of(
            topic("Locked"), "Locked", topic("Settled"), "Settled",
            topic("Refunded"), "Refunded", topic("Withdrawn"), "Withdrawn");
    private static final String[] TOPICS = KINDS.keySet().toArray(String[]::new);

    private record Header(long height, String hash, String parent, boolean hasTransactions) {}
    private record Release(String address, Header deploy) {}
    private record Cursor(long height, String hash) {}
    private record Counts(int matched, int inserted) {}

    private static String topic(String name) { return Hash.sha3String(name + "(address,uint256)"); }

    private static void require(boolean ok, String why) {
        if (!ok) throw new IllegalStateException("STOP " + why);
    }

    private static void sameBranch(boolean ok, long height) {
        if (!ok) throw new IllegalStateException("STOP branch mismatch at height " + height + "; see lesson 19 / Recover");
    }

    private static String hex(String value, Pattern shape) {
        require(value != null && shape.matcher(value).matches(), "invalid hex field");
        return value.toLowerCase(Locale.ROOT);
    }

    private static <T extends Response<?>> T checked(T response, String method) throws IOException {
        if (response.hasError()) throw new IOException(method + ": " + response.getError().getMessage());
        if (response.getResult() == null) throw new IOException(method + ": missing result");
        return response;
    }

    private static Header header(EthBlock.Block block, long height) {
        sameBranch(block != null && block.getNumber().longValueExact() == height, height);
        return new Header(height, hex(block.getHash(), WORD), hex(block.getParentHash(), WORD),
                !block.getTransactions().isEmpty());
    }

    private static void checkCanonical(Web3j web, long height, String hash) throws IOException {
        var current = Lab.block(web, height);
        sameBranch(current != null && current.getNumber().longValueExact() == height
                && hash.equalsIgnoreCase(current.getHash()), height);
    }

    private static Release verifyRelease(Web3j web) throws IOException {
        JsonNode m = Lab.manifest();
        require("m04-escrow-release/1".equals(m.path("format").asText()), "not an M04 release");
        require(m.path("chainId").isIntegralNumber() && m.path("chainId").bigIntegerValue().equals(BigInteger.valueOf(CHAIN))
                && checked(web.ethChainId().send(), "eth_chainId").getChainId().equals(BigInteger.valueOf(CHAIN)), "chain ID mismatch");
        long n = m.required("deploymentBlockNumber").bigIntegerValue().longValueExact();
        require(n > 0 && m.get("deploymentBlockNumber").isIntegralNumber(), "invalid deployment height");
        var address = hex(m.required("contractAddress").asText(), ADDRESS);
        var tx = hex(m.required("deploymentTransactionHash").asText(), WORD);
        var b = Lab.block(web, n);
        require(b != null && b.getNumber().longValueExact() == n
                && hex(m.required("deploymentBlockHash").asText(), WORD).equalsIgnoreCase(b.getHash()), "deployment block mismatch");
        // Only this release's isolated, event-free creation block may be skipped as the first anchor.
        require(b.getTransactions().size() == 1 && tx.equalsIgnoreCase((String) b.getTransactions().getFirst().get()),
                "deployment must be the only transaction in the anchor block");
        var r = checked(web.ethGetTransactionReceipt(tx).send(), "deployment receipt").getTransactionReceipt().orElseThrow();
        require("0x1".equals(r.getStatus()) && tx.equalsIgnoreCase(r.getTransactionHash())
                && r.getBlockNumber().longValueExact() == n && b.getHash().equalsIgnoreCase(r.getBlockHash())
                && address.equalsIgnoreCase(r.getContractAddress()) && r.getLogs().isEmpty(), "creation receipt mismatch");
        return new Release(address, header(b, n));
    }

    private static void storeBlock(Connection db, Header h) throws SQLException {
        // A previously orphaned hash can become canonical again after another fork.
        try (var s = db.prepareStatement("""
                INSERT INTO chain_block(chain_id,height,hash,parent_hash,canonical) VALUES (?,?,?,?,true)
                ON CONFLICT (chain_id,hash) DO UPDATE SET canonical=true WHERE NOT chain_block.canonical
                """)) {
            s.setLong(1, CHAIN); s.setLong(2, h.height); s.setString(3, h.hash); s.setString(4, h.parent);
            s.executeUpdate();
        }
    }

    private static Cursor lockCursor(Connection db, Release release) throws SQLException {
        try (var s = db.prepareStatement("SELECT * FROM scan_cursor WHERE id=1 FOR UPDATE"); var r = s.executeQuery()) {
            if (r.next()) {
                require(r.getLong("chain_id") == CHAIN && release.address.equals(r.getString("contract_address"))
                        && r.getLong("deploy_height") == release.deploy.height && release.deploy.hash.equals(r.getString("deploy_hash")),
                        "database belongs to a different release");
                return new Cursor(r.getLong("height"), r.getString("block_hash"));
            }
        }
        Header h = release.deploy;
        storeBlock(db, h);
        try (var s = db.prepareStatement("""
                INSERT INTO scan_cursor(id,chain_id,contract_address,deploy_height,deploy_hash,height,block_hash)
                VALUES (1,?,?,?,?,?,?)
                """)) {
            s.setLong(1, CHAIN); s.setString(2, release.address); s.setLong(3, h.height); s.setString(4, h.hash);
            s.setLong(5, h.height); s.setString(6, h.hash); s.executeUpdate();
        }
        return new Cursor(h.height, h.hash);
    }

    private static String storedHash(Connection db, long height) throws SQLException {
        try (var s = db.prepareStatement("SELECT hash FROM chain_block WHERE chain_id=? AND height=? AND canonical")) {
            s.setLong(1, CHAIN); s.setLong(2, height);
            try (var r = s.executeQuery()) {
                require(r.next(), "database missing canonical height " + height);
                return r.getString(1);
            }
        }
    }

    private static EthLog logs(Web3j web, EthFilter filter) throws IOException {
        return checked(web.ethGetLogs(filter.addOptionalTopics(TOPICS)).send(), "eth_getLogs");
    }

    private static DefaultBlockParameter at(long n) { return DefaultBlockParameter.valueOf(BigInteger.valueOf(n)); }

    private static Counts scanPage(Connection db, Web3j web, Release release, Cursor cursor, long from, long to)
            throws IOException, SQLException {
        Header[] blocks = new Header[(int) (to - from + 1)];
        String parent = from == release.deploy.height ? release.deploy.parent
                : from - 1 == cursor.height ? cursor.hash : storedHash(db, from - 1);
        for (int i = 0; i < blocks.length; ++i) {
            long n = from + i;
            Header h = header(Lab.block(web, n), n);
            sameBranch(parent.equals(h.parent), n);
            if (n <= cursor.height) sameBranch(h.hash.equals(storedHash(db, n)), n);
            else storeBlock(db, h);
            blocks[i] = h;
            parent = h.hash;
        }
        var rows = logs(web, new EthFilter(at(from), at(to), release.address)).getLogs();
        boolean[] seen = new boolean[blocks.length];
        int inserted = 0;
        try (var s = db.prepareStatement("""
                INSERT INTO escrow_log(chain_id,block_hash,tx_hash,log_index,address,kind,actor,amount_wei)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT (chain_id,block_hash,tx_hash,log_index) DO NOTHING
                """)) {
            for (var row : rows) {
                require(row.get() instanceof Log, "expected a mined log object");
                Log l = (Log) row.get();
                long n = l.getBlockNumber().longValueExact();
                require(!l.isRemoved() && n >= from && n <= to && release.address.equalsIgnoreCase(l.getAddress()),
                        "log outside filter or removed");
                int i = (int) (n - from);
                sameBranch(blocks[i].hash.equalsIgnoreCase(l.getBlockHash()), n);
                seen[i] = true;
                var topics = l.getTopics();
                require(topics != null && topics.size() == 2, "expected signature and indexed address");
                String kind = KINDS.get(hex(topics.get(0), WORD));
                String actorWord = hex(topics.get(1), WORD);
                require(kind != null && actorWord.startsWith("0x000000000000000000000000"), "unknown event or bad address padding");
                var amount = new BigInteger(hex(l.getData(), WORD).substring(2), 16);
                long index = l.getLogIndex().longValueExact();
                require(index >= 0, "negative log index");
                s.setLong(1, CHAIN); s.setString(2, blocks[i].hash); s.setString(3, hex(l.getTransactionHash(), WORD));
                s.setLong(4, index); s.setString(5, release.address); s.setString(6, kind);
                s.setString(7, "0x" + actorWord.substring(26)); s.setBigDecimal(8, new BigDecimal(amount));
                inserted += s.executeUpdate();
            }
        }
        // [] has no blockHash. In Cancun an empty transaction list cannot emit contract logs;
        // otherwise confirm the empty slot by hash, even if the branch switched away and back.
        for (int i = 0; i < blocks.length; ++i) {
            Header h = blocks[i];
            if (!seen[i] && h.hasTransactions) {
                sameBranch(logs(web, new EthFilter(h.hash, release.address)).getLogs().isEmpty(), h.height);
            }
        }
        checkCanonical(web, from, blocks[0].hash);
        if (to != from) checkCanonical(web, to, blocks[blocks.length - 1].hash);
        if (to > cursor.height) {
            try (var s = db.prepareStatement("UPDATE scan_cursor SET height=?,block_hash=? WHERE id=1")) {
                s.setLong(1, to); s.setString(2, blocks[blocks.length - 1].hash); s.executeUpdate();
            }
        }
        return new Counts(rows.size(), inserted);
    }

    public static void main(String[] args) throws Exception {
        require(args.length <= 1, "usage: Scan [fromHeight]");
        Long from = args.length == 1 ? Long.valueOf(args[0]) : null;
        Web3j web = Lab.web3();
        try (var db = Lab.db()) {
            Release release = verifyRelease(web);
            long head = checked(web.ethBlockNumber().send(), "eth_blockNumber").getBlockNumber().longValueExact();
            db.setAutoCommit(false);
            try {
                while (true) {
                    Cursor cursor = lockCursor(db, release);
                    checkCanonical(web, cursor.height, cursor.hash);
                    long next = Math.addExact(cursor.height, 1);
                    if (from == null) from = next;
                    require(from >= release.deploy.height && from <= next, "fromHeight would skip history or precedes deployment");
                    if (from > head) {
                        db.commit();
                        System.out.printf("CAUGHT_UP head=%d cursor=%d%n", head, cursor.height);
                        return;
                    }
                    long to = from + Math.min(WINDOW - 1L, head - from);
                    Counts counts = scanPage(db, web, release, cursor, from, to);
                    db.commit();
                    System.out.printf("PAGE %d..%d matched=%d inserted=%d cursor=%d%n", from, to,
                            counts.matched, counts.inserted, Math.max(cursor.height, to));
                    if (to == head) return;
                    from = to + 1;
                }
            } catch (Exception e) {
                db.rollback();
                throw e;
            }
        } finally { web.shutdown(); }
    }
}
