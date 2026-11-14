import "types"

fun countValidOracleSignatures(
    digest: uint256,
    keys: AuthorityKeys,
    signatures: OracleSignatureSet,
): int {
    val sigA = signatures.signatureA.load();
    val sigB = signatures.signatureB.load();
    val sigC = signatures.signatureC.load();

    var valid = 0;
    if (isSignatureValid(digest, sigA.data as slice, keys.keyA)) {
        valid += 1;
    }
    if (isSignatureValid(digest, sigB.data as slice, keys.keyB)) {
        valid += 1;
    }
    if (isSignatureValid(digest, sigC.data as slice, keys.keyC)) {
        valid += 1;
    }
    return valid;
}

fun countValidResolverSignatures(
    digest: uint256,
    keys: AuthorityKeys,
    signatures: ResolverSignatureSet,
): int {
    val sigA = signatures.signatureA.load();
    val sigB = signatures.signatureB.load();
    val sigC = signatures.signatureC.load();

    var valid = 0;
    if (isSignatureValid(digest, sigA.data as slice, keys.keyA)) {
        valid += 1;
    }
    if (isSignatureValid(digest, sigB.data as slice, keys.keyB)) {
        valid += 1;
    }
    if (isSignatureValid(digest, sigC.data as slice, keys.keyC)) {
        valid += 1;
    }
    return valid;
}
