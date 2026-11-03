-- Drop only the two additions from ADR-0056, outside BEGIN/COMMIT.
\set ON_ERROR_STOP on

DO $$ BEGIN
    IF current_database() <> 'financial_agent_local' THEN
        RAISE EXCEPTION 'Condition index rollback requires financial_agent_local';
    END IF;
END $$;

DROP INDEX CONCURRENTLY IF EXISTS evidence.ix_evidence_observation_origin_reverse_v1;
DROP INDEX CONCURRENTLY IF EXISTS observation.ix_observation_personal_condition_metric_entity_v1;
