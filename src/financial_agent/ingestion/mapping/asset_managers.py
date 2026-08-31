"""Reviewed organizer asset-manager identities and exact source resolution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
import unicodedata

from .common import make_record_hash, normalize_name, stable_id


@dataclass(frozen=True, slots=True)
class AssetManagerIdentity:
    key: str
    canonical_name: str
    dart_corp_code: str | None
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AssetManagerResolution:
    status: Literal[
        "reviewed", "source_equal", "source_local", "conflict", "unresolved"
    ]
    identity: AssetManagerIdentity | None
    supporting_fields: tuple[str, ...]
    fallback_fields: tuple[str, ...]
    accepted_aliases: tuple[str, ...]


def _manager(
    key: str,
    canonical_name: str,
    dart_corp_code: str,
    *aliases: str,
) -> AssetManagerIdentity:
    return AssetManagerIdentity(
        key=key,
        canonical_name=canonical_name,
        dart_corp_code=dart_corp_code,
        aliases=(canonical_name, *aliases),
    )


_MANAGERS = (
    _manager(
        "assetplus_asset_management",
        "에셋플러스자산운용",
        "00336701",
        "Asset Plus Investment Management Co Ltd",
        "에셋플러스",
    ),
    _manager(
        "bnk_asset_management",
        "BNK자산운용",
        "00686776",
        "BNK Asset Management Co Ltd",
        "BNK",
    ),
    _manager(
        "db_asset_management",
        "디비자산운용",
        "00241388",
        "DB Asset Management Co Ltd",
        "DB",
    ),
    _manager(
        "ds_asset_management",
        "디에스자산운용",
        "00930880",
        "DS Asset Management Co Ltd",
        "디에스",
    ),
    _manager(
        "daishin_asset_management",
        "대신자산운용",
        "00110918",
        "Daishin Investment Trust Management",
        "대신",
    ),
    _manager(
        "hana_asset_management",
        "하나자산운용",
        "00326272",
        "Hana Asset Management Co Ltd",
        "하나",
    ),
    _manager(
        "hanwha_asset_management",
        "한화자산운용",
        "00243395",
        "Hanwha Asset Management",
        "한화",
        "한화PLUS",
    ),
    _manager(
        "heungkuk_asset_management",
        "흥국자산운용",
        "00330725",
        "Heungkuk Investment Trust Management Co., Ltd",
        "흥국",
    ),
    _manager(
        "hyundai_asset_management",
        "현대자산운용",
        "00695394",
        "Hyundai Asset Management Co Ltd",
        "현대",
    ),
    _manager(
        "ibk_asset_management",
        "아이비케이자산운용",
        "00516468",
        "IBK Asset Management Co Ltd",
        "IBK",
    ),
    _manager(
        "im_asset_management",
        "아이엠에셋자산운용",
        "00631475",
        "IM Asset Investment & Management Co Ltd",
        "iM에셋",
    ),
    _manager(
        "kb_asset_management",
        "KB자산운용",
        "00104500",
        "KB Asset Ltd",
        "KB",
    ),
    _manager(
        "kcgi_asset_management",
        "케이씨지아이자산운용",
        "00685935",
        "KCGI Asset Management Co Ltd",
        "케이씨지아이",
    ),
    _manager(
        "kiwoom_asset_management",
        "키움투자자산운용",
        "00120191",
        "Kiwoom Asset Management Co.,Ltd",
        "키움",
    ),
    _manager(
        "korea_investment_management",
        "한국투자신탁운용",
        "00324548",
        "Korea Investment Management Co Ltd",
        "한국투자",
        "ACE",
    ),
    _manager(
        "korea_investment_value_asset_management",
        "한국투자밸류자산운용",
        "00564030",
        "Korea Investment Value Asset Management Co Ltd",
        "한국밸류",
    ),
    _manager(
        "kyobo_axa_asset_management",
        "교보악사자산운용",
        "00241412",
        "Kyobo AXA Investment Managers Co Ltd",
        "교보악사",
    ),
    _manager(
        "midas_asset_management",
        "마이다스에셋자산운용",
        "00267526",
        "Midas Asset Management Co Ltd",
        "마이다스",
    ),
    _manager(
        "mirae_asset_global_investments",
        "미래에셋자산운용",
        "00259776",
        "Mirae Asset Global Investments Co Ltd",
        "미래에셋",
        "미래에셋TIGER",
        "TIGER",
    ),
    _manager(
        "nh_amundi_asset_management",
        "엔에이치아문디자산운용",
        "00453804",
        "NH-Amundi Asset Management Co Ltd",
        "NH-Amundi",
    ),
    _manager(
        "samsung_active_asset_management",
        "삼성액티브자산운용",
        "01194731",
        "Samsung Active Asset Management",
        "삼성액티브",
    ),
    _manager(
        "samsung_asset_management",
        "삼성자산운용",
        "00260453",
        "Samsung Asset Management Co Ltd",
        "삼성",
        "삼성KODEX",
    ),
    _manager(
        "shinhan_asset_management",
        "신한자산운용",
        "00243553",
        "Shinhan Asset Management Co Ltd",
        "신한",
    ),
    _manager(
        "the_j_asset_management",
        "더제이자산운용",
        "00883078",
        "The J Investment Co Ltd",
        "더제이",
    ),
    _manager(
        "timefolio_asset_management",
        "타임폴리오자산운용",
        "00787154",
        "Time Folio Asset Management Co Ltd",
        "타임폴리오",
    ),
    _manager(
        "truston_asset_management",
        "트러스톤자산운용",
        "00259794",
        "Truston Asset Management Co Ltd",
        "트러스톤",
    ),
    _manager(
        "vi_asset_management",
        "브이아이자산운용",
        "00260514",
        "VI Asset Management Korea Co Ltd",
        "브이아이",
    ),
    _manager(
        "woori_asset_management",
        "우리자산운용",
        "00331478",
        "Woori Asset Management Corp",
        "우리",
    ),
    _manager(
        "yurie_asset_management",
        "유리자산운용",
        "00324830",
        "Yurie asset Management Inc",
        "유리",
    ),
)


def _normalized(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return " ".join(text.split()).casefold()


def _source_normalized(value: object) -> str:
    normalized = _normalized(value)
    return "" if normalized == "." else normalized


_BY_ALIAS = {
    _normalized(alias): manager
    for manager in _MANAGERS
    for alias in manager.aliases
}
if len(_BY_ALIAS) != sum(len(manager.aliases) for manager in _MANAGERS):
    raise RuntimeError("asset-manager aliases must be unique")


def asset_manager_entity_id(identity: AssetManagerIdentity) -> str:
    return stable_id("institution", "CANONICAL_ASSET_MANAGER", identity.key)


def append_asset_manager_catalog_records(
    records_by_table: dict[str, list[Mapping[str, object]]],
    *,
    identity: AssetManagerIdentity,
    accepted_aliases: tuple[str, ...] = (),
) -> str:
    manager_id = asset_manager_entity_id(identity)

    def hashed(payload: dict[str, object]) -> dict[str, object]:
        payload["record_hash"] = make_record_hash(payload)
        return payload

    records_by_table["catalog.entity"].append(
        hashed(
            {
                "entity_id": manager_id,
                "entity_type": "institution",
                "canonical_name": identity.canonical_name,
                "normalized_name": normalize_name(identity.canonical_name),
            }
        )
    )
    records_by_table["catalog.institution"].append(
        {"entity_id": manager_id, "institution_kind": "asset_manager"}
    )
    identifiers = []
    if identity.dart_corp_code is not None:
        identifiers.append(("DART_CORP_CODE", identity.dart_corp_code, True))
    for scheme, value, primary in identifiers:
        records_by_table["catalog.identifier"].append(
            hashed(
                {
                    "identifier_id": stable_id(
                        "identifier",
                        "CANONICAL_ASSET_MANAGER",
                        f"{scheme}:{value}",
                    ),
                    "entity_id": manager_id,
                    "scheme": scheme,
                    "identifier_value": value,
                    "is_primary": primary,
                    "valid_from": None,
                    "valid_to": None,
                }
            )
        )
    for alias_text in accepted_aliases:
        normalized_alias = normalize_name(alias_text).upper()
        records_by_table["catalog.alias"].append(
            hashed(
                {
                    "alias_id": stable_id(
                        "alias",
                        "CANONICAL_ASSET_MANAGER",
                        f"{identity.key}:{normalized_alias}",
                    ),
                    "entity_id": manager_id,
                    "alias_text": alias_text,
                    "normalized_alias_text": normalized_alias,
                    "valid_from": None,
                    "valid_to": None,
                }
            )
        )
    return manager_id


def resolve_etf_asset_manager(
    cu_name: object,
    refinitiv_name: object,
) -> AssetManagerResolution:
    inputs = (
        ("cu_fund_mgmt_co", cu_name),
        ("ref_fund_mgmt_co", refinitiv_name),
    )
    present = tuple(
        (field, value) for field, value in inputs if _source_normalized(value)
    )
    resolved = tuple(
        (field, value, _BY_ALIAS.get(_normalized(value)))
        for field, value in present
    )
    reviewed = tuple(item for item in resolved if item[2] is not None)
    reviewed_keys = {item[2].key for item in reviewed if item[2] is not None}
    if len(reviewed_keys) > 1:
        return AssetManagerResolution(
            status="conflict",
            identity=None,
            supporting_fields=(),
            fallback_fields=tuple(field for field, _ in present),
            accepted_aliases=(),
        )
    if reviewed:
        identity = reviewed[0][2]
        assert identity is not None
        supporting_fields = tuple(item[0] for item in reviewed)
        fallback_fields = tuple(
            field for field, _, manager in resolved if manager is None
        )
        accepted_aliases = tuple(
            dict.fromkeys(str(value).strip() for _, value, _ in reviewed)
        )
        return AssetManagerResolution(
            status="reviewed",
            identity=identity,
            supporting_fields=supporting_fields,
            fallback_fields=fallback_fields,
            accepted_aliases=accepted_aliases,
        )
    if len(present) == 2 and _source_normalized(
        present[0][1]
    ) == _source_normalized(present[1][1]):
        canonical_name = normalize_name(str(present[0][1]))
        identity = AssetManagerIdentity(
            key=f"source_equal:{_normalized(canonical_name)}",
            canonical_name=canonical_name,
            dart_corp_code=None,
            aliases=(canonical_name,),
        )
        return AssetManagerResolution(
            status="source_equal",
            identity=identity,
            supporting_fields=tuple(field for field, _ in present),
            fallback_fields=(),
            accepted_aliases=(canonical_name,),
        )
    if len(present) == 1:
        field, value = present[0]
        canonical_name = normalize_name(str(value))
        identity = AssetManagerIdentity(
            key=f"source_local:{_source_normalized(canonical_name)}",
            canonical_name=canonical_name,
            dart_corp_code=None,
            aliases=(canonical_name,),
        )
        return AssetManagerResolution(
            status="source_local",
            identity=identity,
            supporting_fields=(field,),
            fallback_fields=(),
            accepted_aliases=(canonical_name,),
        )
    if len(present) == 2:
        return AssetManagerResolution(
            status="conflict",
            identity=None,
            supporting_fields=(),
            fallback_fields=tuple(field for field, _ in present),
            accepted_aliases=(),
        )
    return AssetManagerResolution(
        status="unresolved",
        identity=None,
        supporting_fields=(),
        fallback_fields=tuple(field for field, _ in present),
        accepted_aliases=(),
    )
