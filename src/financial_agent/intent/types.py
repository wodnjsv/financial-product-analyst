from enum import Enum

from financial_agent.contracts.enums import IntentType, ProductFamily


class ChoiceState(str, Enum):
    SELECTED = "selected"
    AMBIGUOUS = "ambiguous"
    UNMAPPED = "unmapped"


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNMAPPED = "unmapped"
    CONTEXT_UNRESOLVED = "context_unresolved"


class SemanticCoverageState(str, Enum):
    COVERED = "covered"
    PARTIAL = "partial"
    UNMAPPED = "unmapped"


class SemanticCoverageReason(str, Enum):
    NONE = "none"
    LEXICAL_OOD = "lexical_ood"
    DOMAIN_OOD = "domain_ood"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    MISSING_CRITICAL_SEMANTIC = "missing_critical_semantic"


class ReferenceForm(str, Enum):
    DEMONSTRATIVE = "demonstrative"
    ZERO_ANAPHORA = "zero_anaphora"
    LEXICAL_ANAPHOR = "lexical_anaphor"
    BRIDGING = "bridging"
    DISCOURSE_DEIXIS = "discourse_deixis"


class ReferenceTargetKind(str, Enum):
    ENTITY = "entity"
    RESULT_SET = "result_set"
    METRIC_VALUE = "metric_value"
    RELATED_ENTITY = "related_entity"
    PRIOR_OPERATION = "prior_operation"
    EVIDENCE_RECORDS = "evidence_records"
    EXCLUSION_SET = "exclusion_set"


class SourceRole(str, Enum):
    CANDIDATES = "candidates"
    SELECTED_PRODUCT = "selected_product"
    TOP_K_PRODUCTS = "top_k_products"
    EXCLUDED_PRODUCTS = "excluded_products"
    METRIC_VALUE = "metric_value"
    RELATION_TARGET = "relation_target"
    COMPARISON_DECISION = "comparison_decision"
    EVIDENCE_RECORDS = "evidence_records"


class Selector(str, Enum):
    ALL = "all"
    FIRST = "first"
    LAST = "last"
    RANK_POSITION = "rank_position"
    TOP_N = "top_n"
    FORMER = "former"
    LATTER = "latter"
    EACH = "each"
    REMAINING = "remaining"


class ContextLinkType(str, Enum):
    CONSUME_SINGLE_RESULT = "consume_single_result"
    CONSUME_RESULT_SET = "consume_result_set"
    DERIVE_ENTITY = "derive_entity"
    DERIVE_METRIC_VALUE = "derive_metric_value"
    INHERIT_SCOPE = "inherit_scope"
    REPLACE_SLOT = "replace_slot"
    REFER_EXCLUSION_SET = "refer_exclusion_set"
    REFER_EVIDENCE = "refer_evidence"


class SlotMutationKind(str, Enum):
    CARRYOVER = "carryover"
    UPDATE = "update"
    DELETE = "delete"
    DONTCARE = "dontcare"


class SlotKind(str, Enum):
    ENTITY = "entity"
    METRIC = "metric"
    FILTER_VALUE = "filter_value"
    FILTER_OPERATOR = "filter_operator"
    PERIOD = "period"
    UNIT = "unit"
    CURRENCY = "currency"
    SORT_KEY = "sort_key"
    SORT_DIRECTION = "sort_direction"
    RESULT_LIMIT = "result_limit"
    DATE_SCOPE = "date_scope"
    RELATION = "relation"
    COMPARISON_BASIS = "comparison_basis"
    SIMILARITY_ANCHOR = "similarity_anchor"
    DOCUMENT_TOPIC = "document_topic"


class SemanticTag(str, Enum):
    CROSS_FAMILY = "CROSS_FAMILY"
    MULTI_STEP = "MULTI_STEP"
    CONTEXT_DEPENDENT = "CONTEXT_DEPENDENT"
    RELATIONSHIP_REQUIRED = "RELATIONSHIP_REQUIRED"
    DOCUMENT_GROUNDED = "DOCUMENT_GROUNDED"
    TEMPORAL = "TEMPORAL"
    NORMALIZATION_REQUIRED = "NORMALIZATION_REQUIRED"
    MISSINGNESS_SENSITIVE = "MISSINGNESS_SENSITIVE"
    OPERATIONAL_STATUS = "OPERATIONAL_STATUS"
    FUTURE_FORECAST = "FUTURE_FORECAST"
    PERSONALIZED_ADVICE = "PERSONALIZED_ADVICE"
    ORDER_EXECUTION = "ORDER_EXECUTION"
    REALTIME_REQUIRED = "REALTIME_REQUIRED"
