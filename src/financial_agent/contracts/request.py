from datetime import timedelta

from pydantic import model_validator

from .base import ContractModel, Identifier, RuntimeArtifact, UtcDateTime
from .canonical import build_request_key
from .enums import EntityResolutionStatus, InteractionMode
from .validation import require_known_ids, require_unique_ids


class Segment(ContractModel):
    segment_id: Identifier
    ordinal: int
    text: str


class NamedEntityMention(ContractModel):
    mention_id: Identifier
    segment_id: Identifier
    text: str
    expected_entity_types: tuple[Identifier, ...]
    resolution_status: EntityResolutionStatus = EntityResolutionStatus.UNRESOLVED


class ReferenceMention(ContractModel):
    mention_id: Identifier
    segment_id: Identifier
    text: str
    start_char: int
    end_char: int


class RequestContext(RuntimeArtifact):
    question_id: str
    question: str
    mode: InteractionMode = InteractionMode.COMPETITION
    segments: tuple[Segment, ...]
    named_entities: tuple[NamedEntityMention, ...] = ()
    reference_mentions: tuple[ReferenceMention, ...] = ()
    deadline_at: UtcDateTime

    @model_validator(mode="after")
    def validate_context(self) -> "RequestContext":
        segment_ids = tuple(segment.segment_id for segment in self.segments)
        require_unique_ids(segment_ids, label="segments")
        require_unique_ids(
            (
                mention.mention_id
                for mention in (*self.named_entities, *self.reference_mentions)
            ),
            label="mentions",
        )

        if tuple(segment.ordinal for segment in self.segments) != tuple(
            range(len(self.segments))
        ):
            raise ValueError("segment ordinals must match tuple order")

        all_mentions = (*self.named_entities, *self.reference_mentions)
        require_known_ids(
            (mention.segment_id for mention in all_mentions),
            segment_ids,
            label="mentions",
        )
        segments_by_id = {segment.segment_id: segment for segment in self.segments}
        for mention in self.reference_mentions:
            segment_text = segments_by_id[mention.segment_id].text
            if not 0 <= mention.start_char <= mention.end_char <= len(segment_text):
                raise ValueError("reference mention range is outside its segment")
            if segment_text[mention.start_char : mention.end_char] != mention.text:
                raise ValueError("reference mention text does not match its segment")

        if not self.question_id.strip() or not self.question.strip():
            raise ValueError("question_id and question must not be empty")
        if not self.created_at < self.deadline_at <= self.created_at + timedelta(
            seconds=55
        ):
            raise ValueError("deadline_at must be within 55 seconds of created_at")
        if self.request_key != build_request_key(
            self.question_id,
            self.question,
            self.dataset_version,
            self.schema_version,
        ):
            raise ValueError("request_key does not match request metadata")
        return self
