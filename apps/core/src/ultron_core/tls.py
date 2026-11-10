"""HTTPS for ULTRON Core on your own network.

`ultron-core tls-init` creates a self-signed certificate for this PC. Apps
pin its SHA-256 fingerprint when they pair (after you check that the short
fingerprint on the phone matches the one on the PC), so nobody else on the
network can pretend to be your ULTRON Core, without needing a public
certificate authority.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def generate(directory: Path, names: list[str], *, days: int = 825) -> tuple[Path, Path]:
    """Writes cert.pem and key.pem (key readable only by the owner)."""
    directory.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    alt: list[x509.GeneralName] = []
    for name in dict.fromkeys(["localhost", "127.0.0.1", *names]):
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            alt.append(x509.DNSName(name))
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ULTRON Core")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    return cert_path, key_path


def fingerprint(cert_path: Path) -> str:
    """SHA-256 of the certificate (DER), as 64 hex characters."""
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def short(fp: str) -> str:
    """What people compare by eye: first and last 8 hex characters."""
    fp = fp.upper()
    return f"{fp[:4]}-{fp[4:8]} … {fp[-8:-4]}-{fp[-4:]}"
