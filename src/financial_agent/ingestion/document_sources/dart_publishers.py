"""Exact organizer-manager reconciliation with OpenDART publishers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from io import BytesIO
import re
from typing import Literal
import unicodedata
from urllib.parse import urlencode
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from .base import NoRedirectHttpOpener
from .dart_targets import OrganizerDartInventory


DartPublisherMatchBasis = Literal[
    "official_identifier", "official_name", "reviewed_alias"
]
_CORP_CODE = re.compile(r"^[0-9]{8}$")
_MODIFY_DATE = re.compile(r"^[0-9]{8}$")
_ZIP_MEMBER = "CORPCODE.xml"
_MAX_ZIP_BYTES = 64 * 1024 * 1024
_MAX_XML_BYTES = 128 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200
_CORP_CODE_ENDPOINT = "https://opendart.fss.or.kr/api/corpCode.xml"
_REQUEST_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class DartPublisherBinding:
    manager_entity_id: str
    manager_name: str
    corp_code: str
    corp_name: str
    match_basis: DartPublisherMatchBasis


@dataclass(frozen=True, slots=True)
class DartPublisherFailure:
    manager_entity_id: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class DartPublisherReconciliation:
    bindings: tuple[DartPublisherBinding, ...]
    failures: tuple[DartPublisherFailure, ...]
    source_checksum: str


class DartPublisherDataError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def fetch_dart_corporation_codes(
    opener: NoRedirectHttpOpener,
    api_key: str,
) -> bytes:
    if not isinstance(api_key, str) or not api_key.strip():
        raise DartPublisherDataError("dart_api_key_missing")
    url = f"{_CORP_CODE_ENDPOINT}?{urlencode({'crtfc_key': api_key})}"
    try:
        response = opener.open_no_redirect(
            url,
            method="GET",
            headers={
                "Accept": "application/zip, application/octet-stream",
                "Accept-Encoding": "identity",
            },
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        try:
            status = getattr(response, "status", None)
            if status != 200:
                raise DartPublisherDataError("dart_corporation_codes_unavailable")
            payload = response.read(_MAX_ZIP_BYTES + 1)
        finally:
            response.close()
    except DartPublisherDataError:
        raise
    except Exception:
        raise DartPublisherDataError("dart_corporation_codes_unavailable") from None
    if not isinstance(payload, bytes) or len(payload) > _MAX_ZIP_BYTES:
        raise DartPublisherDataError("dart_corporation_codes_malformed")
    _decode_corporations(payload)
    return payload


def reconcile_dart_publishers(
    *,
    inventory: OrganizerDartInventory,
    corp_code_zip: bytes,
    institution_identifiers: Mapping[str, tuple[tuple[str, str], ...]],
    reviewed_aliases: Mapping[str, str],
) -> DartPublisherReconciliation:
    managers = {
        manager_id: manager_name
        for target in inventory.targets
        for manager_id, manager_name in target.manager_bindings
    }
    if not set(reviewed_aliases).issubset(managers):
        raise DartPublisherDataError("dart_reviewed_alias_not_anchored")

    corporations = _decode_corporations(corp_code_zip)
    corporations_by_code = {item.corp_code: item for item in corporations}
    corporations_by_name: dict[str, list[_Corporation]] = {}
    for corporation in corporations:
        corporations_by_name.setdefault(
            _normalize_name(corporation.corp_name), []
        ).append(corporation)

    bindings: list[DartPublisherBinding] = []
    failures: list[DartPublisherFailure] = []
    for manager_id, manager_name in sorted(managers.items()):
        official_codes = {
            value
            for scheme, value in institution_identifiers.get(manager_id, ())
            if scheme == "DART_CORP_CODE"
        }
        if official_codes:
            if len(official_codes) != 1:
                failures.append(
                    DartPublisherFailure(
                        manager_id, "dart_publisher_identifier_ambiguous"
                    )
                )
                continue
            corporation = corporations_by_code.get(next(iter(official_codes)))
            if corporation is None:
                failures.append(
                    DartPublisherFailure(
                        manager_id, "dart_publisher_identifier_not_found"
                    )
                )
                continue
            match_basis: DartPublisherMatchBasis = "official_identifier"
        elif manager_id in reviewed_aliases:
            alias_code = reviewed_aliases[manager_id]
            if _CORP_CODE.fullmatch(alias_code) is None:
                raise DartPublisherDataError("dart_reviewed_alias_invalid")
            corporation = corporations_by_code.get(alias_code)
            if corporation is None:
                raise DartPublisherDataError("dart_reviewed_alias_invalid")
            match_basis = "reviewed_alias"
        else:
            name_matches = corporations_by_name.get(
                _normalize_name(manager_name), []
            )
            if len(name_matches) > 1:
                failures.append(
                    DartPublisherFailure(
                        manager_id, "dart_publisher_name_ambiguous"
                    )
                )
                continue
            if not name_matches:
                failures.append(
                    DartPublisherFailure(
                        manager_id, "dart_publisher_not_matched"
                    )
                )
                continue
            corporation = name_matches[0]
            match_basis = "official_name"
        bindings.append(
            DartPublisherBinding(
                manager_entity_id=manager_id,
                manager_name=manager_name,
                corp_code=corporation.corp_code,
                corp_name=corporation.corp_name,
                match_basis=match_basis,
            )
        )

    return DartPublisherReconciliation(
        bindings=tuple(bindings),
        failures=tuple(failures),
        source_checksum=hashlib.sha256(corp_code_zip).hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class _Corporation:
    corp_code: str
    corp_name: str


def _decode_corporations(payload: bytes) -> tuple[_Corporation, ...]:
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > _MAX_ZIP_BYTES
    ):
        raise DartPublisherDataError("dart_corporation_codes_malformed")
    try:
        with ZipFile(BytesIO(payload)) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != _ZIP_MEMBER:
                raise DartPublisherDataError("dart_corporation_codes_malformed")
            member = members[0]
            if (
                member.is_dir()
                or member.file_size <= 0
                or member.file_size > _MAX_XML_BYTES
                or member.compress_size <= 0
                or member.file_size
                > member.compress_size * _MAX_COMPRESSION_RATIO
            ):
                raise DartPublisherDataError("dart_corporation_codes_malformed")
            xml_payload = archive.read(member)
    except (BadZipFile, KeyError, OSError, RuntimeError):
        raise DartPublisherDataError("dart_corporation_codes_malformed") from None
    try:
        root = ElementTree.fromstring(xml_payload)
    except ElementTree.ParseError:
        raise DartPublisherDataError("dart_corporation_codes_malformed") from None
    if root.tag != "result":
        raise DartPublisherDataError("dart_corporation_codes_malformed")

    corporations: list[_Corporation] = []
    seen_codes: set[str] = set()
    for item in root:
        if item.tag != "list":
            raise DartPublisherDataError("dart_corporation_codes_malformed")
        values = {child.tag: child.text or "" for child in item}
        required_fields = {
            "corp_code",
            "corp_name",
            "stock_code",
            "modify_date",
        }
        if (
            len(values) != len(item)
            or frozenset(values) not in {
                frozenset(required_fields),
                frozenset((*required_fields, "corp_eng_name")),
            }
        ):
            raise DartPublisherDataError("dart_corporation_codes_malformed")
        corp_code = values["corp_code"].strip()
        corp_name = _normalize_name(values["corp_name"])
        if (
            _CORP_CODE.fullmatch(corp_code) is None
            or not corp_name
            or _MODIFY_DATE.fullmatch(values["modify_date"].strip()) is None
            or corp_code in seen_codes
        ):
            raise DartPublisherDataError("dart_corporation_codes_malformed")
        seen_codes.add(corp_code)
        corporations.append(_Corporation(corp_code, corp_name))
    if not corporations:
        raise DartPublisherDataError("dart_corporation_codes_malformed")
    return tuple(corporations)


def _normalize_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())
