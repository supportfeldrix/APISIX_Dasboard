"""Version Check Service — compares running APISIX version against latest GitHub release.

Queries the APISIX Admin API for the running gateway version, fetches the latest
stable release from the Apache APISIX GitHub repository, compares them using
semantic versioning, and persists the result to the database.
"""
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree

import httpx

from app.config import settings
from app.database import SessionLocal
from app.models.version_check import VersionCheckResult

logger = logging.getLogger(__name__)

# Regex for semantic version: major.minor.patch with optional pre-release/build suffixes
_SEMVER_RE = re.compile(
    r"v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$"
)

# GitHub Releases API endpoint
_GITHUB_RELEASES_URL = "https://api.github.com/repos/apache/apisix/releases"

# GitHub Atom feed (fallback — lighter weight, no auth needed)
_GITHUB_ATOM_FEED_URL = "https://github.com/apache/apisix/releases.atom"

# Retry configuration for GitHub API
_GITHUB_MAX_RETRIES = 3
_GITHUB_RETRY_DELAY_SECONDS = 5


class VersionCheckService:
    """Service responsible for checking APISIX version against latest GitHub release."""

    def parse_semver(self, version_str: str) -> tuple[int, int, int] | None:
        """Parse a version string into a (major, minor, patch) tuple.

        Strips any leading 'v' prefix and pre-release/build-metadata suffixes.
        Returns None if the string cannot be parsed.

        Args:
            version_str: Version string, e.g. "3.8.0", "v3.9.1-rc1", "3.8.0+build.123"

        Returns:
            Tuple of (major, minor, patch) integers, or None if unparseable.
        """
        if not version_str or not isinstance(version_str, str):
            return None

        version_str = version_str.strip()
        match = _SEMVER_RE.match(version_str)
        if not match:
            return None

        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def compare_versions(self, running: str, latest: str) -> bool:
        """Compare two version strings using semantic versioning.

        Returns True if `latest` is strictly greater than `running`.

        Args:
            running: The currently running version string.
            latest: The latest available version string.

        Returns:
            True if an update is available (latest > running), False otherwise.
        """
        running_tuple = self.parse_semver(running)
        latest_tuple = self.parse_semver(latest)

        if running_tuple is None or latest_tuple is None:
            return False

        return latest_tuple > running_tuple

    async def get_running_version(self) -> str | None:
        """Query the APISIX Admin API to retrieve the running gateway version.

        Parses the version from the 'Server' response header (e.g. "APISIX/3.16.0")
        returned by any Admin API request. Uses a lightweight GET to /apisix/admin/routes
        with the configured APISIX_ADMIN_KEY.

        Returns:
            The version string (e.g. "3.16.0") or None if unreachable/unparseable.
        """
        base_url = settings.APISIX_ADMIN_BASE_URL.rstrip("/")
        # Use /apisix/admin/routes as a lightweight endpoint that always exists
        url = f"{base_url}/apisix/admin/routes"
        headers = {"X-API-KEY": settings.APISIX_ADMIN_KEY}
        timeout = httpx.Timeout(
            connect=settings.APISIX_ADMIN_TIMEOUT,
            read=settings.APISIX_ADMIN_TIMEOUT,
            write=settings.APISIX_ADMIN_TIMEOUT,
            pool=settings.APISIX_ADMIN_TIMEOUT,
        )

        try:
            async with httpx.AsyncClient(
                verify=settings.APISIX_ADMIN_VERIFY_SSL,
                timeout=timeout,
            ) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()

            # Parse version from the Server header (e.g. "APISIX/3.16.0")
            server_header = response.headers.get("server", "")
            version = None

            if server_header.startswith("APISIX/"):
                version = server_header[len("APISIX/"):]
            elif "/" in server_header:
                # Fallback: try to extract version after any slash
                version = server_header.split("/", 1)[1]

            if version:
                if self.parse_semver(version) is not None:
                    logger.info("Running APISIX version: %s", version)
                    return version
                else:
                    logger.error(
                        "APISIX Server header returned unparseable version: '%s'", version
                    )
                    return None
            else:
                logger.error(
                    "Could not extract version from APISIX Server header: '%s'",
                    server_header,
                )
                return None

        except httpx.TimeoutException as exc:
            logger.error(
                "APISIX Admin API request timed out after %ds: %s",
                settings.APISIX_ADMIN_TIMEOUT,
                exc,
            )
            return None
        except httpx.ConnectError as exc:
            logger.error("APISIX Admin API unreachable: %s", exc)
            return None
        except httpx.HTTPStatusError as exc:
            logger.error(
                "APISIX Admin API returned error status %d: %s",
                exc.response.status_code,
                exc,
            )
            return None
        except Exception as exc:
            logger.error("Unexpected error querying APISIX Admin API: %s", exc)
            return None

    async def get_latest_release(self) -> str | None:
        """Query GitHub for the latest stable APISIX release.

        Strategy:
        1. Try the GitHub REST API (/releases/latest) — most accurate.
        2. If that fails after retries, fall back to the Atom feed
           (https://github.com/apache/apisix/releases.atom) which is
           lighter-weight and doesn't count against API rate limits.

        Supports GITHUB_PROXY_URL for outbound requests through corporate proxy.

        Returns:
            The latest stable version tag (e.g. "3.9.1") or None if unavailable.
        """
        # Try REST API first
        version = await self._get_latest_from_rest_api()
        if version is not None:
            return version

        # Fallback: try Atom feed
        logger.info("REST API failed, falling back to GitHub Atom feed...")
        return await self._get_latest_from_atom_feed()

    async def _get_latest_from_rest_api(self) -> str | None:
        """Try the GitHub REST API /releases/latest endpoint."""
        latest_url = f"{_GITHUB_RELEASES_URL}/latest"
        timeout = httpx.Timeout(
            connect=settings.GITHUB_API_TIMEOUT,
            read=settings.GITHUB_API_TIMEOUT,
            write=settings.GITHUB_API_TIMEOUT,
            pool=settings.GITHUB_API_TIMEOUT,
        )

        # Configure proxy if set
        proxy_url = settings.GITHUB_PROXY_URL or None

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "CRO-APISIX-Dashboard/1.0",
        }

        last_error: Exception | None = None

        for attempt in range(1, _GITHUB_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=timeout,
                    proxy=proxy_url,
                ) as client:
                    response = await client.get(latest_url, headers=headers)
                    response.raise_for_status()

                release = response.json()

                if not isinstance(release, dict):
                    logger.error(
                        "GitHub Releases API returned unexpected format (not a dict)"
                    )
                    return None

                # Check it's not a pre-release or draft
                if release.get("prerelease", False) or release.get("draft", False):
                    logger.warning(
                        "GitHub /releases/latest returned a pre-release or draft, skipping"
                    )
                    return None

                tag = release.get("tag_name", "")
                parsed = self.parse_semver(tag)
                if parsed is not None:
                    # Strip leading 'v' for consistency
                    version = f"{parsed[0]}.{parsed[1]}.{parsed[2]}"
                    logger.info("Latest stable APISIX release (REST API): %s", version)
                    return version
                else:
                    logger.warning(
                        "GitHub /releases/latest returned unparseable tag: '%s'", tag
                    )
                    return None

            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
                last_error = exc
                logger.warning(
                    "GitHub REST API request failed (attempt %d/%d): %s",
                    attempt,
                    _GITHUB_MAX_RETRIES,
                    exc,
                )
                if attempt < _GITHUB_MAX_RETRIES:
                    await asyncio.sleep(_GITHUB_RETRY_DELAY_SECONDS)
            except Exception as exc:
                last_error = exc
                logger.error(
                    "Unexpected error querying GitHub REST API (attempt %d/%d): %s",
                    attempt,
                    _GITHUB_MAX_RETRIES,
                    exc,
                )
                if attempt < _GITHUB_MAX_RETRIES:
                    await asyncio.sleep(_GITHUB_RETRY_DELAY_SECONDS)

        # All retries exhausted
        logger.warning(
            "GitHub REST API unreachable after %d attempts. Last error: %s",
            _GITHUB_MAX_RETRIES,
            last_error,
        )
        return None

    async def _get_latest_from_atom_feed(self) -> str | None:
        """Fallback: parse the GitHub Atom feed for the latest release version.

        The Atom feed at https://github.com/apache/apisix/releases.atom lists
        release entries with <title> tags containing the version (e.g. "3.11.0").
        This is lighter-weight than the REST API and doesn't require auth.
        """
        timeout = httpx.Timeout(
            connect=settings.GITHUB_API_TIMEOUT,
            read=settings.GITHUB_API_TIMEOUT,
            write=settings.GITHUB_API_TIMEOUT,
            pool=settings.GITHUB_API_TIMEOUT,
        )

        proxy_url = settings.GITHUB_PROXY_URL or None

        headers = {
            "User-Agent": "CRO-APISIX-Dashboard/1.0",
            "Accept": "application/atom+xml",
        }

        last_error: Exception | None = None

        for attempt in range(1, _GITHUB_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=timeout,
                    proxy=proxy_url,
                ) as client:
                    response = await client.get(
                        _GITHUB_ATOM_FEED_URL, headers=headers
                    )
                    response.raise_for_status()

                # Parse the Atom XML feed
                root = ElementTree.fromstring(response.text)

                # Atom namespace
                ns = {"atom": "http://www.w3.org/2005/Atom"}

                # Iterate through <entry> elements to find first stable release
                for entry in root.findall("atom:entry", ns):
                    title_el = entry.find("atom:title", ns)
                    if title_el is None or not title_el.text:
                        continue

                    tag = title_el.text.strip()
                    parsed = self.parse_semver(tag)
                    if parsed is not None:
                        # Skip pre-release versions (those with -rc, -alpha, etc.)
                        if re.search(r"[-](alpha|beta|rc|dev|pre)", tag, re.IGNORECASE):
                            continue
                        version = f"{parsed[0]}.{parsed[1]}.{parsed[2]}"
                        logger.info(
                            "Latest stable APISIX release (Atom feed): %s", version
                        )
                        return version

                logger.warning("No valid stable release found in Atom feed")
                return None

            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
                last_error = exc
                logger.warning(
                    "GitHub Atom feed request failed (attempt %d/%d): %s",
                    attempt,
                    _GITHUB_MAX_RETRIES,
                    exc,
                )
                if attempt < _GITHUB_MAX_RETRIES:
                    await asyncio.sleep(_GITHUB_RETRY_DELAY_SECONDS)
            except ElementTree.ParseError as exc:
                logger.error("Failed to parse Atom feed XML: %s", exc)
                return None
            except Exception as exc:
                last_error = exc
                logger.error(
                    "Unexpected error querying GitHub Atom feed (attempt %d/%d): %s",
                    attempt,
                    _GITHUB_MAX_RETRIES,
                    exc,
                )
                if attempt < _GITHUB_MAX_RETRIES:
                    await asyncio.sleep(_GITHUB_RETRY_DELAY_SECONDS)

        logger.error(
            "GitHub Atom feed unreachable after %d attempts. Last error: %s",
            _GITHUB_MAX_RETRIES,
            last_error,
        )
        return None

    def persist_result(self, result: VersionCheckResult) -> None:
        """Persist a version check result to the database.

        Replaces any existing result (single-row persistence strategy).

        Args:
            result: The VersionCheckResult to persist.
        """
        db = SessionLocal()
        try:
            # Delete all existing results (keep only the latest)
            db.query(VersionCheckResult).delete()
            db.add(result)
            db.commit()
            logger.info(
                "Version check result persisted: running=%s, latest=%s, update_available=%s",
                result.running_version,
                result.latest_version,
                result.update_available,
            )
        except Exception as exc:
            db.rollback()
            logger.error("Failed to persist version check result: %s", exc)
        finally:
            db.close()

    def get_latest_result(self) -> VersionCheckResult | None:
        """Retrieve the most recent version check result from the database.

        Returns:
            The latest VersionCheckResult, or None if no result exists.
        """
        db = SessionLocal()
        try:
            result = (
                db.query(VersionCheckResult)
                .order_by(VersionCheckResult.check_timestamp.desc())
                .first()
            )
            if result:
                # Detach from session so it can be used after session closes
                db.expunge(result)
            return result
        except Exception as exc:
            logger.error("Failed to retrieve version check result: %s", exc)
            return None
        finally:
            db.close()

    async def run_check(self) -> VersionCheckResult:
        """Orchestrate a full version check cycle.

        Steps:
        1. Query APISIX Admin API for running version
        2. Query GitHub Releases API for latest stable release
        3. Compare versions
        4. Persist result to database
        5. Return the result

        Returns:
            A VersionCheckResult with the comparison outcome.
        """
        logger.info("Starting version check cycle...")
        check_timestamp = datetime.now(timezone.utc)

        # Step 1: Get running version
        running_version = await self.get_running_version()

        # Step 2: Get latest release
        latest_version = await self.get_latest_release()

        # Step 3: Determine outcome
        if running_version is None and latest_version is None:
            # Both failed — record as failed check
            result = VersionCheckResult(
                running_version=None,
                latest_version=None,
                update_available=False,
                check_timestamp=check_timestamp,
                check_successful=False,
                error_message="Unable to retrieve both running and latest versions",
            )
        elif running_version is None:
            # Running version unavailable
            result = VersionCheckResult(
                running_version=None,
                latest_version=latest_version,
                update_available=False,
                check_timestamp=check_timestamp,
                check_successful=False,
                error_message="Unable to retrieve running APISIX version",
            )
        elif latest_version is None:
            # Latest version unavailable
            result = VersionCheckResult(
                running_version=running_version,
                latest_version=None,
                update_available=False,
                check_timestamp=check_timestamp,
                check_successful=False,
                error_message="Unable to retrieve latest APISIX release from GitHub",
            )
        else:
            # Both available — compare
            update_available = self.compare_versions(running_version, latest_version)
            result = VersionCheckResult(
                running_version=running_version,
                latest_version=latest_version,
                update_available=update_available,
                check_timestamp=check_timestamp,
                check_successful=True,
                error_message=None,
            )

        # Step 4: Persist result
        self.persist_result(result)

        # Step 5: Return
        logger.info(
            "Version check complete: running=%s, latest=%s, update_available=%s, successful=%s",
            result.running_version,
            result.latest_version,
            result.update_available,
            result.check_successful,
        )
        return result


# Module-level singleton for use by scheduler and endpoints
version_check_service = VersionCheckService()
