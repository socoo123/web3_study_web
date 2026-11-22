import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

public final class MerkleLab {
    private static final HexFormat HEX = HexFormat.of();
    // Course checkpoint: not calculated from the proof provider's inputs.
    private static final byte[] TRUSTED_ROOT = HEX.parseHex(
            "c2d6ba7ea2bb3bc0a5dec604403dc473df26c923b7e9cd81fefb8701f5ed290d");

    private static byte[] leaf(MessageDigest sha, byte[] record) {
        sha.update((byte) 0x00);
        return sha.digest(record);
    }

    private static byte[] parent(MessageDigest sha, byte[] left, byte[] right) {
        sha.update((byte) 0x01);
        sha.update(left);
        return sha.digest(right);
    }

    private static byte[] tree(MessageDigest sha) {
        String[] records = {"10010203", "11010302", "12030201", "13020102"};
        byte[][] leaves = new byte[records.length][];
        for (int i = 0; i < records.length; i++) {
            leaves[i] = leaf(sha, HEX.parseHex(records[i]));
            System.out.println("L" + i + "=" + HEX.formatHex(leaves[i]));
        }
        byte[] p01 = parent(sha, leaves[0], leaves[1]);
        byte[] p23 = parent(sha, leaves[2], leaves[3]);
        System.out.println("P01=" + HEX.formatHex(p01));
        System.out.println("P23=" + HEX.formatHex(p23));
        return parent(sha, p01, p23);
    }

    private static byte[] bytes(String hex, int size) {
        if (hex.length() != size * 2) {
            throw new IllegalArgumentException("expected " + size + " bytes in hex");
        }
        return HEX.parseHex(hex);
    }

    private static byte[] proofRoot(MessageDigest sha, String[] args) {
        int index = Integer.parseInt(args[1]);
        if (index < 0 || index > 3) {
            throw new IllegalArgumentException("index must be 0..3");
        }
        byte[] current = leaf(sha, bytes(args[2], 4));
        System.out.println("leaf=" + HEX.formatHex(current));
        for (int level = 0; level < 2; level++) {
            byte[] sibling = bytes(args[3 + level], 32);
            boolean currentOnLeft = ((index >>> level) & 1) == 0;
            current = currentOnLeft ? parent(sha, current, sibling) : parent(sha, sibling, current);
            System.out.println("step" + (level + 1) + ".sibling=" + (currentOnLeft ? "RIGHT" : "LEFT"));
            if (level == 0) {
                System.out.println("step1.parent=" + HEX.formatHex(current));
            }
        }
        return current;
    }

    public static void main(String[] args) throws NoSuchAlgorithmException {
        MessageDigest sha = MessageDigest.getInstance("SHA-256");
        byte[] root;
        try {
            if (args.length == 0) {
                root = tree(sha);
            } else if (args.length == 5 && args[0].equals("verify")) {
                root = proofRoot(sha, args);
            } else {
                throw new IllegalArgumentException("usage: java MerkleLab.java [verify INDEX RECORD SIBLING0 SIBLING1]");
            }
        } catch (IllegalArgumentException e) {
            System.err.println(e.getMessage());
            System.exit(2);
            return;
        }
        boolean matches = MessageDigest.isEqual(root, TRUSTED_ROOT);
        System.out.println("candidate.root=" + HEX.formatHex(root));
        System.out.println("trusted.root=" + HEX.formatHex(TRUSTED_ROOT));
        System.out.println("matches.trusted=" + matches);
        if (!matches) {
            System.exit(1);
        }
    }
}
