package course.m05;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.math.BigInteger;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.time.Duration;
import okhttp3.OkHttpClient;
import org.web3j.protocol.Web3j;
import org.web3j.protocol.core.DefaultBlockParameter;
import org.web3j.protocol.core.methods.response.EthBlock;
import org.web3j.protocol.http.HttpService;

final class Lab {
    static final String RPC = "http://127.0.0.1:18556";
    static Web3j web3() {
        var http = new OkHttpClient.Builder().callTimeout(Duration.ofSeconds(8)).build();
        return Web3j.build(new HttpService(RPC, http, false));
    }

    static Connection db() throws SQLException {
        String name = System.getenv().getOrDefault("M05_DB", "m05");
        if (!name.matches("m05(_[a-z0-9]+)?")) throw new SQLException("expected course database m05 or m05_<name>");
        return DriverManager.getConnection("jdbc:postgresql://127.0.0.1:18557/" + name, "course", "course-local");
    }

    static JsonNode manifest() throws IOException {
        String path = System.getenv("M05_MANIFEST");
        if (path == null || path.isBlank()) throw new IOException("set M05_MANIFEST to the trusted M04 manifest.json");
        return new ObjectMapper().readTree(Path.of(path).toFile());
    }

    static EthBlock.Block block(Web3j w, long height) throws IOException {
        var reply = w.ethGetBlockByNumber(DefaultBlockParameter.valueOf(BigInteger.valueOf(height)), false).send();
        if (reply.hasError()) throw new IOException("eth_getBlockByNumber: " + reply.getError().getMessage());
        return reply.getBlock();
    }
}
