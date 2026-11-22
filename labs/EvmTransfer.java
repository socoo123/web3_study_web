import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.IOException;
import java.math.BigInteger;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.Locale;
import java.util.Map;

class EvmTransfer {
    private static final URI ENDPOINT = URI.create("http://127.0.0.1:18545");
    private static final HttpClient HTTP = HttpClient.newBuilder().proxy(HttpClient.Builder.NO_PROXY)
            .version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(2)).build();
    private static final Gson JSON = new Gson();
    private static final BigInteger VALUE = BigInteger.TEN.pow(16); // 0.01 ETH, in wei
    private static final BigInteger GWEI = BigInteger.TEN.pow(9);
    private static final BigInteger GAS_LIMIT = BigInteger.valueOf(30_000);
    private static int nextId;

    private static JsonElement rpc(String method, Object... params) throws IOException, InterruptedException {
        int id = ++nextId;
        String body = JSON.toJson(Map.of("jsonrpc", "2.0", "id", id, "method", method, "params", params));
        var request = HttpRequest.newBuilder(ENDPOINT).timeout(Duration.ofSeconds(3))
                .header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body)).build();
        var reply = HTTP.send(request, HttpResponse.BodyHandlers.ofString());
        if (reply.statusCode() != 200) throw new IOException(method + ": HTTP " + reply.statusCode());
        JsonObject msg = JsonParser.parseString(reply.body()).getAsJsonObject();
        if (!"2.0".equals(msg.get("jsonrpc").getAsString()) || msg.get("id").getAsInt() != id)
            throw new IOException(method + ": response version/id mismatch");
        if (msg.has("error")) throw new IOException(method + ": " + msg.get("error"));
        if (!msg.has("result")) throw new IOException(method + ": missing result");
        return msg.get("result"); // JSON null is meaningful for a not-yet-mined receipt.
    }

    private static BigInteger quantity(JsonElement field) {
        String hex = field.getAsString();
        if (!hex.startsWith("0x")) throw new IllegalArgumentException("Not an RPC quantity: " + hex);
        return new BigInteger(hex.substring(2), 16);
    }

    private record Snapshot(BigInteger senderNonce, BigInteger receiverNonce,
                            BigInteger senderWei, BigInteger receiverWei) {
        void print(String stage, String block, String hash) {
            System.out.printf("%s block=%s blockHash=%s senderNonce=%s receiverNonce=%s senderWei=%s receiverWei=%s%n",
                    stage, block, hash, senderNonce, receiverNonce, senderWei, receiverWei);
        }
    }

    private static Snapshot snapshot(String from, String to, String block) throws Exception {
        return new Snapshot(quantity(rpc("eth_getTransactionCount", from, block)),
                quantity(rpc("eth_getTransactionCount", to, block)),
                quantity(rpc("eth_getBalance", from, block)), quantity(rpc("eth_getBalance", to, block)));
    }

    private static JsonObject awaitReceipt(String hash) throws Exception {
        long start = System.nanoTime();
        while (System.nanoTime() - start < Duration.ofSeconds(15).toNanos()) {
            JsonElement receipt = rpc("eth_getTransactionReceipt", hash);
            if (!receipt.isJsonNull()) return receipt.getAsJsonObject();
            Thread.sleep(250);
        }
        throw new IOException("No receipt yet for " + hash + "; outcome unknown. Query again; do not resend.");
    }

    private static void expect(String label, BigInteger actual, BigInteger expected) {
        if (!actual.equals(expected))
            throw new IllegalStateException(label + ": actual=" + actual + ", expected=" + expected);
    }

    private static String hex(BigInteger n) {
        return "0x" + n.toString(16);
    }

    private static BigInteger maxFee(String[] args) {
        if (args.length == 0) return BigInteger.valueOf(3_000_000_000L);
        if (args.length != 2 || !args[0].equals("--max-fee-wei"))
            throw new IllegalArgumentException("Usage: EvmTransfer.java [--max-fee-wei INTEGER_WEI_PER_GAS]");
        BigInteger cap = new BigInteger(args[1]);
        if (cap.compareTo(GWEI) < 0)
            throw new IllegalArgumentException("maxFeePerGas must cover the 1000000000 wei/gas priority cap");
        return cap;
    }

    public static void main(String[] args) throws Exception {
        BigInteger cap = maxFee(args);
        String client = rpc("web3_clientVersion").getAsString();
        if (!client.toLowerCase(Locale.ROOT).contains("anvil")) throw new IllegalStateException("Anvil required");
        BigInteger chain = quantity(rpc("eth_chainId"));
        expect("chainId", chain, BigInteger.valueOf(31337));
        var accounts = rpc("eth_accounts").getAsJsonArray();
        if (accounts.size() != 2) throw new IllegalStateException("Start a fresh Anvil with --accounts 2");
        String from = accounts.get(0).getAsString(), to = accounts.get(1).getAsString();
        String head = rpc("eth_blockNumber").getAsString();
        if (!head.equals("0x0")) throw new IllegalStateException("This is not a fresh lab chain; refusing to send");
        String genesisHash = rpc("eth_getBlockByNumber", head, false).getAsJsonObject().get("hash").getAsString();
        Snapshot before = snapshot(from, to, head);
        BigInteger nonce = quantity(rpc("eth_getTransactionCount", from, "pending"));
        expect("genesis sender nonce", before.senderNonce(), BigInteger.ZERO);
        expect("genesis receiver nonce", before.receiverNonce(), BigInteger.ZERO);
        expect("pending nonce", nonce, before.senderNonce());
        BigInteger budget = GAS_LIMIT.multiply(cap);
        if (before.senderWei().compareTo(VALUE.add(budget)) < 0)
            throw new IllegalArgumentException("Cannot cover value + gasLimit * maxFeePerGas; not submitted");
        System.out.printf("chainId=%s from=%s to=%s%n", chain, from, to);
        before.print("before", head, genesisHash);

        // Teaching control only. The calculation below still reads baseFeePerGas from the mined block.
        rpc("anvil_setNextBlockBaseFeePerGas", hex(GWEI));
        var transfer = Map.of("type", "0x2", "from", from, "to", to, "nonce", hex(nonce),
                "value", hex(VALUE), "gas", hex(GAS_LIMIT), "maxFeePerGas", hex(cap),
                "maxPriorityFeePerGas", hex(GWEI));
        System.out.printf("submit once: type=2 nonce=%s valueWei=%s gasLimit=%s maxFeePerGas=%s "
                + "maxPriorityFeePerGas=%s feeBudgetWei=%s%n", nonce, VALUE, GAS_LIMIT, cap, GWEI, budget);
        String hash = rpc("eth_sendTransaction", transfer).getAsString(); // local Anvil signs; no retries
        System.out.println("txHash=" + hash);
        JsonObject receipt = awaitReceipt(hash);
        if (!hash.equalsIgnoreCase(receipt.get("transactionHash").getAsString()))
            throw new IllegalStateException("Receipt hash mismatch");
        String block = receipt.get("blockNumber").getAsString();
        String status = receipt.get("status").getAsString();
        if (!status.equals("0x1") && !status.equals("0x0")) throw new IllegalStateException("Unknown status: " + status);
        String blockHash = receipt.get("blockHash").getAsString();
        JsonObject mined = rpc("eth_getBlockByNumber", block, false).getAsJsonObject();
        var hashes = mined.getAsJsonArray("transactions");
        if (!block.equals("0x1") || !blockHash.equalsIgnoreCase(mined.get("hash").getAsString())
                || !genesisHash.equalsIgnoreCase(mined.get("parentHash").getAsString())
                || hashes.size() != 1 || !hash.equalsIgnoreCase(hashes.get(0).getAsString()))
            throw new IllegalStateException("Expected one transaction in the direct child of our genesis block");
        String beneficiary = mined.get("miner").getAsString();
        if (beneficiary.equalsIgnoreCase(from) || beneficiary.equalsIgnoreCase(to))
            throw new IllegalStateException("Fee recipient must be distinct from the two order accounts");
        BigInteger base = quantity(mined.get("baseFeePerGas"));
        expect("lab block base fee", base, GWEI);
        BigInteger used = quantity(receipt.get("gasUsed")), price = quantity(receipt.get("effectiveGasPrice"));
        expect("plain transfer gas", used, BigInteger.valueOf(21_000));
        BigInteger fee = used.multiply(price);
        System.out.printf("receipt block=%s blockHash=%s status=%s gasUsed=%s effectiveGasPrice=%s feeWei=%s%n",
                block, blockHash, status, used, price, fee);

        JsonObject tx = rpc("eth_getTransactionByHash", hash).getAsJsonObject();
        if (!blockHash.equalsIgnoreCase(tx.get("blockHash").getAsString()) ||
                !from.equalsIgnoreCase(tx.get("from").getAsString()) || !to.equalsIgnoreCase(tx.get("to").getAsString()))
            throw new IllegalStateException("Transaction block or endpoints do not match the order");
        expect("type", quantity(tx.get("type")), BigInteger.TWO);
        expect("included chain", quantity(tx.get("chainId")), chain);
        expect("included nonce", quantity(tx.get("nonce")), nonce);
        expect("included value", quantity(tx.get("value")), VALUE);
        expect("gas limit", quantity(tx.get("gas")), GAS_LIMIT);
        BigInteger max = quantity(tx.get("maxFeePerGas")), priorityCap = quantity(tx.get("maxPriorityFeePerGas"));
        expect("max fee", max, cap);
        expect("max priority fee", priorityCap, GWEI);
        BigInteger tip = priorityCap.min(max.subtract(base));
        expect("effective gas price", price, base.add(tip));
        BigInteger burn = used.multiply(base), reward = used.multiply(tip);
        expect("fee split", fee, burn.add(reward));
        System.out.printf("split baseFeePerGas=%s tipPerGas=%s burnWei=%s tipWei=%s feeRecipient=%s%n",
                base, tip, burn, reward, beneficiary);
        Snapshot after = snapshot(from, to, block);
        BigInteger debit = before.senderWei().subtract(after.senderWei()), credit = after.receiverWei().subtract(before.receiverWei());
        after.print("after", block, blockHash);
        System.out.printf("senderDebitWei=%s receiverCreditWei=%s%n", debit, credit);
        BigInteger delivered = status.equals("0x1") ? VALUE : BigInteger.ZERO;
        expect("next sender nonce", after.senderNonce(), nonce.add(BigInteger.ONE));
        expect("receiver nonce", after.receiverNonce(), before.receiverNonce());
        expect("receiver credit", credit, delivered);
        expect("sender debit", debit, delivered.add(fee));
        if (status.equals("0x0")) throw new IllegalStateException("Mined but failed: nonce and gas consumed; no value delivered");
        System.out.println("PASS: Type 2; receiver credit = value; sender debit = value + burn + tip; nonces match");
    }
}
