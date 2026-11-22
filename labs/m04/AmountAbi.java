import java.math.BigInteger;
import java.util.HexFormat;

/** Codec only for AmountRegister.set(uint256) and its single uint256 return. */
public final class AmountAbi {
    // Calibrated against `cast sig 'set(uint256)'` (Foundry v1.7.1).
    private static final String SET = "0x60fe47b1";

    private static String encode(String decimal) {
        BigInteger n = new BigInteger(decimal, 10);
        if (n.signum() < 0 || n.bitLength() > 256) {
            throw new IllegalArgumentException("wei outside uint256");
        }
        String hex = n.toString(16);
        return SET + "0".repeat(64 - hex.length()) + hex;
    }

    private static BigInteger decode(String data, String prefix) {
        if (!data.startsWith(prefix) || data.length() != prefix.length() + 64) {
            throw new IllegalArgumentException("expected " + prefix + " followed by one 32-byte word");
        }
        byte[] word = HexFormat.of().parseHex(data, prefix.length(), data.length());
        return new BigInteger(1, word); // ABI uint256 is an unsigned, big-endian magnitude.
    }

    public static void main(String[] args) {
        try {
            if (args.length != 2) {
                throw new IllegalArgumentException("usage: AmountAbi encode|decode-call|decode-result VALUE");
            }
            switch (args[0]) {
                case "encode" -> System.out.println(encode(args[1]));
                case "decode-call" -> System.out.println(decode(args[1], SET));
                case "decode-result" -> System.out.println(decode(args[1], "0x"));
                default -> throw new IllegalArgumentException("unknown operation: " + args[0]);
            }
        } catch (IllegalArgumentException ex) {
            System.err.println("STOP " + ex.getMessage());
            System.exit(2);
        }
    }
}
