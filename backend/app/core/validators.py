"""Validation and normalisation for Indian business and banking identifiers."""

import ipaddress
import re
from urllib.parse import urlparse

IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
ACCOUNT_NUMBER_RE = re.compile(r"^\d{9,18}$")
VPA_RE = re.compile(r"^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z][a-zA-Z0-9]{1,63}$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PIN_RE = re.compile(r"^[1-9][0-9]{5}$")
MOBILE_RE = re.compile(r"^[6-9]\d{9}$")


def normalize_mobile(value: str) -> str:
    digits = re.sub(r"[\s\-()]", "", value)
    if digits.startswith("+91"):
        digits = digits[3:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if not MOBILE_RE.match(digits):
        raise ValueError("must be a valid 10-digit Indian mobile number")
    return digits


def normalize_ifsc(value: str) -> str:
    v = value.strip().upper()
    if not IFSC_RE.match(v):
        raise ValueError("must be a valid 11-character IFSC (e.g. HDFC0001234)")
    return v


def normalize_account_number(value: str) -> str:
    v = re.sub(r"\s", "", value)
    if not ACCOUNT_NUMBER_RE.match(v):
        raise ValueError("must be 9 to 18 digits")
    return v


def normalize_vpa(value: str) -> str:
    v = value.strip()
    if not VPA_RE.match(v):
        raise ValueError("must be a valid UPI ID (e.g. business@okbank)")
    return v.lower()


def normalize_pan(value: str) -> str:
    v = value.strip().upper()
    if not PAN_RE.match(v):
        raise ValueError("must be a valid PAN (e.g. ABCDE1234F)")
    return v


def normalize_gstin(value: str) -> str:
    v = value.strip().upper()
    if not GSTIN_RE.match(v):
        raise ValueError("must be a valid 15-character GSTIN")
    return v


def normalize_pin(value: str) -> str:
    v = value.strip()
    if not PIN_RE.match(v):
        raise ValueError("must be a valid 6-digit PIN code")
    return v


def validate_website(value: str) -> str:
    v = value.strip()
    p = urlparse(v)
    if p.scheme not in ("http", "https") or not p.hostname or "." not in p.hostname:
        raise ValueError("must be a full http(s) URL")
    return v


def _is_private_host(host: str) -> bool:
    if host in ("localhost",) or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


def validate_webhook_url(url: str, *, environment: str, allow_insecure_local: bool) -> str:
    """LIVE webhooks must be public HTTPS endpoints. TEST webhooks may target http://localhost only in
    development, so merchants can test locally; never in production (SSRF protection).
    Delivery re-checks the resolved IP at send time (Phase 5), since DNS can change."""
    v = url.strip()
    p = urlparse(v)
    if not p.hostname or p.scheme not in ("http", "https"):
        raise ValueError("must be a full http(s) URL")
    if p.username or p.password:
        raise ValueError("must not contain credentials")
    local = _is_private_host(p.hostname.lower())
    relaxed = environment == "TEST" and allow_insecure_local
    if p.scheme != "https" and not (relaxed and local):
        raise ValueError("must use https")
    if local and not relaxed:
        raise ValueError("must be a publicly reachable host")
    return v
