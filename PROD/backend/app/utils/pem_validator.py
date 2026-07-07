"""PEM certificate and private key validation utilities."""
import re


def validate_pem_cert(pem: str) -> bool:
    """Return True if the string contains a valid PEM certificate block."""
    pattern = r"-----BEGIN CERTIFICATE-----[\s\S]+-----END CERTIFICATE-----"
    return bool(re.search(pattern, pem.strip()))


def validate_pem_key(pem: str) -> bool:
    """Return True if the string contains a valid PEM private key block."""
    pattern = r"-----BEGIN (?:RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----[\s\S]+-----END (?:RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----"
    return bool(re.search(pattern, pem.strip()))
