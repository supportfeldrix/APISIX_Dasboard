"""LDAP authentication service using ldap3 with hard timeout enforcement."""
import logging
import ssl
import concurrent.futures
from typing import Optional, Dict

from ldap3 import Server, Connection, ALL, SUBTREE, Tls
from ldap3.core.exceptions import LDAPException

from app.config import settings

logger = logging.getLogger(__name__)

# Hard timeout for the entire LDAP operation (seconds)
# Must be long enough to accommodate MFA/2FA challenges (push notifications)
LDAP_HARD_TIMEOUT = 60


def authenticate_ldap(username: str, password: str) -> Optional[Dict[str, str]]:
    """Authenticate a user against LDAP/Active Directory.
    
    Wraps the LDAP call in a thread with a hard timeout to prevent
    blocking the entire application when LDAP is slow/unreachable.
    
    Returns a dict with user info if successful, None if auth fails or times out.
    """
    if not settings.LDAP_ENABLED:
        return None

    if not username or not password:
        return None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_ldap_authenticate, username, password)
            result = future.result(timeout=LDAP_HARD_TIMEOUT)
            return result
    except concurrent.futures.TimeoutError:
        logger.warning("LDAP: Timeout after %ds for user '%s'", LDAP_HARD_TIMEOUT, username)
        return None
    except Exception as e:
        logger.error("LDAP: Unexpected error for user '%s': %s", username, str(e))
        return None


def _ldap_authenticate(username: str, password: str) -> Optional[Dict[str, str]]:
    """Internal LDAP authentication logic (runs in a thread)."""
    try:
        # Configure TLS for LDAPS
        tls_config = None
        if settings.LDAP_USE_SSL:
            tls_config = Tls(
                validate=ssl.CERT_NONE if not settings.LDAP_VERIFY_SSL else ssl.CERT_REQUIRED,
            )

        # Connect to LDAP server
        server = Server(
            settings.LDAP_SERVER,
            use_ssl=settings.LDAP_USE_SSL,
            tls=tls_config,
            get_info=ALL,
            connect_timeout=5,
        )

        # First, bind with the service account to search for the user
        bind_dn = settings.LDAP_BIND_DN
        bind_password = settings.LDAP_BIND_PASSWORD

        if not bind_dn or not bind_password:
            # If no service account, try direct bind with user credentials
            return _direct_bind_authenticate(server, username, password)

        # Try service account bind to search for the user first
        try:
            conn = Connection(
                server,
                user=bind_dn,
                password=bind_password,
                auto_bind=True,
                read_only=True,
                receive_timeout=55,
            )
        except LDAPException as e:
            logger.warning(
                "LDAP: Service account bind failed (%s) — falling back to direct user bind for '%s'",
                str(e), username,
            )
            return _direct_bind_authenticate(server, username, password)

        # Search for the user DN
        search_filter = settings.LDAP_USER_FILTER.replace("{username}", username)
        conn.search(
            search_base=settings.LDAP_BASE_DN,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=["distinguishedName", "sAMAccountName", "displayName", "mail", "memberOf"],
        )

        if not conn.entries:
            logger.info("LDAP: User '%s' not found in directory", username)
            conn.unbind()
            return None

        user_entry = conn.entries[0]
        user_dn = str(user_entry.distinguishedName)
        conn.unbind()

        # Now bind as the user to verify their password
        user_conn = Connection(
            server,
            user=user_dn,
            password=password,
            auto_bind=True,
            read_only=True,
            receive_timeout=55,
        )

        # Auth succeeded — get user info
        user_conn.search(
            search_base=settings.LDAP_BASE_DN,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=["sAMAccountName", "displayName", "mail", "memberOf"],
        )

        user_info = _extract_user_info(user_conn, username)
        user_conn.unbind()

        logger.info("LDAP: User '%s' authenticated successfully", username)
        return user_info

    except LDAPException as e:
        logger.error("LDAP error for user '%s': %s", username, str(e))
        return None
    except Exception as e:
        logger.error("LDAP unexpected error for user '%s': %s", username, str(e))
        return None


def _direct_bind_authenticate(server, username: str, password: str) -> Optional[Dict[str, str]]:
    """Authenticate by binding directly as the user (used when no service account is available).
    
    This path is taken when LDAP_BIND_PASSWORD is not configured or when
    the service account bind fails. The user's own credentials are used
    to bind, which triggers any MFA/2FA challenges configured in AD.
    """
    user_dn = f"{username}@fnb.co.za"
    conn = Connection(
        server,
        user=user_dn,
        password=password,
        auto_bind=True,
        read_only=True,
        receive_timeout=55,
    )
    # If we get here, auth succeeded (including any 2FA challenge)
    search_filter = settings.LDAP_USER_FILTER.replace("{username}", username)
    conn.search(
        search_base=settings.LDAP_BASE_DN,
        search_filter=search_filter,
        search_scope=SUBTREE,
        attributes=["sAMAccountName", "displayName", "mail", "memberOf"],
    )

    user_info = _extract_user_info(conn, username)
    conn.unbind()
    logger.info("LDAP: User '%s' authenticated successfully (direct bind)", username)
    return user_info


def _extract_user_info(conn, username: str) -> Dict[str, str]:
    """Extract user information from LDAP search results."""
    display_name = username
    email = ""
    groups = []

    if conn.entries:
        entry = conn.entries[0]
        if hasattr(entry, "displayName") and entry.displayName.value:
            display_name = str(entry.displayName.value)
        if hasattr(entry, "mail") and entry.mail.value:
            email = str(entry.mail.value)
        if hasattr(entry, "memberOf") and entry.memberOf.values:
            groups = [str(g) for g in entry.memberOf.values]

    # Check if user is in admin group (if configured)
    is_admin = False
    if settings.LDAP_ADMIN_GROUP:
        admin_group_lower = settings.LDAP_ADMIN_GROUP.lower()
        for group in groups:
            if admin_group_lower in group.lower():
                is_admin = True
                break

    return {
        "username": username,
        "display_name": display_name,
        "email": email,
        "groups": groups,
        "is_admin": is_admin,
    }
