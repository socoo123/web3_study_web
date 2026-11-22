import java.nio.charset.StandardCharsets;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.PublicKey;
import java.security.SecureRandom;
import java.security.Signature;
import java.util.Arrays;
import javax.crypto.AEADBadTagException;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Offline JDK 17+ lab. No wallet, files, network or exported keys. */
public class IntentLab {
    static byte[] bytes(String text) {
        return text.getBytes(StandardCharsets.UTF_8);
    }

    static boolean verify(PublicKey key, byte[] message, byte[] signature) throws Exception {
        Signature verifier = Signature.getInstance("Ed25519");
        verifier.initVerify(key);
        verifier.update(message);
        return verifier.verify(signature);
    }

    static byte[] crypt(int mode, SecretKey key, byte[] iv, byte[] input) throws Exception {
        Cipher aes = Cipher.getInstance("AES/GCM/NoPadding");
        aes.init(mode, key, new GCMParameterSpec(128, iv));
        aes.updateAAD(bytes("intent-lab:v1"));
        return aes.doFinal(input);
    }

    public static void main(String[] args) throws Exception {
        String intent = "lab-only|order=17|recipient=Bob|amount=125|unit=sat";
        byte[] message = bytes(intent);
        KeyPair signer = KeyPairGenerator.getInstance("Ed25519").generateKeyPair();
        Signature signing = Signature.getInstance("Ed25519");
        signing.initSign(signer.getPrivate());
        signing.update(message);
        byte[] signature = signing.sign();
        boolean original = verify(signer.getPublic(), message, signature);
        boolean changed = verify(signer.getPublic(), bytes(intent.replace("125", "126")), signature);
        System.out.printf("signature: original=%b changed_amount=%b%n", original, changed);
        if (!original || changed) throw new IllegalStateException("signature check failed");

        KeyGenerator generator = KeyGenerator.getInstance("AES");
        generator.init(256);
        SecretKey key = generator.generateKey();
        byte[] iv = new byte[12];
        new SecureRandom().nextBytes(iv); // New key per run; exactly one encryption under this key.
        byte[] sealed = crypt(Cipher.ENCRYPT_MODE, key, iv, message);
        boolean same = Arrays.equals(message, crypt(Cipher.DECRYPT_MODE, key, iv, sealed));
        System.out.printf("decryption: matches_original=%b%n", same);
        if (!same) throw new IllegalStateException("round trip changed the bytes");
        sealed[0] ^= 1;
        try {
            crypt(Cipher.DECRYPT_MODE, key, iv, sealed);
            throw new IllegalStateException("altered ciphertext was accepted");
        } catch (AEADBadTagException expected) {
            System.out.println("altered_ciphertext=rejected");
        }
    }
}
