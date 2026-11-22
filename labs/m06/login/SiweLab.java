import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.web3j.crypto.ECKeyPair;
import org.web3j.crypto.Keys;
import org.web3j.crypto.Sign;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.SecureRandom;
import java.security.SignatureException;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.Map;

// JDK 21 source launcher. Start ONE role per JVM: the login process never creates a key.
class SiweLab {
    static final String SITE = "http://127.0.0.1:18121", SIGNER = "http://localhost:18221";
    static final String CHAIN = "31337", STATEMENT = "Sign in to the local course desk. No transaction.";
    static final ObjectMapper JSON = new ObjectMapper();
    static final HexFormat HEX = HexFormat.of();
    static final SecureRandom RANDOM = new SecureRandom();

    static String randomId(int bytes) {
        byte[] value = new byte[bytes]; RANDOM.nextBytes(value); return HEX.formatHex(value);
    }
    record Challenge(String address, String nonce, Instant issued, Instant expires) {
        String text() {
            return SITE + " wants you to sign in with your Ethereum account:\n" + address
                + "\n\n" + STATEMENT + "\n\nURI: " + SITE + "/\nVersion: 1\nChain ID: " + CHAIN
                + "\nNonce: " + nonce + "\nIssued At: " + issued + "\nExpiration Time: " + expires;
        }
    }
    static final class Denied extends RuntimeException {
        final int status;
        Denied(int status, String code) { super(code); this.status = status; }
    }
    static void check(boolean ok, int status, String code) { if (!ok) throw new Denied(status, code); }
    static String field(JsonNode body, String name) {
        var value = body.path(name); check(value.isTextual(), 400, "BAD_FIELD"); return value.textValue();
    }
    static String address(JsonNode body) {
        String text = field(body, "address");
        check(text.matches("0x[0-9a-fA-F]{40}"), 400, "BAD_ADDRESS");
        return Keys.toChecksumAddress(text);
    }
    static String browserCookie(HttpExchange x) {
        String cookies = x.getRequestHeaders().getFirst("Cookie");
        if (cookies != null) for (String item : cookies.split(";\\s*")) {
            if (item.matches("m06b=[0-9a-f]{64}")) return item.substring(5);
        }
        return "";
    }
    static boolean signedBy(String message, String signature, String expected) {
        if (!signature.matches("0x[0-9a-fA-F]{128}(?i:1b|1c|00|01)")) return false;
        try {
            var sig = Sign.signatureDataFromHex(signature);
            var order = Sign.CURVE_PARAMS.getN();
            var r = new java.math.BigInteger(1, sig.getR()); var s = new java.math.BigInteger(1, sig.getS());
            if (r.signum() == 0 || s.signum() == 0 || r.compareTo(order) >= 0 || s.compareTo(order) >= 0) return false;
            var key = Sign.signedPrefixedMessageToKey(message.getBytes(StandardCharsets.UTF_8), sig);
            return expected.equals(Keys.toChecksumAddress(Keys.getAddress(key)));
        } catch (SignatureException | RuntimeException invalid) { return false; }
    }

    interface Api { Object post(HttpExchange x, String path, JsonNode body); }
    static final class BrowserState {
        Challenge pending, login;
        Instant discardAt;
    }
    static final class Login implements Api {
        final Map<String, BrowserState> browsers = new HashMap<>();
        final int ttl;
        Login(int ttl) { check(ttl >= 5 && ttl <= 120, 400, "TTL must be 5..120 seconds"); this.ttl = ttl; }
        public synchronized Object post(HttpExchange x, String path, JsonNode body) {
            Instant now = Instant.now();
            browsers.values().removeIf(state -> !now.isBefore(state.discardAt));
            String id = browserCookie(x);
            BrowserState state = browsers.get(id);
            if (path.equals("/api/reset")) {
                if (state == null) {
                    id = randomId(32); state = new BrowserState(); browsers.put(id, state);
                    x.getResponseHeaders().add("Set-Cookie", "m06b=" + id + "; Path=/api/; HttpOnly; SameSite=Strict");
                }
                state.discardAt = now.plusSeconds(900); state.pending = null; state.login = null;
                return Map.of("status", "ANONYMOUS");
            }
            check(state != null, 401, "NO_BROWSER");
            if (state.login != null && !now.isBefore(state.login.expires())) state.login = null;
            return switch (path) {
                case "/api/challenge" -> {
                    check(CHAIN.equals(field(body, "chainId")), 400, "WRONG_CHAIN");
                    Instant issued = now.truncatedTo(ChronoUnit.SECONDS);
                    state.login = null; state.discardAt = now.plusSeconds(900);
                    state.pending = new Challenge(address(body), randomId(16), issued, issued.plusSeconds(ttl));
                    yield Map.of("message", state.pending.text());
                }
                case "/api/verify" -> {
                    Challenge c = state.pending;
                    check(c != null, 409, "NO_CHALLENGE");
                    // Accept exactly the server-issued profile, not a caller's parsed claims.
                    String expected = c.text();
                    check(expected.equals(field(body, "message")), 400, "MESSAGE_MISMATCH");
                    if (now.isBefore(c.issued()) || !now.isBefore(c.expires())) {
                        state.pending = null; throw new Denied(410, "EXPIRED");
                    }
                    check(signedBy(expected, field(body, "signature"), c.address()), 401, "BAD_SIGNATURE");
                    state.pending = null; state.login = c;
                    yield view(c);
                }
                case "/api/status" -> state.login == null ? Map.of("status", "ANONYMOUS") : view(state.login);
                default -> throw new Denied(404, "NOT_FOUND");
            };
        }
        static Map<String, String> view(Challenge c) {
            return Map.of("status", "AUTHENTICATED", "address", c.address(), "chainId", CHAIN, "expires", c.expires().toString());
        }
    }

    // A separate, disposable signer on the operator's own machine, never a login API route.
    static final class Keyring implements Api {
        final Map<String, ECKeyPair> keys = new java.util.LinkedHashMap<>();
        Keyring() throws Exception {
            for (int i = 0; i < 2; i++) {
                var key = Keys.createEcKeyPair(); keys.put(Keys.toChecksumAddress(Keys.getAddress(key)), key);
            }
        }
        public Object post(HttpExchange x, String path, JsonNode body) {
            if (path.equals("/wallet/accounts")) return Map.of("accounts", keys.keySet());
            check(path.equals("/wallet/confirm"), 404, "NOT_FOUND");
            String a = address(body), text = field(body, "message");
            ECKeyPair key = keys.get(a); check(key != null, 400, "NOT_A_LAB_KEY");
            // No general-purpose signing endpoint: reconstruct the one allowed local login format.
            String[] lines = text.split("\n", -1);
            check(lines.length == 11 && lines[8].matches("Nonce: [0-9a-f]{32}")
                && lines[9].startsWith("Issued At: ") && lines[10].startsWith("Expiration Time: "), 400, "NOT_LAB_SIWE");
            try {
                var c = new Challenge(a, lines[8].substring(7), Instant.parse(lines[9].substring(11)),
                    Instant.parse(lines[10].substring(17)));
                check(c.text().equals(text) && c.expires().isAfter(c.issued()) && !c.expires().isAfter(c.issued().plusSeconds(120)),
                    400, "NOT_LAB_SIWE");
            } catch (java.time.DateTimeException invalid) { throw new Denied(400, "NOT_LAB_SIWE"); }
            var sig = Sign.signPrefixedMessage(text.getBytes(StandardCharsets.UTF_8), key);
            return Map.of("signature", "0x" + HEX.formatHex(sig.getR()) + HEX.formatHex(sig.getS()) + HEX.formatHex(sig.getV()));
        }
    }
    static void reply(HttpExchange x, int status, String type, byte[] bytes) throws IOException {
        x.getResponseHeaders().set("Content-Type", type); x.sendResponseHeaders(status, bytes.length);
        x.getResponseBody().write(bytes);
    }
    static void serve(HttpExchange x, String origin, boolean signer, Api api) throws IOException {
        try (x) {
            var headers = x.getResponseHeaders(); headers.set("Cache-Control", "no-store");
            headers.set("X-Content-Type-Options", "nosniff"); headers.set("Referrer-Policy", "no-referrer");
            headers.set("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'");
            try {
                check(origin.substring(7).equals(x.getRequestHeaders().getFirst("Host")), 403, "WRONG_HOST");
                String path = x.getRequestURI().getRawPath();
                if (x.getRequestMethod().equals("GET")) {
                    String script = signer ? "signer.js" : "app.js";
                    String file = switch (path) {
                        case "/" -> signer ? "signer.html" : "login.html";
                        case "/desk.css" -> "desk.css";
                        default -> { check(path.equals("/" + script) || (!signer && path.equals("/bridge.js")), 404, "NOT_FOUND"); yield path.substring(1); }
                    };
                    String type = file.endsWith("js") ? "text/javascript" : file.endsWith("css") ? "text/css" : "text/html";
                    reply(x, 200, type + "; charset=utf-8", Files.readAllBytes(Path.of(file))); return;
                }
                check(x.getRequestMethod().equals("POST"), 405, "POST_ONLY");
                check(origin.equals(x.getRequestHeaders().getFirst("Origin")), 403, "WRONG_ORIGIN");
                check("application/json".equals(x.getRequestHeaders().getFirst("Content-Type")), 415, "JSON_REQUIRED");
                byte[] bytes = x.getRequestBody().readNBytes(8193); check(bytes.length <= 8192, 413, "TOO_LARGE");
                JsonNode body;
                try { body = JSON.readTree(bytes); } catch (IOException invalid) { throw new Denied(400, "BAD_JSON"); }
                check(body != null && body.isObject(), 400, "BAD_JSON");
                Object result = api.post(x, path, body);
                reply(x, 200, "application/json", JSON.writeValueAsBytes(result));
            } catch (Denied e) { reply(x, e.status, "application/json", JSON.writeValueAsBytes(Map.of("error", e.getMessage()))); }
        }
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 1 || !(args[0].equals("login") || args[0].equals("signer")))
            throw new IllegalArgumentException("mode: login | signer");
        boolean signer = args[0].equals("signer"); String origin = signer ? SIGNER : SITE;
        Api api = signer ? new Keyring() : new Login(Integer.parseInt(System.getenv().getOrDefault("SIWE_TTL_SECONDS", "120")));
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", signer ? 18221 : 18121), 0);
        server.createContext("/", x -> serve(x, origin, signer, api)); server.start();
        System.out.println(args[0] + " " + origin + "/ · Ctrl-C to stop");
    }
}
