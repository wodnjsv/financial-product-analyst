from enum import Enum


class InteractionMode(str, Enum):
    COMPETITION = "competition"


class EntityResolutionStatus(str, Enum):
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    INVALID_AT_CUTOFF = "invalid_at_cutoff"


class IntentType(str, Enum):
    LOOKUP = "lookup"
    SCREEN = "screen"
    RANK = "rank"
    COMPARE = "compare"
    AGGREGATE = "aggregate"
    CALCULATE = "calculate"
    SIMILAR = "similar"
    EXPLAIN = "explain"


class ProductFamily(str, Enum):
    DOMESTIC_BOND = "domestic_bond"
    DOMESTIC_ETF = "domestic_etf"
    OVERSEAS_ETF = "overseas_etf"
    PUBLIC_FUND = "public_fund"


class SubtaskImportance(str, Enum):
    CRITICAL = "critical"
    REQUIRED_INDEPENDENT = "required_independent"
    OPTIONAL = "optional"


class InitialAnswerability(str, Enum):
    SUPPORTED = "supported"
    REQUIRES_NORMALIZATION = "requires_normalization"
    REQUIRES_ADDITIONAL_DATA = "requires_additional_data"
    UNSUPPORTED = "unsupported"


class Capability(str, Enum):
    RDB_LOOKUP = "rdb_lookup"
    GRAPH_TRAVERSAL = "graph_traversal"
    KEYWORD_SEARCH = "keyword_search"
    VECTOR_SEARCH = "vector_search"
    FINANCIAL_CALCULATION = "financial_calculation"
    RANKING = "ranking"
    SIMILARITY = "similarity"
    COMPARISON = "comparison"


class ToolStatus(str, Enum):
    SUCCESS = "success"
    EMPTY = "empty"
    UNSUPPORTED = "unsupported"
    INVALID_INPUT = "invalid_input"
    TIMEOUT = "timeout"
    TRANSIENT_ERROR = "transient_error"
    PERMANENT_ERROR = "permanent_error"


class ResultType(str, Enum):
    ROW_SET = "row_set"
    SCALAR = "scalar"
    ENTITY_REF = "entity_ref"
    RELATION_PATH = "relation_path"
    CALCULATION = "calculation"
    COMPARISON_DECISION = "comparison_decision"


class ExecutionOutcome(str, Enum):
    COMPLETED = "completed"
    COMPLETED_WITH_FAILURES = "completed_with_failures"
    FAILED = "failed"


class VerificationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class AnswerDisposition(str, Enum):
    ANSWER = "answer"
    PARTIAL = "partial"
    LIMITATION = "limitation"
    ABSTAIN = "abstain"


class EvidenceKind(str, Enum):
    OBSERVATION = "observation"
    RELATION = "relation"
    DOCUMENT_SPAN = "document_span"
    QUERY_SCOPE = "query_scope"
    EXCLUSION = "exclusion"
    POLICY = "policy"


class CutoffStatus(str, Enum):
    ELIGIBLE = "eligible"
    AFTER_CUTOFF = "after_cutoff"
    UNKNOWN_VINTAGE = "unknown_vintage"
    INAPPLICABLE = "inapplicable"


class CalculationType(str, Enum):
    CONVERSION = "conversion"
    RETURN = "return"
    RANKING = "ranking"
    AGGREGATION = "aggregation"
    COMPARISON = "comparison"
    SIMILARITY = "similarity"


class ClaimType(str, Enum):
    DIRECT_FACT = "direct_fact"
    RELATION = "relation"
    DERIVED_METRIC = "derived_metric"
    RANK = "rank"
    SIMILARITY = "similarity"
    NO_MATCH = "no_match"
    DATA_LIMITATION = "data_limitation"
    POLICY_BOUNDARY = "policy_boundary"


class SupportKind(str, Enum):
    DIRECT = "direct"
    CALCULATION = "calculation"
    SCOPE = "scope"
    EXCLUSION = "exclusion"
    POLICY = "policy"


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    NOT_APPLICABLE = "not_applicable"


class CheckTargetType(str, Enum):
    CLAIM = "claim"
    EVIDENCE = "evidence"
    CALCULATION = "calculation"
    SUBTASK = "subtask"


class Repairability(str, Enum):
    NONE = "none"
    LEDGER_REBUILD = "ledger_rebuild"
    LLM_REPAIR = "llm_repair"


class BlockType(str, Enum):
    SUMMARY = "summary"
    FACT_LIST = "fact_list"
    TABLE = "table"
    COMPARISON = "comparison"
    CALCULATION = "calculation"
    LIMITATION = "limitation"
    ABSTENTION = "abstention"


class ResultShape(str, Enum):
    SINGLE_VALUE = "single_value"
    PRODUCT_LIST = "product_list"
    TOP_K = "top_k"
    COMPARISON_TABLE = "comparison_table"
    EXPLANATION = "explanation"


class ReferenceTargetKind(str, Enum):
    ENTITY_MENTION = "entity_mention"
    BINDING = "binding"


class ReferenceMentionType(str, Enum):
    EXPLICIT = "explicit"
    ELLIPSIS = "ellipsis"


class Cardinality(str, Enum):
    ONE = "one"
    MANY = "many"
