"""A small private CA for the internal mTLS API (decision of 18.11.2026; Planung 8.0, section 3).

The CA signs one server certificate for the auth service and one client certificate per
Mailhelp instance. An instance is identified by the SHA-256 fingerprint of its certificate in
the operator's registry; disabling the instance there revokes it at once, without a CRL. The CA
key is written readable only by its owner and belongs into separate, offline storage.
"""
from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CA_DAYS = 3650
LEAF_DAYS = 397


def _private(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def _key_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def fingerprint(certificate_pem: bytes) -> str:
    """SHA-256 of the DER form; the same value ``ssl`` reports for the peer certificate."""
    return hashlib.sha256(x509.load_pem_x509_certificate(certificate_pem).public_bytes(
        serialization.Encoding.DER)).hexdigest()


def der_fingerprint(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def create_ca(directory: Path, now: datetime | None = None) -> Path:
    """``ca.key`` and ``ca.pem``; an existing CA is never overwritten."""
    now = now or datetime.now(UTC)
    directory.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Inboxstride interne CA")])
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
                   .not_valid_after(now + timedelta(days=CA_DAYS))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                   .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                                                key_encipherment=False, data_encipherment=False,
                                                key_agreement=False, key_cert_sign=True, crl_sign=True,
                                                encipher_only=False, decipher_only=False), critical=True)
                   .sign(key, hashes.SHA256()))
    _private(directory / "ca.key", _key_bytes(key))
    _private(directory / "ca.pem", certificate.public_bytes(serialization.Encoding.PEM))
    return directory / "ca.pem"


def issue(ca_directory: Path, out: Path, name: str, *, server: bool, now: datetime | None = None) -> str:
    """``<name>.key`` and ``<name>.pem`` signed by the CA; returns the certificate fingerprint.

    A server certificate names *name* as DNS name; a client certificate carries the instance id.
    """
    now = now or datetime.now(UTC)
    ca_key = serialization.load_pem_private_key((ca_directory / "ca.key").read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate((ca_directory / "ca.pem").read_bytes())
    if not isinstance(ca_key, ec.EllipticCurvePrivateKey):
        raise ValueError("Unerwarteter CA-Schlüssel")
    key = ec.generate_private_key(ec.SECP256R1())
    builder = (x509.CertificateBuilder()
               .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
               .issuer_name(ca_cert.subject).public_key(key.public_key())
               .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
               .not_valid_after(now + timedelta(days=LEAF_DAYS))
               .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
               .add_extension(x509.ExtendedKeyUsage(
                   [ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False))
    if server:
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
    certificate = builder.sign(ca_key, hashes.SHA256())
    out.mkdir(parents=True, exist_ok=True)
    pem = certificate.public_bytes(serialization.Encoding.PEM)
    _private(out / f"{name}.key", _key_bytes(key))
    _private(out / f"{name}.pem", pem)
    return fingerprint(pem)


__all__ = ["CA_DAYS", "LEAF_DAYS", "create_ca", "der_fingerprint", "fingerprint", "issue"]
