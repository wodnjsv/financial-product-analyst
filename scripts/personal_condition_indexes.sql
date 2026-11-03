-- Approved local maintenance only; run with psql outside BEGIN/COMMIT.
-- Application fa_runtime permissions and all source rows remain unchanged.
\set ON_ERROR_STOP on

DO $$ BEGIN
    IF current_database() <> 'financial_agent_local' THEN
        RAISE EXCEPTION 'Condition indexes require financial_agent_local';
    END IF;
END $$;

CREATE INDEX CONCURRENTLY ix_observation_personal_condition_metric_entity_v1
ON observation.observation_record
    (dataset_version, metric_id, metric_definition_version, entity_id)
WHERE metric_definition_version = '2' AND metric_id IN (
    'organizer.pref02n001.investment_region',
    'organizer.pref02n001.investment_asset_type',
    'organizer.pref02n001.total_fee_rate',
    'organizer.pref02n001.aum',
    'organizer.pref02n001.product_type',
    'organizer.prbd01n001.currency',
    'organizer.prbd01n001.credit_grade_representative',
    'organizer.prbd01n001.maturity_date',
    'organizer.prbd01n001.remaining_days'
);

CREATE INDEX CONCURRENTLY ix_evidence_observation_origin_reverse_v1
ON evidence.evidence_observation_origin
    (dataset_version, observation_id, evidence_id);
