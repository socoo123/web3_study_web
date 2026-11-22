package course.m05;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.net.InetSocketAddress;
import java.net.ProxySelector;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.time.Duration;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicLong;
import java.util.regex.Pattern;
import org.web3j.abi.EventEncoder;
import org.web3j.abi.FunctionReturnDecoder;
import org.web3j.abi.TypeReference;
import org.web3j.abi.datatypes.Address;
import org.web3j.abi.datatypes.Event;
import org.web3j.abi.datatypes.Type;
import org.web3j.abi.datatypes.generated.Uint256;
import org.web3j.protocol.ObjectMapperFactory;
import org.web3j.protocol.core.methods.response.TransactionReceipt;

/** M04 single-release observer. Not an RPC proxy, transaction sender or order ledger. */
public final class ReceiptApi {
    private static final int PORT = 18117;
    private static final URI NODE = URI.create(Lab.RPC);
    private static final String ROUTE = "/receipts/";
    private static final Pattern WORD = Pattern.compile("0x[0-9a-fA-F]{64}");
    private static final Pattern PADDED_ADDRESS = Pattern.compile("0x0{24}[0-9a-fA-F]{40}");
    private static final ObjectMapper JSON = ObjectMapperFactory.getObjectMapper();
    private static final HttpClient HTTP = HttpClient.newBuilder().proxy(ProxySelector.of(null))
            .connectTimeout(Duration.ofSeconds(1)).version(HttpClient.Version.HTTP_1_1).build();
    private static final AtomicLong IDS = new AtomicLong();
    private static final Event LOCKED = new Event("Locked", List.of(
            new TypeReference<Address>(true) {}, new TypeReference<Uint256>() {}));
    private static final String LOCK_TOPIC = EventEncoder.encode(LOCKED);
    private static final List<TypeReference<Type>> DATA_TYPES = LOCKED.getNonIndexedParameters();

    private final String address;
    private final String payer;
    private final String deployHeight;
    private final String deployHash;
    private long windowStart = System.nanoTime();
    private int reads;

    private ReceiptApi(JsonNode m) {
        if (!"m04-escrow-release/1".equals(m.path("format").asText()) || m.path("chainId").asInt() != 31337) {
            throw new IllegalArgumentException("expected course release on chain 31337");
        }
        address = m.required("contractAddress").asText().toLowerCase(Locale.ROOT);
        payer = m.required("deployer").asText().toLowerCase(Locale.ROOT);
        deployHash = m.required("deploymentBlockHash").asText().toLowerCase(Locale.ROOT);
        deployHeight = "0x" + Long.toHexString(m.required("deploymentBlockNumber").longValue());
    }

    private static final class Failure extends Exception {
        final int status;
        Failure(int status, String state) { super(state); this.status = status; }
    }

    // One request, one node response; never retry in this layer.
    private static JsonNode rpc(String method, Object... params) throws Failure, InterruptedException {
        long id = IDS.incrementAndGet();
        ObjectNode request = JSON.createObjectNode().put("jsonrpc", "2.0").put("id", id).put("method", method);
        request.set("params", JSON.valueToTree(params));
        var post = HttpRequest.newBuilder(NODE)
                .header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(request.toString())).build();
        var pending = HTTP.sendAsync(post, HttpResponse.BodyHandlers.ofByteArray());
        try {
            var response = pending.get(2, TimeUnit.SECONDS);
            if (response.statusCode() == 429) throw new Failure(503, "RPC_THROTTLED");
            if (response.statusCode() != 200) throw new Failure(502, "RPC_HTTP_ERROR");
            JsonNode reply = JSON.readTree(response.body());
            if (reply == null || !"2.0".equals(reply.path("jsonrpc").asText()) || !reply.path("id").isIntegralNumber()
                    || reply.path("id").longValue() != id || reply.has("result") == reply.has("error")) {
                throw new Failure(502, "INVALID_RPC_REPLY");
            }
            if (reply.has("error")) {
                System.err.println(method + " id=" + id + " rpcCode=" + reply.path("error").path("code"));
                throw new Failure(502, "RPC_ERROR");
            }
            return reply;
        } catch (TimeoutException e) {
            pending.cancel(true);
            throw new Failure(504, "RPC_TIMEOUT");
        } catch (InterruptedException e) {
            pending.cancel(true);
            throw e;
        } catch (ExecutionException e) {
            if (e.getCause() instanceof HttpTimeoutException) throw new Failure(504, "RPC_TIMEOUT");
            throw new Failure(503, "RPC_UNAVAILABLE");
        } catch (IOException e) { throw new Failure(502, "INVALID_RPC_REPLY"); }
    }

    private synchronized boolean admit() {
        long now = System.nanoTime();
        if (now - windowStart >= 1_000_000_000L) { windowStart = now; reads = 0; }
        if (reads == 8) return false;
        reads++;
        return true;
    }

    private ObjectNode lookup(String hash) throws Failure, InterruptedException {
        if (!"0x7a69".equals(rpc("eth_chainId").path("result").asText()) || !deployHash.equalsIgnoreCase(
                rpc("eth_getBlockByNumber", deployHeight, false).path("result").path("hash").asText())) {
            throw new Failure(502, "RELEASE_MISMATCH");
        }
        JsonNode result = rpc("eth_getTransactionReceipt", hash).get("result");
        if (result.isNull()) throw new Failure(404, "NO_RECEIPT");
        try {
            TransactionReceipt r = JSON.treeToValue(result, TransactionReceipt.class);
            if (!hash.equalsIgnoreCase(r.getTransactionHash()) || r.getBlockHash() == null
                    || !WORD.matcher(r.getBlockHash()).matches() || r.getLogs() == null) throw new Failure(502, "INVALID_RECEIPT");
            boolean ok = "0x1".equals(r.getStatus());
            if (!ok && !"0x0".equals(r.getStatus())) throw new Failure(502, "INVALID_RECEIPT");
            ObjectNode out = JSON.createObjectNode().put("state", ok ? "EXECUTED" : "REVERTED").put("chainId", 31337)
                    .put("transactionHash", hash).put("status", r.getStatus()).put("blockNumber", r.getBlockNumber().toString())
                    .put("blockHash", r.getBlockHash().toLowerCase(Locale.ROOT)).put("gasUsed", r.getGasUsed().toString());
            if (!ok) return out;
            for (var log : r.getLogs()) {
                if (!address.equalsIgnoreCase(log.getAddress()) || log.getTopics().isEmpty()
                        || !LOCK_TOPIC.equalsIgnoreCase(log.getTopics().get(0))) continue;
                var topics = log.getTopics();
                if (out.has("lockedWei") || topics.size() != 2 || !PADDED_ADDRESS.matcher(topics.get(1)).matches()
                        || !payer.substring(2).equalsIgnoreCase(topics.get(1).substring(26))
                        || !WORD.matcher(log.getData()).matches()) throw new Failure(502, "INVALID_LOCK_LOG");
                Uint256 amount = (Uint256) FunctionReturnDecoder.decode(log.getData(), DATA_TYPES).get(0);
                BigInteger wei = amount.getValue();
                out.put("contractAddress", address).put("payer", payer).put("lockedWei", wei.toString())
                        .put("lockedEth", new BigDecimal(wei, 18).toPlainString());
            }
            return out;
        } catch (JsonProcessingException | RuntimeException e) { throw new Failure(502, "INVALID_RECEIPT"); }
    }

    private void handle(HttpExchange x) throws IOException {
        try (x) {
            int code = 200;
            ObjectNode body;
            try {
                if (!"GET".equals(x.getRequestMethod())) {
                    x.getResponseHeaders().set("Allow", "GET");
                    throw new Failure(405, "METHOD_NOT_ALLOWED");
                }
                String path = x.getRequestURI().getRawPath();
                if (!path.startsWith(ROUTE)) throw new Failure(404, "NO_ROUTE");
                String hash = path.substring(ROUTE.length());
                if (!WORD.matcher(hash).matches() || x.getRequestURI().getRawQuery() != null) throw new Failure(400, "BAD_REQUEST");
                if (!admit()) {
                    x.getResponseHeaders().set("Retry-After", "1");
                    throw new Failure(429, "RATE_LIMITED");
                }
                body = lookup(hash.toLowerCase(Locale.ROOT));
            } catch (Failure e) {
                code = e.status;
                body = JSON.createObjectNode().put("state", e.getMessage());
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                code = 503;
                body = JSON.createObjectNode().put("state", "INTERRUPTED");
            }
            byte[] bytes = JSON.writeValueAsBytes(body);
            x.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
            x.getResponseHeaders().set("Cache-Control", "no-store");
            x.sendResponseHeaders(code, bytes.length);
            x.getResponseBody().write(bytes);
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length == 2 && args[0].equals("raw") && WORD.matcher(args[1]).matches()) {
            System.out.println(rpc("eth_getTransactionReceipt", args[1]));
            return;
        }
        if (args.length != 0) throw new IllegalArgumentException("Usage: ReceiptApi [raw 0x<32 bytes>]");
        var api = new ReceiptApi(Lab.manifest());
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", PORT), 16);
        server.createContext("/", api::handle);
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
        Runtime.getRuntime().addShutdownHook(new Thread(() -> server.stop(0)));
        server.start();
        System.out.println("GET http://127.0.0.1:" + PORT + ROUTE + "{hash}  (Ctrl-C to stop)");
    }
}
