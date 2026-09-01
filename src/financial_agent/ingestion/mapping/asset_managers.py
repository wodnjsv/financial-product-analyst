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
    dart_corp_code: str | None,
    *aliases: str,
) -> AssetManagerIdentity:
    return AssetManagerIdentity(
        key=key,
        canonical_name=canonical_name,
        dart_corp_code=dart_corp_code,
        aliases=(canonical_name, *aliases),
    )


_MANAGERS = (
    _manager("ak_partners_asset_management", "에이케이파트너스자산운용", "00501059"),
    _manager("alliancebernstein_asset_management", "얼라이언스번스틴자산운용", "00697718"),
    _manager("alpha_asset_management", "알파자산운용", "00501545"),
    _manager("blackrock_asset_management", "블랙록자산운용", "00717580"),
    _manager("brain_asset_management", "브레인자산운용", "00826453"),
    _manager("cadian_asset_management", "카디안자산운용", "00380942"),
    _manager("cansus_asset_management", "칸서스자산운용", "00514187"),
    _manager("daol_asset_management", "다올자산운용", "00267331"),
    _manager("eugene_asset_management", "유진자산운용", "00188380"),
    _manager(
        "franklin_templeton_investment_trust_management",
        "프랭클린템플턴투자신탁운용",
        None,
    ),
    _manager("golden_bridge_asset_management", "골든브릿지자산운용", "00267322"),
    _manager("goldman_sachs_asset_management", "골드만삭스자산운용", "00331502"),
    _manager("hdc_asset_management", "에이치디씨자산운용", "00405463"),
    _manager("hyundai_investment_asset_management", "현대인베스트먼트자산운용", "00419484"),
    _manager("igis_asset_management", "이지스자산운용", "00862905"),
    _manager("koreit_asset_management", "코레이트자산운용", "00314790"),
    _manager("lazard_korea_asset_management", "라자드코리아자산운용", None),
    _manager("multi_asset_asset_management", "멀티에셋자산운용", "00241342"),
    _manager("must_asset_management", "머스트자산운용", "01107586"),
    _manager("plus_asset_management", "플러스자산운용", "00326999"),
    _manager("shinyoung_asset_management", "신영자산운용", "00251428"),
    _manager("sparx_asset_management", "스팍스자산운용", "00373784"),
    _manager("v_asset_management", "브이자산운용", "00170460"),
    _manager("vip_asset_management", "브이아이피자산운용", "00477424"),
    _manager("welcome_asset_management", "웰컴자산운용", "00647722"),
    _manager("yugyeong_psg_asset_management", "유경피에스지자산운용", "00377540"),
    _manager(
        "barings_asset_management",
        "베어링자산운용",
        "00260480",
        "Barings Asset Management Korea Limited",
    ),
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

_BY_KEY = {manager.key: manager for manager in _MANAGERS}


@dataclass(frozen=True, slots=True)
class PublicFundManagerBinding:
    source_manager_code: str
    kofia_company_code: str
    kofia_company_name: str
    identity: AssetManagerIdentity
    evidence_url: str = "https://dis.kofia.or.kr/proframeWeb/XMLSERVICES/"


def _public_fund_binding(
    source_manager_code: str,
    kofia_company_code: str,
    kofia_company_name: str,
    manager_key: str,
) -> PublicFundManagerBinding:
    return PublicFundManagerBinding(
        source_manager_code=source_manager_code,
        kofia_company_code=kofia_company_code,
        kofia_company_name=kofia_company_name,
        identity=_BY_KEY[manager_key],
    )


_PUBLIC_FUND_MANAGER_BINDINGS = tuple(
    _public_fund_binding(*values)
    for values in (
        ("00040001", "A01015", "교보악사자산운용", "kyobo_axa_asset_management"),
        ("00040004", "A01011", "대신자산운용", "daishin_asset_management"),
        ("00040005", "A01002", "하나자산운용", "hana_asset_management"),
        ("00040006", "A01024", "디비자산운용", "db_asset_management"),
        ("00040007", "A01007", "우리자산운용", "woori_asset_management"),
        ("00040010", "A01005", "삼성자산운용", "samsung_asset_management"),
        ("00040011", "A01013", "멀티에셋자산운용", "multi_asset_asset_management"),
        ("00040014", "A01017", "신영자산운용", "shinyoung_asset_management"),
        ("00040016", "A01034", "에이치디씨자산운용", "hdc_asset_management"),
        ("00040018", "A01004", "브이아이자산운용", "vi_asset_management"),
        ("00040021", "A01032", "흥국자산운용", "heungkuk_asset_management"),
        ("00040022", "A01025", "프랭클린템플턴투자신탁운용", "franklin_templeton_investment_trust_management"),
        ("00040024", "A01001", "한국투자신탁운용", "korea_investment_management"),
        ("00040026", "A01022", "유진자산운용", "eugene_asset_management"),
        ("00040027", "A01021", "한화자산운용", "hanwha_asset_management"),
        ("00040038", "A01037", "카디안자산운용", "cadian_asset_management"),
        ("00040040", "A01040", "엔에이치아문디자산운용", "nh_amundi_asset_management"),
        ("00040067", "A01018", "신한자산운용", "shinhan_asset_management"),
        ("00040087", "A01069", "케이씨지아이자산운용", "kcgi_asset_management"),
        ("00040092", "A01005", "삼성자산운용", "samsung_asset_management"),
        ("00080002", "A01055", "에이케이파트너스자산운용", "ak_partners_asset_management"),
        ("00080003", "A01056", "골든브릿지자산운용", "golden_bridge_asset_management"),
        ("00080005", "A01050", "마이다스에셋자산운용", "midas_asset_management"),
        ("00080006", "A01057", "코레이트자산운용", "koreit_asset_management"),
        ("00080007", "A01059", "골드만삭스자산운용", "goldman_sachs_asset_management"),
        ("00080008", "A01048", "미래에셋자산운용", "mirae_asset_global_investments"),
        ("00080010", "A01054", "유리자산운용", "yurie_asset_management"),
        ("00080013", "A01053", "다올자산운용", "daol_asset_management"),
        ("00080016", "A01041", "칸서스자산운용", "cansus_asset_management"),
        ("00080017", "A01052", "유경피에스지자산운용", "yugyeong_psg_asset_management"),
        ("00080018", "A01058", "플러스자산운용", "plus_asset_management"),
        ("00080019", "A01049", "베어링자산운용", "barings_asset_management"),
        ("00080021", "A01044", "한국투자밸류자산운용", "korea_investment_value_asset_management"),
        ("00080022", "A01042", "아이비케이자산운용", "ibk_asset_management"),
        ("00080026", "A01109", "스팍스자산운용", "sparx_asset_management"),
        ("00080031", "A01061", "알파자산운용", "alpha_asset_management"),
        ("00080032", "A01047", "현대인베스트먼트자산운용", "hyundai_investment_asset_management"),
        ("00080033", "A01075", "비엔케이자산운용", "bnk_asset_management"),
        ("00080034", "A01070", "블랙록자산운용", "blackrock_asset_management"),
        ("00080035", "A01072", "아이엠에셋자산운용", "im_asset_management"),
        ("00080041", "A01082", "현대자산운용", "hyundai_asset_management"),
        ("00080042", "A01074", "얼라이언스번스틴자산운용", "alliancebernstein_asset_management"),
        ("00080043", "A01068", "트러스톤자산운용", "truston_asset_management"),
        ("00080048", "A01114", "브레인자산운용", "brain_asset_management"),
        ("00080052", "A01014", "키움투자자산운용", "kiwoom_asset_management"),
        ("00080056", "A01071", "라자드코리아자산운용", "lazard_korea_asset_management"),
        ("00080061", "A01005", "삼성자산운용", "samsung_asset_management"),
        ("00080062", "A01092", "이지스자산운용", "igis_asset_management"),
        ("00080086", "A01067", "에셋플러스자산운용", "assetplus_asset_management"),
        ("00080087", "A01020", "브이자산운용", "v_asset_management"),
        ("00080127", "A01182", "머스트자산운용", "must_asset_management"),
        ("00080135", "A01197", "삼성액티브자산운용", "samsung_active_asset_management"),
        ("00080156", "A01056", "골든브릿지자산운용", "golden_bridge_asset_management"),
        ("00080162", "A01132", "디에스자산운용", "ds_asset_management"),
        ("00080208", "A01079", "웰컴자산운용", "welcome_asset_management"),
        ("00080248", "A01158", "타임폴리오자산운용", "timefolio_asset_management"),
        ("00080359", "A01154", "더제이자산운용", "the_j_asset_management"),
        ("00080368", "A01266", "브이아이피자산운용", "vip_asset_management"),
        ("00130026", "A01070", "블랙록자산운용", "blackrock_asset_management"),
    )
)
_PUBLIC_FUND_BINDING_BY_CODE = {
    binding.source_manager_code: binding
    for binding in _PUBLIC_FUND_MANAGER_BINDINGS
}
if len(_PUBLIC_FUND_BINDING_BY_CODE) != len(_PUBLIC_FUND_MANAGER_BINDINGS):
    raise RuntimeError("public-fund manager source codes must be unique")

_PUBLIC_FUND_GROUP_MANAGERS = {
    ("032280034925", "00040024"): _BY_KEY["korea_investment_management"],
    ("032280034925", "00040105"): _BY_KEY["korea_investment_management"],
    ("032530069031", "00080019"): _BY_KEY["barings_asset_management"],
    ("032530069031", "00080159"): _BY_KEY["barings_asset_management"],
    ("034790011100", "00080151"): _BY_KEY["the_j_asset_management"],
    ("034790011100", "00080359"): _BY_KEY["the_j_asset_management"],
    ("2000102M9920", "00080134"): _BY_KEY[
        "samsung_active_asset_management"
    ],
    ("2000102M9920", "00080135"): _BY_KEY[
        "samsung_active_asset_management"
    ],
}


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


def resolve_public_fund_asset_manager(
    representative_fund_id: object,
    manager_code: object,
) -> AssetManagerIdentity | None:
    """Resolve reviewed public-offering codes or bounded group exceptions."""
    source_code = _source_normalized(manager_code).upper()
    binding = _PUBLIC_FUND_BINDING_BY_CODE.get(source_code)
    if binding is not None:
        return binding.identity
    key = (
        _source_normalized(representative_fund_id).upper(),
        source_code,
    )
    return _PUBLIC_FUND_GROUP_MANAGERS.get(key)


def public_fund_manager_binding(
    manager_code: object,
) -> PublicFundManagerBinding | None:
    return _PUBLIC_FUND_BINDING_BY_CODE.get(
        _source_normalized(manager_code).upper()
    )


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
