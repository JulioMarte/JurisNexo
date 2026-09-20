--
-- PostgreSQL database dump
--


-- Dumped from database version 17.11 (Debian 17.11-1.pgdg12+2)
-- Dumped by pg_dump version 17.11 (Debian 17.11-1.pgdg12+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: corpus; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA corpus;


--
-- Name: SCHEMA corpus; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA corpus IS 'JurisNexo canonical legal corpus. Law-owned vocabularies use extensible concept rows; CHECK enums are reserved for system/structural mechanics.';


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'Legacy JurisNexo prototype objects may remain here for compatibility/forensics, but browser roles are quarantined. New product data belongs in explicit private schemas such as corpus.';


--
-- Name: canonicalize_norm_claim(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.canonicalize_norm_claim() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE c corpus.legal_norm_claims%ROWTYPE;
        BEGIN
          IF NEW.norm_claim_id IS NULL THEN
            INSERT INTO corpus.legal_norm_claims(scope_id,proposition_id,jurisdiction_code,norm_kind,valid_from,valid_to)
            VALUES(NEW.scope_id,NEW.proposition_id,NEW.jurisdiction_code,NEW.norm_kind,NEW.valid_from,NEW.valid_to)
            ON CONFLICT ON CONSTRAINT legal_norm_claims_identity DO UPDATE SET proposition_id=EXCLUDED.proposition_id
            RETURNING * INTO c;
            NEW.norm_claim_id := c.id;
          ELSE
            SELECT * INTO c FROM corpus.legal_norm_claims WHERE id=NEW.norm_claim_id;
            IF c.id IS NULL OR c.scope_id <> NEW.scope_id THEN RAISE EXCEPTION 'unknown or cross-scope legal norm claim' USING ERRCODE='23503'; END IF;
            NEW.proposition_id:=c.proposition_id; NEW.jurisdiction_code:=c.jurisdiction_code; NEW.norm_kind:=c.norm_kind;
            NEW.valid_from:=c.valid_from; NEW.valid_to:=c.valid_to;
          END IF; RETURN NEW;
        END $$;


--
-- Name: canonicalize_norm_source_scope(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.canonicalize_norm_source_scope() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            SELECT a.scope_id INTO NEW.assertion_scope_id
            FROM corpus.legal_norm_assertions a
            WHERE a.id = NEW.norm_assertion_id;
            IF NEW.assertion_scope_id IS NULL THEN
                RAISE EXCEPTION 'unknown legal norm assertion'
                    USING ERRCODE = '23503';
            END IF;
            NEW.scope_id := NEW.assertion_scope_id;
            RETURN NEW;
        END $$;


--
-- Name: canonicalize_relation_assertion_scope(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.canonicalize_relation_assertion_scope() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            SELECT r.scope_id INTO NEW.scope_id
            FROM corpus.legal_relation_identities r
            WHERE r.id = NEW.relation_identity_id;
            IF NEW.scope_id IS NULL THEN
                RAISE EXCEPTION 'unknown legal relation identity'
                    USING ERRCODE = '23503';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: canonicalize_relation_identity_scope(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.canonicalize_relation_identity_scope() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            SELECT d.scope_id INTO NEW.scope_id
            FROM corpus.legal_documents d
            WHERE d.id = NEW.source_document_id;
            IF NEW.scope_id IS NULL THEN
                RAISE EXCEPTION 'unknown source legal document'
                    USING ERRCODE = '23503';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: ensure_authority_legal_entity(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.ensure_authority_legal_entity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE k text;
        BEGIN
          IF NEW.legal_entity_id IS NULL THEN
            k := CASE WHEN NEW.authority_type='court' THEN 'court' WHEN NEW.authority_type='international_body' THEN 'international_body' ELSE 'public_body' END;
            INSERT INTO corpus.legal_entities(scope_id,entity_kind,canonical_name,normalized_name,country_code,identity_status)
            VALUES(NEW.scope_id,k,NEW.canonical_name,NEW.normalized_name,NEW.country_code,NEW.identity_status) RETURNING id INTO NEW.legal_entity_id;
          END IF; RETURN NEW;
        END $$;


--
-- Name: ensure_court_legal_entity(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.ensure_court_legal_entity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF NEW.legal_entity_id IS NULL THEN
            INSERT INTO corpus.legal_entities(scope_id,entity_kind,canonical_name,country_code,identity_status)
            VALUES('00000000-0000-0000-0000-000000000001'::uuid,'court',NEW.name,NEW.country_code,'canonical') RETURNING id INTO NEW.legal_entity_id;
          END IF; RETURN NEW;
        END $$;


--
-- Name: ensure_officer_legal_entity(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.ensure_officer_legal_entity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF NEW.legal_entity_id IS NULL THEN
            INSERT INTO corpus.legal_entities(scope_id,entity_kind,canonical_name,normalized_name,identity_status)
            VALUES(NEW.scope_id,'person',NEW.display_name,NEW.normalized_name,NEW.identity_status) RETURNING id INTO NEW.legal_entity_id;
          END IF; RETURN NEW;
        END $$;


--
-- Name: ensure_participant_legal_entity(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.ensure_participant_legal_entity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE k text;
        BEGIN
          IF NEW.legal_entity_id IS NULL THEN
            k := CASE NEW.participant_kind WHEN 'person' THEN 'person' WHEN 'organization' THEN 'organization' WHEN 'public_body' THEN 'public_body' ELSE 'other' END;
            INSERT INTO corpus.legal_entities(scope_id,entity_kind,canonical_name,normalized_name,identity_status)
            VALUES(NEW.scope_id,k,NEW.display_name,NEW.normalized_name,NEW.identity_status) RETURNING id INTO NEW.legal_entity_id;
          END IF; RETURN NEW;
        END $$;


--
-- Name: reject_decision_state_knowledge_overlap(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_decision_state_knowledge_overlap() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          PERFORM pg_advisory_xact_lock(hashtextextended(concat_ws(':',NEW.decision_id,NEW.state_concept_id),3101));
          IF EXISTS (SELECT 1 FROM corpus.decision_legal_states s WHERE s.id<>NEW.id AND s.decision_id=NEW.decision_id AND s.state_concept_id=NEW.state_concept_id AND tstzrange(s.known_from,s.known_to,'[)') && tstzrange(NEW.known_from,NEW.known_to,'[)')) THEN
            RAISE EXCEPTION 'overlapping decision legal-state knowledge interval' USING ERRCODE='23514';
          END IF; RETURN NEW;
        END $$;


--
-- Name: reject_decision_status_knowledge_overlap(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_decision_status_knowledge_overlap() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(
                concat_ws(':', NEW.case_id, NEW.event_type_concept_id, NEW.occurred_on),
                2805
            ));
            IF EXISTS (
                SELECT 1 FROM corpus.decision_legal_status_events k
                WHERE k.id <> NEW.id
                  AND k.case_id = NEW.case_id
                  AND k.event_type_concept_id = NEW.event_type_concept_id
                  AND k.occurred_on IS NOT DISTINCT FROM NEW.occurred_on
                  AND tstzrange(k.known_from, k.known_to, '[)')
                      && tstzrange(NEW.known_from, NEW.known_to, '[)')
            ) THEN
                RAISE EXCEPTION 'overlapping decision-event knowledge interval'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: reject_entity_resolution_knowledge_overlap(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_entity_resolution_knowledge_overlap() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(NEW.observed_entity_id::text,4501)
            );
            IF NEW.verification_status NOT IN ('rejected','superseded')
               AND EXISTS (
                   SELECT 1 FROM corpus.entity_identity_resolutions r
                   WHERE r.id<>NEW.id
                     AND r.observed_entity_id=NEW.observed_entity_id
                     AND r.verification_status NOT IN ('rejected','superseded')
                     AND tstzrange(r.known_from,r.known_to,'[)')
                         && tstzrange(NEW.known_from,NEW.known_to,'[)')
               ) THEN
                RAISE EXCEPTION
                    'overlapping canonical entity resolution knowledge interval'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: reject_factual_proposition_identity_mutation(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_factual_proposition_identity_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.kind_concept_id IS DISTINCT FROM OLD.kind_concept_id
               OR NEW.canonical_text IS DISTINCT FROM OLD.canonical_text
               OR NEW.normalized_text IS DISTINCT FROM OLD.normalized_text
               OR NEW.assertion_kind IS DISTINCT FROM OLD.assertion_kind THEN
                RAISE EXCEPTION
                    'factual proposition identity is immutable; supersede it with a new proposition'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: reject_instrument_knowledge_overlap(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_instrument_knowledge_overlap() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(NEW.instrument_version_id::text, 2025)
            );
            IF EXISTS (
                SELECT 1 FROM corpus.legal_instrument_version_knowledge k
                WHERE k.instrument_version_id = NEW.instrument_version_id
                  AND k.id <> NEW.id
                  AND tstzrange(k.known_from, k.known_to, '[)')
                      && tstzrange(NEW.known_from, NEW.known_to, '[)')
            ) THEN
                RAISE EXCEPTION 'overlapping instrument knowledge time'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: reject_judicial_authority_knowledge_overlap(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_judicial_authority_knowledge_overlap() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(
                concat_ws(':',NEW.decision_id,NEW.proposition_id,
                    NEW.authority_effect_concept_id,NEW.jurisdiction_code,
                    NEW.court_id,NEW.legal_matter_concept_id),3501));
            IF EXISTS (
                SELECT 1 FROM corpus.judicial_authority_assertions k
                WHERE k.id<>NEW.id
                  AND k.decision_id=NEW.decision_id
                  AND k.proposition_id IS NOT DISTINCT FROM NEW.proposition_id
                  AND k.authority_effect_concept_id=NEW.authority_effect_concept_id
                  AND k.jurisdiction_code IS NOT DISTINCT FROM NEW.jurisdiction_code
                  AND k.court_id IS NOT DISTINCT FROM NEW.court_id
                  AND k.legal_matter_concept_id
                      IS NOT DISTINCT FROM NEW.legal_matter_concept_id
                  AND tstzrange(k.known_from,k.known_to,'[)')
                      && tstzrange(NEW.known_from,NEW.known_to,'[)')
            ) THEN
                RAISE EXCEPTION 'overlapping judicial-authority knowledge interval'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: reject_legal_concept_hierarchy_cycle(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_legal_concept_hierarchy_cycle() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE normalized_source uuid;
        DECLARE normalized_target uuid;
        BEGIN
            IF NEW.relation_type NOT IN ('broader','narrower') THEN
                RETURN NEW;
            END IF;

            IF NEW.relation_type='broader' THEN
                normalized_source := NEW.source_concept_id;
                normalized_target := NEW.target_concept_id;
            ELSE
                normalized_source := NEW.target_concept_id;
                normalized_target := NEW.source_concept_id;
            END IF;

            IF EXISTS (
                WITH RECURSIVE walk(id) AS (
                    SELECT normalized_target
                    UNION
                    SELECT CASE
                        WHEN e.relation_type='broader' THEN e.target_concept_id
                        ELSE e.source_concept_id
                    END
                    FROM corpus.legal_concept_edges e
                    JOIN walk w ON (
                        (e.relation_type='broader' AND e.source_concept_id=w.id)
                        OR (e.relation_type='narrower' AND e.target_concept_id=w.id)
                    )
                    WHERE e.id<>NEW.id
                )
                SELECT 1 FROM walk WHERE id=normalized_source
            ) THEN
                RAISE EXCEPTION 'legal concept hierarchy cycle detected'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: reject_legal_issue_identity_mutation(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_legal_issue_identity_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.canonical_question IS DISTINCT FROM OLD.canonical_question
               OR NEW.normalized_question IS DISTINCT FROM OLD.normalized_question
               OR NEW.assertion_kind IS DISTINCT FROM OLD.assertion_kind THEN
                RAISE EXCEPTION
                    'legal issue identity is immutable; supersede it with a new issue'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: reject_legal_proposition_identity_mutation(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_legal_proposition_identity_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.proposition_type IS DISTINCT FROM OLD.proposition_type
               OR NEW.canonical_text IS DISTINCT FROM OLD.canonical_text
               OR NEW.normalized_text IS DISTINCT FROM OLD.normalized_text
               OR NEW.assertion_kind IS DISTINCT FROM OLD.assertion_kind THEN
                RAISE EXCEPTION 'legal proposition identity is immutable; create a new proposition'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: reject_matter_concept_cycle(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_matter_concept_cycle() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended('legal-matter-taxonomy', 0));
            IF NEW.relation_type IN ('broader', 'part_of') AND EXISTS (
                WITH RECURSIVE ancestors(id) AS (
                    SELECT NEW.broader_concept_id
                    UNION
                    SELECT edge.broader_concept_id
                    FROM corpus.legal_matter_concept_edges edge
                    JOIN ancestors a ON edge.narrower_concept_id = a.id
                    WHERE edge.relation_type IN ('broader', 'part_of')
                )
                SELECT 1 FROM ancestors WHERE id = NEW.narrower_concept_id
            ) THEN
                RAISE EXCEPTION 'legal matter taxonomy cycle' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: reject_norm_claim_knowledge_overlap(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_norm_claim_knowledge_overlap() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(NEW.norm_claim_id::text, 3201)
            );
            IF EXISTS (
                SELECT 1
                FROM corpus.legal_norm_assertions a
                WHERE a.id <> NEW.id
                  AND a.norm_claim_id = NEW.norm_claim_id
                  AND tstzrange(a.known_from, a.known_to, '[)')
                      && tstzrange(NEW.known_from, NEW.known_to, '[)')
            ) THEN
                RAISE EXCEPTION 'overlapping legal norm claim knowledge interval'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: reject_procedure_concept_cycle(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_procedure_concept_cycle() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended('procedure-taxonomy', 0));
            IF NEW.relation_type IN ('broader', 'part_of') AND EXISTS (
                WITH RECURSIVE ancestors(id) AS (
                    SELECT NEW.broader_concept_id
                    UNION
                    SELECT edge.broader_concept_id
                    FROM corpus.procedure_concept_edges edge
                    JOIN ancestors a ON edge.narrower_concept_id = a.id
                    WHERE edge.relation_type IN ('broader', 'part_of')
                )
                SELECT 1 FROM ancestors WHERE id = NEW.narrower_concept_id
            ) THEN
                RAISE EXCEPTION 'procedure taxonomy cycle' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: reject_provision_knowledge_overlap(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_provision_knowledge_overlap() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(NEW.provision_version_id::text, 2025)
            );
            IF EXISTS (
                SELECT 1 FROM corpus.legal_provision_version_knowledge k
                WHERE k.provision_version_id = NEW.provision_version_id
                  AND k.id <> NEW.id
                  AND tstzrange(k.known_from, k.known_to, '[)')
                      && tstzrange(NEW.known_from, NEW.known_to, '[)')
            ) THEN
                RAISE EXCEPTION 'overlapping provision knowledge time'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: reject_relation_knowledge_overlap(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_relation_knowledge_overlap() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(NEW.relation_identity_id::text, 2802)
            );
            IF EXISTS (
                SELECT 1 FROM corpus.legal_relation_assertions k
                WHERE k.relation_identity_id = NEW.relation_identity_id
                  AND k.id <> NEW.id
                  AND tstzrange(k.known_from, k.known_to, '[)')
                      && tstzrange(NEW.known_from, NEW.known_to, '[)')
            ) THEN
                RAISE EXCEPTION 'overlapping knowledge interval in legal_relation_assertions'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: reject_treatment_knowledge_overlap(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.reject_treatment_knowledge_overlap() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(
                concat_ws(':',NEW.source_case_id,NEW.target_case_id,
                    NEW.treatment_type,NEW.legal_issue_id,
                    NEW.source_proposition_id,NEW.target_proposition_id),
                4701
            ));
            IF EXISTS (
                SELECT 1
                FROM corpus.legal_treatment_assertions k
                WHERE k.id<>NEW.id
                  AND k.source_case_id=NEW.source_case_id
                  AND k.target_case_id=NEW.target_case_id
                  AND k.treatment_type=NEW.treatment_type
                  AND k.legal_issue_id IS NOT DISTINCT FROM NEW.legal_issue_id
                  AND k.source_proposition_id
                      IS NOT DISTINCT FROM NEW.source_proposition_id
                  AND k.target_proposition_id
                      IS NOT DISTINCT FROM NEW.target_proposition_id
                  AND tstzrange(k.known_from,k.known_to,'[)')
                      && tstzrange(NEW.known_from,NEW.known_to,'[)')
            ) THEN
                RAISE EXCEPTION
                    'overlapping judicial treatment knowledge interval'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: require_verified_entity_identity_evidence(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.require_verified_entity_identity_evidence() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.verification_status='verified'
               AND NOT EXISTS (
                   SELECT 1 FROM corpus.entity_identity_assertion_evidence e
                   WHERE e.assertion_id=NEW.id AND e.scope_id=NEW.scope_id
               ) THEN
                RAISE EXCEPTION
                    'verified entity identity assertion requires persisted evidence'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: require_verified_fact_evidence(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.require_verified_fact_evidence() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.verification_status='verified'
               AND NOT EXISTS (
                   SELECT 1 FROM corpus.factual_proposition_evidence e
                   WHERE e.factual_proposition_id=NEW.id
                     AND e.scope_id=NEW.scope_id
                     AND (
                         e.case_page_id IS NOT NULL
                         OR e.artifact_page_id IS NOT NULL
                         OR btrim(coalesce(e.exact_excerpt,'')) <> ''
                     )
               ) THEN
                RAISE EXCEPTION
                    'verified factual proposition requires page/passage or exact-excerpt evidence'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: require_verified_issue_evidence(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.require_verified_issue_evidence() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.verification_status='verified'
               AND NOT EXISTS (
                   SELECT 1 FROM corpus.legal_issue_evidence e
                   WHERE e.issue_id=NEW.id
                     AND e.scope_id=NEW.scope_id
                     AND (
                         e.case_page_id IS NOT NULL
                         OR e.artifact_page_id IS NOT NULL
                         OR btrim(coalesce(e.exact_excerpt,'')) <> ''
                     )
               ) THEN
                RAISE EXCEPTION
                    'verified legal issue requires page/passage or exact-excerpt evidence'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: validate_decision_state_concept(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.validate_decision_state_concept() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE concept_code text;
        BEGIN
            SELECT code INTO concept_code
            FROM corpus.decision_state_concepts
            WHERE id = NEW.state_concept_id;
            IF concept_code IN (
                'vacated', 'annulled', 'reversed', 'partially_reversed'
            ) THEN
                RAISE EXCEPTION
                    'point-in-time judicial acts cannot be persisted as decision legal states'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: validate_disposition_action_argument_context(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.validate_disposition_action_argument_context() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE source_decision uuid;
        DECLARE target_proceeding uuid;
        BEGIN
            SELECT case_id INTO source_decision
            FROM corpus.judicial_decision_dispositions
            WHERE id=NEW.disposition_id AND scope_id=NEW.scope_id;
            IF source_decision IS NULL THEN
                RAISE EXCEPTION 'unknown or cross-scope judicial disposition'
                    USING ERRCODE='23503';
            END IF;

            IF NEW.object_type='claim' THEN
                SELECT proceeding_id INTO target_proceeding
                FROM corpus.legal_claims
                WHERE id=NEW.target_claim_id AND scope_id=NEW.scope_id;
                IF target_proceeding IS NULL OR NOT EXISTS (
                    SELECT 1 FROM corpus.proceeding_decisions pd
                    WHERE pd.scope_id=NEW.scope_id
                      AND pd.proceeding_id=target_proceeding
                      AND pd.case_id=source_decision
                      AND pd.verification_status NOT IN ('rejected','superseded')
                ) THEN
                    RAISE EXCEPTION
                        'disposition action cannot use a claim from an unrelated proceeding'
                        USING ERRCODE='23514';
                END IF;
            ELSIF NEW.object_type='party_role' THEN
                SELECT proceeding_id INTO target_proceeding
                FROM corpus.proceeding_party_roles
                WHERE id=NEW.target_party_role_id AND scope_id=NEW.scope_id;
                IF target_proceeding IS NULL OR NOT EXISTS (
                    SELECT 1 FROM corpus.proceeding_decisions pd
                    WHERE pd.scope_id=NEW.scope_id
                      AND pd.proceeding_id=target_proceeding
                      AND pd.case_id=source_decision
                      AND pd.verification_status NOT IN ('rejected','superseded')
                ) THEN
                    RAISE EXCEPTION
                        'disposition action cannot use a party role from an unrelated proceeding'
                        USING ERRCODE='23514';
                END IF;
            ELSIF NEW.object_type='proposition' THEN
                IF EXISTS (
                    SELECT 1 FROM corpus.legal_proposition_subjects s
                    WHERE s.scope_id=NEW.scope_id
                      AND s.proposition_id=NEW.target_proposition_id
                      AND s.subject_type='judicial_decision'
                ) AND NOT EXISTS (
                    SELECT 1 FROM corpus.legal_proposition_subjects s
                    WHERE s.scope_id=NEW.scope_id
                      AND s.proposition_id=NEW.target_proposition_id
                      AND s.subject_type='judicial_decision'
                      AND s.judicial_decision_id=source_decision
                ) THEN
                    RAISE EXCEPTION
                        'disposition action proposition belongs to another decision'
                        USING ERRCODE='23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: validate_entity_identity_resolution(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.validate_entity_identity_resolution() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE assertion_relation text;
        BEGIN
            SELECT c.code INTO assertion_relation
            FROM corpus.entity_identity_assertions a
            JOIN corpus.legal_concepts c ON c.id=a.relation_concept_id
            WHERE a.id=NEW.supporting_assertion_id
              AND a.scope_id=NEW.scope_id
              AND a.observed_entity_id=NEW.observed_entity_id
              AND a.candidate_entity_id=NEW.canonical_entity_id
              AND a.verification_status='verified';

            IF assertion_relation IS NULL OR assertion_relation NOT IN (
                'same_as','merged_into'
            ) THEN
                RAISE EXCEPTION
                    'entity identity resolution requires a matching verified conclusive identity assertion'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: validate_proceeding_relation_symmetry(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.validate_proceeding_relation_symmetry() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE symmetric_relation boolean;
        BEGIN
            SELECT is_symmetric INTO symmetric_relation
            FROM corpus.proceeding_relation_concepts WHERE id=NEW.relation_concept_id;
            IF symmetric_relation AND NEW.source_proceeding_id::text > NEW.target_proceeding_id::text THEN
                RAISE EXCEPTION 'symmetric proceeding relations must use canonical UUID ordering' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: validate_treatment_proposition_membership(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.validate_treatment_proposition_membership() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.source_proposition_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM corpus.legal_proposition_subjects s
                WHERE s.proposition_id = NEW.source_proposition_id
                  AND s.subject_type = 'judicial_decision'
                  AND s.judicial_decision_id = NEW.source_case_id
            ) THEN RAISE EXCEPTION 'source proposition does not belong to source judicial decision' USING ERRCODE='23514'; END IF;
            IF NEW.target_proposition_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM corpus.legal_proposition_subjects s
                WHERE s.proposition_id = NEW.target_proposition_id
                  AND s.subject_type = 'judicial_decision'
                  AND s.judicial_decision_id = NEW.target_case_id
            ) THEN RAISE EXCEPTION 'target proposition does not belong to target judicial decision' USING ERRCODE='23514'; END IF;
            IF NEW.evidence_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM corpus.legal_proposition_evidence e
                WHERE e.id = NEW.evidence_id AND e.source_case_id = NEW.source_case_id
            ) THEN RAISE EXCEPTION 'treatment evidence must belong to source judicial decision' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;


--
-- Name: validate_verified_norm_sources(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.validate_verified_norm_sources() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.verification_status = 'verified' AND NOT EXISTS (
                SELECT 1 FROM corpus.legal_norm_sources s
                WHERE s.norm_assertion_id = NEW.id AND s.verification_status = 'verified'
            ) THEN
                RAISE EXCEPTION 'verified legal norm assertion requires verified source evidence' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;


--
-- Name: validate_vote_stance_target(); Type: FUNCTION; Schema: corpus; Owner: -
--

CREATE FUNCTION corpus.validate_vote_stance_target() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.scope_type = 'proposition'
               AND EXISTS (
                    SELECT 1
                    FROM corpus.legal_proposition_subjects s
                    WHERE s.proposition_id = NEW.proposition_id
                      AND s.scope_id = NEW.scope_id
                      AND s.subject_type = 'judicial_decision'
               )
               AND NOT EXISTS (
                    SELECT 1
                    FROM corpus.legal_proposition_subjects s
                    WHERE s.proposition_id = NEW.proposition_id
                      AND s.scope_id = NEW.scope_id
                      AND s.subject_type = 'judicial_decision'
                      AND s.judicial_decision_id = NEW.case_id
               ) THEN
                RAISE EXCEPTION
                    'proposition-scoped judicial stance cannot target another decision'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: acquisition_run_items; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.acquisition_run_items (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    run_id uuid NOT NULL,
    source_document_id uuid NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    artifact_id uuid,
    error_code text,
    error_message text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT acquisition_run_items_error_pair_check CHECK (((error_code IS NULL) = (error_message IS NULL))),
    CONSTRAINT acquisition_run_items_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'acquired'::text, 'already_present'::text, 'failed'::text, 'skipped'::text]))),
    CONSTRAINT acquisition_run_items_time_check CHECK (((finished_at IS NULL) OR (started_at IS NULL) OR (finished_at >= started_at)))
);


--
-- Name: TABLE acquisition_run_items; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.acquisition_run_items IS 'Per-source-document acquisition outcomes. S3 bytes and canonical legal identity remain separate concerns.';


--
-- Name: acquisition_runs; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.acquisition_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_collection_id uuid NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    requested_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    selected_count integer DEFAULT 0 NOT NULL,
    acquired_count integer DEFAULT 0 NOT NULL,
    already_present_count integer DEFAULT 0 NOT NULL,
    failed_count integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT acquisition_runs_counts_check CHECK (((selected_count >= 0) AND (acquired_count >= 0) AND (already_present_count >= 0) AND (failed_count >= 0))),
    CONSTRAINT acquisition_runs_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'succeeded'::text, 'completed_with_errors'::text, 'failed'::text, 'cancelled'::text]))),
    CONSTRAINT acquisition_runs_time_check CHECK (((finished_at IS NULL) OR (started_at IS NULL) OR (finished_at >= started_at)))
);


--
-- Name: TABLE acquisition_runs; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.acquisition_runs IS 'Durable acquisition execution ledger. API requests create runs; workers or explicit execute commands perform external I/O after the run transaction commits.';


--
-- Name: adjudicative_act_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.adjudicative_act_type_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    broader_concept_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT adjudicative_act_type_concepts_check CHECK (((broader_concept_id IS NULL) OR (broader_concept_id <> id))),
    CONSTRAINT adjudicative_act_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT adjudicative_act_type_concepts_name_check CHECK ((btrim(name) <> ''::text))
);


--
-- Name: TABLE adjudicative_act_type_concepts; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.adjudicative_act_type_concepts IS 'Open legal vocabulary. Add observed forms as data; do not add CHECK-list migrations for jurisdiction-specific act types.';


--
-- Name: analysis_observations; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.analysis_observations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    observation_key text NOT NULL,
    subject_type text NOT NULL,
    case_id uuid,
    proceeding_id uuid,
    legal_document_id uuid,
    observation_type text NOT NULL,
    payload jsonb NOT NULL,
    evidence jsonb DEFAULT '[]'::jsonb NOT NULL,
    producer_type text DEFAULT 'llm_agent'::text NOT NULL,
    producer_name text NOT NULL,
    model_name text,
    model_version text,
    analysis_run_id text,
    schema_hint text,
    confidence real,
    status text DEFAULT 'observed'::text NOT NULL,
    review_notes text,
    promoted_to_schema text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    reviewed_at timestamp with time zone,
    CONSTRAINT analysis_observations_confidence_check CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT analysis_observations_evidence_array_check CHECK ((jsonb_typeof(evidence) = 'array'::text)),
    CONSTRAINT analysis_observations_key_check CHECK ((observation_key ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT analysis_observations_payload_object_check CHECK ((jsonb_typeof(payload) = 'object'::text)),
    CONSTRAINT analysis_observations_producer_name_nonempty CHECK ((btrim(producer_name) <> ''::text)),
    CONSTRAINT analysis_observations_producer_type_check CHECK ((producer_type = ANY (ARRAY['llm_agent'::text, 'deterministic_tool'::text, 'human'::text, 'other'::text]))),
    CONSTRAINT analysis_observations_promoted_target_check CHECK (((status <> 'promoted'::text) OR (btrim(COALESCE(promoted_to_schema, ''::text)) <> ''::text))),
    CONSTRAINT analysis_observations_reviewed_at_check CHECK (((reviewed_at IS NULL) OR (reviewed_at >= created_at))),
    CONSTRAINT analysis_observations_status_check CHECK ((status = ANY (ARRAY['observed'::text, 'reviewed'::text, 'promoted'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT analysis_observations_subject_shape_check CHECK ((((subject_type = 'case'::text) AND (case_id IS NOT NULL) AND (proceeding_id IS NULL) AND (legal_document_id IS NULL)) OR ((subject_type = 'proceeding'::text) AND (proceeding_id IS NOT NULL) AND (case_id IS NULL) AND (legal_document_id IS NULL)) OR ((subject_type = 'legal_document'::text) AND (legal_document_id IS NOT NULL) AND (case_id IS NULL) AND (proceeding_id IS NULL)) OR ((subject_type = 'corpus'::text) AND (case_id IS NULL) AND (proceeding_id IS NULL) AND (legal_document_id IS NULL)))),
    CONSTRAINT analysis_observations_subject_type_check CHECK ((subject_type = ANY (ARRAY['case'::text, 'proceeding'::text, 'legal_document'::text, 'corpus'::text]))),
    CONSTRAINT analysis_observations_type_nonempty CHECK ((btrim(observation_type) <> ''::text))
);


--
-- Name: TABLE analysis_observations; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.analysis_observations IS 'Quarantined extensibility ledger for analysis findings, especially LLM discoveries not yet modeled canonically. JSONB payloads never become source facts merely because they were submitted; promotion requires explicit review and a named canonical destination.';


--
-- Name: artifact_pages; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.artifact_pages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    artifact_id uuid NOT NULL,
    page_number integer NOT NULL,
    extracted_text text,
    text_sha256 text,
    extraction_method text,
    extraction_status text DEFAULT 'pending'::text NOT NULL,
    ocr_confidence real,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT artifact_pages_number_check CHECK ((page_number > 0)),
    CONSTRAINT artifact_pages_ocr_confidence_check CHECK (((ocr_confidence IS NULL) OR ((ocr_confidence >= (0)::double precision) AND (ocr_confidence <= (1)::double precision)))),
    CONSTRAINT artifact_pages_status_check CHECK ((extraction_status = ANY (ARRAY['pending'::text, 'native_text'::text, 'ocr_complete'::text, 'quality_review_required'::text, 'blocked'::text]))),
    CONSTRAINT artifact_pages_text_sha256_check CHECK (((text_sha256 IS NULL) OR (text_sha256 ~ '^[0-9a-f]{64}$'::text)))
);


--
-- Name: case_artifact_occurrences; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.case_artifact_occurrences (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_id uuid NOT NULL,
    artifact_id uuid NOT NULL,
    start_page integer NOT NULL,
    end_page integer NOT NULL,
    segmentation_status text DEFAULT 'candidate'::text NOT NULL,
    segmentation_method text NOT NULL,
    segmentation_confidence real,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    CONSTRAINT case_artifact_occurrences_confidence_check CHECK (((segmentation_confidence IS NULL) OR ((segmentation_confidence >= (0)::double precision) AND (segmentation_confidence <= (1)::double precision)))),
    CONSTRAINT case_artifact_occurrences_page_range_check CHECK (((start_page > 0) AND (end_page >= start_page))),
    CONSTRAINT case_artifact_occurrences_status_check CHECK ((segmentation_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'ambiguous'::text, 'rejected'::text])))
);


--
-- Name: TABLE case_artifact_occurrences; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.case_artifact_occurrences IS 'Maps one canonical judicial case to the exact page range where it occurs inside a source artifact or compilation.';


--
-- Name: COLUMN case_artifact_occurrences.scope_id; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.case_artifact_occurrences.scope_id IS 'Scope shared by the canonical case and source artifact; public links default to the stable public scope while private links must name their private scope explicitly.';


--
-- Name: case_identifier_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.case_identifier_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT case_identifier_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT case_identifier_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: case_identifiers; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.case_identifiers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_id uuid NOT NULL,
    identifier_type text NOT NULL,
    raw_value text NOT NULL,
    normalized_value text,
    is_primary boolean DEFAULT false NOT NULL,
    evidence_case_page_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: COLUMN case_identifiers.identifier_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.case_identifiers.identifier_type IS 'Extensible legal-domain code; FK to corpus.case_identifier_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: COLUMN case_identifiers.evidence_case_page_id; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.case_identifiers.evidence_case_page_id IS 'Case-owned page containing the identifier evidence. Composite FK prevents cross-case provenance.';


--
-- Name: case_metadata_observations; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.case_metadata_observations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    ingestion_job_id uuid NOT NULL,
    case_id uuid NOT NULL,
    observation_key text NOT NULL,
    field_name text NOT NULL,
    value_type text NOT NULL,
    raw_value text NOT NULL,
    normalized_text text,
    normalized_date date,
    normalized_json jsonb,
    observation_method text NOT NULL,
    method_name text NOT NULL,
    confidence real,
    evidence_case_page_id uuid,
    evidence_excerpt text,
    evidence_char_start integer,
    evidence_char_end integer,
    status text DEFAULT 'observed'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    artifact_id uuid NOT NULL,
    CONSTRAINT case_metadata_observations_confidence_check CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT case_metadata_observations_key_check CHECK ((observation_key ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT case_metadata_observations_method_check CHECK ((observation_method = ANY (ARRAY['deterministic_parser'::text, 'official_metadata_import'::text, 'llm_assist'::text, 'manual_review'::text]))),
    CONSTRAINT case_metadata_observations_normalized_shape_check CHECK ((((value_type = 'date'::text) AND (normalized_text IS NULL) AND (normalized_json IS NULL)) OR ((value_type = ANY (ARRAY['text'::text, 'identifier'::text])) AND (normalized_date IS NULL) AND (normalized_json IS NULL)) OR ((value_type = 'json'::text) AND (normalized_text IS NULL) AND (normalized_date IS NULL)))),
    CONSTRAINT case_metadata_observations_offsets_check CHECK ((((evidence_char_start IS NULL) AND (evidence_char_end IS NULL)) OR ((evidence_char_start IS NOT NULL) AND (evidence_char_end IS NOT NULL) AND (evidence_char_start >= 0) AND (evidence_char_end > evidence_char_start)))),
    CONSTRAINT case_metadata_observations_status_check CHECK ((status = ANY (ARRAY['observed'::text, 'accepted'::text, 'rejected'::text, 'conflicting'::text, 'superseded'::text]))),
    CONSTRAINT case_metadata_observations_value_type_check CHECK ((value_type = ANY (ARRAY['text'::text, 'date'::text, 'identifier'::text, 'json'::text])))
);


--
-- Name: TABLE case_metadata_observations; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.case_metadata_observations IS 'Auditable extracted observations. Rows are evidence-bearing candidates, not canonical legal metadata until reconciliation or verification promotes them.';


--
-- Name: COLUMN case_metadata_observations.observation_key; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.case_metadata_observations.observation_key IS 'Stable parser-generated SHA-256 key used to make observation writes idempotent inside one ingestion job.';


--
-- Name: COLUMN case_metadata_observations.confidence; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.case_metadata_observations.confidence IS 'Optional calibrated score. Deterministic parsers should leave this NULL unless the score has an explicit measured calibration.';


--
-- Name: COLUMN case_metadata_observations.artifact_id; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.case_metadata_observations.artifact_id IS 'Artifact processed by ingestion_job_id. Observation evidence must resolve to a case page from this same artifact.';


--
-- Name: case_metadata_resolution_observations; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.case_metadata_resolution_observations (
    resolution_id uuid NOT NULL,
    case_id uuid NOT NULL,
    observation_id uuid NOT NULL,
    role text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT case_metadata_resolution_observations_role_check CHECK ((role = ANY (ARRAY['supporting'::text, 'conflicting'::text, 'selected'::text])))
);


--
-- Name: TABLE case_metadata_resolution_observations; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.case_metadata_resolution_observations IS 'Exact observation set considered by one metadata resolution, including supporting, conflicting, and selected evidence.';


--
-- Name: case_metadata_resolutions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.case_metadata_resolutions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_id uuid NOT NULL,
    field_name text NOT NULL,
    value_type text NOT NULL,
    resolved_text text,
    resolved_date date,
    resolved_json jsonb,
    resolution_status text NOT NULL,
    resolver_name text NOT NULL,
    resolver_version text NOT NULL,
    code_revision text NOT NULL,
    idempotency_key text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT case_metadata_resolutions_code_revision_check CHECK ((btrim(code_revision) <> ''::text)),
    CONSTRAINT case_metadata_resolutions_field_name_check CHECK ((btrim(field_name) <> ''::text)),
    CONSTRAINT case_metadata_resolutions_idempotency_key_check CHECK ((idempotency_key ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT case_metadata_resolutions_normalized_shape_check CHECK ((((value_type = 'date'::text) AND (resolved_text IS NULL) AND (resolved_json IS NULL)) OR ((value_type = ANY (ARRAY['text'::text, 'identifier'::text])) AND (resolved_date IS NULL) AND (resolved_json IS NULL)) OR ((value_type = 'json'::text) AND (resolved_text IS NULL) AND (resolved_date IS NULL)))),
    CONSTRAINT case_metadata_resolutions_resolver_name_check CHECK ((btrim(resolver_name) <> ''::text)),
    CONSTRAINT case_metadata_resolutions_resolver_version_check CHECK ((btrim(resolver_version) <> ''::text)),
    CONSTRAINT case_metadata_resolutions_status_check CHECK ((resolution_status = ANY (ARRAY['verified_primary_text'::text, 'verified_official_metadata'::text, 'parsed_high_confidence'::text, 'parsed_unverified'::text, 'conflicting'::text, 'unknown'::text]))),
    CONSTRAINT case_metadata_resolutions_status_value_check CHECK ((((resolution_status = ANY (ARRAY['conflicting'::text, 'unknown'::text])) AND (num_nonnulls(resolved_text, resolved_date, resolved_json) = 0)) OR ((resolution_status <> ALL (ARRAY['conflicting'::text, 'unknown'::text])) AND (num_nonnulls(resolved_text, resolved_date, resolved_json) = 1)))),
    CONSTRAINT case_metadata_resolutions_value_type_check CHECK ((value_type = ANY (ARRAY['text'::text, 'date'::text, 'identifier'::text, 'json'::text])))
);


--
-- Name: TABLE case_metadata_resolutions; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.case_metadata_resolutions IS 'Immutable-in-practice resolver output between raw observations and canonical case metadata. Promotion is recorded separately and must not mutate this row.';


--
-- Name: case_pages; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.case_pages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_id uuid NOT NULL,
    artifact_page_id uuid NOT NULL,
    ordinal_in_case integer NOT NULL,
    printed_page_label text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    artifact_id uuid NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    CONSTRAINT case_pages_ordinal_check CHECK ((ordinal_in_case > 0))
);


--
-- Name: COLUMN case_pages.artifact_id; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.case_pages.artifact_id IS 'Artifact owning artifact_page_id; duplicated intentionally so cross-artifact provenance is enforceable with foreign keys.';


--
-- Name: COLUMN case_pages.scope_id; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.case_pages.scope_id IS 'Scope shared by the canonical case and source artifact page; public links default to the stable public scope while private links must name their private scope explicitly.';


--
-- Name: claim_relation_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.claim_relation_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    broader_concept_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT claim_relation_concepts_check CHECK (((broader_concept_id IS NULL) OR (broader_concept_id <> id))),
    CONSTRAINT claim_relation_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT claim_relation_concepts_name_check CHECK ((btrim(name) <> ''::text))
);


--
-- Name: claim_relations; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.claim_relations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    source_claim_id uuid NOT NULL,
    target_claim_id uuid NOT NULL,
    relation_concept_id uuid NOT NULL,
    raw_relation text,
    valid_from date,
    valid_to date,
    known_from timestamp with time zone DEFAULT now() NOT NULL,
    known_to timestamp with time zone,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    evidence_note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT claim_relations_check CHECK ((source_claim_id <> target_claim_id)),
    CONSTRAINT claim_relations_check1 CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT claim_relations_check2 CHECK (((known_to IS NULL) OR (known_to > known_from))),
    CONSTRAINT claim_relations_verification_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: TABLE claim_relations; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.claim_relations IS 'Canonical lineage between claims/grounds across proceedings. It deliberately does not require the two claims to belong to the same proceeding.';


--
-- Name: concept_schemes; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.concept_schemes (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT concept_schemes_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT concept_schemes_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: TABLE concept_schemes; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.concept_schemes IS 'Shared ontology registry for new legal categories. Mature specialized registries may remain canonical until intentionally migrated; V4 does not perform a big-bang rewrite.';


--
-- Name: controversy_membership_role_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.controversy_membership_role_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    broader_concept_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT controversy_membership_role_concepts_check CHECK (((broader_concept_id IS NULL) OR (broader_concept_id <> id))),
    CONSTRAINT controversy_membership_role_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT controversy_membership_role_concepts_name_check CHECK ((btrim(name) <> ''::text))
);


--
-- Name: TABLE controversy_membership_role_concepts; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.controversy_membership_role_concepts IS 'Open legal vocabulary for a proceeding role inside a litigation family. Procedural ancestry belongs exclusively in proceeding_relations.';


--
-- Name: controversy_proceedings; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.controversy_proceedings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    controversy_id uuid NOT NULL,
    proceeding_id uuid NOT NULL,
    valid_from date,
    valid_to date,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    relation_concept_id uuid NOT NULL,
    CONSTRAINT controversy_proceedings_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT controversy_proceedings_verification_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: court_alias_kind_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.court_alias_kind_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT court_alias_kind_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT court_alias_kind_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: court_aliases; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.court_aliases (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    court_id uuid NOT NULL,
    alias text NOT NULL,
    normalized_alias text NOT NULL,
    alias_kind text DEFAULT 'source_label'::text NOT NULL,
    source_registry_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT court_aliases_alias_nonempty CHECK ((btrim(alias) <> ''::text)),
    CONSTRAINT court_aliases_normalized_nonempty CHECK ((btrim(normalized_alias) <> ''::text))
);


--
-- Name: TABLE court_aliases; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.court_aliases IS 'Source-facing labels used to resolve heterogeneous portal text to a canonical court without overwriting source metadata.';


--
-- Name: COLUMN court_aliases.alias_kind; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.court_aliases.alias_kind IS 'Extensible legal-domain code; FK to corpus.court_alias_kind_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: court_function_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.court_function_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT court_function_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT court_function_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: court_functional_competences; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.court_functional_competences (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    court_id uuid NOT NULL,
    function_type text NOT NULL,
    instance_level text NOT NULL,
    procedure_concept_id uuid,
    valid_from date,
    valid_to date,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT court_functional_competences_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT court_functional_competences_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN court_functional_competences.function_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.court_functional_competences.function_type IS 'Extensible legal-domain code; FK to corpus.court_function_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: COLUMN court_functional_competences.instance_level; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.court_functional_competences.instance_level IS 'Extensible legal-domain code; FK to corpus.court_instance_level_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: court_instance_level_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.court_instance_level_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT court_instance_level_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT court_instance_level_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: court_jurisdictions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.court_jurisdictions (
    court_id uuid NOT NULL,
    jurisdiction_code text NOT NULL,
    is_primary boolean DEFAULT false NOT NULL,
    active_from date,
    active_to date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT court_jurisdictions_active_range_check CHECK (((active_to IS NULL) OR (active_from IS NULL) OR (active_to >= active_from)))
);


--
-- Name: court_organ_alias_kind_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.court_organ_alias_kind_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT court_organ_alias_kind_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT court_organ_alias_kind_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: court_organ_aliases; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.court_organ_aliases (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    court_organ_id uuid NOT NULL,
    alias text NOT NULL,
    normalized_alias text NOT NULL,
    alias_kind text DEFAULT 'source_label'::text NOT NULL,
    source_registry_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT court_organ_aliases_alias_nonempty CHECK ((btrim(alias) <> ''::text)),
    CONSTRAINT court_organ_aliases_normalized_nonempty CHECK ((btrim(normalized_alias) <> ''::text))
);


--
-- Name: COLUMN court_organ_aliases.alias_kind; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.court_organ_aliases.alias_kind IS 'Extensible legal-domain code; FK to corpus.court_organ_alias_kind_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: court_organs; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.court_organs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    court_id uuid NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    organ_type text NOT NULL,
    active_from date,
    active_to date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT court_organs_active_range_check CHECK (((active_to IS NULL) OR (active_from IS NULL) OR (active_to >= active_from)))
);


--
-- Name: court_relation_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.court_relation_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT court_relation_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT court_relation_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: court_relations; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.court_relations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    from_court_id uuid NOT NULL,
    to_court_id uuid NOT NULL,
    relation_type text NOT NULL,
    active_from date,
    active_to date,
    source_note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT court_relations_active_range_check CHECK (((active_to IS NULL) OR (active_from IS NULL) OR (active_to >= active_from))),
    CONSTRAINT court_relations_distinct_check CHECK ((from_court_id <> to_court_id))
);


--
-- Name: TABLE court_relations; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.court_relations IS 'Typed, temporal relationships between courts. Appeal, review and administrative relationships remain explicit instead of being collapsed into parent_court_id.';


--
-- Name: COLUMN court_relations.relation_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.court_relations.relation_type IS 'Extensible legal-domain code; FK to corpus.court_relation_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: court_subject_matter_competences; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.court_subject_matter_competences (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    court_id uuid NOT NULL,
    legal_matter_concept_id uuid NOT NULL,
    valid_from date,
    valid_to date,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT court_subject_matter_competences_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT court_subject_matter_competences_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: court_territorial_competences; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.court_territorial_competences (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    court_id uuid NOT NULL,
    territorial_unit_id uuid NOT NULL,
    valid_from date,
    valid_to date,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT court_territorial_competences_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT court_territorial_competences_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: court_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.court_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT court_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT court_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: courts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.courts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    short_name text,
    jurisdiction text NOT NULL,
    country_code character(2) DEFAULT 'DO'::bpchar NOT NULL,
    authority_rank smallint,
    active_from date,
    active_to date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    judicial_system text DEFAULT 'other'::text NOT NULL,
    court_type text DEFAULT 'other'::text NOT NULL,
    legal_entity_id uuid NOT NULL,
    CONSTRAINT courts_active_range_check CHECK (((active_to IS NULL) OR (active_from IS NULL) OR (active_to >= active_from)))
);


--
-- Name: COLUMN courts.judicial_system; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.courts.judicial_system IS 'Extensible legal-domain code; FK to corpus.judicial_system_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: COLUMN courts.court_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.courts.court_type IS 'Extensible legal-domain code; FK to corpus.court_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: decision_legal_matters; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.decision_legal_matters (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    decision_id uuid NOT NULL,
    legal_matter_concept_id uuid NOT NULL,
    relation_type text DEFAULT 'addresses'::text NOT NULL,
    ordinal integer,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT decision_legal_matters_ordinal_check CHECK (((ordinal IS NULL) OR (ordinal > 0))),
    CONSTRAINT decision_legal_matters_verification_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN decision_legal_matters.relation_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.decision_legal_matters.relation_type IS 'Extensible legal-domain code; FK to corpus.decision_matter_relation_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: decision_legal_states; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.decision_legal_states (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    decision_id uuid NOT NULL,
    state_concept_id uuid NOT NULL,
    valid_from date,
    valid_to date,
    known_from timestamp with time zone DEFAULT now() NOT NULL,
    known_to timestamp with time zone,
    source_document_id uuid,
    evidence_case_page_id uuid,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT decision_legal_states_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT decision_legal_states_check1 CHECK (((known_to IS NULL) OR (known_to > known_from))),
    CONSTRAINT decision_legal_states_verification_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: TABLE decision_legal_states; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.decision_legal_states IS 'Durative legal effect/state. Point-in-time lifecycle acts remain decision_legal_status_events.';


--
-- Name: decision_legal_status_events; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.decision_legal_status_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    case_id uuid NOT NULL,
    occurred_on date,
    date_status text DEFAULT 'unknown'::text NOT NULL,
    source_document_id uuid,
    evidence_case_page_id uuid,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    known_from timestamp with time zone DEFAULT now() NOT NULL,
    known_to timestamp with time zone,
    event_type_concept_id uuid NOT NULL,
    CONSTRAINT decision_legal_status_events_date_status_check CHECK ((date_status = ANY (ARRAY['verified_primary_text'::text, 'verified_official_metadata'::text, 'parsed_high_confidence'::text, 'parsed_unverified'::text, 'conflicting'::text, 'unknown'::text]))),
    CONSTRAINT decision_legal_status_events_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT decision_legal_status_events_verified_date_requires_date CHECK (((date_status <> ALL (ARRAY['verified_primary_text'::text, 'verified_official_metadata'::text, 'parsed_high_confidence'::text])) OR (occurred_on IS NOT NULL))),
    CONSTRAINT decision_legal_status_known_range_check CHECK (((known_to IS NULL) OR (known_to > known_from)))
);


--
-- Name: TABLE decision_legal_status_events; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.decision_legal_status_events IS 'Point-in-time lifecycle acts only. New state-like facts such as finality, res judicata, appealability, stays and suspension belong in decision_legal_states.';


--
-- Name: decision_matter_relation_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.decision_matter_relation_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT decision_matter_relation_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT decision_matter_relation_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: decision_panel_members; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.decision_panel_members (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    case_id uuid NOT NULL,
    officer_id uuid NOT NULL,
    role_raw text NOT NULL,
    panel_role text DEFAULT 'member'::text NOT NULL,
    ordinal integer,
    evidence_case_page_id uuid,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT decision_panel_members_ordinal_check CHECK (((ordinal IS NULL) OR (ordinal > 0))),
    CONSTRAINT decision_panel_members_role_raw_nonempty CHECK ((btrim(role_raw) <> ''::text)),
    CONSTRAINT decision_panel_members_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN decision_panel_members.panel_role; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.decision_panel_members.panel_role IS 'Extensible legal-domain code; FK to corpus.panel_role_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: decision_procedure_relation_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.decision_procedure_relation_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT decision_procedure_relation_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT decision_procedure_relation_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: decision_procedures; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.decision_procedures (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    decision_id uuid NOT NULL,
    procedure_concept_id uuid NOT NULL,
    relation_type text DEFAULT 'uses'::text NOT NULL,
    ordinal integer,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT decision_procedures_ordinal_check CHECK (((ordinal IS NULL) OR (ordinal > 0))),
    CONSTRAINT decision_procedures_verification_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN decision_procedures.relation_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.decision_procedures.relation_type IS 'Extensible legal-domain code; FK to corpus.decision_procedure_relation_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: decision_state_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.decision_state_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    broader_concept_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT decision_state_concepts_check CHECK (((broader_concept_id IS NULL) OR (broader_concept_id <> id))),
    CONSTRAINT decision_state_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT decision_state_concepts_name_check CHECK ((btrim(name) <> ''::text))
);


--
-- Name: decision_votes; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.decision_votes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    case_id uuid NOT NULL,
    officer_id uuid NOT NULL,
    vote_type text NOT NULL,
    opinion_id uuid,
    note text,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT decision_votes_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN decision_votes.vote_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.decision_votes.vote_type IS 'Extensible legal-domain code; FK to corpus.judicial_vote_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: disposition_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.disposition_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    broader_concept_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT disposition_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT disposition_concepts_name_check CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT disposition_concepts_not_self_parent CHECK (((broader_concept_id IS NULL) OR (broader_concept_id <> id)))
);


--
-- Name: disposition_effect_argument_rules; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.disposition_effect_argument_rules (
    effect_concept_id uuid NOT NULL,
    role_scheme_code text DEFAULT 'disposition_argument_role'::text NOT NULL,
    role_concept_id uuid NOT NULL,
    object_type text NOT NULL,
    required boolean DEFAULT false NOT NULL,
    max_count integer,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT disposition_effect_argument_rules_max_count_check CHECK (((max_count IS NULL) OR (max_count > 0))),
    CONSTRAINT disposition_effect_argument_rules_object_type_check CHECK ((object_type = ANY (ARRAY['claim'::text, 'party_role'::text, 'proceeding'::text, 'decision'::text, 'proposition'::text, 'provision'::text, 'court'::text, 'court_organ'::text, 'text'::text, 'number'::text, 'money'::text, 'date'::text, 'duration'::text, 'percentage'::text]))),
    CONSTRAINT disposition_effect_argument_rules_scheme_check CHECK ((role_scheme_code = 'disposition_argument_role'::text))
);


--
-- Name: TABLE disposition_effect_argument_rules; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.disposition_effect_argument_rules IS 'Machine-readable baseline grammar for known disposition effects. Rules describe expected roles/object kinds but are not a complete legal reasoning engine; jurisdiction-specific effects may extend them as data.';


--
-- Name: disposition_effect_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.disposition_effect_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    broader_concept_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    description text,
    CONSTRAINT claim_effect_concepts_check CHECK (((broader_concept_id IS NULL) OR (broader_concept_id <> id))),
    CONSTRAINT claim_effect_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT claim_effect_concepts_name_check CHECK ((btrim(name) <> ''::text))
);


--
-- Name: entity_identity_assertion_evidence; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.entity_identity_assertion_evidence (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    assertion_id uuid NOT NULL,
    artifact_page_id uuid,
    source_document_observation_id uuid,
    exact_excerpt text,
    char_start integer,
    char_end integer,
    evidence_kind text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT entity_identity_evidence_kind_check CHECK ((evidence_kind = ANY (ARRAY['primary_text'::text, 'official_metadata'::text, 'deterministic_match'::text, 'manual_review'::text]))),
    CONSTRAINT entity_identity_evidence_offsets_check CHECK ((((char_start IS NULL) AND (char_end IS NULL)) OR ((char_start IS NOT NULL) AND (char_end IS NOT NULL) AND (char_start >= 0) AND (char_end > char_start)))),
    CONSTRAINT entity_identity_evidence_presence_check CHECK (((artifact_page_id IS NOT NULL) OR (source_document_observation_id IS NOT NULL)))
);


--
-- Name: entity_identity_assertions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.entity_identity_assertions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    observed_entity_id uuid NOT NULL,
    candidate_entity_id uuid NOT NULL,
    relation_scheme_code text DEFAULT 'entity_identity_relation'::text NOT NULL,
    relation_concept_id uuid NOT NULL,
    known_from timestamp with time zone DEFAULT now() NOT NULL,
    known_to timestamp with time zone,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    extraction_confidence real,
    semantic_confidence real,
    evidence_note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT entity_identity_assertions_distinct_check CHECK ((observed_entity_id <> candidate_entity_id)),
    CONSTRAINT entity_identity_assertions_extraction_confidence_check CHECK (((extraction_confidence IS NULL) OR ((extraction_confidence >= (0)::double precision) AND (extraction_confidence <= (1)::double precision)))),
    CONSTRAINT entity_identity_assertions_known_range_check CHECK (((known_to IS NULL) OR (known_to > known_from))),
    CONSTRAINT entity_identity_assertions_scheme_check CHECK ((relation_scheme_code = 'entity_identity_relation'::text)),
    CONSTRAINT entity_identity_assertions_semantic_confidence_check CHECK (((semantic_confidence IS NULL) OR ((semantic_confidence >= (0)::double precision) AND (semantic_confidence <= (1)::double precision)))),
    CONSTRAINT entity_identity_assertions_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: TABLE entity_identity_assertions; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.entity_identity_assertions IS 'Auditable claim that two preserved legal-entity identities denote the same, probably same, or different real-world entity. Similar names alone never perform a destructive merge.';


--
-- Name: entity_identity_resolutions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.entity_identity_resolutions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    observed_entity_id uuid NOT NULL,
    canonical_entity_id uuid NOT NULL,
    supporting_assertion_id uuid NOT NULL,
    known_from timestamp with time zone DEFAULT now() NOT NULL,
    known_to timestamp with time zone,
    verification_status text DEFAULT 'verified'::text NOT NULL,
    verification_method text NOT NULL,
    review_note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT entity_identity_resolutions_distinct_check CHECK ((observed_entity_id <> canonical_entity_id)),
    CONSTRAINT entity_identity_resolutions_known_range_check CHECK (((known_to IS NULL) OR (known_to > known_from))),
    CONSTRAINT entity_identity_resolutions_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: TABLE entity_identity_resolutions; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.entity_identity_resolutions IS 'Bitemporal resolution from an observed legal entity to the currently accepted canonical identity. A resolution requires a conclusive verified same_as/merged_into assertion; probable_same_as may remain evidence/candidate knowledge but cannot canonicalize identity. The observed entity remains addressable.';


--
-- Name: factual_proposition_evidence; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.factual_proposition_evidence (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    factual_proposition_id uuid NOT NULL,
    source_decision_id uuid,
    source_document_id uuid,
    case_page_id uuid,
    artifact_page_id uuid,
    exact_excerpt text,
    char_start integer,
    char_end integer,
    extraction_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT factual_evidence_offsets_check CHECK ((((char_start IS NULL) AND (char_end IS NULL)) OR ((char_start IS NOT NULL) AND (char_end IS NOT NULL) AND (char_start >= 0) AND (char_end > char_start)))),
    CONSTRAINT factual_evidence_page_requires_decision CHECK (((case_page_id IS NULL) OR (source_decision_id IS NOT NULL))),
    CONSTRAINT factual_evidence_presence_check CHECK (((source_decision_id IS NOT NULL) OR (source_document_id IS NOT NULL) OR (artifact_page_id IS NOT NULL)))
);


--
-- Name: factual_proposition_subjects; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.factual_proposition_subjects (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    factual_proposition_id uuid NOT NULL,
    relation_scheme_code text DEFAULT 'factual_subject_relation'::text NOT NULL,
    relation_concept_id uuid NOT NULL,
    subject_type text NOT NULL,
    judicial_decision_id uuid,
    proceeding_id uuid,
    claim_id uuid,
    party_role_id uuid,
    ordinal integer,
    raw_relation text,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT factual_subjects_ordinal_check CHECK (((ordinal IS NULL) OR (ordinal > 0))),
    CONSTRAINT factual_subjects_scheme_check CHECK ((relation_scheme_code = 'factual_subject_relation'::text)),
    CONSTRAINT factual_subjects_shape_check CHECK ((((subject_type = 'judicial_decision'::text) AND (judicial_decision_id IS NOT NULL) AND (proceeding_id IS NULL) AND (claim_id IS NULL) AND (party_role_id IS NULL)) OR ((subject_type = 'proceeding'::text) AND (judicial_decision_id IS NULL) AND (proceeding_id IS NOT NULL) AND (claim_id IS NULL) AND (party_role_id IS NULL)) OR ((subject_type = 'claim'::text) AND (judicial_decision_id IS NULL) AND (proceeding_id IS NULL) AND (claim_id IS NOT NULL) AND (party_role_id IS NULL)) OR ((subject_type = 'party_role'::text) AND (judicial_decision_id IS NULL) AND (proceeding_id IS NULL) AND (claim_id IS NULL) AND (party_role_id IS NOT NULL)))),
    CONSTRAINT factual_subjects_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT factual_subjects_type_check CHECK ((subject_type = ANY (ARRAY['judicial_decision'::text, 'proceeding'::text, 'claim'::text, 'party_role'::text])))
);


--
-- Name: factual_propositions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.factual_propositions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    kind_scheme_code text DEFAULT 'factual_proposition_kind'::text NOT NULL,
    kind_concept_id uuid NOT NULL,
    canonical_text text NOT NULL,
    normalized_text text,
    assertion_kind text NOT NULL,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    extraction_confidence real,
    semantic_confidence real,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT factual_propositions_assertion_kind_check CHECK ((assertion_kind = ANY (ARRAY['explicit_primary_text'::text, 'derived_from_primary_text'::text, 'synthesized_interpretation'::text, 'human_authored'::text]))),
    CONSTRAINT factual_propositions_extraction_confidence_check CHECK (((extraction_confidence IS NULL) OR ((extraction_confidence >= (0)::double precision) AND (extraction_confidence <= (1)::double precision)))),
    CONSTRAINT factual_propositions_kind_scheme_check CHECK ((kind_scheme_code = 'factual_proposition_kind'::text)),
    CONSTRAINT factual_propositions_semantic_confidence_check CHECK (((semantic_confidence IS NULL) OR ((semantic_confidence >= (0)::double precision) AND (semantic_confidence <= (1)::double precision)))),
    CONSTRAINT factual_propositions_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT factual_propositions_text_nonempty CHECK ((btrim(canonical_text) <> ''::text))
);


--
-- Name: TABLE factual_propositions; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.factual_propositions IS 'Canonical factual propositions. Kind distinguishes allegation, admission, finding and other epistemic/legal roles; storing an allegation never implies the alleged fact is true.';


--
-- Name: ingestion_jobs; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.ingestion_jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    artifact_id uuid NOT NULL,
    parser_version_id uuid NOT NULL,
    idempotency_key text NOT NULL,
    state text DEFAULT 'pending'::text NOT NULL,
    attempt integer DEFAULT 1 NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    error_code text,
    error_detail text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ingestion_jobs_attempt_check CHECK ((attempt > 0)),
    CONSTRAINT ingestion_jobs_finished_after_started_check CHECK (((finished_at IS NULL) OR (started_at IS NULL) OR (finished_at >= started_at))),
    CONSTRAINT ingestion_jobs_state_check CHECK ((state = ANY (ARRAY['pending'::text, 'extracting'::text, 'segmenting'::text, 'observing_metadata'::text, 'reconciling'::text, 'quality_check'::text, 'ready'::text, 'partial'::text, 'failed'::text, 'cancelled'::text, 'blocked'::text])))
);


--
-- Name: instrument_authority_role_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.instrument_authority_role_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT instrument_authority_role_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT instrument_authority_role_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: instrument_document_role_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.instrument_document_role_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT instrument_document_role_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT instrument_document_role_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: instrument_version_kind_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.instrument_version_kind_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT instrument_version_kind_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT instrument_version_kind_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: judicial_authority_assertions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_authority_assertions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    decision_id uuid NOT NULL,
    proposition_id uuid,
    jurisdiction_code text,
    court_id uuid,
    legal_matter_concept_id uuid,
    valid_from date,
    valid_to date,
    basis text NOT NULL,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    known_from timestamp with time zone DEFAULT now() NOT NULL,
    known_to timestamp with time zone,
    authority_effect_concept_id uuid NOT NULL,
    CONSTRAINT precedential_authority_assertions_context_check CHECK (((jurisdiction_code IS NOT NULL) OR (court_id IS NOT NULL) OR (legal_matter_concept_id IS NOT NULL))),
    CONSTRAINT precedential_authority_assertions_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT precedential_authority_assertions_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT precedential_authority_known_range_check CHECK (((known_to IS NULL) OR (known_to > known_from)))
);


--
-- Name: TABLE judicial_authority_assertions; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.judicial_authority_assertions IS 'Contextual judicial-authority assertion. Canonical effect vocabulary is extensible through judicial_authority_effect_concepts.';


--
-- Name: judicial_authority_effect_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_authority_effect_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    broader_concept_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT judicial_authority_effect_concepts_check CHECK (((broader_concept_id IS NULL) OR (broader_concept_id <> id))),
    CONSTRAINT judicial_authority_effect_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT judicial_authority_effect_concepts_name_check CHECK ((btrim(name) <> ''::text))
);


--
-- Name: judicial_authorship_role_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_authorship_role_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT judicial_authorship_role_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT judicial_authorship_role_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: judicial_decision_dispositions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_decision_dispositions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    case_id uuid NOT NULL,
    ordinal integer NOT NULL,
    raw_text text NOT NULL,
    normalized_text text,
    affected_case_id uuid,
    affected_proceeding_id uuid,
    evidence_case_page_id uuid,
    extraction_method text NOT NULL,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    confidence real,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    disposition_concept_id uuid NOT NULL,
    CONSTRAINT case_dispositions_confidence_check CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT case_dispositions_ordinal_check CHECK ((ordinal > 0)),
    CONSTRAINT case_dispositions_raw_text_nonempty CHECK ((btrim(raw_text) <> ''::text)),
    CONSTRAINT case_dispositions_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: judicial_decisions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_decisions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    court_id uuid NOT NULL,
    court_organ_id uuid,
    decision_number text,
    normalized_decision_number text,
    decision_date date,
    decision_date_status text DEFAULT 'unknown'::text NOT NULL,
    decision_date_evidence_case_page_id uuid,
    title text,
    matter text,
    procedure_type text,
    language text DEFAULT 'es'::text NOT NULL,
    identity_status text DEFAULT 'identity_unresolved'::text NOT NULL,
    quality_status text DEFAULT 'unreviewed'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    legal_document_id uuid,
    act_type_concept_id uuid,
    CONSTRAINT cases_decision_date_status_check CHECK ((decision_date_status = ANY (ARRAY['verified_primary_text'::text, 'verified_official_metadata'::text, 'parsed_high_confidence'::text, 'parsed_unverified'::text, 'conflicting'::text, 'unknown'::text]))),
    CONSTRAINT cases_identity_status_check CHECK ((identity_status = ANY (ARRAY['canonical'::text, 'probable_duplicate'::text, 'identity_unresolved'::text, 'merged_with_canonical'::text]))),
    CONSTRAINT cases_quality_status_check CHECK ((quality_status = ANY (ARRAY['unreviewed'::text, 'searchable'::text, 'quality_review_required'::text, 'blocked'::text]))),
    CONSTRAINT cases_verified_date_requires_date_check CHECK (((decision_date_status <> ALL (ARRAY['verified_primary_text'::text, 'verified_official_metadata'::text, 'parsed_high_confidence'::text])) OR (decision_date IS NOT NULL)))
);


--
-- Name: TABLE judicial_decisions; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.judicial_decisions IS 'One judicial decision. It is distinct from a controversy, proceeding, publication and source artifact.';


--
-- Name: COLUMN judicial_decisions.id; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.judicial_decisions.id IS 'Legacy physical table name: each row represents one judicial decision, not the full litigation controversy or proceeding.';


--
-- Name: COLUMN judicial_decisions.decision_date; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.judicial_decisions.decision_date IS 'Date on which the judicial decision itself was rendered. Not publication, acquisition, filing, or lower-court date.';


--
-- Name: COLUMN judicial_decisions.decision_date_status; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.judicial_decisions.decision_date_status IS 'Verification/provenance state for decision_date; temporal legal research must not silently treat unknown/conflicting dates as verified.';


--
-- Name: COLUMN judicial_decisions.decision_date_evidence_case_page_id; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.judicial_decisions.decision_date_evidence_case_page_id IS 'Case-owned page containing the primary evidence for decision_date. Composite FK prevents cross-case provenance.';


--
-- Name: COLUMN judicial_decisions.matter; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.judicial_decisions.matter IS 'Source-facing/raw matter text retained even when legal_matter_concept_id is populated.';


--
-- Name: COLUMN judicial_decisions.procedure_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.judicial_decisions.procedure_type IS 'Source-facing/raw procedure text retained even when procedure_concept_id is populated.';


--
-- Name: COLUMN judicial_decisions.legal_document_id; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.judicial_decisions.legal_document_id IS 'Optional judicial specialization link. Existing case workflows remain compatible while new canonical material can use legal_documents directly.';


--
-- Name: COLUMN judicial_decisions.act_type_concept_id; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.judicial_decisions.act_type_concept_id IS 'Canonical juridical act form when known. NULL means not yet classified; no compatibility default fabricates a legal classification.';


--
-- Name: judicial_disposition_action_arguments; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_disposition_action_arguments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    disposition_id uuid NOT NULL,
    action_id uuid NOT NULL,
    role_scheme_code text DEFAULT 'disposition_argument_role'::text NOT NULL,
    role_concept_id uuid NOT NULL,
    object_type text NOT NULL,
    target_claim_id uuid,
    target_party_role_id uuid,
    target_proceeding_id uuid,
    target_decision_id uuid,
    target_proposition_id uuid,
    target_provision_id uuid,
    target_court_id uuid,
    target_court_organ_id uuid,
    text_value text,
    numeric_value numeric,
    currency_code character(3),
    date_value date,
    duration_value numeric,
    duration_unit text,
    percentage_value numeric,
    raw_argument_text text,
    ordinal integer NOT NULL,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT disposition_arguments_currency_check CHECK (((currency_code IS NULL) OR (currency_code ~ '^[A-Z]{3}$'::text))),
    CONSTRAINT disposition_arguments_duration_check CHECK ((((duration_value IS NULL) AND (duration_unit IS NULL)) OR ((duration_value IS NOT NULL) AND (duration_value > (0)::numeric) AND (btrim(COALESCE(duration_unit, ''::text)) <> ''::text)))),
    CONSTRAINT disposition_arguments_object_type_check CHECK ((object_type = ANY (ARRAY['claim'::text, 'party_role'::text, 'proceeding'::text, 'decision'::text, 'proposition'::text, 'provision'::text, 'court'::text, 'court_organ'::text, 'text'::text, 'number'::text, 'money'::text, 'date'::text, 'duration'::text, 'percentage'::text]))),
    CONSTRAINT disposition_arguments_ordinal_check CHECK ((ordinal > 0)),
    CONSTRAINT disposition_arguments_role_scheme_check CHECK ((role_scheme_code = 'disposition_argument_role'::text)),
    CONSTRAINT disposition_arguments_shape_check CHECK ((((object_type = 'claim'::text) AND (target_claim_id IS NOT NULL) AND (num_nonnulls(target_party_role_id, target_proceeding_id, target_decision_id, target_proposition_id, target_provision_id, target_court_id, target_court_organ_id, text_value, numeric_value, currency_code, date_value, duration_value, duration_unit, percentage_value) = 0)) OR ((object_type = 'party_role'::text) AND (target_party_role_id IS NOT NULL) AND (num_nonnulls(target_claim_id, target_proceeding_id, target_decision_id, target_proposition_id, target_provision_id, target_court_id, target_court_organ_id, text_value, numeric_value, currency_code, date_value, duration_value, duration_unit, percentage_value) = 0)) OR ((object_type = 'proceeding'::text) AND (target_proceeding_id IS NOT NULL) AND (num_nonnulls(target_claim_id, target_party_role_id, target_decision_id, target_proposition_id, target_provision_id, target_court_id, target_court_organ_id, text_value, numeric_value, currency_code, date_value, duration_value, duration_unit, percentage_value) = 0)) OR ((object_type = 'decision'::text) AND (target_decision_id IS NOT NULL) AND (num_nonnulls(target_claim_id, target_party_role_id, target_proceeding_id, target_proposition_id, target_provision_id, target_court_id, target_court_organ_id, text_value, numeric_value, currency_code, date_value, duration_value, duration_unit, percentage_value) = 0)) OR ((object_type = 'proposition'::text) AND (target_proposition_id IS NOT NULL) AND (num_nonnulls(target_claim_id, target_party_role_id, target_proceeding_id, target_decision_id, target_provision_id, target_court_id, target_court_organ_id, text_value, numeric_value, currency_code, date_value, duration_value, duration_unit, percentage_value) = 0)) OR ((object_type = 'provision'::text) AND (target_provision_id IS NOT NULL) AND (num_nonnulls(target_claim_id, target_party_role_id, target_proceeding_id, target_decision_id, target_proposition_id, target_court_id, target_court_organ_id, text_value, numeric_value, currency_code, date_value, duration_value, duration_unit, percentage_value) = 0)) OR ((object_type = 'court'::text) AND (target_court_id IS NOT NULL) AND (num_nonnulls(target_claim_id, target_party_role_id, target_proceeding_id, target_decision_id, target_proposition_id, target_provision_id, target_court_organ_id, text_value, numeric_value, currency_code, date_value, duration_value, duration_unit, percentage_value) = 0)) OR ((object_type = 'court_organ'::text) AND (target_court_organ_id IS NOT NULL) AND (num_nonnulls(target_claim_id, target_party_role_id, target_proceeding_id, target_decision_id, target_proposition_id, target_provision_id, target_court_id, text_value, numeric_value, currency_code, date_value, duration_value, duration_unit, percentage_value) = 0)) OR ((object_type = 'text'::text) AND (btrim(COALESCE(text_value, ''::text)) <> ''::text) AND (num_nonnulls(target_claim_id, target_party_role_id, target_proceeding_id, target_decision_id, target_proposition_id, target_provision_id, target_court_id, target_court_organ_id, numeric_value, currency_code, date_value, duration_value, duration_unit, percentage_value) = 0)) OR ((object_type = 'number'::text) AND (numeric_value IS NOT NULL) AND (num_nonnulls(target_claim_id, target_party_role_id, target_proceeding_id, target_decision_id, target_proposition_id, target_provision_id, target_court_id, target_court_organ_id, text_value, currency_code, date_value, duration_value, duration_unit, percentage_value) = 0)) OR ((object_type = 'money'::text) AND (numeric_value IS NOT NULL) AND (currency_code IS NOT NULL) AND (num_nonnulls(target_claim_id, target_party_role_id, target_proceeding_id, target_decision_id, target_proposition_id, target_provision_id, target_court_id, target_court_organ_id, text_value, date_value, duration_value, duration_unit, percentage_value) = 0)) OR ((object_type = 'date'::text) AND (date_value IS NOT NULL) AND (num_nonnulls(target_claim_id, target_party_role_id, target_proceeding_id, target_decision_id, target_proposition_id, target_provision_id, target_court_id, target_court_organ_id, text_value, numeric_value, currency_code, duration_value, duration_unit, percentage_value) = 0)) OR ((object_type = 'duration'::text) AND (duration_value IS NOT NULL) AND (duration_unit IS NOT NULL) AND (num_nonnulls(target_claim_id, target_party_role_id, target_proceeding_id, target_decision_id, target_proposition_id, target_provision_id, target_court_id, target_court_organ_id, text_value, numeric_value, currency_code, date_value, percentage_value) = 0)) OR ((object_type = 'percentage'::text) AND (percentage_value IS NOT NULL) AND (num_nonnulls(target_claim_id, target_party_role_id, target_proceeding_id, target_decision_id, target_proposition_id, target_provision_id, target_court_id, target_court_organ_id, text_value, numeric_value, currency_code, date_value, duration_value, duration_unit) = 0)))),
    CONSTRAINT disposition_arguments_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: TABLE judicial_disposition_action_arguments; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.judicial_disposition_action_arguments IS 'Typed semantic arguments of a canonical dispositive action. An action may express several roles (object, obligor, beneficiary, destination, amount, condition, etc.); exact source wording remains on the clause/action and optional raw_argument_text.';


--
-- Name: judicial_disposition_actions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_disposition_actions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    disposition_id uuid NOT NULL,
    effect_concept_id uuid NOT NULL,
    ordinal integer NOT NULL,
    condition_text text,
    raw_action_text text,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT judicial_disposition_actions_ordinal_check CHECK ((ordinal > 0)),
    CONSTRAINT judicial_disposition_actions_verification_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: TABLE judicial_disposition_actions; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.judicial_disposition_actions IS 'Canonical actions expressed by a textual disposition clause; one clause may have many actions and one action may have many targets. V3 compatibility-backfill duplicates are removed by 0038.';


--
-- Name: judicial_event_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_event_type_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    broader_concept_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT judicial_event_type_concepts_check CHECK (((broader_concept_id IS NULL) OR (broader_concept_id <> id))),
    CONSTRAINT judicial_event_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT judicial_event_type_concepts_name_check CHECK ((btrim(name) <> ''::text))
);


--
-- Name: TABLE judicial_event_type_concepts; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.judicial_event_type_concepts IS 'Open point-event vocabulary. Legal states such as finality/res judicata remain separate in decision_legal_states.';


--
-- Name: judicial_officer_position_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_officer_position_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT judicial_officer_position_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT judicial_officer_position_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: judicial_officer_positions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_officer_positions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    officer_id uuid NOT NULL,
    court_id uuid NOT NULL,
    position_type text NOT NULL,
    title_raw text,
    valid_from date,
    valid_to date,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT judicial_officer_positions_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT judicial_officer_positions_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN judicial_officer_positions.position_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.judicial_officer_positions.position_type IS 'Extensible legal-domain code; FK to corpus.judicial_officer_position_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: judicial_officers; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_officers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    display_name text NOT NULL,
    normalized_name text,
    identity_status text DEFAULT 'identity_unresolved'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    legal_entity_id uuid NOT NULL,
    CONSTRAINT judicial_officers_identity_status_check CHECK ((identity_status = ANY (ARRAY['canonical'::text, 'probable_duplicate'::text, 'identity_unresolved'::text, 'merged_with_canonical'::text]))),
    CONSTRAINT judicial_officers_name_nonempty CHECK ((btrim(display_name) <> ''::text))
);


--
-- Name: judicial_opinion_authors; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_opinion_authors (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    opinion_id uuid NOT NULL,
    case_id uuid NOT NULL,
    officer_id uuid NOT NULL,
    authorship_role text DEFAULT 'author'::text NOT NULL,
    ordinal integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT judicial_opinion_authors_ordinal_check CHECK (((ordinal IS NULL) OR (ordinal > 0)))
);


--
-- Name: COLUMN judicial_opinion_authors.authorship_role; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.judicial_opinion_authors.authorship_role IS 'Extensible legal-domain code; FK to corpus.judicial_authorship_role_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: judicial_opinion_join_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_opinion_join_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT judicial_opinion_join_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT judicial_opinion_join_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: judicial_opinion_joiners; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_opinion_joiners (
    opinion_id uuid NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    officer_id uuid NOT NULL,
    join_type text DEFAULT 'joins_all'::text NOT NULL,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    case_id uuid NOT NULL
);


--
-- Name: COLUMN judicial_opinion_joiners.join_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.judicial_opinion_joiners.join_type IS 'Extensible legal-domain code; FK to corpus.judicial_opinion_join_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: judicial_opinion_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_opinion_type_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    broader_concept_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT judicial_opinion_type_concepts_check CHECK (((broader_concept_id IS NULL) OR (broader_concept_id <> id))),
    CONSTRAINT judicial_opinion_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT judicial_opinion_type_concepts_name_check CHECK ((btrim(name) <> ''::text))
);


--
-- Name: judicial_opinions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_opinions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    case_id uuid NOT NULL,
    document_id uuid,
    proposition_id uuid,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    opinion_type_concept_id uuid NOT NULL,
    CONSTRAINT judicial_opinions_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: judicial_stance_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_stance_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    broader_concept_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT judicial_stance_concepts_check CHECK (((broader_concept_id IS NULL) OR (broader_concept_id <> id))),
    CONSTRAINT judicial_stance_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT judicial_stance_concepts_name_check CHECK ((btrim(name) <> ''::text))
);


--
-- Name: judicial_system_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_system_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT judicial_system_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT judicial_system_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: judicial_vote_stances; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_vote_stances (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    vote_id uuid NOT NULL,
    case_id uuid NOT NULL,
    officer_id uuid NOT NULL,
    scope_type text NOT NULL,
    opinion_id uuid,
    proposition_id uuid,
    disposition_id uuid,
    raw_stance text,
    note text,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    stance_concept_id uuid NOT NULL,
    CONSTRAINT judicial_vote_stances_check CHECK ((((scope_type = 'whole_decision'::text) AND (opinion_id IS NULL) AND (proposition_id IS NULL) AND (disposition_id IS NULL)) OR ((scope_type = 'opinion'::text) AND (opinion_id IS NOT NULL) AND (proposition_id IS NULL) AND (disposition_id IS NULL)) OR ((scope_type = 'proposition'::text) AND (opinion_id IS NULL) AND (proposition_id IS NOT NULL) AND (disposition_id IS NULL)) OR ((scope_type = 'disposition'::text) AND (opinion_id IS NULL) AND (proposition_id IS NULL) AND (disposition_id IS NOT NULL)))),
    CONSTRAINT judicial_vote_stances_scope_type_check CHECK ((scope_type = ANY (ARRAY['whole_decision'::text, 'opinion'::text, 'proposition'::text, 'disposition'::text]))),
    CONSTRAINT judicial_vote_stances_verification_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: judicial_vote_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.judicial_vote_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT judicial_vote_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT judicial_vote_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: jurisdictions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.jurisdictions (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT jurisdictions_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT jurisdictions_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_amendment_effect_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_amendment_effect_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_amendment_effect_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_amendment_effect_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_amendment_effects; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_amendment_effects (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    source_instrument_id uuid NOT NULL,
    source_version_id uuid,
    target_instrument_id uuid NOT NULL,
    target_provision_id uuid,
    effect_type text NOT NULL,
    effective_on date,
    raw_effect_text text,
    source_document_id uuid,
    evidence_artifact_page_id uuid,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_amendment_effects_other_text_check CHECK (((effect_type <> 'other'::text) OR (btrim(COALESCE(raw_effect_text, ''::text)) <> ''::text))),
    CONSTRAINT legal_amendment_effects_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: TABLE legal_amendment_effects; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_amendment_effects IS 'Evidence-bearing legal effect caused by one instrument upon another instrument or provision. An amending law remains its own instrument rather than being collapsed into the target version.';


--
-- Name: COLUMN legal_amendment_effects.effect_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_amendment_effects.effect_type IS 'Extensible legal-domain code; FK to corpus.legal_amendment_effect_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_amendment_operation_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_amendment_operation_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_amendment_operation_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_amendment_operation_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_amendment_operations; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_amendment_operations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    amendment_effect_id uuid NOT NULL,
    target_provision_version_id uuid NOT NULL,
    sequence_number integer NOT NULL,
    operation_type text NOT NULL,
    char_start integer,
    char_end integer,
    anchor_text text,
    replacement_text text,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_amendment_operations_anchor_check CHECK (((char_start IS NOT NULL) OR (btrim(COALESCE(anchor_text, ''::text)) <> ''::text) OR (operation_type = ANY (ARRAY['renumber'::text, 'whole_provision_replace'::text])))),
    CONSTRAINT legal_amendment_operations_offsets_check CHECK ((((char_start IS NULL) AND (char_end IS NULL)) OR ((char_start IS NOT NULL) AND (char_end IS NOT NULL) AND (char_start >= 0) AND (char_end >= char_start)))),
    CONSTRAINT legal_amendment_operations_sequence_check CHECK ((sequence_number > 0)),
    CONSTRAINT legal_amendment_operations_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN legal_amendment_operations.operation_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_amendment_operations.operation_type IS 'Extensible legal-domain code; FK to corpus.legal_amendment_operation_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_authorities; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_authorities (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    authority_type text NOT NULL,
    canonical_name text NOT NULL,
    normalized_name text,
    country_code character(2) DEFAULT 'DO'::bpchar NOT NULL,
    jurisdiction_code text,
    identity_status text DEFAULT 'identity_unresolved'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    legal_entity_id uuid NOT NULL,
    CONSTRAINT legal_authorities_country_check CHECK ((country_code ~ '^[A-Z]{2}$'::text)),
    CONSTRAINT legal_authorities_identity_status_check CHECK ((identity_status = ANY (ARRAY['canonical'::text, 'probable_duplicate'::text, 'identity_unresolved'::text, 'merged_with_canonical'::text]))),
    CONSTRAINT legal_authorities_name_nonempty CHECK ((btrim(canonical_name) <> ''::text))
);


--
-- Name: COLUMN legal_authorities.authority_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_authorities.authority_type IS 'Extensible legal-domain code; FK to corpus.legal_authority_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_authority_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_authority_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_authority_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_authority_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_claim_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_claim_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    jurisdiction_code text,
    broader_concept_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_claim_concepts_check CHECK (((broader_concept_id IS NULL) OR (broader_concept_id <> id))),
    CONSTRAINT legal_claim_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_claim_concepts_name_check CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_claims; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_claims (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    proceeding_id uuid NOT NULL,
    asserted_by_party_role_id uuid,
    parent_claim_id uuid,
    claim_concept_id uuid NOT NULL,
    claim_text text NOT NULL,
    introduced_on date,
    ordinal integer,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_claims_check CHECK (((parent_claim_id IS NULL) OR (parent_claim_id <> id))),
    CONSTRAINT legal_claims_claim_text_check CHECK ((btrim(claim_text) <> ''::text)),
    CONSTRAINT legal_claims_ordinal_check CHECK (((ordinal IS NULL) OR (ordinal > 0))),
    CONSTRAINT legal_claims_verification_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: legal_concept_aliases; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_concept_aliases (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    concept_id uuid NOT NULL,
    alias text NOT NULL,
    normalized_alias text,
    language_code text,
    source_note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_concept_aliases_alias_nonempty CHECK ((btrim(alias) <> ''::text)),
    CONSTRAINT legal_concept_aliases_language_check CHECK (((language_code IS NULL) OR (language_code ~ '^[a-z]{2,3}(-[A-Z]{2})?$'::text)))
);


--
-- Name: legal_concept_edges; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_concept_edges (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_concept_id uuid NOT NULL,
    relation_type text NOT NULL,
    target_concept_id uuid NOT NULL,
    valid_from date,
    valid_to date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_concept_edges_distinct_check CHECK ((source_concept_id <> target_concept_id)),
    CONSTRAINT legal_concept_edges_relation_check CHECK ((relation_type = ANY (ARRAY['broader'::text, 'narrower'::text, 'equivalent'::text, 'close_match'::text, 'related'::text, 'historical_successor'::text, 'derived_from'::text]))),
    CONSTRAINT legal_concept_edges_valid_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from)))
);


--
-- Name: legal_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scheme_code text NOT NULL,
    jurisdiction_code text,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    valid_from date,
    valid_to date,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_concepts_metadata_object_check CHECK ((jsonb_typeof(metadata) = 'object'::text)),
    CONSTRAINT legal_concepts_name_nonempty CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT legal_concepts_valid_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from)))
);


--
-- Name: TABLE legal_concepts; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_concepts IS 'Cross-jurisdiction concept identities grouped by scheme. Equal source wording across jurisdictions does not imply identity; jurisdiction-specific concepts may share a code and be connected through legal_concept_edges.';


--
-- Name: legal_controversies; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_controversies (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    country_code character(2) DEFAULT 'DO'::bpchar NOT NULL,
    canonical_title text,
    status text DEFAULT 'unknown'::text NOT NULL,
    identity_status text DEFAULT 'identity_unresolved'::text NOT NULL,
    opened_on date,
    closed_on date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_controversies_country_code_check CHECK ((country_code ~ '^[A-Z]{2}$'::text)),
    CONSTRAINT legal_controversies_date_range_check CHECK (((closed_on IS NULL) OR (opened_on IS NULL) OR (closed_on >= opened_on))),
    CONSTRAINT legal_controversies_identity_status_check CHECK ((identity_status = ANY (ARRAY['canonical'::text, 'probable_duplicate'::text, 'identity_unresolved'::text, 'merged_with_canonical'::text])))
);


--
-- Name: TABLE legal_controversies; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_controversies IS 'A real-world dispute or litigation family that may span multiple court-specific proceedings/expedientes. It is not itself a judicial decision.';


--
-- Name: COLUMN legal_controversies.status; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_controversies.status IS 'Extensible legal-domain code; FK to corpus.legal_controversy_status_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_controversy_status_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_controversy_status_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_controversy_status_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_controversy_status_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_document_artifact_occurrences; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_document_artifact_occurrences (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_id uuid NOT NULL,
    artifact_id uuid NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    occurrence_kind text DEFAULT 'whole_artifact'::text NOT NULL,
    start_page integer,
    end_page integer,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text DEFAULT 'deterministic_source_mapping'::text NOT NULL,
    verification_confidence real,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_document_occurrence_confidence_check CHECK (((verification_confidence IS NULL) OR ((verification_confidence >= (0)::double precision) AND (verification_confidence <= (1)::double precision)))),
    CONSTRAINT legal_document_occurrence_kind_check CHECK ((occurrence_kind = ANY (ARRAY['whole_artifact'::text, 'page_range'::text]))),
    CONSTRAINT legal_document_occurrence_pages_check CHECK ((((occurrence_kind = 'whole_artifact'::text) AND (start_page IS NULL) AND (end_page IS NULL)) OR ((occurrence_kind = 'page_range'::text) AND (start_page > 0) AND (end_page >= start_page)))),
    CONSTRAINT legal_document_occurrence_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'ambiguous'::text, 'rejected'::text])))
);


--
-- Name: TABLE legal_document_artifact_occurrences; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_document_artifact_occurrences IS 'Maps one canonical legal document to the exact immutable source artifact or page range in which it appears.';


--
-- Name: legal_document_identifiers; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_document_identifiers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_id uuid NOT NULL,
    identifier_type text NOT NULL,
    raw_value text NOT NULL,
    normalized_value text,
    source_registry_id uuid,
    is_primary boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_document_identifiers_raw_nonempty CHECK ((btrim(raw_value) <> ''::text)),
    CONSTRAINT legal_document_identifiers_type_nonempty CHECK ((btrim(identifier_type) <> ''::text))
);


--
-- Name: legal_document_provisions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_document_provisions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_id uuid NOT NULL,
    parent_provision_id uuid,
    provision_type text NOT NULL,
    label text,
    normalized_label text,
    ordinal integer,
    heading text,
    text text,
    effective_from date,
    effective_to date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_document_provisions_effective_range_check CHECK (((effective_to IS NULL) OR (effective_from IS NULL) OR (effective_to >= effective_from))),
    CONSTRAINT legal_document_provisions_ordinal_check CHECK (((ordinal IS NULL) OR (ordinal > 0)))
);


--
-- Name: COLUMN legal_document_provisions.provision_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_document_provisions.provision_type IS 'Extensible legal-domain code; FK to corpus.provision_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_document_tags; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_document_tags (
    document_id uuid NOT NULL,
    tag_id uuid NOT NULL,
    provenance text NOT NULL,
    confidence real,
    evidence_artifact_page_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_document_tags_confidence_check CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT legal_document_tags_provenance_check CHECK ((provenance = ANY (ARRAY['source_provided'::text, 'deterministic'::text, 'agent_extracted'::text, 'human_reviewed'::text])))
);


--
-- Name: TABLE legal_document_tags; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_document_tags IS 'Classification metadata only. Tags describe subject or category and must not substitute for typed legal relations.';


--
-- Name: legal_document_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_document_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_document_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_document_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_documents; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_documents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    document_type text NOT NULL,
    country_code character(2) DEFAULT 'DO'::bpchar NOT NULL,
    jurisdiction_code text,
    issuing_authority text,
    title text,
    document_number text,
    document_date date,
    effective_from date,
    effective_to date,
    language text DEFAULT 'es'::text NOT NULL,
    identity_status text DEFAULT 'identity_unresolved'::text NOT NULL,
    quality_status text DEFAULT 'unreviewed'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_documents_country_code_check CHECK ((country_code ~ '^[A-Z]{2}$'::text)),
    CONSTRAINT legal_documents_effective_range_check CHECK (((effective_to IS NULL) OR (effective_from IS NULL) OR (effective_to >= effective_from))),
    CONSTRAINT legal_documents_identity_status_check CHECK ((identity_status = ANY (ARRAY['canonical'::text, 'probable_duplicate'::text, 'identity_unresolved'::text, 'merged_with_canonical'::text]))),
    CONSTRAINT legal_documents_quality_status_check CHECK ((quality_status = ANY (ARRAY['unreviewed'::text, 'searchable'::text, 'quality_review_required'::text, 'blocked'::text])))
);


--
-- Name: TABLE legal_documents; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_documents IS 'Canonical legal-document superclass for judicial and non-judicial material. Source bytes remain immutable in source_artifacts; this table represents the legal work embodied by those bytes.';


--
-- Name: COLUMN legal_documents.document_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_documents.document_type IS 'Extensible legal-domain code; FK to corpus.legal_document_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_entities; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_entities (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    entity_kind text NOT NULL,
    canonical_name text NOT NULL,
    normalized_name text,
    country_code character(2),
    identity_status text DEFAULT 'identity_unresolved'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_entities_canonical_name_check CHECK ((btrim(canonical_name) <> ''::text)),
    CONSTRAINT legal_entities_country_code_check CHECK (((country_code IS NULL) OR (country_code ~ '^[A-Z]{2}$'::text))),
    CONSTRAINT legal_entities_entity_kind_check CHECK ((entity_kind = ANY (ARRAY['person'::text, 'organization'::text, 'court'::text, 'public_body'::text, 'international_body'::text, 'other'::text]))),
    CONSTRAINT legal_entities_identity_status_check CHECK ((identity_status = ANY (ARRAY['canonical'::text, 'probable_duplicate'::text, 'identity_unresolved'::text, 'merged_with_canonical'::text])))
);


--
-- Name: COLUMN legal_entities.identity_status; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_entities.identity_status IS 'Coarse workflow summary only. Canonical cross-entity identity decisions live in entity_identity_assertions and entity_identity_resolutions.';


--
-- Name: legal_instrument_authority_roles; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_instrument_authority_roles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    instrument_id uuid NOT NULL,
    authority_id uuid NOT NULL,
    authority_role text NOT NULL,
    valid_from date,
    valid_to date,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_instrument_authority_roles_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT legal_instrument_authority_roles_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN legal_instrument_authority_roles.authority_role; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_instrument_authority_roles.authority_role IS 'Extensible legal-domain code; FK to corpus.instrument_authority_role_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_instrument_event_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_instrument_event_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_instrument_event_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_instrument_event_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_instrument_events; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_instrument_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    instrument_id uuid NOT NULL,
    event_type text NOT NULL,
    occurred_on date,
    date_status text DEFAULT 'unknown'::text NOT NULL,
    source_document_id uuid,
    evidence_artifact_page_id uuid,
    raw_description text,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_instrument_events_date_status_check CHECK ((date_status = ANY (ARRAY['verified_primary_text'::text, 'verified_official_metadata'::text, 'parsed_high_confidence'::text, 'parsed_unverified'::text, 'conflicting'::text, 'unknown'::text]))),
    CONSTRAINT legal_instrument_events_other_description_check CHECK (((event_type <> 'other'::text) OR (btrim(COALESCE(raw_description, ''::text)) <> ''::text))),
    CONSTRAINT legal_instrument_events_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT legal_instrument_events_verified_date_requires_date CHECK (((date_status <> ALL (ARRAY['verified_primary_text'::text, 'verified_official_metadata'::text, 'parsed_high_confidence'::text])) OR (occurred_on IS NOT NULL)))
);


--
-- Name: COLUMN legal_instrument_events.event_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_instrument_events.event_type IS 'Extensible legal-domain code; FK to corpus.legal_instrument_event_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_instrument_identifiers; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_instrument_identifiers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    instrument_id uuid NOT NULL,
    identifier_type text NOT NULL,
    raw_value text NOT NULL,
    normalized_value text,
    source_registry_id uuid,
    is_primary boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_instrument_identifiers_type_nonempty CHECK ((btrim(identifier_type) <> ''::text)),
    CONSTRAINT legal_instrument_identifiers_value_nonempty CHECK ((btrim(raw_value) <> ''::text))
);


--
-- Name: legal_instrument_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_instrument_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_instrument_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_instrument_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_instrument_version_documents; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_instrument_version_documents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    instrument_version_id uuid NOT NULL,
    document_id uuid NOT NULL,
    document_role text NOT NULL,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_instrument_version_documents_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN legal_instrument_version_documents.document_role; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_instrument_version_documents.document_role IS 'Extensible legal-domain code; FK to corpus.instrument_document_role_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_instrument_version_knowledge; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_instrument_version_knowledge (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    instrument_version_id uuid NOT NULL,
    valid_from date,
    valid_to date,
    known_from timestamp with time zone NOT NULL,
    known_to timestamp with time zone,
    asserted_status text DEFAULT 'candidate'::text NOT NULL,
    assertion_method text NOT NULL,
    source_document_id uuid,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_instrument_version_knowledge_known_range_check CHECK (((known_to IS NULL) OR (known_to > known_from))),
    CONSTRAINT legal_instrument_version_knowledge_status_check CHECK ((asserted_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT legal_instrument_version_knowledge_valid_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from)))
);


--
-- Name: TABLE legal_instrument_version_knowledge; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_instrument_version_knowledge IS 'Bitemporal legal-version assertions: valid_* is legal time and known_* is JurisNexo knowledge time.';


--
-- Name: legal_instrument_versions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_instrument_versions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    instrument_id uuid NOT NULL,
    version_kind text NOT NULL,
    version_label text,
    valid_from date,
    valid_to date,
    version_status text DEFAULT 'candidate'::text NOT NULL,
    derivation_method text NOT NULL,
    derived_from_version_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_instrument_versions_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT legal_instrument_versions_status_check CHECK ((version_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'superseded'::text, 'withdrawn'::text])))
);


--
-- Name: TABLE legal_instrument_versions; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_instrument_versions IS 'Temporal/legal text state of one stable legal instrument. Versions do not replace immutable source documents and may be candidate or derived until verified.';


--
-- Name: COLUMN legal_instrument_versions.version_kind; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_instrument_versions.version_kind IS 'Extensible legal-domain code; FK to corpus.instrument_version_kind_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_instruments; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_instruments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    instrument_type text NOT NULL,
    country_code character(2) DEFAULT 'DO'::bpchar NOT NULL,
    jurisdiction_code text,
    canonical_title text,
    issuing_authority_raw text,
    identity_status text DEFAULT 'identity_unresolved'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_instruments_country_check CHECK ((country_code ~ '^[A-Z]{2}$'::text)),
    CONSTRAINT legal_instruments_identity_status_check CHECK ((identity_status = ANY (ARRAY['canonical'::text, 'probable_duplicate'::text, 'identity_unresolved'::text, 'merged_with_canonical'::text])))
);


--
-- Name: TABLE legal_instruments; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_instruments IS 'Stable identity of a normative legal instrument. It is distinct from any one publication, consolidated text, or temporal version.';


--
-- Name: COLUMN legal_instruments.instrument_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_instruments.instrument_type IS 'Extensible legal-domain code; FK to corpus.legal_instrument_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_issue_evidence; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_issue_evidence (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    issue_id uuid NOT NULL,
    source_decision_id uuid,
    source_document_id uuid,
    case_page_id uuid,
    artifact_page_id uuid,
    exact_excerpt text,
    char_start integer,
    char_end integer,
    extraction_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_issue_evidence_offsets_check CHECK ((((char_start IS NULL) AND (char_end IS NULL)) OR ((char_start IS NOT NULL) AND (char_end IS NOT NULL) AND (char_start >= 0) AND (char_end > char_start)))),
    CONSTRAINT legal_issue_evidence_page_requires_decision CHECK (((case_page_id IS NULL) OR (source_decision_id IS NOT NULL))),
    CONSTRAINT legal_issue_evidence_presence_check CHECK (((source_decision_id IS NOT NULL) OR (source_document_id IS NOT NULL) OR (artifact_page_id IS NOT NULL)))
);


--
-- Name: legal_issue_subjects; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_issue_subjects (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    issue_id uuid NOT NULL,
    relation_scheme_code text DEFAULT 'legal_issue_relation'::text NOT NULL,
    relation_concept_id uuid NOT NULL,
    subject_type text NOT NULL,
    judicial_decision_id uuid,
    proceeding_id uuid,
    claim_id uuid,
    proposition_id uuid,
    ordinal integer,
    raw_relation text,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_issue_subjects_ordinal_check CHECK (((ordinal IS NULL) OR (ordinal > 0))),
    CONSTRAINT legal_issue_subjects_scheme_check CHECK ((relation_scheme_code = 'legal_issue_relation'::text)),
    CONSTRAINT legal_issue_subjects_shape_check CHECK ((((subject_type = 'judicial_decision'::text) AND (judicial_decision_id IS NOT NULL) AND (proceeding_id IS NULL) AND (claim_id IS NULL) AND (proposition_id IS NULL)) OR ((subject_type = 'proceeding'::text) AND (judicial_decision_id IS NULL) AND (proceeding_id IS NOT NULL) AND (claim_id IS NULL) AND (proposition_id IS NULL)) OR ((subject_type = 'claim'::text) AND (judicial_decision_id IS NULL) AND (proceeding_id IS NULL) AND (claim_id IS NOT NULL) AND (proposition_id IS NULL)) OR ((subject_type = 'proposition'::text) AND (judicial_decision_id IS NULL) AND (proceeding_id IS NULL) AND (claim_id IS NULL) AND (proposition_id IS NOT NULL)))),
    CONSTRAINT legal_issue_subjects_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT legal_issue_subjects_type_check CHECK ((subject_type = ANY (ARRAY['judicial_decision'::text, 'proceeding'::text, 'claim'::text, 'proposition'::text])))
);


--
-- Name: legal_issues; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_issues (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    canonical_question text NOT NULL,
    normalized_question text,
    assertion_kind text NOT NULL,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    extraction_confidence real,
    semantic_confidence real,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_issues_assertion_kind_check CHECK ((assertion_kind = ANY (ARRAY['explicit_primary_text'::text, 'derived_from_primary_text'::text, 'synthesized_interpretation'::text, 'human_authored'::text]))),
    CONSTRAINT legal_issues_extraction_confidence_check CHECK (((extraction_confidence IS NULL) OR ((extraction_confidence >= (0)::double precision) AND (extraction_confidence <= (1)::double precision)))),
    CONSTRAINT legal_issues_question_nonempty CHECK ((btrim(canonical_question) <> ''::text)),
    CONSTRAINT legal_issues_semantic_confidence_check CHECK (((semantic_confidence IS NULL) OR ((semantic_confidence >= (0)::double precision) AND (semantic_confidence <= (1)::double precision)))),
    CONSTRAINT legal_issues_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: TABLE legal_issues; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_issues IS 'Canonical legal questions/issues. An issue is not a claim, holding or topic tag. Its wording is immutable; competing formulations coexist until resolved rather than being silently rewritten.';


--
-- Name: legal_matter_concept_edges; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_matter_concept_edges (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    narrower_concept_id uuid NOT NULL,
    broader_concept_id uuid NOT NULL,
    relation_type text DEFAULT 'broader'::text NOT NULL,
    verification_status text DEFAULT 'verified'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_matter_concept_edges_distinct_check CHECK ((narrower_concept_id <> broader_concept_id)),
    CONSTRAINT legal_matter_concept_edges_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN legal_matter_concept_edges.relation_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_matter_concept_edges.relation_type IS 'Extensible legal-domain code; FK to corpus.matter_taxonomy_relation_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_matter_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_matter_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    jurisdiction_code text,
    active_from date,
    active_to date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_matter_concepts_active_range_check CHECK (((active_to IS NULL) OR (active_from IS NULL) OR (active_to >= active_from))),
    CONSTRAINT legal_matter_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_matter_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_norm_assertions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_norm_assertions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    proposition_id uuid NOT NULL,
    jurisdiction_code text,
    norm_kind text NOT NULL,
    derivation_kind text NOT NULL,
    valid_from date,
    valid_to date,
    known_from timestamp with time zone DEFAULT now() NOT NULL,
    known_to timestamp with time zone,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    reviewed_by text,
    review_note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    norm_claim_id uuid NOT NULL,
    CONSTRAINT legal_norm_assertions_derivation_check CHECK ((derivation_kind = ANY (ARRAY['explicit_primary_text'::text, 'derived_from_sources'::text, 'synthesized_interpretation'::text, 'human_legal_analysis'::text]))),
    CONSTRAINT legal_norm_assertions_kind_check CHECK ((btrim(norm_kind) <> ''::text)),
    CONSTRAINT legal_norm_assertions_known_range_check CHECK (((known_to IS NULL) OR (known_to > known_from))),
    CONSTRAINT legal_norm_assertions_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT legal_norm_assertions_valid_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from)))
);


--
-- Name: TABLE legal_norm_assertions; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_norm_assertions IS 'Epistemic and temporal assertion that a legal proposition functions as a norm/requirement; the proposition text is not treated as promulgated canonical text unless evidence says so.';


--
-- Name: legal_norm_claims; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_norm_claims (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    proposition_id uuid NOT NULL,
    jurisdiction_code text,
    norm_kind text NOT NULL,
    legal_matter_concept_id uuid,
    valid_from date,
    valid_to date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_norm_claims_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT legal_norm_claims_norm_kind_check CHECK ((btrim(norm_kind) <> ''::text))
);


--
-- Name: TABLE legal_norm_claims; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_norm_claims IS 'Contextual norm identity; legal_norm_assertions is the bitemporal epistemic history for that claim.';


--
-- Name: legal_norm_source_role_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_norm_source_role_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_norm_source_role_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_norm_source_role_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_norm_sources; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_norm_sources (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    norm_assertion_id uuid NOT NULL,
    source_document_id uuid NOT NULL,
    source_document_provision_id uuid,
    source_role text NOT NULL,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    evidence_artifact_page_id uuid,
    evidence_excerpt text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    assertion_scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    CONSTRAINT legal_norm_sources_scope_match_check CHECK ((scope_id = assertion_scope_id)),
    CONSTRAINT legal_norm_sources_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: TABLE legal_norm_sources; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_norm_sources IS 'Typed legal-source support for a derived norm assertion. It preserves establishes/defines/exception/interprets semantics without treating synthesized norm text as primary-source text.';


--
-- Name: COLUMN legal_norm_sources.source_role; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_norm_sources.source_role IS 'Extensible legal-domain code; FK to corpus.legal_norm_source_role_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_proceeding_status_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_proceeding_status_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_proceeding_status_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_proceeding_status_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_proceedings; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_proceedings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    country_code character(2) DEFAULT 'DO'::bpchar NOT NULL,
    jurisdiction_code text,
    originating_court_id uuid,
    legal_matter_concept_id uuid,
    procedure_concept_id uuid,
    canonical_title text,
    filing_date date,
    closed_date date,
    status text DEFAULT 'unknown'::text NOT NULL,
    identity_status text DEFAULT 'identity_unresolved'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_proceedings_country_code_check CHECK ((country_code ~ '^[A-Z]{2}$'::text)),
    CONSTRAINT legal_proceedings_date_range_check CHECK (((closed_date IS NULL) OR (filing_date IS NULL) OR (closed_date >= filing_date))),
    CONSTRAINT legal_proceedings_identity_status_check CHECK ((identity_status = ANY (ARRAY['canonical'::text, 'probable_duplicate'::text, 'identity_unresolved'::text, 'merged_with_canonical'::text])))
);


--
-- Name: TABLE legal_proceedings; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_proceedings IS 'Underlying judicial proceeding or expediente. A proceeding may contain multiple judicial decisions and a decision may participate in multiple proceedings when consolidation or review requires it.';


--
-- Name: COLUMN legal_proceedings.status; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_proceedings.status IS 'Extensible legal-domain code; FK to corpus.legal_proceeding_status_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_proposition_evidence; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_proposition_evidence (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    proposition_id uuid NOT NULL,
    source_case_id uuid,
    source_document_id uuid,
    case_page_id uuid,
    artifact_page_id uuid,
    evidence_role text DEFAULT 'supports'::text NOT NULL,
    exact_excerpt text,
    char_start integer,
    char_end integer,
    extraction_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_proposition_evidence_case_page_shape_check CHECK (((case_page_id IS NULL) OR (source_case_id IS NOT NULL))),
    CONSTRAINT legal_proposition_evidence_offsets_check CHECK ((((char_start IS NULL) AND (char_end IS NULL)) OR ((char_start IS NOT NULL) AND (char_end IS NOT NULL) AND (char_start >= 0) AND (char_end > char_start)))),
    CONSTRAINT legal_proposition_evidence_source_check CHECK (((source_case_id IS NOT NULL) OR (source_document_id IS NOT NULL) OR (artifact_page_id IS NOT NULL)))
);


--
-- Name: COLUMN legal_proposition_evidence.evidence_role; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_proposition_evidence.evidence_role IS 'Extensible legal-domain code; FK to corpus.legal_proposition_evidence_role_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_proposition_evidence_role_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_proposition_evidence_role_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_proposition_evidence_role_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_proposition_evidence_role_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_proposition_relation_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_proposition_relation_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_proposition_relation_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_proposition_relation_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_proposition_relations; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_proposition_relations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    from_proposition_id uuid NOT NULL,
    relation_type text NOT NULL,
    to_proposition_id uuid NOT NULL,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    evidence_note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_proposition_relations_distinct_check CHECK ((from_proposition_id <> to_proposition_id)),
    CONSTRAINT legal_proposition_relations_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN legal_proposition_relations.relation_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_proposition_relations.relation_type IS 'Extensible legal-domain code; FK to corpus.legal_proposition_relation_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_proposition_subjects; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_proposition_subjects (
    proposition_id uuid NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    subject_type text NOT NULL,
    judicial_decision_id uuid,
    legal_document_id uuid,
    proceeding_id uuid,
    provision_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    subject_role text DEFAULT 'about'::text NOT NULL,
    ordinal integer,
    CONSTRAINT legal_proposition_subjects_ordinal_check CHECK (((ordinal IS NULL) OR (ordinal > 0))),
    CONSTRAINT legal_proposition_subjects_role_nonempty CHECK ((btrim(subject_role) <> ''::text)),
    CONSTRAINT legal_proposition_subjects_shape_check CHECK ((((subject_type = 'judicial_decision'::text) AND (judicial_decision_id IS NOT NULL) AND (legal_document_id IS NULL) AND (proceeding_id IS NULL) AND (provision_id IS NULL)) OR ((subject_type = 'legal_document'::text) AND (judicial_decision_id IS NULL) AND (legal_document_id IS NOT NULL) AND (proceeding_id IS NULL) AND (provision_id IS NULL)) OR ((subject_type = 'proceeding'::text) AND (judicial_decision_id IS NULL) AND (legal_document_id IS NULL) AND (proceeding_id IS NOT NULL) AND (provision_id IS NULL)) OR ((subject_type = 'provision'::text) AND (judicial_decision_id IS NULL) AND (legal_document_id IS NULL) AND (proceeding_id IS NULL) AND (provision_id IS NOT NULL)) OR ((subject_type = 'general_law'::text) AND (judicial_decision_id IS NULL) AND (legal_document_id IS NULL) AND (proceeding_id IS NULL) AND (provision_id IS NULL)))),
    CONSTRAINT legal_proposition_subjects_type_check CHECK ((subject_type = ANY (ARRAY['judicial_decision'::text, 'legal_document'::text, 'proceeding'::text, 'provision'::text, 'general_law'::text])))
);


--
-- Name: TABLE legal_proposition_subjects; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_proposition_subjects IS 'N:N subjects for an immutable proposition; multiple subjects of the same type are valid.';


--
-- Name: legal_propositions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_propositions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    proposition_type text NOT NULL,
    canonical_text text NOT NULL,
    normalized_text text,
    assertion_kind text NOT NULL,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    confidence real,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_propositions_assertion_kind_check CHECK ((assertion_kind = ANY (ARRAY['explicit_primary_text'::text, 'derived_from_primary_text'::text, 'synthesized_interpretation'::text, 'human_authored'::text]))),
    CONSTRAINT legal_propositions_confidence_check CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT legal_propositions_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT legal_propositions_text_nonempty CHECK ((btrim(canonical_text) <> ''::text)),
    CONSTRAINT legal_propositions_type_check CHECK ((proposition_type = ANY (ARRAY['holding'::text, 'legal_rule'::text, 'legal_test'::text, 'legal_requirement'::text, 'exception'::text, 'argument'::text, 'counterargument'::text, 'reasoning'::text, 'conclusion'::text, 'dictum'::text, 'other'::text])))
);


--
-- Name: TABLE legal_propositions; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_propositions IS 'Immutable legal/argumentative proposition identity. Legal questions belong in legal_issues; allegations and judicial factual findings belong in factual_propositions; these identities must not be duplicated here.';


--
-- Name: legal_provision_lineage; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_provision_lineage (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    from_provision_id uuid NOT NULL,
    to_provision_id uuid NOT NULL,
    lineage_type text NOT NULL,
    effective_on date,
    amendment_effect_id uuid,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_provision_lineage_distinct_check CHECK ((from_provision_id <> to_provision_id)),
    CONSTRAINT legal_provision_lineage_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN legal_provision_lineage.lineage_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_provision_lineage.lineage_type IS 'Extensible legal-domain code; FK to corpus.legal_provision_lineage_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_provision_lineage_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_provision_lineage_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_provision_lineage_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_provision_lineage_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_provision_version_knowledge; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_provision_version_knowledge (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    provision_version_id uuid NOT NULL,
    valid_from date,
    valid_to date,
    known_from timestamp with time zone NOT NULL,
    known_to timestamp with time zone,
    heading text,
    text text,
    content_status text DEFAULT 'candidate'::text NOT NULL,
    assertion_method text NOT NULL,
    source_document_id uuid,
    source_document_provision_id uuid,
    exact_excerpt text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_provision_version_knowledge_known_range_check CHECK (((known_to IS NULL) OR (known_to > known_from))),
    CONSTRAINT legal_provision_version_knowledge_source_shape_check CHECK (((source_document_provision_id IS NULL) OR (source_document_id IS NOT NULL))),
    CONSTRAINT legal_provision_version_knowledge_status_check CHECK ((content_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT legal_provision_version_knowledge_valid_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from)))
);


--
-- Name: TABLE legal_provision_version_knowledge; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_provision_version_knowledge IS 'Bitemporal provision text knowledge. Later corrections do not erase what JurisNexo knew earlier.';


--
-- Name: legal_provision_version_sources; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_provision_version_sources (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    instrument_version_id uuid NOT NULL,
    provision_version_id uuid NOT NULL,
    source_document_id uuid NOT NULL,
    source_document_provision_id uuid,
    source_role text DEFAULT 'primary_text'::text NOT NULL,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_provision_version_sources_shape_check CHECK (((source_document_provision_id IS NULL) OR (source_document_id IS NOT NULL))),
    CONSTRAINT legal_provision_version_sources_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN legal_provision_version_sources.source_role; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_provision_version_sources.source_role IS 'Extensible legal-domain code; FK to corpus.provision_source_role_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_provision_versions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_provision_versions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    instrument_id uuid NOT NULL,
    instrument_version_id uuid NOT NULL,
    provision_id uuid NOT NULL,
    parent_provision_id uuid,
    provision_type text NOT NULL,
    label text,
    normalized_label text,
    ordinal integer,
    heading text,
    text text,
    content_status text DEFAULT 'candidate'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_provision_versions_not_self_parent_check CHECK (((parent_provision_id IS NULL) OR (parent_provision_id <> provision_id))),
    CONSTRAINT legal_provision_versions_ordinal_check CHECK (((ordinal IS NULL) OR (ordinal > 0))),
    CONSTRAINT legal_provision_versions_status_check CHECK ((content_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'superseded'::text])))
);


--
-- Name: COLUMN legal_provision_versions.provision_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_provision_versions.provision_type IS 'Extensible legal-domain code; FK to corpus.provision_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_provisions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_provisions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    instrument_id uuid NOT NULL,
    identity_status text DEFAULT 'canonical'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_provisions_identity_status_check CHECK ((identity_status = ANY (ARRAY['canonical'::text, 'probable_duplicate'::text, 'identity_unresolved'::text, 'merged_with_canonical'::text])))
);


--
-- Name: TABLE legal_provisions; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_provisions IS 'Stable identity of a provision within an instrument. Labels, hierarchy, and text belong to provision versions because all may change over time.';


--
-- Name: legal_relation_assertion_evidence; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_relation_assertion_evidence (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    assertion_id uuid NOT NULL,
    observation_id uuid,
    artifact_page_id uuid,
    evidence_kind text NOT NULL,
    evidence_excerpt text,
    evidence_char_start integer,
    evidence_char_end integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_relation_assertion_evidence_kind_check CHECK ((evidence_kind = ANY (ARRAY['primary_text'::text, 'official_metadata'::text, 'deterministic_match'::text, 'manual_review'::text]))),
    CONSTRAINT legal_relation_assertion_evidence_offsets_check CHECK ((((evidence_char_start IS NULL) AND (evidence_char_end IS NULL)) OR ((evidence_char_start IS NOT NULL) AND (evidence_char_end IS NOT NULL) AND (evidence_char_start >= 0) AND (evidence_char_end > evidence_char_start)))),
    CONSTRAINT legal_relation_assertion_evidence_presence_check CHECK (((observation_id IS NOT NULL) OR (artifact_page_id IS NOT NULL)))
);


--
-- Name: legal_relation_assertions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_relation_assertions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    relation_identity_id uuid NOT NULL,
    status text DEFAULT 'verified'::text NOT NULL,
    valid_from date,
    valid_to date,
    known_from timestamp with time zone DEFAULT now() NOT NULL,
    known_to timestamp with time zone,
    verification_method text NOT NULL,
    reviewed_by text,
    promoted_from_observation_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    CONSTRAINT legal_relation_assertions_known_range_check CHECK (((known_to IS NULL) OR (known_to > known_from))),
    CONSTRAINT legal_relation_assertions_status_check CHECK ((status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT legal_relation_assertions_valid_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from)))
);


--
-- Name: TABLE legal_relation_assertions; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_relation_assertions IS 'Time- and knowledge-bounded assertion over a stable structural legal relation identity.';


--
-- Name: legal_relation_identities; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_relation_identities (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_document_id uuid NOT NULL,
    source_provision_id uuid,
    relation_type text NOT NULL,
    target_document_id uuid NOT NULL,
    target_provision_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    CONSTRAINT legal_relation_identities_distinct_check CHECK (((source_document_id <> target_document_id) OR (source_provision_id IS DISTINCT FROM target_provision_id)))
);


--
-- Name: COLUMN legal_relation_identities.relation_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_relation_identities.relation_type IS 'Extensible legal-domain code; FK to corpus.legal_relation_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_relation_observation_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_relation_observation_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_relation_observation_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_relation_observation_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_relation_observations; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_relation_observations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    ingestion_job_id uuid,
    observation_key text NOT NULL,
    source_document_id uuid NOT NULL,
    source_provision_id uuid,
    relation_type text NOT NULL,
    target_document_id uuid,
    target_provision_id uuid,
    raw_target_citation text,
    assertion_method text NOT NULL,
    method_name text NOT NULL,
    confidence real,
    evidence_artifact_page_id uuid,
    evidence_excerpt text,
    evidence_char_start integer,
    evidence_char_end integer,
    status text DEFAULT 'observed'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_relation_observations_confidence_check CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT legal_relation_observations_key_check CHECK ((observation_key ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT legal_relation_observations_method_check CHECK ((assertion_method = ANY (ARRAY['explicit_primary_text'::text, 'official_metadata'::text, 'deterministic_reference'::text, 'llm_extracted'::text, 'human_verified'::text]))),
    CONSTRAINT legal_relation_observations_offsets_check CHECK ((((evidence_char_start IS NULL) AND (evidence_char_end IS NULL)) OR ((evidence_char_start IS NOT NULL) AND (evidence_char_end IS NOT NULL) AND (evidence_char_start >= 0) AND (evidence_char_end > evidence_char_start)))),
    CONSTRAINT legal_relation_observations_status_check CHECK ((status = ANY (ARRAY['observed'::text, 'accepted'::text, 'rejected'::text, 'conflicting'::text, 'superseded'::text]))),
    CONSTRAINT legal_relation_observations_target_check CHECK (((target_document_id IS NOT NULL) OR (btrim(COALESCE(raw_target_citation, ''::text)) <> ''::text))),
    CONSTRAINT legal_relation_observations_target_provision_check CHECK (((target_provision_id IS NULL) OR (target_document_id IS NOT NULL)))
);


--
-- Name: TABLE legal_relation_observations; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_relation_observations IS 'Evidence-bearing candidate legal relationships. Observations are never canonical merely because an LLM or parser emitted them.';


--
-- Name: COLUMN legal_relation_observations.relation_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_relation_observations.relation_type IS 'Extensible legal-domain code; FK to corpus.legal_relation_observation_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_relation_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_relation_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_relation_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_relation_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_tag_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_tag_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_tag_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_tag_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_tags; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_tags (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    slug text NOT NULL,
    label text NOT NULL,
    tag_type text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_tags_slug_check CHECK ((slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'::text))
);


--
-- Name: COLUMN legal_tags.tag_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_tags.tag_type IS 'Extensible legal-domain code; FK to corpus.legal_tag_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: legal_treatment_assertions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_treatment_assertions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    source_case_id uuid NOT NULL,
    target_case_id uuid NOT NULL,
    treatment_type text NOT NULL,
    source_proposition_id uuid,
    target_proposition_id uuid,
    evidence_id uuid,
    valid_from date,
    valid_to date,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    known_from timestamp with time zone DEFAULT now() NOT NULL,
    known_to timestamp with time zone,
    legal_issue_id uuid,
    CONSTRAINT legal_treatment_assertions_context_check CHECK (((treatment_type = ANY (ARRAY['cites'::text, 'references'::text])) OR (legal_issue_id IS NOT NULL))),
    CONSTRAINT legal_treatment_assertions_distinct_check CHECK ((source_case_id <> target_case_id)),
    CONSTRAINT legal_treatment_assertions_known_range_check CHECK (((known_to IS NULL) OR (known_to > known_from))),
    CONSTRAINT legal_treatment_assertions_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT legal_treatment_assertions_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT legal_treatment_assertions_verified_evidence_check CHECK (((verification_status <> 'verified'::text) OR (treatment_type = ANY (ARRAY['cites'::text, 'references'::text])) OR (evidence_id IS NOT NULL)))
);


--
-- Name: TABLE legal_treatment_assertions; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.legal_treatment_assertions IS 'Contextual judicial treatment between decisions. Substantive treatment requires a first-class legal issue; source/target propositions may further identify the reasoning treated.';


--
-- Name: COLUMN legal_treatment_assertions.treatment_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_treatment_assertions.treatment_type IS 'Extensible legal-domain code; FK to corpus.legal_treatment_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: COLUMN legal_treatment_assertions.legal_issue_id; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.legal_treatment_assertions.legal_issue_id IS 'First-class legal question that supplies doctrinal context for substantive judicial treatment. A legal issue is not a legal proposition.';


--
-- Name: legal_treatment_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_treatment_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_treatment_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT legal_treatment_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: legal_version_authority_assessments; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.legal_version_authority_assessments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    instrument_version_id uuid NOT NULL,
    source_document_id uuid,
    authority_class text NOT NULL,
    assessment text NOT NULL,
    basis text NOT NULL,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_version_authority_assessments_class_check CHECK ((authority_class = ANY (ARRAY['official_primary_text'::text, 'official_gazette'::text, 'official_consolidation'::text, 'official_correction'::text, 'editorial_consolidation'::text, 'historical_copy'::text, 'unknown'::text]))),
    CONSTRAINT legal_version_authority_assessments_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT legal_version_authority_assessments_value_check CHECK ((assessment = ANY (ARRAY['authoritative'::text, 'corroborating'::text, 'informational'::text, 'conflicting'::text, 'rejected'::text, 'unknown'::text])))
);


--
-- Name: matter_taxonomy_relation_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.matter_taxonomy_relation_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT matter_taxonomy_relation_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT matter_taxonomy_relation_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: panel_role_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.panel_role_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT panel_role_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT panel_role_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: parser_versions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.parser_versions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    parser_name text NOT NULL,
    parser_version text NOT NULL,
    code_revision text NOT NULL,
    configuration jsonb DEFAULT '{}'::jsonb NOT NULL,
    configuration_sha256 text,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT parser_versions_configuration_sha256_check CHECK (((configuration_sha256 IS NULL) OR (configuration_sha256 ~ '^[0-9a-f]{64}$'::text)))
);


--
-- Name: COLUMN parser_versions.code_revision; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.parser_versions.code_revision IS 'Immutable source-code revision or equivalent content identifier used to reproduce this parser version.';


--
-- Name: participants; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.participants (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    participant_kind text DEFAULT 'unknown'::text NOT NULL,
    display_name text NOT NULL,
    normalized_name text,
    identity_status text DEFAULT 'identity_unresolved'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    legal_entity_id uuid NOT NULL,
    CONSTRAINT participants_identity_status_check CHECK ((identity_status = ANY (ARRAY['canonical'::text, 'probable_duplicate'::text, 'identity_unresolved'::text, 'merged_with_canonical'::text]))),
    CONSTRAINT participants_kind_check CHECK ((participant_kind = ANY (ARRAY['person'::text, 'organization'::text, 'public_body'::text, 'unknown'::text]))),
    CONSTRAINT participants_name_nonempty CHECK ((btrim(display_name) <> ''::text))
);


--
-- Name: party_representations; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.party_representations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    party_role_id uuid NOT NULL,
    representative_participant_id uuid NOT NULL,
    representation_type text NOT NULL,
    valid_from date,
    valid_to date,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT party_representations_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT party_representations_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN party_representations.representation_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.party_representations.representation_type IS 'Extensible legal-domain code; FK to corpus.representation_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: party_side_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.party_side_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT party_side_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT party_side_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: passages; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.passages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_id uuid NOT NULL,
    page_start integer NOT NULL,
    page_end integer NOT NULL,
    passage_order integer NOT NULL,
    text text NOT NULL,
    section_type text,
    token_count integer,
    fts tsvector GENERATED ALWAYS AS (to_tsvector('spanish'::regconfig, COALESCE(text, ''::text))) STORED,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT passages_page_range_check CHECK (((page_start > 0) AND (page_end >= page_start))),
    CONSTRAINT passages_token_count_check CHECK (((token_count IS NULL) OR (token_count >= 0)))
);


--
-- Name: procedural_decision_relation_observations; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.procedural_decision_relation_observations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    observation_key text NOT NULL,
    source_case_id uuid NOT NULL,
    relation_type text NOT NULL,
    target_case_id uuid,
    raw_target_reference text,
    assertion_method text NOT NULL,
    method_name text NOT NULL,
    confidence real,
    evidence_case_page_id uuid,
    evidence_excerpt text,
    status text DEFAULT 'observed'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT procedural_relation_observations_confidence_check CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT procedural_relation_observations_key_check CHECK ((observation_key ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT procedural_relation_observations_method_check CHECK ((assertion_method = ANY (ARRAY['explicit_primary_text'::text, 'official_metadata'::text, 'deterministic_reference'::text, 'llm_extracted'::text, 'human_verified'::text]))),
    CONSTRAINT procedural_relation_observations_status_check CHECK ((status = ANY (ARRAY['observed'::text, 'accepted'::text, 'rejected'::text, 'conflicting'::text, 'superseded'::text]))),
    CONSTRAINT procedural_relation_observations_target_check CHECK (((target_case_id IS NOT NULL) OR (btrim(COALESCE(raw_target_reference, ''::text)) <> ''::text)))
);


--
-- Name: COLUMN procedural_decision_relation_observations.relation_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.procedural_decision_relation_observations.relation_type IS 'Extensible legal-domain code; FK to corpus.procedural_decision_relation_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: procedural_decision_relation_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.procedural_decision_relation_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT procedural_decision_relation_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT procedural_decision_relation_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: procedural_decision_relations; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.procedural_decision_relations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    source_case_id uuid NOT NULL,
    relation_type text NOT NULL,
    target_case_id uuid NOT NULL,
    verification_method text NOT NULL,
    promoted_from_observation_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT procedural_decision_relations_distinct_check CHECK ((source_case_id <> target_case_id))
);


--
-- Name: TABLE procedural_decision_relations; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.procedural_decision_relations IS 'Verified procedural history between decisions. It is intentionally separate from jurisprudential citation/treatment relations.';


--
-- Name: COLUMN procedural_decision_relations.relation_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.procedural_decision_relations.relation_type IS 'Extensible legal-domain code; FK to corpus.procedural_decision_relation_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: procedural_event_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.procedural_event_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT procedural_event_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT procedural_event_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: procedural_events; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.procedural_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    proceeding_id uuid NOT NULL,
    event_type text NOT NULL,
    event_type_raw text,
    occurred_on date,
    date_status text DEFAULT 'unknown'::text NOT NULL,
    sequence_number integer,
    raw_description text,
    normalized_description text,
    source_document_observation_id uuid,
    evidence_case_page_id uuid,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    confidence real,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT procedural_events_confidence_check CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT procedural_events_date_status_check CHECK ((date_status = ANY (ARRAY['verified_primary_text'::text, 'verified_official_metadata'::text, 'parsed_high_confidence'::text, 'parsed_unverified'::text, 'conflicting'::text, 'unknown'::text]))),
    CONSTRAINT procedural_events_description_check CHECK (((event_type <> 'other'::text) OR (btrim(COALESCE(event_type_raw, raw_description, ''::text)) <> ''::text))),
    CONSTRAINT procedural_events_sequence_check CHECK (((sequence_number IS NULL) OR (sequence_number > 0))),
    CONSTRAINT procedural_events_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT procedural_events_verified_date_requires_date CHECK (((date_status <> ALL (ARRAY['verified_primary_text'::text, 'verified_official_metadata'::text, 'parsed_high_confidence'::text])) OR (occurred_on IS NOT NULL)))
);


--
-- Name: TABLE procedural_events; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.procedural_events IS 'Ordered/evidenced events inside a proceeding. A proceeding is not reducible to the set of judicial decisions issued in it.';


--
-- Name: COLUMN procedural_events.event_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.procedural_events.event_type IS 'Extensible legal-domain code; FK to corpus.procedural_event_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: procedural_role_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.procedural_role_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    default_party_side text DEFAULT 'other'::text NOT NULL,
    broader_concept_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT procedural_role_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT procedural_role_concepts_name_check CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT procedural_role_concepts_not_self_parent CHECK (((broader_concept_id IS NULL) OR (broader_concept_id <> id)))
);


--
-- Name: COLUMN procedural_role_concepts.default_party_side; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.procedural_role_concepts.default_party_side IS 'Extensible legal-domain code; FK to corpus.party_side_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: procedure_concept_edges; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.procedure_concept_edges (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    narrower_concept_id uuid NOT NULL,
    broader_concept_id uuid NOT NULL,
    relation_type text DEFAULT 'broader'::text NOT NULL,
    verification_status text DEFAULT 'verified'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT procedure_concept_edges_distinct_check CHECK ((narrower_concept_id <> broader_concept_id)),
    CONSTRAINT procedure_concept_edges_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN procedure_concept_edges.relation_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.procedure_concept_edges.relation_type IS 'Extensible legal-domain code; FK to corpus.procedure_taxonomy_relation_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: procedure_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.procedure_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    jurisdiction_code text,
    active_from date,
    active_to date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT procedure_concepts_active_range_check CHECK (((active_to IS NULL) OR (active_from IS NULL) OR (active_to >= active_from))),
    CONSTRAINT procedure_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT procedure_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: procedure_taxonomy_relation_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.procedure_taxonomy_relation_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT procedure_taxonomy_relation_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT procedure_taxonomy_relation_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: proceeding_decision_relation_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.proceeding_decision_relation_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT proceeding_decision_relation_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT proceeding_decision_relation_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: proceeding_decisions; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.proceeding_decisions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    proceeding_id uuid NOT NULL,
    case_id uuid NOT NULL,
    relation_type text DEFAULT 'decision_in_proceeding'::text NOT NULL,
    procedural_stage text,
    ordinal integer,
    is_primary boolean DEFAULT false NOT NULL,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT proceeding_decisions_ordinal_check CHECK (((ordinal IS NULL) OR (ordinal > 0))),
    CONSTRAINT proceeding_decisions_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN proceeding_decisions.relation_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.proceeding_decisions.relation_type IS 'Extensible legal-domain code; FK to corpus.proceeding_decision_relation_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: COLUMN proceeding_decisions.is_primary; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.proceeding_decisions.is_primary IS 'Source/display preference only, not legal identity; consolidated decisions may relate equally to multiple proceedings.';


--
-- Name: proceeding_identifier_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.proceeding_identifier_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT proceeding_identifier_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT proceeding_identifier_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: proceeding_identifiers; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.proceeding_identifiers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    proceeding_id uuid NOT NULL,
    identifier_type text NOT NULL,
    raw_value text NOT NULL,
    normalized_value text,
    court_id uuid,
    source_registry_id uuid,
    is_primary boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT proceeding_identifiers_raw_nonempty CHECK ((btrim(raw_value) <> ''::text))
);


--
-- Name: COLUMN proceeding_identifiers.identifier_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.proceeding_identifiers.identifier_type IS 'Extensible legal-domain code; FK to corpus.proceeding_identifier_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: proceeding_participants; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.proceeding_participants (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    proceeding_id uuid NOT NULL,
    participant_id uuid NOT NULL,
    participant_name_raw text NOT NULL,
    role_raw text NOT NULL,
    role_normalized text,
    party_side text DEFAULT 'other'::text NOT NULL,
    ordinal integer,
    source_document_observation_id uuid,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT proceeding_participants_name_nonempty CHECK ((btrim(participant_name_raw) <> ''::text)),
    CONSTRAINT proceeding_participants_ordinal_check CHECK (((ordinal IS NULL) OR (ordinal > 0))),
    CONSTRAINT proceeding_participants_role_nonempty CHECK ((btrim(role_raw) <> ''::text)),
    CONSTRAINT proceeding_participants_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN proceeding_participants.role_normalized; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.proceeding_participants.role_normalized IS 'Raw/legacy normalization aid only; canonical procedural roles live in proceeding_party_roles.';


--
-- Name: COLUMN proceeding_participants.party_side; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.proceeding_participants.party_side IS 'Extensible legal-domain code; FK to corpus.party_side_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: proceeding_party_roles; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.proceeding_party_roles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    proceeding_id uuid NOT NULL,
    participant_id uuid NOT NULL,
    party_side text DEFAULT 'other'::text NOT NULL,
    raw_role text,
    valid_from date,
    valid_to date,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    role_concept_id uuid NOT NULL,
    CONSTRAINT proceeding_party_roles_range_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT proceeding_party_roles_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: COLUMN proceeding_party_roles.party_side; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.proceeding_party_roles.party_side IS 'Extensible legal-domain code; FK to corpus.party_side_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Name: proceeding_relation_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.proceeding_relation_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    broader_concept_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    is_symmetric boolean DEFAULT false NOT NULL,
    CONSTRAINT proceeding_relation_concepts_check CHECK (((broader_concept_id IS NULL) OR (broader_concept_id <> id))),
    CONSTRAINT proceeding_relation_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT proceeding_relation_concepts_name_check CHECK ((btrim(name) <> ''::text))
);


--
-- Name: proceeding_relations; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.proceeding_relations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    source_proceeding_id uuid NOT NULL,
    target_proceeding_id uuid NOT NULL,
    relation_concept_id uuid NOT NULL,
    raw_relation text,
    valid_from date,
    valid_to date,
    known_from timestamp with time zone DEFAULT now() NOT NULL,
    known_to timestamp with time zone,
    verification_status text DEFAULT 'candidate'::text NOT NULL,
    verification_method text NOT NULL,
    evidence_note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT proceeding_relations_check CHECK ((source_proceeding_id <> target_proceeding_id)),
    CONSTRAINT proceeding_relations_check1 CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT proceeding_relations_check2 CHECK (((known_to IS NULL) OR (known_to > known_from))),
    CONSTRAINT proceeding_relations_verification_status_check CHECK ((verification_status = ANY (ARRAY['candidate'::text, 'verified'::text, 'conflicting'::text, 'rejected'::text, 'superseded'::text])))
);


--
-- Name: TABLE proceeding_relations; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.proceeding_relations IS 'Canonical directed graph of procedural history. controversy_proceedings is litigation-family membership, not ancestry.';


--
-- Name: provision_source_role_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.provision_source_role_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT provision_source_role_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT provision_source_role_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: provision_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.provision_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT provision_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT provision_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: representation_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.representation_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT representation_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT representation_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: scopes; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.scopes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    visibility text NOT NULL,
    organization_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT corpus_scopes_ownership_check CHECK ((((visibility = 'public'::text) AND (organization_id IS NULL)) OR ((visibility = 'private'::text) AND (organization_id IS NOT NULL)))),
    CONSTRAINT corpus_scopes_visibility_check CHECK ((visibility = ANY (ARRAY['public'::text, 'private'::text])))
);


--
-- Name: TABLE scopes; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.scopes IS 'Provider-neutral corpus visibility boundary. Public scope is shared; private scopes are owned by one external organization UUID.';


--
-- Name: COLUMN scopes.organization_id; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.scopes.organization_id IS 'External organization identifier resolved by trusted server authentication/authorization code; not supplied by agents.';


--
-- Name: source_artifact_locations; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.source_artifact_locations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    artifact_id uuid NOT NULL,
    locator_type text NOT NULL,
    locator text NOT NULL,
    observed_filename text,
    is_preferred boolean DEFAULT false NOT NULL,
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    source_registry_id uuid,
    source_identifier text,
    discovered_via text,
    source_collection text,
    CONSTRAINT source_artifact_locations_collection_check CHECK (((source_collection IS NULL) OR (source_collection ~ '^[a-z0-9]+(-[a-z0-9]+)*$'::text))),
    CONSTRAINT source_artifact_locations_seen_range_check CHECK ((last_seen_at >= first_seen_at)),
    CONSTRAINT source_artifact_locations_type_check CHECK ((locator_type = ANY (ARRAY['official_url'::text, 'storage_object'::text, 'mirror_url'::text, 'manual_import'::text])))
);


--
-- Name: TABLE source_artifact_locations; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.source_artifact_locations IS 'Preserves every observed URL/storage locator even when multiple locators resolve to identical artifact bytes.';


--
-- Name: COLUMN source_artifact_locations.source_registry_id; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.source_artifact_locations.source_registry_id IS 'Source registry that exposed this locator. Location-level source identity allows identical bytes to be observed by multiple official registries.';


--
-- Name: COLUMN source_artifact_locations.source_identifier; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.source_artifact_locations.source_identifier IS 'Identifier exposed by the source for this document, such as a TC sentence number or SCJ source-specific id.';


--
-- Name: COLUMN source_artifact_locations.discovered_via; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.source_artifact_locations.discovered_via IS 'Official listing, result, or detail URL from which this artifact locator was discovered; it is provenance, not artifact identity.';


--
-- Name: COLUMN source_artifact_locations.source_collection; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.source_artifact_locations.source_collection IS 'Source-native or normalized collection such as decisions, historical-decisions, bulletins, gazettes, statutes, or regulations. It is routing/classification metadata, never artifact identity.';


--
-- Name: source_artifacts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.source_artifacts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_registry_id uuid,
    sha256 text NOT NULL,
    mime_type text NOT NULL,
    byte_size bigint NOT NULL,
    page_count integer,
    acquired_at timestamp with time zone DEFAULT now() NOT NULL,
    published_at date,
    parser_status text DEFAULT 'acquired'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    scope_id uuid DEFAULT '00000000-0000-0000-0000-000000000001'::uuid NOT NULL,
    CONSTRAINT source_artifacts_byte_size_check CHECK ((byte_size >= 0)),
    CONSTRAINT source_artifacts_page_count_check CHECK (((page_count IS NULL) OR (page_count > 0))),
    CONSTRAINT source_artifacts_parser_status_check CHECK ((parser_status = ANY (ARRAY['acquired'::text, 'extracting'::text, 'parsed'::text, 'ocr_required'::text, 'quality_review_required'::text, 'searchable'::text, 'blocked'::text]))),
    CONSTRAINT source_artifacts_sha256_check CHECK ((sha256 ~ '^[0-9a-f]{64}$'::text))
);


--
-- Name: source_collections; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.source_collections (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_registry_id uuid NOT NULL,
    code text NOT NULL,
    document_kind text NOT NULL,
    acquisition_policy text DEFAULT 'catalog_only'::text NOT NULL,
    agent_visibility text DEFAULT 'hidden'::text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT source_collections_acquisition_policy_check CHECK ((acquisition_policy = ANY (ARRAY['enabled'::text, 'catalog_only'::text, 'paused'::text, 'blocked'::text]))),
    CONSTRAINT source_collections_agent_visibility_check CHECK ((agent_visibility = ANY (ARRAY['hidden'::text, 'discoverable'::text, 'searchable'::text]))),
    CONSTRAINT source_collections_code_check CHECK ((code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'::text)),
    CONSTRAINT source_collections_kind_nonempty CHECK ((btrim(document_kind) <> ''::text)),
    CONSTRAINT source_collections_revision_check CHECK ((revision > 0))
);


--
-- Name: TABLE source_collections; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.source_collections IS 'Operator-controlled acquisition and agent-visibility policy for a source-native collection. Discovery alone never enables acquisition.';


--
-- Name: source_document_artifacts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.source_document_artifacts (
    source_document_id uuid NOT NULL,
    artifact_id uuid NOT NULL,
    relationship_type text DEFAULT 'primary'::text NOT NULL,
    first_seen_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT source_document_artifacts_relationship_check CHECK ((relationship_type = ANY (ARRAY['primary'::text, 'attachment'::text, 'replacement'::text, 'supplement'::text, 'scan'::text, 'transcription'::text]))),
    CONSTRAINT source_document_artifacts_seen_range_check CHECK ((last_seen_at >= first_seen_at))
);


--
-- Name: TABLE source_document_artifacts; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.source_document_artifacts IS 'Links source-level logical publications to immutable acquired artifacts without conflating source identity with content identity.';


--
-- Name: source_document_observations; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.source_document_observations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_document_id uuid NOT NULL,
    observed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    discovery_url text NOT NULL,
    document_url text,
    artifact_availability text NOT NULL,
    source_payload jsonb NOT NULL,
    payload_sha256 text NOT NULL,
    normalization_notes jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT source_document_observations_availability_check CHECK ((artifact_availability = ANY (ARRAY['available'::text, 'not_published'::text, 'unavailable'::text, 'unknown'::text]))),
    CONSTRAINT source_document_observations_discovery_https CHECK ((discovery_url ~ '^https://'::text)),
    CONSTRAINT source_document_observations_document_url_https CHECK (((document_url IS NULL) OR (document_url ~ '^https://'::text))),
    CONSTRAINT source_document_observations_payload_sha256_check CHECK ((payload_sha256 ~ '^[0-9a-f]{64}$'::text))
);


--
-- Name: TABLE source_document_observations; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.source_document_observations IS 'Append-only distinct source payload observations preserving official metadata and deterministic normalization notes.';


--
-- Name: source_documents; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.source_documents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_registry_id uuid NOT NULL,
    source_identifier text NOT NULL,
    source_collection text NOT NULL,
    document_kind text NOT NULL,
    discovery_url text NOT NULL,
    current_document_url text,
    artifact_availability text DEFAULT 'unknown'::text NOT NULL,
    latest_source_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    latest_payload_sha256 text NOT NULL,
    first_seen_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT source_documents_availability_check CHECK ((artifact_availability = ANY (ARRAY['available'::text, 'not_published'::text, 'unavailable'::text, 'unknown'::text]))),
    CONSTRAINT source_documents_collection_nonempty CHECK ((btrim(source_collection) <> ''::text)),
    CONSTRAINT source_documents_discovery_https CHECK ((discovery_url ~ '^https://'::text)),
    CONSTRAINT source_documents_document_url_https CHECK (((current_document_url IS NULL) OR (current_document_url ~ '^https://'::text))),
    CONSTRAINT source_documents_identifier_nonempty CHECK ((btrim(source_identifier) <> ''::text)),
    CONSTRAINT source_documents_kind_nonempty CHECK ((btrim(document_kind) <> ''::text)),
    CONSTRAINT source_documents_payload_sha256_check CHECK ((latest_payload_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT source_documents_seen_range_check CHECK ((last_seen_at >= first_seen_at))
);


--
-- Name: TABLE source_documents; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON TABLE corpus.source_documents IS 'Logical records published by an external source. They may exist before any downloadable artifact and are not automatically canonical legal_documents.';


--
-- Name: source_registries; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.source_registries (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    institution text NOT NULL,
    authority_class text NOT NULL,
    base_locator text,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT source_registries_authority_class_check CHECK ((authority_class = ANY (ARRAY['official_primary'::text, 'official_secondary'::text, 'trusted_mirror'::text, 'manual_import'::text])))
);


--
-- Name: territorial_unit_type_concepts; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.territorial_unit_type_concepts (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    jurisdiction_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT territorial_unit_type_concepts_code_check CHECK ((code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT territorial_unit_type_concepts_name_nonempty CHECK ((btrim(name) <> ''::text))
);


--
-- Name: territorial_units; Type: TABLE; Schema: corpus; Owner: -
--

CREATE TABLE corpus.territorial_units (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    unit_type text NOT NULL,
    parent_id uuid,
    country_code character(2) DEFAULT 'DO'::bpchar NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT territorial_units_name_check CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT territorial_units_not_self_parent CHECK (((parent_id IS NULL) OR (parent_id <> id)))
);


--
-- Name: COLUMN territorial_units.unit_type; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON COLUMN corpus.territorial_units.unit_type IS 'Extensible legal-domain code; FK to corpus.territorial_unit_type_concepts(code). Adding a legal category requires data, not DDL.';


--
-- Data for Name: acquisition_run_items; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: acquisition_runs; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: adjudicative_act_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.adjudicative_act_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('23e7c42d-095e-4358-a046-68985f845067', 'decision', 'Judicial decision / unspecified act', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.adjudicative_act_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('3afecb13-b3a9-46af-9cef-37673df1b28d', 'judgment', 'Judgment / sentencia', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.adjudicative_act_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('9c397674-22ab-4e39-b96a-df00c254601b', 'interlocutory_judgment', 'Interlocutory judgment', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.adjudicative_act_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('f8637f4a-8436-4aae-800a-d4190e6f812b', 'order', 'Order / auto', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.adjudicative_act_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('2ad2c8df-2872-464a-9edc-3a5bd15bd2e1', 'resolution', 'Resolution', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.adjudicative_act_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('f458e570-501b-4507-bd1e-5e18e93465e3', 'decree', 'Decree / providencia', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.adjudicative_act_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('baafb1c7-ad96-4b0e-ad9c-ec5e94def7a4', 'advisory_opinion', 'Advisory opinion', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.adjudicative_act_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('75eb43c3-8f2c-4677-84e9-91126c74ba46', 'other', 'Other adjudicative act', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: analysis_observations; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: artifact_pages; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: case_artifact_occurrences; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: case_identifier_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.case_identifier_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('decision_number', 'Decision Number', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.case_identifier_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('docket_number', 'Docket Number', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.case_identifier_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('legacy_docket_number', 'Legacy Docket Number', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.case_identifier_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('source_specific_id', 'Source Specific Id', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.case_identifier_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: case_identifiers; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: case_metadata_observations; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: case_metadata_resolution_observations; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: case_metadata_resolutions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: case_pages; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: claim_relation_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.claim_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('74dc19af-8eef-49d7-99be-9d8414ab66bd', 'challenges', 'Challenges', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.claim_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('510ecd8c-0b72-4248-b69a-3938ad5fc404', 'reviews', 'Reviews', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.claim_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('ba4ad511-1c09-4797-a027-5829ede34e3f', 'derives_from', 'Derives from', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.claim_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('92396c89-d7b3-4797-9f85-b98a89b758c3', 'renews', 'Renews', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.claim_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('13eeaa03-fa2c-491d-a617-a1dccc74e8ac', 'abandons', 'Abandons', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.claim_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('b903290b-569f-45e5-b555-1fc265aa0e28', 'moots', 'Moots', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.claim_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('55fc89a3-02af-4a22-a03a-35bbf36e5861', 'narrows', 'Narrows', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.claim_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('a6725717-1c46-4ff2-83d2-0af1dff9d357', 'expands', 'Expands', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.claim_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('6dbaf7ba-ef70-49ae-b7ba-3936704b9499', 'duplicates', 'Duplicates', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.claim_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('b28ff45e-f9d4-404c-9a84-2dbfca623693', 'responds_to', 'Responds to', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.claim_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('6d862e4b-7492-41a5-b21f-516e2633e48c', 'related_to', 'Related to', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: claim_relations; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: concept_schemes; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.concept_schemes (code, name, description, created_at, updated_at) VALUES ('legal_issue_relation', 'Legal issue relation', 'How a persisted legal object relates to a legal issue/question.', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.concept_schemes (code, name, description, created_at, updated_at) VALUES ('factual_proposition_kind', 'Factual proposition kind', 'Epistemic/legal role of a factual proposition without asserting that it is true.', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.concept_schemes (code, name, description, created_at, updated_at) VALUES ('factual_subject_relation', 'Factual subject relation', 'How a decision, proceeding, claim or party role relates to a factual proposition.', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.concept_schemes (code, name, description, created_at, updated_at) VALUES ('disposition_argument_role', 'Disposition action argument role', 'Semantic role played by an argument of a normalized dispositive action.', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.concept_schemes (code, name, description, created_at, updated_at) VALUES ('entity_identity_relation', 'Entity identity relation', 'Claim about whether two observed legal entities denote the same real-world identity.', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: controversy_membership_role_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.controversy_membership_role_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('553e04be-fac5-45bb-bff6-72027986460b', 'originating', 'Originating proceeding', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.controversy_membership_role_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('a26bd025-322d-422f-a042-40a62a94358a', 'review', 'Review proceeding', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.controversy_membership_role_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('e4dbe812-71bc-4910-93ed-b161e272b46a', 'enforcement', 'Enforcement proceeding', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.controversy_membership_role_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('6f28e6c8-7307-471b-ae5e-7dfad3db7099', 'incident', 'Incidental proceeding', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.controversy_membership_role_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('1feb5fd3-f363-4c0b-8bce-6b7a5e2f6237', 'related', 'Related proceeding', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.controversy_membership_role_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('ec5d63fd-b946-418b-914d-2d751a9c1c65', 'other', 'Other litigation-family role', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: controversy_proceedings; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: court_alias_kind_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.court_alias_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('official_name', 'Official Name', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_alias_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('abbreviation', 'Abbreviation', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_alias_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('source_label', 'Source Label', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_alias_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('historical_name', 'Historical Name', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_alias_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: court_aliases; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: court_function_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.court_function_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('original', 'Original', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_function_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('appellate', 'Appellate', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_function_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('cassation', 'Cassation', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_function_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('constitutional_review', 'Constitutional Review', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_function_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('electoral_review', 'Electoral Review', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_function_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('execution', 'Execution', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_function_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('administrative_review', 'Administrative Review', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_function_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: court_functional_competences; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: court_instance_level_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.court_instance_level_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('first', 'First', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_instance_level_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('second', 'Second', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_instance_level_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('supreme', 'Supreme', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_instance_level_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('special', 'Special', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_instance_level_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('not_applicable', 'Not Applicable', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_instance_level_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: court_jurisdictions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: court_organ_alias_kind_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.court_organ_alias_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('official_name', 'Official Name', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_organ_alias_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('abbreviation', 'Abbreviation', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_organ_alias_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('source_label', 'Source Label', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_organ_alias_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('historical_name', 'Historical Name', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_organ_alias_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: court_organ_aliases; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: court_organs; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: court_relation_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.court_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('appeals_to', 'Appeals To', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('reviewed_by', 'Reviewed By', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('administratively_supervised_by', 'Administratively Supervised By', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('successor_of', 'Successor Of', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: court_relations; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: court_subject_matter_competences; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: court_territorial_competences; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: court_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.court_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('constitutional', 'Constitutional', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('supreme', 'Supreme', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('appellate', 'Appellate', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('first_instance', 'First Instance', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('peace', 'Peace', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('specialized', 'Specialized', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('electoral', 'Electoral', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.court_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: courts; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: decision_legal_matters; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: decision_legal_states; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: decision_legal_status_events; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: decision_matter_relation_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.decision_matter_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('primary', 'Primary', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_matter_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('addresses', 'Addresses', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_matter_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('incidental', 'Incidental', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_matter_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('background', 'Background', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_matter_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: decision_panel_members; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: decision_procedure_relation_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.decision_procedure_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('primary', 'Primary', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_procedure_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('uses', 'Uses', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_procedure_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('reviews', 'Reviews', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_procedure_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('incident', 'Incident', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_procedure_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: decision_procedures; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: decision_state_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.decision_state_concepts (id, code, name, broader_concept_id, created_at) VALUES ('73f8d022-81fe-4105-bd07-d1ff372d1e2f', 'appealable', 'Appealable', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_state_concepts (id, code, name, broader_concept_id, created_at) VALUES ('faab2372-8db4-42f4-970f-9e0e57f9caef', 'final', 'Final', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_state_concepts (id, code, name, broader_concept_id, created_at) VALUES ('3c4f7f14-8338-476c-9861-3a379338313a', 'res_judicata', 'Res judicata', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_state_concepts (id, code, name, broader_concept_id, created_at) VALUES ('70e1fd75-6069-4d9d-8e34-e4fd81c7519a', 'stayed', 'Stayed', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_state_concepts (id, code, name, broader_concept_id, created_at) VALUES ('336b2743-1f39-40c3-aef9-2fcea3de490b', 'suspended', 'Suspended', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_state_concepts (id, code, name, broader_concept_id, created_at) VALUES ('f38995d8-69f8-4f55-853f-4ce32cf83a2c', 'enforceable', 'Enforceable', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_state_concepts (id, code, name, broader_concept_id, created_at) VALUES ('efeb0bb6-b932-4789-9d23-bfbb058cc84c', 'superseded', 'Superseded', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.decision_state_concepts (id, code, name, broader_concept_id, created_at) VALUES ('fb7dbacd-6654-4f05-8e83-3f720e10c766', 'other', 'Other', NULL, '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: decision_votes; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: disposition_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.disposition_concepts (id, code, name, broader_concept_id, created_at) VALUES ('31786bf2-6088-49e8-a13e-f277890ba6ab', 'granted', 'Granted', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_concepts (id, code, name, broader_concept_id, created_at) VALUES ('09292c8c-7df1-4a75-8985-dba4a6e05dcb', 'denied', 'Denied', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_concepts (id, code, name, broader_concept_id, created_at) VALUES ('8cdce57e-4787-4f68-9b29-6108f3b73b64', 'dismissed', 'Dismissed', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_concepts (id, code, name, broader_concept_id, created_at) VALUES ('3eb43b71-3854-4221-a806-25ad7806e377', 'inadmissible', 'Inadmissible', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_concepts (id, code, name, broader_concept_id, created_at) VALUES ('8fcb9b9c-d961-497a-9a4f-e56046f290a1', 'affirmed', 'Affirmed', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_concepts (id, code, name, broader_concept_id, created_at) VALUES ('bdfbe66c-f30e-4733-a966-6d1bb1d6490a', 'reversed', 'Reversed', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_concepts (id, code, name, broader_concept_id, created_at) VALUES ('ec6646d7-ee2b-42d6-8a91-e77eaaabcf75', 'vacated', 'Vacated', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_concepts (id, code, name, broader_concept_id, created_at) VALUES ('ebeeebc8-4df0-4574-bf08-c9c9a634e891', 'modified', 'Modified', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_concepts (id, code, name, broader_concept_id, created_at) VALUES ('cc8b8b72-b96d-4919-9fe7-f20d0a40766e', 'remanded', 'Remanded', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_concepts (id, code, name, broader_concept_id, created_at) VALUES ('17b3a2a3-92dd-45b8-b9c0-be7be48137b6', 'cassated', 'Cassated', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_concepts (id, code, name, broader_concept_id, created_at) VALUES ('8e58c3e7-45f1-4ede-923f-082cab322e14', 'partially_cassated', 'Partially cassated', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_concepts (id, code, name, broader_concept_id, created_at) VALUES ('72e2f517-ece7-4019-9727-59c60d36820c', 'costs', 'Costs', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_concepts (id, code, name, broader_concept_id, created_at) VALUES ('a81203a4-9295-4524-9850-508d4664ae6f', 'other', 'Other', NULL, '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: disposition_effect_argument_rules; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('f390e3b2-abc9-46c3-8672-6cefe479a7d5', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'claim', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('070d57c0-5cc2-49ad-b3a8-ce2c725de318', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'claim', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('f744c17b-5306-4ac2-87ea-a7fef03c6c11', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'claim', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('d32e3cc9-fa91-4a8d-9a10-bedb8d9942a0', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'claim', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('869e1196-56c1-42ae-a65f-211369b39fc5', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'claim', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('0897ad63-85f1-48a4-9eb3-04d7ff4dbab0', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'claim', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('2be0a0f4-6932-48b3-855f-f3da5a31595c', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'claim', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('c2413d1e-ac03-4722-bc91-7a0fcd70978b', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'party_role', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('d3095b53-4c4c-4f02-8537-b497baa508eb', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'party_role', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('62446898-7ca1-4263-9de7-bb58f15af83e', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'party_role', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('abba35cb-3c4a-44c5-89db-5394993fc5bb', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'proceeding', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('dcd95d47-438d-4225-af1b-6ebf4a9e1950', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'proceeding', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('2cd8176e-f1d5-47b4-bd65-2dfc44eb245b', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'proceeding', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('5d534df4-f0c0-4ecc-9fbe-c60081bfeebf', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'decision', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('6df0c554-4d1a-405a-9b05-2617b58f631b', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'decision', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('652adfe1-3511-49cb-8894-b0d97bd06737', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'decision', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('3e337ac8-f6f1-4f59-bf5a-dce23a7f0aea', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'decision', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('e8ba471c-4f5a-4b36-b3f1-eee40c2537a8', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'decision', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('46d3aae5-c2a1-4605-8554-4ef5b89b24f1', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'decision', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('8b4a92b1-8e58-4f01-9189-938d5dbb696c', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'proposition', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('2f2a7305-8dff-491e-aad0-de9e0648d479', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'proposition', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('fc8a9cd6-a1c3-4b99-97fb-ddce84be60e1', 'disposition_argument_role', '4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'proposition', true, 1, 'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('62446898-7ca1-4263-9de7-bb58f15af83e', 'disposition_argument_role', 'aa5eca49-901b-4d7a-a08e-a55769c06741', 'money', false, 1, 'Optional normalized monetary amount.', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.disposition_effect_argument_rules (effect_concept_id, role_scheme_code, role_concept_id, object_type, required, max_count, note, created_at) VALUES ('abba35cb-3c4a-44c5-89db-5394993fc5bb', 'disposition_argument_role', '7407dbd1-0280-4094-88c2-f6d9a0a1a6ef', 'court_organ', false, 1, 'Optional destination court organ on remand.', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: disposition_effect_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('f390e3b2-abc9-46c3-8672-6cefe479a7d5', 'granted', 'Granted', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('070d57c0-5cc2-49ad-b3a8-ce2c725de318', 'partially_granted', 'Partially granted', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('f744c17b-5306-4ac2-87ea-a7fef03c6c11', 'denied', 'Denied', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('d32e3cc9-fa91-4a8d-9a10-bedb8d9942a0', 'inadmissible', 'Inadmissible', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('869e1196-56c1-42ae-a65f-211369b39fc5', 'moot', 'Moot', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('0897ad63-85f1-48a4-9eb3-04d7ff4dbab0', 'withdrawn', 'Withdrawn', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('2be0a0f4-6932-48b3-855f-f3da5a31595c', 'other', 'Other', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('c2413d1e-ac03-4722-bc91-7a0fcd70978b', 'orders', 'Orders party', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('d3095b53-4c4c-4f02-8537-b497baa508eb', 'restrains', 'Restrains party', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('62446898-7ca1-4263-9de7-bb58f15af83e', 'awards_costs_against', 'Awards costs against party', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('abba35cb-3c4a-44c5-89db-5394993fc5bb', 'remands', 'Remands proceeding', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('dcd95d47-438d-4225-af1b-6ebf4a9e1950', 'terminates', 'Terminates proceeding', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('2cd8176e-f1d5-47b4-bd65-2dfc44eb245b', 'stays', 'Stays proceeding', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('5d534df4-f0c0-4ecc-9fbe-c60081bfeebf', 'affirms', 'Affirms decision', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('6df0c554-4d1a-405a-9b05-2617b58f631b', 'reverses', 'Reverses decision', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('652adfe1-3511-49cb-8894-b0d97bd06737', 'vacates', 'Vacates decision', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('3e337ac8-f6f1-4f59-bf5a-dce23a7f0aea', 'annuls', 'Annuls decision', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('e8ba471c-4f5a-4b36-b3f1-eee40c2537a8', 'modifies', 'Modifies decision', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('46d3aae5-c2a1-4605-8554-4ef5b89b24f1', 'cassates', 'Cassates decision', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('8b4a92b1-8e58-4f01-9189-938d5dbb696c', 'adopts', 'Adopts proposition', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('2f2a7305-8dff-491e-aad0-de9e0648d479', 'rejects', 'Rejects proposition', NULL, '2026-09-20 03:17:55.220807+00', NULL);
INSERT INTO corpus.disposition_effect_concepts (id, code, name, broader_concept_id, created_at, description) VALUES ('fc8a9cd6-a1c3-4b99-97fb-ddce84be60e1', 'limits', 'Limits proposition', NULL, '2026-09-20 03:17:55.220807+00', NULL);


--
-- Data for Name: entity_identity_assertion_evidence; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: entity_identity_assertions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: entity_identity_resolutions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: factual_proposition_evidence; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: factual_proposition_subjects; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: factual_propositions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: ingestion_jobs; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: instrument_authority_role_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.instrument_authority_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('enacted_by', 'Enacted By', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_authority_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('promulgated_by', 'Promulgated By', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_authority_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('issued_by', 'Issued By', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_authority_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('published_by', 'Published By', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_authority_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('administered_by', 'Administered By', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_authority_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('enforced_by', 'Enforced By', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_authority_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('delegated_by', 'Delegated By', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_authority_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: instrument_document_role_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.instrument_document_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('official_text', 'Official Text', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_document_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('official_publication', 'Official Publication', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_document_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('consolidated_text', 'Consolidated Text', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_document_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('corrected_text', 'Corrected Text', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_document_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('historical_copy', 'Historical Copy', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_document_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('editorial_text', 'Editorial Text', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_document_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: instrument_version_kind_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.instrument_version_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('original', 'Original', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_version_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('amended', 'Amended', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_version_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('official_consolidation', 'Official Consolidation', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_version_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('editorial_consolidation', 'Editorial Consolidation', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_version_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('corrected', 'Corrected', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_version_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('historical_snapshot', 'Historical Snapshot', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.instrument_version_kind_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: judicial_authority_assertions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: judicial_authority_effect_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.judicial_authority_effect_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('b4702c12-bdac-4b82-80d9-9e0f849be361', 'binding', 'Binding authority', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_authority_effect_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('b348dec9-0de3-4163-a3fa-5bdd1e8eca7a', 'persuasive', 'Persuasive authority', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_authority_effect_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('f4a0ba4d-8442-47c3-b189-d97656ec7dd2', 'nonbinding', 'Non-binding authority', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_authority_effect_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('81f1a68e-82d7-49aa-ac60-baa4ba9fc95d', 'superseded', 'Superseded authority', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_authority_effect_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('7dc23bde-700f-40ec-8260-f75af0d5f8d0', 'abrogated', 'Abrogated authority', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_authority_effect_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('0be59a0f-ea3d-42cb-845d-6d9bd9cb58ec', 'unknown', 'Unknown authority effect', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: judicial_authorship_role_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.judicial_authorship_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('author', 'Author', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_authorship_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('coauthor', 'Coauthor', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_authorship_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('ponente', 'Ponente', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_authorship_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('redactor', 'Redactor', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_authorship_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('signatory', 'Signatory', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_authorship_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('legacy_primary_author', 'Legacy Primary Author', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_authorship_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: judicial_decision_dispositions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: judicial_decisions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: judicial_disposition_action_arguments; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: judicial_disposition_actions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: judicial_event_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('d6cfcc50-a736-4c17-8097-2fb9743ba3f9', 'issued', 'Issued', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('ea0e497d-bceb-4b0d-8c1c-9e7b788d6d92', 'notified', 'Notified', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('1a7c766d-02d8-4ce3-b853-46d1c7d3c1a5', 'vacated', 'Vacated', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('d75565a9-3fbd-4010-b463-ae86699ccd90', 'annulled', 'Annulled', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('48f727a2-62e2-4ea5-8ec2-35ac52502fb5', 'reversed', 'Reversed', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('c10e40f0-743f-4a92-b639-97b864b7e1cc', 'partially_reversed', 'Partially reversed', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('f11ec0f2-1fce-402a-9e09-1241b7ede05f', 'enforced', 'Enforced', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('13e14e87-c055-4d69-86be-edb31d31b0a8', 'superseded', 'Superseded', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('91d3a6d5-2f5f-4e68-9309-a34c9aceab42', 'clarified', 'Clarified', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('844ad490-8e4d-45a2-9dde-643b2a111afd', 'corrected', 'Corrected / rectified', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('eb40c056-6041-41b2-bf87-787a180e1838', 'supplemented', 'Supplemented', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('f77596df-2e95-41ed-a29d-07d3c0db8714', 'reconsidered', 'Reconsidered', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('51847220-764a-49af-852c-5115b7b35cd5', 'remitted', 'Remitted', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('4d7a1ca0-7634-4fed-bda9-0a3065fc67bd', 'archived', 'Archived', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_event_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('2aa20e08-83a6-4849-aa41-2225ef6e6ee3', 'other', 'Other judicial event', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: judicial_officer_position_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.judicial_officer_position_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('judge', 'Judge', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_officer_position_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('chief_judge', 'Chief Judge', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_officer_position_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('president', 'President', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_officer_position_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('vice_president', 'Vice President', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_officer_position_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('substitute', 'Substitute', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_officer_position_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('emeritus', 'Emeritus', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_officer_position_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: judicial_officer_positions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: judicial_officers; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: judicial_opinion_authors; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: judicial_opinion_join_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.judicial_opinion_join_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('joins_all', 'Joins All', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_opinion_join_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('joins_part', 'Joins Part', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_opinion_join_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('concurs_in_result', 'Concurs In Result', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_opinion_join_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('dissents_in_part', 'Dissents In Part', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: judicial_opinion_joiners; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: judicial_opinion_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.judicial_opinion_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('b86578b0-bc67-4293-8d03-d05a92cfd909', 'majority', 'Majority opinion', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_opinion_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('debf8485-5563-42f1-8ea2-dddf5b5c7d12', 'plurality', 'Plurality opinion', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_opinion_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('d43afccb-f2df-4e1c-a129-f1af550f9f16', 'per_curiam', 'Per curiam / collective court opinion', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_opinion_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('0dbe249f-3000-4a85-9c5d-c824fde4958f', 'concurring', 'Concurring opinion', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_opinion_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('8303ce3c-e21f-45b4-97e2-f1ab8bf285c8', 'dissenting', 'Dissenting opinion', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_opinion_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('477c1c7b-d1c5-4389-b3c6-e7d58831b056', 'concurring_in_result', 'Opinion concurring in result', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_opinion_type_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('cdb06961-9df9-4b39-a470-3a3f0d2e17db', 'separate', 'Separate opinion', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: judicial_opinions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: judicial_stance_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.judicial_stance_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('14314904-e6e0-462a-8e16-48311c763061', 'joins', 'Joins', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_stance_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('8e3b6432-6c67-460a-b9b8-8e2d51aaeb8e', 'concurs', 'Concurs', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_stance_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('5b5983d0-ee03-4be4-b23d-d2e662cb4863', 'concurs_in_result', 'Concurs in result', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_stance_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('02834e96-5dbe-4641-bfa2-0c36f935d99c', 'concurs_in_part', 'Concurs in part', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_stance_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('5006071b-be20-4054-929d-247cf241fe1a', 'dissents', 'Dissents', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_stance_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('9aa75ae3-f786-4766-8781-9dca54b57ab3', 'dissents_in_part', 'Dissents in part', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_stance_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('af8ade1e-b0a9-4202-9ff4-0c1a712e25ba', 'saved_vote', 'Saved vote / voto salvado', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_stance_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('e6d0b886-e0b2-496e-9a72-b86188d53f0f', 'reservation', 'Reservation', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_stance_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('62402a83-042e-42a3-8ce0-213c8b1bddd5', 'abstains', 'Abstains', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_stance_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at) VALUES ('b26831bc-9900-4e9d-a264-b2263ec77e16', 'other', 'Other', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: judicial_system_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.judicial_system_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('ordinary_judiciary', 'Ordinary Judiciary', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_system_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('constitutional_jurisdiction', 'Constitutional Jurisdiction', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_system_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('electoral_jurisdiction', 'Electoral Jurisdiction', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_system_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: judicial_vote_stances; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: judicial_vote_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.judicial_vote_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('majority', 'Majority', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_vote_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('plurality', 'Plurality', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_vote_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('concurring', 'Concurring', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_vote_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('dissenting', 'Dissenting', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_vote_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('concurs_in_result', 'Concurs In Result', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_vote_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('abstained', 'Abstained', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.judicial_vote_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('not_participating', 'Not Participating', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: jurisdictions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_amendment_effect_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_amendment_effect_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('amends', 'Amends', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_amendment_effect_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('inserts', 'Inserts', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_amendment_effect_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('replaces', 'Replaces', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_amendment_effect_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('renumbers', 'Renumbers', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_amendment_effect_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('repeals', 'Repeals', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_amendment_effect_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('partially_repeals', 'Partially Repeals', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_amendment_effect_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('suspends', 'Suspends', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_amendment_effect_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('reinstates', 'Reinstates', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_amendment_effect_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('corrects', 'Corrects', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_amendment_effect_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_amendment_effects; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_amendment_operation_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_amendment_operation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('insert', 'Insert', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_amendment_operation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('delete', 'Delete', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_amendment_operation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('replace', 'Replace', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_amendment_operation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('move', 'Move', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_amendment_operation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('renumber', 'Renumber', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_amendment_operation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('whole_provision_replace', 'Whole Provision Replace', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_amendment_operations; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_authorities; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_authority_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_authority_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('legislature', 'Legislature', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_authority_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('executive', 'Executive', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_authority_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('ministry', 'Ministry', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_authority_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('regulator', 'Regulator', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_authority_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('municipality', 'Municipality', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_authority_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('court', 'Court', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_authority_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('constitutional_body', 'Constitutional Body', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_authority_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('international_body', 'International Body', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_authority_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_claim_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_claim_concepts (id, code, name, jurisdiction_code, broader_concept_id, created_at) VALUES ('9d33c817-bc71-4340-96a7-a8fbda29517a', 'principal_claim', 'Principal claim', NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_claim_concepts (id, code, name, jurisdiction_code, broader_concept_id, created_at) VALUES ('ccd135aa-0928-41aa-ae88-8209127fbf83', 'alternative_claim', 'Alternative/subsidiary claim', NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_claim_concepts (id, code, name, jurisdiction_code, broader_concept_id, created_at) VALUES ('c1becd28-d089-46a7-ac5b-d17319c52a18', 'counterclaim', 'Counterclaim', NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_claim_concepts (id, code, name, jurisdiction_code, broader_concept_id, created_at) VALUES ('a3a7ffc0-78ae-405d-986a-29c2a9bf9089', 'procedural_exception', 'Procedural exception', NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_claim_concepts (id, code, name, jurisdiction_code, broader_concept_id, created_at) VALUES ('bb499a60-dd82-459c-8048-fc498b29ea05', 'inadmissibility_motion', 'Inadmissibility motion', NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_claim_concepts (id, code, name, jurisdiction_code, broader_concept_id, created_at) VALUES ('60c747b0-d243-4200-adf7-7cb3fa902bff', 'appeal_ground', 'Appeal/cassation/review ground', NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_claim_concepts (id, code, name, jurisdiction_code, broader_concept_id, created_at) VALUES ('ffb9e026-2826-477f-bd83-987d6d67ef92', 'interim_request', 'Interim request', NULL, NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_claim_concepts (id, code, name, jurisdiction_code, broader_concept_id, created_at) VALUES ('29fdb6e7-999e-49fd-894e-e25e660ebeea', 'other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_claims; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_concept_aliases; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_concept_edges; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('e9a08d3a-82ed-43a4-9afb-f9051ee948e6', 'legal_issue_relation', NULL, 'addresses', 'Addresses', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('058ec234-3177-4039-bc86-52d3df9c5ae2', 'legal_issue_relation', NULL, 'raises', 'Raises', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('4f2b2e35-7f94-4d84-b5a1-2ea9f0ebc026', 'legal_issue_relation', NULL, 'answers', 'Answers', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('2610d382-89b6-4981-b017-743f49d2d7ee', 'legal_issue_relation', NULL, 'qualifies', 'Qualifies', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('ae5954ad-2745-4f7e-ad18-e892d90ac6ef', 'legal_issue_relation', NULL, 'rejects', 'Rejects', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('0ea222ab-adbc-4276-811e-1988479edf1e', 'legal_issue_relation', NULL, 'frames', 'Frames', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('a00aa807-52b3-41d2-9166-d415e50359fa', 'legal_issue_relation', NULL, 'supports', 'Supports', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('b368453f-556d-43c5-b12e-8418d02b1baa', 'legal_issue_relation', NULL, 'opposes', 'Opposes', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('4f47b354-31c6-4695-857b-2c51d1752d6a', 'legal_issue_relation', NULL, 'related_to', 'Related to', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('f4b4d396-45fc-4a72-8eda-cad681e111b0', 'factual_proposition_kind', NULL, 'allegation', 'Allegation', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('499f6173-4f7c-49bc-a07e-b01aca8a8b6c', 'factual_proposition_kind', NULL, 'denial', 'Denial', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('292e838f-ffed-44dd-b003-281c9266c326', 'factual_proposition_kind', NULL, 'admission', 'Admission', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('6b44d8ba-519b-4869-9d54-2c05b25134a5', 'factual_proposition_kind', NULL, 'stipulation', 'Stipulation', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('9f5ab01a-205b-4629-96ee-a34e55e6e275', 'factual_proposition_kind', NULL, 'finding', 'Judicial finding', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('b59ab63b-47a5-44de-b01f-167b1ca3ba98', 'factual_proposition_kind', NULL, 'presumption', 'Presumption', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('17d7f931-0f3a-42ec-8d8a-6b1c80a11bb3', 'factual_proposition_kind', NULL, 'background_fact', 'Background fact', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('3871ce08-86bf-4e9c-aec2-3d0e986e319c', 'factual_proposition_kind', NULL, 'evidentiary_fact', 'Evidentiary fact', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('5dd10537-37f7-4db6-a770-438fc35c12ee', 'factual_subject_relation', NULL, 'alleged_by', 'Alleged by', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('28809fbc-c38b-48b5-9f2d-49cff77d0795', 'factual_subject_relation', NULL, 'denied_by', 'Denied by', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('0eefd22b-58e7-4a9c-8343-eb592b1f9b83', 'factual_subject_relation', NULL, 'admitted_by', 'Admitted by', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('484dd924-a3ee-429f-8286-268f88531ddc', 'factual_subject_relation', NULL, 'stipulated_by', 'Stipulated by', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('5342cce2-e39a-48b8-893e-2a758f2a44df', 'factual_subject_relation', NULL, 'found_by', 'Found by judicial decision', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('85e8eb49-91db-4b1b-8ad4-6333fe27ecbc', 'factual_subject_relation', NULL, 'supports_claim', 'Supports claim', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('e233b964-6d72-44b4-acd3-ad7702b62313', 'factual_subject_relation', NULL, 'opposes_claim', 'Opposes claim', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('46af9acf-3159-45a3-9064-b888200d1873', 'factual_subject_relation', NULL, 'material_to', 'Material to', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('9225d21c-9886-477a-a505-f963ffa93cb0', 'factual_subject_relation', NULL, 'occurred_in', 'Occurred in proceeding', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('d3982563-03d5-45d5-942f-8e9e4eede2cb', 'factual_subject_relation', NULL, 'mentioned_by', 'Mentioned by', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('4be7fac3-2faa-46ec-8905-772ec3cfc4b6', 'disposition_argument_role', NULL, 'object', 'Object', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('bf83caf4-a64f-4790-ae17-00c639f8953c', 'disposition_argument_role', NULL, 'obligor', 'Obligor', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('cafa6363-af24-47d5-b3e6-dd79af4edae2', 'disposition_argument_role', NULL, 'beneficiary', 'Beneficiary', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('7407dbd1-0280-4094-88c2-f6d9a0a1a6ef', 'disposition_argument_role', NULL, 'destination', 'Destination', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('f40eeb2d-c99a-4989-91d4-b973ed8479f8', 'disposition_argument_role', NULL, 'claim', 'Claim', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('3631ca4c-8bef-4456-9a83-2cad66d3a0a7', 'disposition_argument_role', NULL, 'legal_provision', 'Legal provision', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('aa5eca49-901b-4d7a-a08e-a55769c06741', 'disposition_argument_role', NULL, 'amount', 'Amount', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('ceb8c750-13b8-4cc3-8cd5-94acceebfd9b', 'disposition_argument_role', NULL, 'scope', 'Scope', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('35dc820c-ff56-41b2-a0a2-48f718506a9e', 'disposition_argument_role', NULL, 'condition', 'Condition', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('3c953e28-a367-497a-a192-95c19c812216', 'disposition_argument_role', NULL, 'other', 'Other', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('336c1082-10ce-422c-9ab1-3fddb3a0ec3c', 'entity_identity_relation', NULL, 'same_as', 'Same identity', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('3f07a953-72d4-41f0-ab56-d0b909361d23', 'entity_identity_relation', NULL, 'probable_same_as', 'Probable same identity', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('c14e96fb-1245-4fb0-b944-c22f6b65d188', 'entity_identity_relation', NULL, 'not_same_as', 'Different identity', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_concepts (id, scheme_code, jurisdiction_code, code, name, description, valid_from, valid_to, metadata, created_at, updated_at) VALUES ('751f693b-2677-4726-ac28-7881a84ee2b3', 'entity_identity_relation', NULL, 'merged_into', 'Resolved into canonical identity', NULL, NULL, NULL, '{}', '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_controversies; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_controversy_status_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_controversy_status_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('unknown', 'Unknown', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_controversy_status_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('active', 'Active', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_controversy_status_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('closed', 'Closed', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_controversy_status_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('dormant', 'Dormant', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_controversy_status_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('archived', 'Archived', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_document_artifact_occurrences; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_document_identifiers; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_document_provisions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_document_tags; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_document_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_document_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('judicial_decision', 'Judicial Decision', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_document_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('constitution', 'Constitution', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_document_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('statute', 'Statute', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_document_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('decree', 'Decree', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_document_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('regulation', 'Regulation', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_document_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('administrative_resolution', 'Administrative Resolution', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_document_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('circular', 'Circular', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_document_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('gazette', 'Gazette', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_document_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('treaty', 'Treaty', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_document_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('opinion', 'Opinion', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_document_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('order', 'Order', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_document_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_documents; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_entities; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_instrument_authority_roles; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_instrument_event_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_instrument_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('adopted', 'Adopted', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('enacted', 'Enacted', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('promulgated', 'Promulgated', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('published', 'Published', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('effective', 'Effective', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('amended', 'Amended', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('corrected', 'Corrected', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('suspended', 'Suspended', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('reinstated', 'Reinstated', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('repealed', 'Repealed', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('expired', 'Expired', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_instrument_events; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_instrument_identifiers; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_instrument_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_instrument_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('constitution', 'Constitution', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('code', 'Code', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('statute', 'Statute', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('decree', 'Decree', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('regulation', 'Regulation', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('administrative_resolution', 'Administrative Resolution', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('circular', 'Circular', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('treaty', 'Treaty', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('ordinance', 'Ordinance', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('rule', 'Rule', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_instrument_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_instrument_version_documents; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_instrument_version_knowledge; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_instrument_versions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_instruments; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_issue_evidence; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_issue_subjects; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_issues; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_matter_concept_edges; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_matter_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_norm_assertions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_norm_claims; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_norm_source_role_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_norm_source_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('establishes', 'Establishes', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_norm_source_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('defines', 'Defines', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_norm_source_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('amends', 'Amends', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_norm_source_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('repeals', 'Repeals', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_norm_source_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('creates_exception', 'Creates Exception', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_norm_source_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('interprets', 'Interprets', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_norm_source_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('satisfies', 'Satisfies', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_norm_source_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('evidences', 'Evidences', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_norm_sources; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_proceeding_status_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_proceeding_status_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('unknown', 'Unknown', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proceeding_status_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('pending', 'Pending', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proceeding_status_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('closed', 'Closed', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proceeding_status_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('stayed', 'Stayed', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proceeding_status_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('archived', 'Archived', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_proceedings; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_proposition_evidence; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_proposition_evidence_role_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_proposition_evidence_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('supports', 'Supports', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proposition_evidence_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('qualifies', 'Qualifies', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proposition_evidence_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('contradicts', 'Contradicts', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proposition_evidence_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('context', 'Context', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_proposition_relation_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_proposition_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('answers', 'Answers', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proposition_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('supports', 'Supports', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proposition_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('opposes', 'Opposes', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proposition_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('qualifies', 'Qualifies', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proposition_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('limits', 'Limits', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proposition_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('creates_exception_to', 'Creates Exception To', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proposition_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('depends_on', 'Depends On', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proposition_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('derived_from', 'Derived From', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proposition_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('applies_to', 'Applies To', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proposition_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('distinguishes_from', 'Distinguishes From', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proposition_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('supersedes', 'Supersedes', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_proposition_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('contradicts', 'Contradicts', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_proposition_relations; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_proposition_subjects; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_propositions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_provision_lineage; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_provision_lineage_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_provision_lineage_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('continues_as', 'Continues As', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_provision_lineage_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('renumbered_as', 'Renumbered As', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_provision_lineage_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('split_into', 'Split Into', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_provision_lineage_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('merged_into', 'Merged Into', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_provision_lineage_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('replaced_by', 'Replaced By', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_provision_lineage_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('transferred_to', 'Transferred To', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_provision_lineage_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('derived_from', 'Derived From', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_provision_version_knowledge; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_provision_version_sources; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_provision_versions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_provisions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_relation_assertion_evidence; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_relation_assertions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_relation_identities; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_relation_observation_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('cites', 'Cites', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('references', 'References', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('interprets', 'Interprets', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('applies', 'Applies', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('declines_to_apply', 'Declines To Apply', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('follows', 'Follows', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('distinguishes', 'Distinguishes', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('overrules', 'Overrules', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('authorized_by', 'Authorized By', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('implements', 'Implements', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('amends', 'Amends', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('repeals', 'Repeals', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('partially_repeals', 'Partially Repeals', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('supersedes', 'Supersedes', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('conflicts_with', 'Conflicts With', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('consistent_with', 'Consistent With', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('requires', 'Requires', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('satisfies', 'Satisfies', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_observation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('exempts_from', 'Exempts From', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_relation_observations; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_relation_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('cites', 'Cites', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('references', 'References', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('authorized_by', 'Authorized By', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('implements', 'Implements', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('amends', 'Amends', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('repeals', 'Repeals', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('partially_repeals', 'Partially Repeals', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('supersedes', 'Supersedes', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('requires', 'Requires', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('satisfies', 'Satisfies', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('exempts_from', 'Exempts From', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_tag_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_tag_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('topic', 'Topic', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_tag_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('doctrine', 'Doctrine', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_tag_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('practice_area', 'Practice Area', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_tag_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('industry', 'Industry', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_tag_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('procedure', 'Procedure', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_tag_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('institution', 'Institution', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_tag_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_tags; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_treatment_assertions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: legal_treatment_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.legal_treatment_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('cites', 'Cites', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_treatment_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('references', 'References', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_treatment_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('interprets', 'Interprets', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_treatment_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('applies', 'Applies', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_treatment_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('declines_to_apply', 'Declines To Apply', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_treatment_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('follows', 'Follows', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_treatment_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('distinguishes', 'Distinguishes', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_treatment_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('limits', 'Limits', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_treatment_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('questions', 'Questions', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_treatment_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('criticizes', 'Criticizes', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_treatment_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('overrules', 'Overrules', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_treatment_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('abrogates', 'Abrogates', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_treatment_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('conflicts_with', 'Conflicts With', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.legal_treatment_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('consistent_with', 'Consistent With', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: legal_version_authority_assessments; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: matter_taxonomy_relation_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.matter_taxonomy_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('broader', 'Broader', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.matter_taxonomy_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('part_of', 'Part Of', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.matter_taxonomy_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('related', 'Related', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: panel_role_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.panel_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('presiding', 'Presiding', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.panel_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('rapporteur', 'Rapporteur', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.panel_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('ponente', 'Ponente', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.panel_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('member', 'Member', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.panel_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: parser_versions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: participants; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: party_representations; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: party_side_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.party_side_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('claimant', 'Claimant', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.party_side_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('respondent', 'Respondent', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.party_side_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('neutral', 'Neutral', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.party_side_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('state', 'State', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.party_side_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: passages; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: procedural_decision_relation_observations; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: procedural_decision_relation_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.procedural_decision_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('reviews', 'Reviews', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_decision_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('affirms', 'Affirms', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_decision_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('reverses', 'Reverses', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_decision_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('vacates', 'Vacates', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_decision_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('modifies', 'Modifies', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_decision_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('remands', 'Remands', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_decision_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('cassates', 'Cassates', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_decision_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('partially_cassates', 'Partially Cassates', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_decision_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('orders_new_trial', 'Orders New Trial', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_decision_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('enforces', 'Enforces', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_decision_relation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: procedural_decision_relations; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: procedural_event_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('filing', 'Filing', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('service', 'Service', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('hearing', 'Hearing', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('motion', 'Motion', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('appeal', 'Appeal', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('cassation_filing', 'Cassation Filing', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('constitutional_review_filing', 'Constitutional Review Filing', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('evidence_submission', 'Evidence Submission', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('opinion_submission', 'Opinion Submission', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('interlocutory_order', 'Interlocutory Order', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('decision_issued', 'Decision Issued', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('remand', 'Remand', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('settlement', 'Settlement', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('withdrawal', 'Withdrawal', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('stay', 'Stay', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('execution', 'Execution', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('transfer', 'Transfer', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_event_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: procedural_events; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: procedural_role_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('2ffc5661-fbd2-4329-9b6a-e1c9e36181dc', 'plaintiff', 'Plaintiff', 'claimant', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('e351bca8-0c6a-42d7-9628-3a1f15957871', 'defendant', 'Defendant', 'respondent', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('7a91fce2-fafa-4f61-9ab8-bd11dac7e844', 'appellant', 'Appellant / recurrente', 'claimant', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('ecd01b7e-0958-4722-a4f9-66ce560bc39b', 'appellee', 'Appellee / recurrido', 'respondent', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('a2779ee3-9540-4ad0-8ddf-ab1fe2f8f3b8', 'petitioner', 'Petitioner / accionante', 'claimant', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('35beb335-e394-4773-a634-8f309573aba1', 'respondent', 'Respondent / accionado', 'respondent', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('6f844e3d-3f9c-4fba-8545-c69acc1f2262', 'claimant', 'Claimant', 'claimant', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('972ddfea-bbdb-4b81-8e16-892aa37ec4d2', 'complainant', 'Complainant / querellante', 'claimant', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('8ef9b36d-ca42-4d9a-9e49-bc093089005d', 'accused', 'Accused / imputado', 'respondent', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('fe71b2ba-07f4-4e03-846e-2852fda891e9', 'prosecutor', 'Prosecutor', 'state', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('fe2aa9a8-447c-4b95-b703-5b5411cdfb5d', 'public_ministry', 'Ministerio Público', 'state', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('e64defc3-dc61-47d5-8728-8034231d10ff', 'intervenor', 'Intervenor', 'neutral', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('d2b895b1-494b-44b3-b86b-5e7104d96893', 'third_party', 'Third party', 'other', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('247afb24-5e78-4c4e-9fc0-65584075d9fc', 'amicus', 'Amicus curiae', 'neutral', NULL, '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedural_role_concepts (id, code, name, default_party_side, broader_concept_id, created_at) VALUES ('e87b28e8-d9e2-47fd-aa9d-5f08ec1ff226', 'other', 'Other', 'other', NULL, '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: procedure_concept_edges; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: procedure_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: procedure_taxonomy_relation_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.procedure_taxonomy_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('broader', 'Broader', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedure_taxonomy_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('part_of', 'Part Of', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.procedure_taxonomy_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('related', 'Related', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: proceeding_decision_relation_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.proceeding_decision_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('decision_in_proceeding', 'Decision In Proceeding', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.proceeding_decision_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('reviews_proceeding', 'Reviews Proceeding', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.proceeding_decision_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('consolidates_proceeding', 'Consolidates Proceeding', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.proceeding_decision_relation_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('arises_from_proceeding', 'Arises From Proceeding', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: proceeding_decisions; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: proceeding_identifier_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.proceeding_identifier_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('expediente_number', 'Expediente Number', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.proceeding_identifier_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('docket_number', 'Docket Number', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.proceeding_identifier_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('legacy_docket_number', 'Legacy Docket Number', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.proceeding_identifier_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('source_specific_id', 'Source Specific Id', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.proceeding_identifier_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: proceeding_identifiers; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: proceeding_participants; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: proceeding_party_roles; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: proceeding_relation_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.proceeding_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at, is_symmetric) VALUES ('ee9e404f-3e43-4f7f-87f4-67abefb3c817', 'appeal_of', 'Appeal of', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00', false);
INSERT INTO corpus.proceeding_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at, is_symmetric) VALUES ('91b949be-c236-418b-97e7-1161128607e4', 'cassation_of', 'Cassation of', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00', false);
INSERT INTO corpus.proceeding_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at, is_symmetric) VALUES ('eaa0f2d2-d491-4d88-80f1-c1d4b99ff5f8', 'review_of', 'Review of', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00', false);
INSERT INTO corpus.proceeding_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at, is_symmetric) VALUES ('cbae07ad-8f94-4637-89f5-b47a9c1e3f60', 'constitutional_review_of', 'Constitutional review of', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00', false);
INSERT INTO corpus.proceeding_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at, is_symmetric) VALUES ('95585f20-f553-4962-a9bb-7a27bd25a1d0', 'incident_to', 'Incident to', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00', false);
INSERT INTO corpus.proceeding_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at, is_symmetric) VALUES ('6e487b66-2df2-433f-aca0-aad33d3c0607', 'remand_from', 'Remand from', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00', false);
INSERT INTO corpus.proceeding_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at, is_symmetric) VALUES ('756b5651-1333-44ed-b867-8c6faa8f1459', 'continuation_of', 'Continuation of', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00', false);
INSERT INTO corpus.proceeding_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at, is_symmetric) VALUES ('54353d35-deee-4f96-bc2e-1e3c33bf0527', 'enforcement_of', 'Enforcement of', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00', false);
INSERT INTO corpus.proceeding_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at, is_symmetric) VALUES ('f7357e03-85e2-4f92-8c43-38f507cf5c00', 'reopened_from', 'Reopened from', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00', false);
INSERT INTO corpus.proceeding_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at, is_symmetric) VALUES ('4dfa6332-14c7-4924-a12c-2b28f25414dc', 'consolidated_with', 'Consolidated with', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00', true);
INSERT INTO corpus.proceeding_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at, is_symmetric) VALUES ('87e9b466-a1fd-4182-ab50-9ec13e56d368', 'severed_from', 'Severed from', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00', false);
INSERT INTO corpus.proceeding_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at, is_symmetric) VALUES ('941b6f06-0d7c-4777-bca4-7a3feddc6343', 'transferred_from', 'Transferred from', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00', false);
INSERT INTO corpus.proceeding_relation_concepts (id, code, name, description, jurisdiction_code, broader_concept_id, created_at, is_symmetric) VALUES ('a2714c17-c3a6-486b-8261-708f795021e2', 'related_to', 'Related to', NULL, NULL, NULL, '2026-09-20 03:17:55.220807+00', true);


--
-- Data for Name: proceeding_relations; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: provision_source_role_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.provision_source_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('primary_text', 'Primary Text', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_source_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('official_consolidation', 'Official Consolidation', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_source_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('editorial_consolidation', 'Editorial Consolidation', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_source_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('correction', 'Correction', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_source_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('historical_copy', 'Historical Copy', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_source_role_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: provision_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.provision_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('title', 'Title', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('book', 'Book', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('chapter', 'Chapter', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('section', 'Section', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('article', 'Article', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('paragraph', 'Paragraph', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('clause', 'Clause', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('subclause', 'Subclause', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('item', 'Item', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('annex', 'Annex', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('preamble', 'Preamble', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.provision_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: representation_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.representation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('counsel', 'Counsel', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.representation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('lead_counsel', 'Lead Counsel', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.representation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('public_defender', 'Public Defender', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.representation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('attorney_in_fact', 'Attorney In Fact', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.representation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('government_counsel', 'Government Counsel', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.representation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('guardian_ad_litem', 'Guardian Ad Litem', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.representation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('self_represented', 'Self Represented', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.representation_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: scopes; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.scopes (id, visibility, organization_id, created_at) VALUES ('00000000-0000-0000-0000-000000000001', 'public', NULL, '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: source_artifact_locations; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: source_artifacts; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: source_collections; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: source_document_artifacts; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: source_document_observations; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: source_documents; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: source_registries; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Data for Name: territorial_unit_type_concepts; Type: TABLE DATA; Schema: corpus; Owner: -
--

INSERT INTO corpus.territorial_unit_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('country', 'Country', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.territorial_unit_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('province', 'Province', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.territorial_unit_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('municipality', 'Municipality', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.territorial_unit_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('district', 'District', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.territorial_unit_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('judicial_district', 'Judicial District', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.territorial_unit_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('region', 'Region', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');
INSERT INTO corpus.territorial_unit_type_concepts (code, name, description, jurisdiction_code, created_at, updated_at) VALUES ('other', 'Other', NULL, NULL, '2026-09-20 03:17:55.220807+00', '2026-09-20 03:17:55.220807+00');


--
-- Data for Name: territorial_units; Type: TABLE DATA; Schema: corpus; Owner: -
--



--
-- Name: acquisition_run_items acquisition_run_items_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.acquisition_run_items
    ADD CONSTRAINT acquisition_run_items_pkey PRIMARY KEY (id);


--
-- Name: acquisition_run_items acquisition_run_items_run_id_source_document_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.acquisition_run_items
    ADD CONSTRAINT acquisition_run_items_run_id_source_document_id_key UNIQUE (run_id, source_document_id);


--
-- Name: acquisition_runs acquisition_runs_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.acquisition_runs
    ADD CONSTRAINT acquisition_runs_pkey PRIMARY KEY (id);


--
-- Name: adjudicative_act_type_concepts adjudicative_act_type_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.adjudicative_act_type_concepts
    ADD CONSTRAINT adjudicative_act_type_concepts_code_key UNIQUE (code);


--
-- Name: adjudicative_act_type_concepts adjudicative_act_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.adjudicative_act_type_concepts
    ADD CONSTRAINT adjudicative_act_type_concepts_pkey PRIMARY KEY (id);


--
-- Name: analysis_observations analysis_observations_identity_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.analysis_observations
    ADD CONSTRAINT analysis_observations_identity_key UNIQUE (scope_id, observation_key);


--
-- Name: analysis_observations analysis_observations_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.analysis_observations
    ADD CONSTRAINT analysis_observations_pkey PRIMARY KEY (id);


--
-- Name: artifact_pages artifact_pages_artifact_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.artifact_pages
    ADD CONSTRAINT artifact_pages_artifact_id_id_key UNIQUE (artifact_id, id);


--
-- Name: artifact_pages artifact_pages_artifact_id_page_number_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.artifact_pages
    ADD CONSTRAINT artifact_pages_artifact_id_page_number_key UNIQUE (artifact_id, page_number);


--
-- Name: artifact_pages artifact_pages_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.artifact_pages
    ADD CONSTRAINT artifact_pages_pkey PRIMARY KEY (id);


--
-- Name: case_artifact_occurrences case_artifact_occurrences_case_id_artifact_id_start_page_en_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_artifact_occurrences
    ADD CONSTRAINT case_artifact_occurrences_case_id_artifact_id_start_page_en_key UNIQUE (case_id, artifact_id, start_page, end_page);


--
-- Name: case_artifact_occurrences case_artifact_occurrences_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_artifact_occurrences
    ADD CONSTRAINT case_artifact_occurrences_pkey PRIMARY KEY (id);


--
-- Name: judicial_decision_dispositions case_dispositions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decision_dispositions
    ADD CONSTRAINT case_dispositions_pkey PRIMARY KEY (id);


--
-- Name: judicial_decision_dispositions case_dispositions_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decision_dispositions
    ADD CONSTRAINT case_dispositions_unique UNIQUE (case_id, ordinal);


--
-- Name: case_identifier_type_concepts case_identifier_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_identifier_type_concepts
    ADD CONSTRAINT case_identifier_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: case_identifiers case_identifiers_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_identifiers
    ADD CONSTRAINT case_identifiers_pkey PRIMARY KEY (id);


--
-- Name: case_metadata_observations case_metadata_observations_case_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_metadata_observations
    ADD CONSTRAINT case_metadata_observations_case_id_id_key UNIQUE (case_id, id);


--
-- Name: case_metadata_observations case_metadata_observations_ingestion_job_id_observation_key_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_metadata_observations
    ADD CONSTRAINT case_metadata_observations_ingestion_job_id_observation_key_key UNIQUE (ingestion_job_id, observation_key);


--
-- Name: case_metadata_observations case_metadata_observations_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_metadata_observations
    ADD CONSTRAINT case_metadata_observations_pkey PRIMARY KEY (id);


--
-- Name: case_metadata_resolution_observations case_metadata_resolution_observations_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_metadata_resolution_observations
    ADD CONSTRAINT case_metadata_resolution_observations_pkey PRIMARY KEY (resolution_id, observation_id);


--
-- Name: case_metadata_resolutions case_metadata_resolutions_case_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_metadata_resolutions
    ADD CONSTRAINT case_metadata_resolutions_case_id_id_key UNIQUE (case_id, id);


--
-- Name: case_metadata_resolutions case_metadata_resolutions_idempotency_key_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_metadata_resolutions
    ADD CONSTRAINT case_metadata_resolutions_idempotency_key_key UNIQUE (idempotency_key);


--
-- Name: case_metadata_resolutions case_metadata_resolutions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_metadata_resolutions
    ADD CONSTRAINT case_metadata_resolutions_pkey PRIMARY KEY (id);


--
-- Name: case_pages case_pages_case_id_artifact_page_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_pages
    ADD CONSTRAINT case_pages_case_id_artifact_page_id_key UNIQUE (case_id, artifact_page_id);


--
-- Name: case_pages case_pages_case_id_id_artifact_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_pages
    ADD CONSTRAINT case_pages_case_id_id_artifact_id_key UNIQUE (case_id, id, artifact_id);


--
-- Name: case_pages case_pages_case_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_pages
    ADD CONSTRAINT case_pages_case_id_id_key UNIQUE (case_id, id);


--
-- Name: case_pages case_pages_case_id_ordinal_in_case_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_pages
    ADD CONSTRAINT case_pages_case_id_ordinal_in_case_key UNIQUE (case_id, ordinal_in_case);


--
-- Name: case_pages case_pages_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_pages
    ADD CONSTRAINT case_pages_pkey PRIMARY KEY (id);


--
-- Name: judicial_decisions cases_legal_document_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decisions
    ADD CONSTRAINT cases_legal_document_id_key UNIQUE (legal_document_id);


--
-- Name: judicial_decisions cases_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decisions
    ADD CONSTRAINT cases_pkey PRIMARY KEY (id);


--
-- Name: judicial_decisions cases_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decisions
    ADD CONSTRAINT cases_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: disposition_effect_concepts claim_effect_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.disposition_effect_concepts
    ADD CONSTRAINT claim_effect_concepts_code_key UNIQUE (code);


--
-- Name: disposition_effect_concepts claim_effect_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.disposition_effect_concepts
    ADD CONSTRAINT claim_effect_concepts_pkey PRIMARY KEY (id);


--
-- Name: claim_relation_concepts claim_relation_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.claim_relation_concepts
    ADD CONSTRAINT claim_relation_concepts_code_key UNIQUE (code);


--
-- Name: claim_relation_concepts claim_relation_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.claim_relation_concepts
    ADD CONSTRAINT claim_relation_concepts_pkey PRIMARY KEY (id);


--
-- Name: claim_relations claim_relations_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.claim_relations
    ADD CONSTRAINT claim_relations_pkey PRIMARY KEY (id);


--
-- Name: claim_relations claim_relations_source_claim_id_target_claim_id_relation_co_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.claim_relations
    ADD CONSTRAINT claim_relations_source_claim_id_target_claim_id_relation_co_key UNIQUE NULLS NOT DISTINCT (source_claim_id, target_claim_id, relation_concept_id, known_from);


--
-- Name: concept_schemes concept_schemes_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.concept_schemes
    ADD CONSTRAINT concept_schemes_pkey PRIMARY KEY (code);


--
-- Name: controversy_membership_role_concepts controversy_membership_role_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.controversy_membership_role_concepts
    ADD CONSTRAINT controversy_membership_role_concepts_code_key UNIQUE (code);


--
-- Name: controversy_membership_role_concepts controversy_membership_role_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.controversy_membership_role_concepts
    ADD CONSTRAINT controversy_membership_role_concepts_pkey PRIMARY KEY (id);


--
-- Name: controversy_proceedings controversy_proceedings_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.controversy_proceedings
    ADD CONSTRAINT controversy_proceedings_pkey PRIMARY KEY (id);


--
-- Name: court_alias_kind_concepts court_alias_kind_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_alias_kind_concepts
    ADD CONSTRAINT court_alias_kind_concepts_pkey PRIMARY KEY (code);


--
-- Name: court_aliases court_aliases_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_aliases
    ADD CONSTRAINT court_aliases_pkey PRIMARY KEY (id);


--
-- Name: court_aliases court_aliases_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_aliases
    ADD CONSTRAINT court_aliases_unique UNIQUE (court_id, normalized_alias, alias_kind, source_registry_id);


--
-- Name: court_function_type_concepts court_function_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_function_type_concepts
    ADD CONSTRAINT court_function_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: court_functional_competences court_functional_competences_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_functional_competences
    ADD CONSTRAINT court_functional_competences_pkey PRIMARY KEY (id);


--
-- Name: court_functional_competences court_functional_competences_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_functional_competences
    ADD CONSTRAINT court_functional_competences_unique UNIQUE NULLS NOT DISTINCT (court_id, function_type, instance_level, procedure_concept_id, valid_from);


--
-- Name: court_instance_level_concepts court_instance_level_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_instance_level_concepts
    ADD CONSTRAINT court_instance_level_concepts_pkey PRIMARY KEY (code);


--
-- Name: court_jurisdictions court_jurisdictions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_jurisdictions
    ADD CONSTRAINT court_jurisdictions_pkey PRIMARY KEY (court_id, jurisdiction_code);


--
-- Name: court_organ_alias_kind_concepts court_organ_alias_kind_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_organ_alias_kind_concepts
    ADD CONSTRAINT court_organ_alias_kind_concepts_pkey PRIMARY KEY (code);


--
-- Name: court_organ_aliases court_organ_aliases_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_organ_aliases
    ADD CONSTRAINT court_organ_aliases_pkey PRIMARY KEY (id);


--
-- Name: court_organ_aliases court_organ_aliases_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_organ_aliases
    ADD CONSTRAINT court_organ_aliases_unique UNIQUE (court_organ_id, normalized_alias, alias_kind, source_registry_id);


--
-- Name: court_organs court_organs_court_id_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_organs
    ADD CONSTRAINT court_organs_court_id_code_key UNIQUE (court_id, code);


--
-- Name: court_organs court_organs_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_organs
    ADD CONSTRAINT court_organs_pkey PRIMARY KEY (id);


--
-- Name: court_relation_type_concepts court_relation_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_relation_type_concepts
    ADD CONSTRAINT court_relation_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: court_relations court_relations_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_relations
    ADD CONSTRAINT court_relations_pkey PRIMARY KEY (id);


--
-- Name: court_relations court_relations_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_relations
    ADD CONSTRAINT court_relations_unique UNIQUE (from_court_id, to_court_id, relation_type, active_from);


--
-- Name: court_subject_matter_competences court_subject_matter_competences_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_subject_matter_competences
    ADD CONSTRAINT court_subject_matter_competences_pkey PRIMARY KEY (id);


--
-- Name: court_subject_matter_competences court_subject_matter_competences_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_subject_matter_competences
    ADD CONSTRAINT court_subject_matter_competences_unique UNIQUE NULLS NOT DISTINCT (court_id, legal_matter_concept_id, valid_from);


--
-- Name: court_territorial_competences court_territorial_competences_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_territorial_competences
    ADD CONSTRAINT court_territorial_competences_pkey PRIMARY KEY (id);


--
-- Name: court_territorial_competences court_territorial_competences_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_territorial_competences
    ADD CONSTRAINT court_territorial_competences_unique UNIQUE NULLS NOT DISTINCT (court_id, territorial_unit_id, valid_from);


--
-- Name: court_type_concepts court_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_type_concepts
    ADD CONSTRAINT court_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: courts courts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.courts
    ADD CONSTRAINT courts_code_key UNIQUE (code);


--
-- Name: courts courts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.courts
    ADD CONSTRAINT courts_pkey PRIMARY KEY (id);


--
-- Name: decision_legal_matters decision_legal_matters_decision_id_legal_matter_concept_id__key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_matters
    ADD CONSTRAINT decision_legal_matters_decision_id_legal_matter_concept_id__key UNIQUE (decision_id, legal_matter_concept_id, relation_type);


--
-- Name: decision_legal_matters decision_legal_matters_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_matters
    ADD CONSTRAINT decision_legal_matters_pkey PRIMARY KEY (id);


--
-- Name: decision_legal_states decision_legal_states_decision_id_state_concept_id_known_fr_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_states
    ADD CONSTRAINT decision_legal_states_decision_id_state_concept_id_known_fr_key UNIQUE (decision_id, state_concept_id, known_from);


--
-- Name: decision_legal_states decision_legal_states_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_states
    ADD CONSTRAINT decision_legal_states_pkey PRIMARY KEY (id);


--
-- Name: decision_legal_status_events decision_legal_status_events_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_status_events
    ADD CONSTRAINT decision_legal_status_events_pkey PRIMARY KEY (id);


--
-- Name: decision_matter_relation_concepts decision_matter_relation_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_matter_relation_concepts
    ADD CONSTRAINT decision_matter_relation_concepts_pkey PRIMARY KEY (code);


--
-- Name: decision_panel_members decision_panel_members_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_panel_members
    ADD CONSTRAINT decision_panel_members_pkey PRIMARY KEY (id);


--
-- Name: decision_panel_members decision_panel_members_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_panel_members
    ADD CONSTRAINT decision_panel_members_unique UNIQUE (case_id, officer_id);


--
-- Name: decision_procedure_relation_concepts decision_procedure_relation_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_procedure_relation_concepts
    ADD CONSTRAINT decision_procedure_relation_concepts_pkey PRIMARY KEY (code);


--
-- Name: decision_procedures decision_procedures_decision_id_procedure_concept_id_relati_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_procedures
    ADD CONSTRAINT decision_procedures_decision_id_procedure_concept_id_relati_key UNIQUE (decision_id, procedure_concept_id, relation_type);


--
-- Name: decision_procedures decision_procedures_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_procedures
    ADD CONSTRAINT decision_procedures_pkey PRIMARY KEY (id);


--
-- Name: decision_state_concepts decision_state_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_state_concepts
    ADD CONSTRAINT decision_state_concepts_code_key UNIQUE (code);


--
-- Name: decision_state_concepts decision_state_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_state_concepts
    ADD CONSTRAINT decision_state_concepts_pkey PRIMARY KEY (id);


--
-- Name: decision_votes decision_votes_case_officer_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_votes
    ADD CONSTRAINT decision_votes_case_officer_id_key UNIQUE (case_id, officer_id, id);


--
-- Name: decision_votes decision_votes_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_votes
    ADD CONSTRAINT decision_votes_pkey PRIMARY KEY (id);


--
-- Name: decision_votes decision_votes_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_votes
    ADD CONSTRAINT decision_votes_unique UNIQUE (case_id, officer_id);


--
-- Name: judicial_disposition_action_arguments disposition_arguments_action_ordinal_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_action_arguments
    ADD CONSTRAINT disposition_arguments_action_ordinal_key UNIQUE (action_id, ordinal);


--
-- Name: disposition_concepts disposition_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.disposition_concepts
    ADD CONSTRAINT disposition_concepts_code_key UNIQUE (code);


--
-- Name: disposition_concepts disposition_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.disposition_concepts
    ADD CONSTRAINT disposition_concepts_pkey PRIMARY KEY (id);


--
-- Name: disposition_effect_argument_rules disposition_effect_argument_rules_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.disposition_effect_argument_rules
    ADD CONSTRAINT disposition_effect_argument_rules_pkey PRIMARY KEY (effect_concept_id, role_concept_id, object_type);


--
-- Name: entity_identity_assertion_evidence entity_identity_assertion_evidence_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_assertion_evidence
    ADD CONSTRAINT entity_identity_assertion_evidence_pkey PRIMARY KEY (id);


--
-- Name: entity_identity_assertions entity_identity_assertions_history_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_assertions
    ADD CONSTRAINT entity_identity_assertions_history_key UNIQUE (observed_entity_id, candidate_entity_id, relation_concept_id, known_from);


--
-- Name: entity_identity_assertions entity_identity_assertions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_assertions
    ADD CONSTRAINT entity_identity_assertions_pkey PRIMARY KEY (id);


--
-- Name: entity_identity_assertions entity_identity_assertions_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_assertions
    ADD CONSTRAINT entity_identity_assertions_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: entity_identity_resolutions entity_identity_resolutions_history_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_resolutions
    ADD CONSTRAINT entity_identity_resolutions_history_key UNIQUE (observed_entity_id, known_from);


--
-- Name: entity_identity_resolutions entity_identity_resolutions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_resolutions
    ADD CONSTRAINT entity_identity_resolutions_pkey PRIMARY KEY (id);


--
-- Name: factual_proposition_evidence factual_proposition_evidence_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_proposition_evidence
    ADD CONSTRAINT factual_proposition_evidence_pkey PRIMARY KEY (id);


--
-- Name: factual_proposition_subjects factual_proposition_subjects_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_proposition_subjects
    ADD CONSTRAINT factual_proposition_subjects_pkey PRIMARY KEY (id);


--
-- Name: factual_propositions factual_propositions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_propositions
    ADD CONSTRAINT factual_propositions_pkey PRIMARY KEY (id);


--
-- Name: factual_propositions factual_propositions_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_propositions
    ADD CONSTRAINT factual_propositions_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: ingestion_jobs ingestion_jobs_id_artifact_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.ingestion_jobs
    ADD CONSTRAINT ingestion_jobs_id_artifact_id_key UNIQUE (id, artifact_id);


--
-- Name: ingestion_jobs ingestion_jobs_idempotency_key_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.ingestion_jobs
    ADD CONSTRAINT ingestion_jobs_idempotency_key_key UNIQUE (idempotency_key);


--
-- Name: ingestion_jobs ingestion_jobs_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.ingestion_jobs
    ADD CONSTRAINT ingestion_jobs_pkey PRIMARY KEY (id);


--
-- Name: instrument_authority_role_concepts instrument_authority_role_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.instrument_authority_role_concepts
    ADD CONSTRAINT instrument_authority_role_concepts_pkey PRIMARY KEY (code);


--
-- Name: instrument_document_role_concepts instrument_document_role_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.instrument_document_role_concepts
    ADD CONSTRAINT instrument_document_role_concepts_pkey PRIMARY KEY (code);


--
-- Name: instrument_version_kind_concepts instrument_version_kind_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.instrument_version_kind_concepts
    ADD CONSTRAINT instrument_version_kind_concepts_pkey PRIMARY KEY (code);


--
-- Name: judicial_authority_effect_concepts judicial_authority_effect_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_authority_effect_concepts
    ADD CONSTRAINT judicial_authority_effect_concepts_code_key UNIQUE (code);


--
-- Name: judicial_authority_effect_concepts judicial_authority_effect_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_authority_effect_concepts
    ADD CONSTRAINT judicial_authority_effect_concepts_pkey PRIMARY KEY (id);


--
-- Name: judicial_authorship_role_concepts judicial_authorship_role_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_authorship_role_concepts
    ADD CONSTRAINT judicial_authorship_role_concepts_pkey PRIMARY KEY (code);


--
-- Name: judicial_decision_dispositions judicial_decision_dispositions_case_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decision_dispositions
    ADD CONSTRAINT judicial_decision_dispositions_case_id_id_key UNIQUE (case_id, id);


--
-- Name: judicial_decision_dispositions judicial_decision_dispositions_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decision_dispositions
    ADD CONSTRAINT judicial_decision_dispositions_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: judicial_disposition_action_arguments judicial_disposition_action_arguments_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_action_arguments
    ADD CONSTRAINT judicial_disposition_action_arguments_pkey PRIMARY KEY (id);


--
-- Name: judicial_disposition_actions judicial_disposition_actions_disposition_id_ordinal_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_actions
    ADD CONSTRAINT judicial_disposition_actions_disposition_id_ordinal_key UNIQUE (disposition_id, ordinal);


--
-- Name: judicial_disposition_actions judicial_disposition_actions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_actions
    ADD CONSTRAINT judicial_disposition_actions_pkey PRIMARY KEY (id);


--
-- Name: judicial_disposition_actions judicial_disposition_actions_scope_id_disposition_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_actions
    ADD CONSTRAINT judicial_disposition_actions_scope_id_disposition_id_id_key UNIQUE (scope_id, disposition_id, id);


--
-- Name: judicial_event_type_concepts judicial_event_type_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_event_type_concepts
    ADD CONSTRAINT judicial_event_type_concepts_code_key UNIQUE (code);


--
-- Name: judicial_event_type_concepts judicial_event_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_event_type_concepts
    ADD CONSTRAINT judicial_event_type_concepts_pkey PRIMARY KEY (id);


--
-- Name: judicial_officer_position_type_concepts judicial_officer_position_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_officer_position_type_concepts
    ADD CONSTRAINT judicial_officer_position_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: judicial_officer_positions judicial_officer_positions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_officer_positions
    ADD CONSTRAINT judicial_officer_positions_pkey PRIMARY KEY (id);


--
-- Name: judicial_officer_positions judicial_officer_positions_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_officer_positions
    ADD CONSTRAINT judicial_officer_positions_unique UNIQUE NULLS NOT DISTINCT (officer_id, court_id, position_type, valid_from);


--
-- Name: judicial_officers judicial_officers_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_officers
    ADD CONSTRAINT judicial_officers_pkey PRIMARY KEY (id);


--
-- Name: judicial_officers judicial_officers_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_officers
    ADD CONSTRAINT judicial_officers_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: judicial_opinion_authors judicial_opinion_authors_opinion_id_officer_id_authorship_r_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_authors
    ADD CONSTRAINT judicial_opinion_authors_opinion_id_officer_id_authorship_r_key UNIQUE (opinion_id, officer_id, authorship_role);


--
-- Name: judicial_opinion_authors judicial_opinion_authors_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_authors
    ADD CONSTRAINT judicial_opinion_authors_pkey PRIMARY KEY (id);


--
-- Name: judicial_opinion_join_type_concepts judicial_opinion_join_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_join_type_concepts
    ADD CONSTRAINT judicial_opinion_join_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: judicial_opinion_joiners judicial_opinion_joiners_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_joiners
    ADD CONSTRAINT judicial_opinion_joiners_pkey PRIMARY KEY (opinion_id, officer_id, join_type);


--
-- Name: judicial_opinion_type_concepts judicial_opinion_type_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_type_concepts
    ADD CONSTRAINT judicial_opinion_type_concepts_code_key UNIQUE (code);


--
-- Name: judicial_opinion_type_concepts judicial_opinion_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_type_concepts
    ADD CONSTRAINT judicial_opinion_type_concepts_pkey PRIMARY KEY (id);


--
-- Name: judicial_opinions judicial_opinions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinions
    ADD CONSTRAINT judicial_opinions_pkey PRIMARY KEY (id);


--
-- Name: judicial_opinions judicial_opinions_scope_case_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinions
    ADD CONSTRAINT judicial_opinions_scope_case_id_key UNIQUE (scope_id, case_id, id);


--
-- Name: judicial_opinions judicial_opinions_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinions
    ADD CONSTRAINT judicial_opinions_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: judicial_stance_concepts judicial_stance_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_stance_concepts
    ADD CONSTRAINT judicial_stance_concepts_code_key UNIQUE (code);


--
-- Name: judicial_stance_concepts judicial_stance_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_stance_concepts
    ADD CONSTRAINT judicial_stance_concepts_pkey PRIMARY KEY (id);


--
-- Name: judicial_system_concepts judicial_system_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_system_concepts
    ADD CONSTRAINT judicial_system_concepts_pkey PRIMARY KEY (code);


--
-- Name: judicial_vote_stances judicial_vote_stances_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_vote_stances
    ADD CONSTRAINT judicial_vote_stances_pkey PRIMARY KEY (id);


--
-- Name: judicial_vote_type_concepts judicial_vote_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_vote_type_concepts
    ADD CONSTRAINT judicial_vote_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: jurisdictions jurisdictions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.jurisdictions
    ADD CONSTRAINT jurisdictions_pkey PRIMARY KEY (code);


--
-- Name: legal_amendment_effect_type_concepts legal_amendment_effect_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_effect_type_concepts
    ADD CONSTRAINT legal_amendment_effect_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_amendment_effects legal_amendment_effects_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_effects
    ADD CONSTRAINT legal_amendment_effects_pkey PRIMARY KEY (id);


--
-- Name: legal_amendment_operation_type_concepts legal_amendment_operation_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_operation_type_concepts
    ADD CONSTRAINT legal_amendment_operation_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_amendment_operations legal_amendment_operations_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_operations
    ADD CONSTRAINT legal_amendment_operations_pkey PRIMARY KEY (id);


--
-- Name: legal_amendment_operations legal_amendment_operations_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_operations
    ADD CONSTRAINT legal_amendment_operations_unique UNIQUE (amendment_effect_id, sequence_number);


--
-- Name: legal_authorities legal_authorities_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_authorities
    ADD CONSTRAINT legal_authorities_pkey PRIMARY KEY (id);


--
-- Name: legal_authorities legal_authorities_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_authorities
    ADD CONSTRAINT legal_authorities_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_authority_type_concepts legal_authority_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_authority_type_concepts
    ADD CONSTRAINT legal_authority_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_claim_concepts legal_claim_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_claim_concepts
    ADD CONSTRAINT legal_claim_concepts_code_key UNIQUE (code);


--
-- Name: legal_claim_concepts legal_claim_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_claim_concepts
    ADD CONSTRAINT legal_claim_concepts_pkey PRIMARY KEY (id);


--
-- Name: legal_claims legal_claims_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_claims
    ADD CONSTRAINT legal_claims_pkey PRIMARY KEY (id);


--
-- Name: legal_claims legal_claims_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_claims
    ADD CONSTRAINT legal_claims_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_claims legal_claims_scope_proceeding_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_claims
    ADD CONSTRAINT legal_claims_scope_proceeding_id_key UNIQUE (scope_id, proceeding_id, id);


--
-- Name: legal_concept_aliases legal_concept_aliases_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_concept_aliases
    ADD CONSTRAINT legal_concept_aliases_pkey PRIMARY KEY (id);


--
-- Name: legal_concept_aliases legal_concept_aliases_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_concept_aliases
    ADD CONSTRAINT legal_concept_aliases_unique UNIQUE NULLS NOT DISTINCT (concept_id, language_code, alias);


--
-- Name: legal_concept_edges legal_concept_edges_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_concept_edges
    ADD CONSTRAINT legal_concept_edges_pkey PRIMARY KEY (id);


--
-- Name: legal_concept_edges legal_concept_edges_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_concept_edges
    ADD CONSTRAINT legal_concept_edges_unique UNIQUE NULLS NOT DISTINCT (source_concept_id, relation_type, target_concept_id, valid_from);


--
-- Name: legal_concepts legal_concepts_identity_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_concepts
    ADD CONSTRAINT legal_concepts_identity_key UNIQUE NULLS NOT DISTINCT (scheme_code, jurisdiction_code, code);


--
-- Name: legal_concepts legal_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_concepts
    ADD CONSTRAINT legal_concepts_pkey PRIMARY KEY (id);


--
-- Name: legal_concepts legal_concepts_scheme_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_concepts
    ADD CONSTRAINT legal_concepts_scheme_id_key UNIQUE (scheme_code, id);


--
-- Name: legal_controversies legal_controversies_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_controversies
    ADD CONSTRAINT legal_controversies_pkey PRIMARY KEY (id);


--
-- Name: legal_controversies legal_controversies_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_controversies
    ADD CONSTRAINT legal_controversies_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_controversy_status_concepts legal_controversy_status_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_controversy_status_concepts
    ADD CONSTRAINT legal_controversy_status_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_document_artifact_occurrences legal_document_artifact_occurrences_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_artifact_occurrences
    ADD CONSTRAINT legal_document_artifact_occurrences_pkey PRIMARY KEY (id);


--
-- Name: legal_document_identifiers legal_document_identifiers_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_identifiers
    ADD CONSTRAINT legal_document_identifiers_pkey PRIMARY KEY (id);


--
-- Name: legal_document_identifiers legal_document_identifiers_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_identifiers
    ADD CONSTRAINT legal_document_identifiers_unique UNIQUE (document_id, identifier_type, raw_value, source_registry_id);


--
-- Name: legal_document_artifact_occurrences legal_document_occurrence_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_artifact_occurrences
    ADD CONSTRAINT legal_document_occurrence_unique UNIQUE (document_id, artifact_id, occurrence_kind, start_page, end_page);


--
-- Name: legal_document_provisions legal_document_provisions_document_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_provisions
    ADD CONSTRAINT legal_document_provisions_document_id_id_key UNIQUE (document_id, id);


--
-- Name: legal_document_provisions legal_document_provisions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_provisions
    ADD CONSTRAINT legal_document_provisions_pkey PRIMARY KEY (id);


--
-- Name: legal_document_tags legal_document_tags_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_tags
    ADD CONSTRAINT legal_document_tags_pkey PRIMARY KEY (document_id, tag_id, provenance);


--
-- Name: legal_document_type_concepts legal_document_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_type_concepts
    ADD CONSTRAINT legal_document_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_documents legal_documents_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_documents
    ADD CONSTRAINT legal_documents_pkey PRIMARY KEY (id);


--
-- Name: legal_documents legal_documents_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_documents
    ADD CONSTRAINT legal_documents_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_entities legal_entities_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_entities
    ADD CONSTRAINT legal_entities_pkey PRIMARY KEY (id);


--
-- Name: legal_entities legal_entities_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_entities
    ADD CONSTRAINT legal_entities_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_instrument_authority_roles legal_instrument_authority_roles_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_authority_roles
    ADD CONSTRAINT legal_instrument_authority_roles_pkey PRIMARY KEY (id);


--
-- Name: legal_instrument_authority_roles legal_instrument_authority_roles_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_authority_roles
    ADD CONSTRAINT legal_instrument_authority_roles_unique UNIQUE NULLS NOT DISTINCT (instrument_id, authority_id, authority_role, valid_from);


--
-- Name: legal_instrument_event_type_concepts legal_instrument_event_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_event_type_concepts
    ADD CONSTRAINT legal_instrument_event_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_instrument_events legal_instrument_events_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_events
    ADD CONSTRAINT legal_instrument_events_pkey PRIMARY KEY (id);


--
-- Name: legal_instrument_identifiers legal_instrument_identifiers_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_identifiers
    ADD CONSTRAINT legal_instrument_identifiers_pkey PRIMARY KEY (id);


--
-- Name: legal_instrument_identifiers legal_instrument_identifiers_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_identifiers
    ADD CONSTRAINT legal_instrument_identifiers_unique UNIQUE NULLS NOT DISTINCT (instrument_id, identifier_type, raw_value, source_registry_id);


--
-- Name: legal_instrument_type_concepts legal_instrument_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_type_concepts
    ADD CONSTRAINT legal_instrument_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_instrument_version_documents legal_instrument_version_documents_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_version_documents
    ADD CONSTRAINT legal_instrument_version_documents_pkey PRIMARY KEY (id);


--
-- Name: legal_instrument_version_documents legal_instrument_version_documents_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_version_documents
    ADD CONSTRAINT legal_instrument_version_documents_unique UNIQUE (instrument_version_id, document_id, document_role);


--
-- Name: legal_instrument_version_knowledge legal_instrument_version_knowledge_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_version_knowledge
    ADD CONSTRAINT legal_instrument_version_knowledge_pkey PRIMARY KEY (id);


--
-- Name: legal_instrument_version_knowledge legal_instrument_version_knowledge_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_version_knowledge
    ADD CONSTRAINT legal_instrument_version_knowledge_unique UNIQUE (instrument_version_id, known_from);


--
-- Name: legal_instrument_versions legal_instrument_versions_instrument_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_versions
    ADD CONSTRAINT legal_instrument_versions_instrument_id_id_key UNIQUE (instrument_id, id);


--
-- Name: legal_instrument_versions legal_instrument_versions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_versions
    ADD CONSTRAINT legal_instrument_versions_pkey PRIMARY KEY (id);


--
-- Name: legal_instrument_versions legal_instrument_versions_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_versions
    ADD CONSTRAINT legal_instrument_versions_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_instruments legal_instruments_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instruments
    ADD CONSTRAINT legal_instruments_pkey PRIMARY KEY (id);


--
-- Name: legal_instruments legal_instruments_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instruments
    ADD CONSTRAINT legal_instruments_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_issue_evidence legal_issue_evidence_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issue_evidence
    ADD CONSTRAINT legal_issue_evidence_pkey PRIMARY KEY (id);


--
-- Name: legal_issue_subjects legal_issue_subjects_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issue_subjects
    ADD CONSTRAINT legal_issue_subjects_pkey PRIMARY KEY (id);


--
-- Name: legal_issues legal_issues_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issues
    ADD CONSTRAINT legal_issues_pkey PRIMARY KEY (id);


--
-- Name: legal_issues legal_issues_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issues
    ADD CONSTRAINT legal_issues_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_matter_concept_edges legal_matter_concept_edges_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_matter_concept_edges
    ADD CONSTRAINT legal_matter_concept_edges_pkey PRIMARY KEY (id);


--
-- Name: legal_matter_concept_edges legal_matter_concept_edges_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_matter_concept_edges
    ADD CONSTRAINT legal_matter_concept_edges_unique UNIQUE (narrower_concept_id, broader_concept_id, relation_type);


--
-- Name: legal_matter_concepts legal_matter_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_matter_concepts
    ADD CONSTRAINT legal_matter_concepts_code_key UNIQUE (code);


--
-- Name: legal_matter_concepts legal_matter_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_matter_concepts
    ADD CONSTRAINT legal_matter_concepts_pkey PRIMARY KEY (id);


--
-- Name: legal_norm_assertions legal_norm_assertions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_assertions
    ADD CONSTRAINT legal_norm_assertions_pkey PRIMARY KEY (id);


--
-- Name: legal_norm_assertions legal_norm_assertions_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_assertions
    ADD CONSTRAINT legal_norm_assertions_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_norm_claims legal_norm_claims_identity; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_claims
    ADD CONSTRAINT legal_norm_claims_identity UNIQUE NULLS NOT DISTINCT (scope_id, proposition_id, jurisdiction_code, norm_kind, legal_matter_concept_id, valid_from, valid_to);


--
-- Name: legal_norm_claims legal_norm_claims_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_claims
    ADD CONSTRAINT legal_norm_claims_pkey PRIMARY KEY (id);


--
-- Name: legal_norm_claims legal_norm_claims_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_claims
    ADD CONSTRAINT legal_norm_claims_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_norm_source_role_concepts legal_norm_source_role_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_source_role_concepts
    ADD CONSTRAINT legal_norm_source_role_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_norm_sources legal_norm_sources_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_sources
    ADD CONSTRAINT legal_norm_sources_pkey PRIMARY KEY (id);


--
-- Name: legal_norm_sources legal_norm_sources_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_sources
    ADD CONSTRAINT legal_norm_sources_unique UNIQUE NULLS NOT DISTINCT (norm_assertion_id, source_document_id, source_document_provision_id, source_role);


--
-- Name: legal_proceeding_status_concepts legal_proceeding_status_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proceeding_status_concepts
    ADD CONSTRAINT legal_proceeding_status_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_proceedings legal_proceedings_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proceedings
    ADD CONSTRAINT legal_proceedings_pkey PRIMARY KEY (id);


--
-- Name: legal_proceedings legal_proceedings_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proceedings
    ADD CONSTRAINT legal_proceedings_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_proposition_evidence legal_proposition_evidence_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_evidence
    ADD CONSTRAINT legal_proposition_evidence_pkey PRIMARY KEY (id);


--
-- Name: legal_proposition_evidence_role_concepts legal_proposition_evidence_role_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_evidence_role_concepts
    ADD CONSTRAINT legal_proposition_evidence_role_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_proposition_evidence legal_proposition_evidence_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_evidence
    ADD CONSTRAINT legal_proposition_evidence_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_proposition_relation_concepts legal_proposition_relation_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_relation_concepts
    ADD CONSTRAINT legal_proposition_relation_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_proposition_relations legal_proposition_relations_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_relations
    ADD CONSTRAINT legal_proposition_relations_pkey PRIMARY KEY (id);


--
-- Name: legal_proposition_relations legal_proposition_relations_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_relations
    ADD CONSTRAINT legal_proposition_relations_unique UNIQUE (from_proposition_id, relation_type, to_proposition_id);


--
-- Name: legal_proposition_subjects legal_proposition_subjects_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_subjects
    ADD CONSTRAINT legal_proposition_subjects_pkey PRIMARY KEY (id);


--
-- Name: legal_propositions legal_propositions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_propositions
    ADD CONSTRAINT legal_propositions_pkey PRIMARY KEY (id);


--
-- Name: legal_propositions legal_propositions_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_propositions
    ADD CONSTRAINT legal_propositions_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_provision_lineage legal_provision_lineage_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_lineage
    ADD CONSTRAINT legal_provision_lineage_pkey PRIMARY KEY (id);


--
-- Name: legal_provision_lineage_type_concepts legal_provision_lineage_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_lineage_type_concepts
    ADD CONSTRAINT legal_provision_lineage_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_provision_lineage legal_provision_lineage_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_lineage
    ADD CONSTRAINT legal_provision_lineage_unique UNIQUE NULLS NOT DISTINCT (from_provision_id, to_provision_id, lineage_type, effective_on);


--
-- Name: legal_provision_version_knowledge legal_provision_version_knowledge_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_version_knowledge
    ADD CONSTRAINT legal_provision_version_knowledge_pkey PRIMARY KEY (id);


--
-- Name: legal_provision_version_knowledge legal_provision_version_knowledge_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_version_knowledge
    ADD CONSTRAINT legal_provision_version_knowledge_unique UNIQUE (provision_version_id, known_from);


--
-- Name: legal_provision_version_sources legal_provision_version_sources_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_version_sources
    ADD CONSTRAINT legal_provision_version_sources_pkey PRIMARY KEY (id);


--
-- Name: legal_provision_version_sources legal_provision_version_sources_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_version_sources
    ADD CONSTRAINT legal_provision_version_sources_unique UNIQUE NULLS NOT DISTINCT (provision_version_id, source_document_id, source_document_provision_id, source_role);


--
-- Name: legal_provision_versions legal_provision_versions_instrument_version_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_versions
    ADD CONSTRAINT legal_provision_versions_instrument_version_id_id_key UNIQUE (instrument_version_id, id);


--
-- Name: legal_provision_versions legal_provision_versions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_versions
    ADD CONSTRAINT legal_provision_versions_pkey PRIMARY KEY (id);


--
-- Name: legal_provision_versions legal_provision_versions_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_versions
    ADD CONSTRAINT legal_provision_versions_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_provision_versions legal_provision_versions_unique_version_provision; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_versions
    ADD CONSTRAINT legal_provision_versions_unique_version_provision UNIQUE (instrument_version_id, provision_id);


--
-- Name: legal_provisions legal_provisions_instrument_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provisions
    ADD CONSTRAINT legal_provisions_instrument_id_id_key UNIQUE (instrument_id, id);


--
-- Name: legal_provisions legal_provisions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provisions
    ADD CONSTRAINT legal_provisions_pkey PRIMARY KEY (id);


--
-- Name: legal_provisions legal_provisions_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provisions
    ADD CONSTRAINT legal_provisions_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_relation_assertion_evidence legal_relation_assertion_evidence_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_assertion_evidence
    ADD CONSTRAINT legal_relation_assertion_evidence_pkey PRIMARY KEY (id);


--
-- Name: legal_relation_assertions legal_relation_assertions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_assertions
    ADD CONSTRAINT legal_relation_assertions_pkey PRIMARY KEY (id);


--
-- Name: legal_relation_assertions legal_relation_assertions_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_assertions
    ADD CONSTRAINT legal_relation_assertions_unique UNIQUE (relation_identity_id, known_from);


--
-- Name: legal_relation_identities legal_relation_identities_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_identities
    ADD CONSTRAINT legal_relation_identities_pkey PRIMARY KEY (id);


--
-- Name: legal_relation_identities legal_relation_identities_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_identities
    ADD CONSTRAINT legal_relation_identities_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: legal_relation_observation_type_concepts legal_relation_observation_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_observation_type_concepts
    ADD CONSTRAINT legal_relation_observation_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_relation_observations legal_relation_observations_observation_key_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_observations
    ADD CONSTRAINT legal_relation_observations_observation_key_key UNIQUE (observation_key);


--
-- Name: legal_relation_observations legal_relation_observations_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_observations
    ADD CONSTRAINT legal_relation_observations_pkey PRIMARY KEY (id);


--
-- Name: legal_relation_type_concepts legal_relation_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_type_concepts
    ADD CONSTRAINT legal_relation_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_tag_type_concepts legal_tag_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_tag_type_concepts
    ADD CONSTRAINT legal_tag_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_tags legal_tags_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_tags
    ADD CONSTRAINT legal_tags_pkey PRIMARY KEY (id);


--
-- Name: legal_tags legal_tags_slug_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_tags
    ADD CONSTRAINT legal_tags_slug_key UNIQUE (slug);


--
-- Name: legal_treatment_assertions legal_treatment_assertions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_treatment_assertions
    ADD CONSTRAINT legal_treatment_assertions_pkey PRIMARY KEY (id);


--
-- Name: legal_treatment_type_concepts legal_treatment_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_treatment_type_concepts
    ADD CONSTRAINT legal_treatment_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: legal_version_authority_assessments legal_version_authority_assessments_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_version_authority_assessments
    ADD CONSTRAINT legal_version_authority_assessments_pkey PRIMARY KEY (id);


--
-- Name: legal_version_authority_assessments legal_version_authority_assessments_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_version_authority_assessments
    ADD CONSTRAINT legal_version_authority_assessments_unique UNIQUE NULLS NOT DISTINCT (instrument_version_id, source_document_id, authority_class);


--
-- Name: matter_taxonomy_relation_concepts matter_taxonomy_relation_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.matter_taxonomy_relation_concepts
    ADD CONSTRAINT matter_taxonomy_relation_concepts_pkey PRIMARY KEY (code);


--
-- Name: panel_role_concepts panel_role_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.panel_role_concepts
    ADD CONSTRAINT panel_role_concepts_pkey PRIMARY KEY (code);


--
-- Name: parser_versions parser_versions_parser_name_parser_version_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.parser_versions
    ADD CONSTRAINT parser_versions_parser_name_parser_version_key UNIQUE (parser_name, parser_version);


--
-- Name: parser_versions parser_versions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.parser_versions
    ADD CONSTRAINT parser_versions_pkey PRIMARY KEY (id);


--
-- Name: participants participants_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.participants
    ADD CONSTRAINT participants_pkey PRIMARY KEY (id);


--
-- Name: participants participants_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.participants
    ADD CONSTRAINT participants_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: party_representations party_representations_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.party_representations
    ADD CONSTRAINT party_representations_pkey PRIMARY KEY (id);


--
-- Name: party_representations party_representations_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.party_representations
    ADD CONSTRAINT party_representations_unique UNIQUE NULLS NOT DISTINCT (party_role_id, representative_participant_id, representation_type, valid_from);


--
-- Name: party_side_concepts party_side_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.party_side_concepts
    ADD CONSTRAINT party_side_concepts_pkey PRIMARY KEY (code);


--
-- Name: passages passages_case_id_passage_order_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.passages
    ADD CONSTRAINT passages_case_id_passage_order_key UNIQUE (case_id, passage_order);


--
-- Name: passages passages_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.passages
    ADD CONSTRAINT passages_pkey PRIMARY KEY (id);


--
-- Name: judicial_authority_assertions precedential_authority_assertions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_authority_assertions
    ADD CONSTRAINT precedential_authority_assertions_pkey PRIMARY KEY (id);


--
-- Name: procedural_decision_relation_observations procedural_decision_relation_observations_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_decision_relation_observations
    ADD CONSTRAINT procedural_decision_relation_observations_pkey PRIMARY KEY (id);


--
-- Name: procedural_decision_relation_type_concepts procedural_decision_relation_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_decision_relation_type_concepts
    ADD CONSTRAINT procedural_decision_relation_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: procedural_decision_relations procedural_decision_relations_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_decision_relations
    ADD CONSTRAINT procedural_decision_relations_pkey PRIMARY KEY (id);


--
-- Name: procedural_decision_relations procedural_decision_relations_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_decision_relations
    ADD CONSTRAINT procedural_decision_relations_unique UNIQUE (source_case_id, relation_type, target_case_id);


--
-- Name: procedural_event_type_concepts procedural_event_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_event_type_concepts
    ADD CONSTRAINT procedural_event_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: procedural_events procedural_events_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_events
    ADD CONSTRAINT procedural_events_pkey PRIMARY KEY (id);


--
-- Name: procedural_decision_relation_observations procedural_relation_observations_identity_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_decision_relation_observations
    ADD CONSTRAINT procedural_relation_observations_identity_key UNIQUE (scope_id, observation_key);


--
-- Name: procedural_role_concepts procedural_role_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_role_concepts
    ADD CONSTRAINT procedural_role_concepts_code_key UNIQUE (code);


--
-- Name: procedural_role_concepts procedural_role_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_role_concepts
    ADD CONSTRAINT procedural_role_concepts_pkey PRIMARY KEY (id);


--
-- Name: procedure_concept_edges procedure_concept_edges_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedure_concept_edges
    ADD CONSTRAINT procedure_concept_edges_pkey PRIMARY KEY (id);


--
-- Name: procedure_concept_edges procedure_concept_edges_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedure_concept_edges
    ADD CONSTRAINT procedure_concept_edges_unique UNIQUE (narrower_concept_id, broader_concept_id, relation_type);


--
-- Name: procedure_concepts procedure_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedure_concepts
    ADD CONSTRAINT procedure_concepts_code_key UNIQUE (code);


--
-- Name: procedure_concepts procedure_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedure_concepts
    ADD CONSTRAINT procedure_concepts_pkey PRIMARY KEY (id);


--
-- Name: procedure_taxonomy_relation_concepts procedure_taxonomy_relation_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedure_taxonomy_relation_concepts
    ADD CONSTRAINT procedure_taxonomy_relation_concepts_pkey PRIMARY KEY (code);


--
-- Name: proceeding_decision_relation_concepts proceeding_decision_relation_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_decision_relation_concepts
    ADD CONSTRAINT proceeding_decision_relation_concepts_pkey PRIMARY KEY (code);


--
-- Name: proceeding_decisions proceeding_decisions_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_decisions
    ADD CONSTRAINT proceeding_decisions_pkey PRIMARY KEY (id);


--
-- Name: proceeding_decisions proceeding_decisions_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_decisions
    ADD CONSTRAINT proceeding_decisions_unique UNIQUE (proceeding_id, case_id, relation_type);


--
-- Name: proceeding_identifier_type_concepts proceeding_identifier_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_identifier_type_concepts
    ADD CONSTRAINT proceeding_identifier_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: proceeding_identifiers proceeding_identifiers_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_identifiers
    ADD CONSTRAINT proceeding_identifiers_pkey PRIMARY KEY (id);


--
-- Name: proceeding_participants proceeding_participants_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_participants
    ADD CONSTRAINT proceeding_participants_pkey PRIMARY KEY (id);


--
-- Name: proceeding_party_roles proceeding_party_roles_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_party_roles
    ADD CONSTRAINT proceeding_party_roles_pkey PRIMARY KEY (id);


--
-- Name: proceeding_party_roles proceeding_party_roles_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_party_roles
    ADD CONSTRAINT proceeding_party_roles_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: proceeding_party_roles proceeding_party_roles_scope_proceeding_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_party_roles
    ADD CONSTRAINT proceeding_party_roles_scope_proceeding_id_key UNIQUE (scope_id, proceeding_id, id);


--
-- Name: proceeding_party_roles proceeding_party_roles_unique; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_party_roles
    ADD CONSTRAINT proceeding_party_roles_unique UNIQUE NULLS NOT DISTINCT (proceeding_id, participant_id, role_concept_id, valid_from);


--
-- Name: proceeding_relation_concepts proceeding_relation_concepts_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_relation_concepts
    ADD CONSTRAINT proceeding_relation_concepts_code_key UNIQUE (code);


--
-- Name: proceeding_relation_concepts proceeding_relation_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_relation_concepts
    ADD CONSTRAINT proceeding_relation_concepts_pkey PRIMARY KEY (id);


--
-- Name: proceeding_relations proceeding_relations_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_relations
    ADD CONSTRAINT proceeding_relations_pkey PRIMARY KEY (id);


--
-- Name: proceeding_relations proceeding_relations_source_proceeding_id_target_proceeding_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_relations
    ADD CONSTRAINT proceeding_relations_source_proceeding_id_target_proceeding_key UNIQUE NULLS NOT DISTINCT (source_proceeding_id, target_proceeding_id, relation_concept_id, known_from);


--
-- Name: provision_source_role_concepts provision_source_role_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.provision_source_role_concepts
    ADD CONSTRAINT provision_source_role_concepts_pkey PRIMARY KEY (code);


--
-- Name: provision_type_concepts provision_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.provision_type_concepts
    ADD CONSTRAINT provision_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: representation_type_concepts representation_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.representation_type_concepts
    ADD CONSTRAINT representation_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: scopes scopes_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.scopes
    ADD CONSTRAINT scopes_pkey PRIMARY KEY (id);


--
-- Name: source_artifact_locations source_artifact_locations_artifact_locator_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_artifact_locations
    ADD CONSTRAINT source_artifact_locations_artifact_locator_key UNIQUE (artifact_id, locator_type, locator);


--
-- Name: CONSTRAINT source_artifact_locations_artifact_locator_key ON source_artifact_locations; Type: COMMENT; Schema: corpus; Owner: -
--

COMMENT ON CONSTRAINT source_artifact_locations_artifact_locator_key ON corpus.source_artifact_locations IS 'The same locator may point to different immutable artifacts over time; uniqueness applies only within one artifact.';


--
-- Name: source_artifact_locations source_artifact_locations_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_artifact_locations
    ADD CONSTRAINT source_artifact_locations_pkey PRIMARY KEY (id);


--
-- Name: source_artifacts source_artifacts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_artifacts
    ADD CONSTRAINT source_artifacts_pkey PRIMARY KEY (id);


--
-- Name: source_artifacts source_artifacts_scope_id_id_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_artifacts
    ADD CONSTRAINT source_artifacts_scope_id_id_key UNIQUE (scope_id, id);


--
-- Name: source_artifacts source_artifacts_sha256_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_artifacts
    ADD CONSTRAINT source_artifacts_sha256_key UNIQUE (sha256);


--
-- Name: source_collections source_collections_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_collections
    ADD CONSTRAINT source_collections_pkey PRIMARY KEY (id);


--
-- Name: source_collections source_collections_source_registry_id_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_collections
    ADD CONSTRAINT source_collections_source_registry_id_code_key UNIQUE (source_registry_id, code);


--
-- Name: source_document_artifacts source_document_artifacts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_document_artifacts
    ADD CONSTRAINT source_document_artifacts_pkey PRIMARY KEY (source_document_id, artifact_id, relationship_type);


--
-- Name: source_document_observations source_document_observations_identity_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_document_observations
    ADD CONSTRAINT source_document_observations_identity_key UNIQUE NULLS NOT DISTINCT (source_document_id, payload_sha256, artifact_availability, document_url);


--
-- Name: source_document_observations source_document_observations_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_document_observations
    ADD CONSTRAINT source_document_observations_pkey PRIMARY KEY (id);


--
-- Name: source_documents source_documents_identity_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_documents
    ADD CONSTRAINT source_documents_identity_key UNIQUE (source_registry_id, source_collection, source_identifier);


--
-- Name: source_documents source_documents_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_documents
    ADD CONSTRAINT source_documents_pkey PRIMARY KEY (id);


--
-- Name: source_registries source_registries_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_registries
    ADD CONSTRAINT source_registries_code_key UNIQUE (code);


--
-- Name: source_registries source_registries_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_registries
    ADD CONSTRAINT source_registries_pkey PRIMARY KEY (id);


--
-- Name: territorial_unit_type_concepts territorial_unit_type_concepts_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.territorial_unit_type_concepts
    ADD CONSTRAINT territorial_unit_type_concepts_pkey PRIMARY KEY (code);


--
-- Name: territorial_units territorial_units_code_key; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.territorial_units
    ADD CONSTRAINT territorial_units_code_key UNIQUE (code);


--
-- Name: territorial_units territorial_units_pkey; Type: CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.territorial_units
    ADD CONSTRAINT territorial_units_pkey PRIMARY KEY (id);


--
-- Name: acquisition_run_items_document_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX acquisition_run_items_document_idx ON corpus.acquisition_run_items USING btree (source_document_id, created_at DESC);


--
-- Name: acquisition_run_items_run_status_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX acquisition_run_items_run_status_idx ON corpus.acquisition_run_items USING btree (run_id, status);


--
-- Name: acquisition_runs_collection_time_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX acquisition_runs_collection_time_idx ON corpus.acquisition_runs USING btree (source_collection_id, requested_at DESC);


--
-- Name: acquisition_runs_status_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX acquisition_runs_status_idx ON corpus.acquisition_runs USING btree (status, requested_at);


--
-- Name: analysis_observations_case_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX analysis_observations_case_idx ON corpus.analysis_observations USING btree (scope_id, case_id, created_at DESC) WHERE (case_id IS NOT NULL);


--
-- Name: analysis_observations_payload_gin_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX analysis_observations_payload_gin_idx ON corpus.analysis_observations USING gin (payload jsonb_path_ops);


--
-- Name: analysis_observations_proceeding_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX analysis_observations_proceeding_idx ON corpus.analysis_observations USING btree (scope_id, proceeding_id, created_at DESC) WHERE (proceeding_id IS NOT NULL);


--
-- Name: analysis_observations_review_queue_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX analysis_observations_review_queue_idx ON corpus.analysis_observations USING btree (scope_id, status, observation_type, created_at DESC);


--
-- Name: artifact_pages_artifact_page_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX artifact_pages_artifact_page_idx ON corpus.artifact_pages USING btree (artifact_id, page_number);


--
-- Name: case_artifact_occurrences_artifact_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_artifact_occurrences_artifact_idx ON corpus.case_artifact_occurrences USING btree (artifact_id, start_page, end_page);


--
-- Name: case_artifact_occurrences_scope_artifact_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_artifact_occurrences_scope_artifact_idx ON corpus.case_artifact_occurrences USING btree (scope_id, artifact_id);


--
-- Name: case_artifact_occurrences_scope_case_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_artifact_occurrences_scope_case_idx ON corpus.case_artifact_occurrences USING btree (scope_id, case_id);


--
-- Name: case_identifiers_case_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_identifiers_case_idx ON corpus.case_identifiers USING btree (case_id);


--
-- Name: case_identifiers_evidence_case_page_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_identifiers_evidence_case_page_idx ON corpus.case_identifiers USING btree (evidence_case_page_id) WHERE (evidence_case_page_id IS NOT NULL);


--
-- Name: case_identifiers_lookup_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_identifiers_lookup_idx ON corpus.case_identifiers USING btree (identifier_type, normalized_value) WHERE (normalized_value IS NOT NULL);


--
-- Name: case_identifiers_same_case_evidence_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_identifiers_same_case_evidence_idx ON corpus.case_identifiers USING btree (case_id, evidence_case_page_id) WHERE (evidence_case_page_id IS NOT NULL);


--
-- Name: case_metadata_observations_case_field_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_metadata_observations_case_field_idx ON corpus.case_metadata_observations USING btree (case_id, field_name, status);


--
-- Name: case_metadata_observations_date_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_metadata_observations_date_idx ON corpus.case_metadata_observations USING btree (case_id, normalized_date) WHERE (normalized_date IS NOT NULL);


--
-- Name: case_metadata_observations_evidence_case_artifact_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_metadata_observations_evidence_case_artifact_idx ON corpus.case_metadata_observations USING btree (case_id, evidence_case_page_id, artifact_id) WHERE (evidence_case_page_id IS NOT NULL);


--
-- Name: case_metadata_observations_evidence_page_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_metadata_observations_evidence_page_idx ON corpus.case_metadata_observations USING btree (evidence_case_page_id) WHERE (evidence_case_page_id IS NOT NULL);


--
-- Name: case_metadata_observations_job_artifact_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_metadata_observations_job_artifact_idx ON corpus.case_metadata_observations USING btree (ingestion_job_id, artifact_id);


--
-- Name: case_metadata_observations_same_case_evidence_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_metadata_observations_same_case_evidence_idx ON corpus.case_metadata_observations USING btree (case_id, evidence_case_page_id) WHERE (evidence_case_page_id IS NOT NULL);


--
-- Name: case_metadata_resolution_observations_case_observation_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_metadata_resolution_observations_case_observation_idx ON corpus.case_metadata_resolution_observations USING btree (case_id, observation_id);


--
-- Name: case_metadata_resolution_observations_case_resolution_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_metadata_resolution_observations_case_resolution_idx ON corpus.case_metadata_resolution_observations USING btree (case_id, resolution_id);


--
-- Name: case_metadata_resolution_one_selected_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX case_metadata_resolution_one_selected_idx ON corpus.case_metadata_resolution_observations USING btree (resolution_id) WHERE (role = 'selected'::text);


--
-- Name: case_metadata_resolutions_case_field_created_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_metadata_resolutions_case_field_created_idx ON corpus.case_metadata_resolutions USING btree (case_id, field_name, created_at DESC);


--
-- Name: case_metadata_resolutions_status_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_metadata_resolutions_status_idx ON corpus.case_metadata_resolutions USING btree (resolution_status);


--
-- Name: case_pages_artifact_page_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_pages_artifact_page_idx ON corpus.case_pages USING btree (artifact_page_id);


--
-- Name: case_pages_artifact_page_provenance_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_pages_artifact_page_provenance_idx ON corpus.case_pages USING btree (artifact_id, artifact_page_id);


--
-- Name: case_pages_scope_artifact_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_pages_scope_artifact_idx ON corpus.case_pages USING btree (scope_id, artifact_id);


--
-- Name: case_pages_scope_case_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX case_pages_scope_case_idx ON corpus.case_pages USING btree (scope_id, case_id);


--
-- Name: cases_court_date_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX cases_court_date_idx ON corpus.judicial_decisions USING btree (court_id, decision_date DESC) WHERE (decision_date IS NOT NULL);


--
-- Name: cases_decision_date_evidence_case_page_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX cases_decision_date_evidence_case_page_idx ON corpus.judicial_decisions USING btree (decision_date_evidence_case_page_id) WHERE (decision_date_evidence_case_page_id IS NOT NULL);


--
-- Name: cases_decision_date_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX cases_decision_date_idx ON corpus.judicial_decisions USING btree (decision_date DESC) WHERE (decision_date IS NOT NULL);


--
-- Name: cases_normalized_decision_number_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX cases_normalized_decision_number_idx ON corpus.judicial_decisions USING btree (normalized_decision_number) WHERE (normalized_decision_number IS NOT NULL);


--
-- Name: cases_organ_date_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX cases_organ_date_idx ON corpus.judicial_decisions USING btree (court_organ_id, decision_date DESC) WHERE ((court_organ_id IS NOT NULL) AND (decision_date IS NOT NULL));


--
-- Name: cases_same_case_date_evidence_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX cases_same_case_date_evidence_idx ON corpus.judicial_decisions USING btree (id, decision_date_evidence_case_page_id) WHERE (decision_date_evidence_case_page_id IS NOT NULL);


--
-- Name: cases_scope_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX cases_scope_idx ON corpus.judicial_decisions USING btree (scope_id);


--
-- Name: claim_relations_source_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX claim_relations_source_idx ON corpus.claim_relations USING btree (scope_id, source_claim_id, relation_concept_id, known_from DESC);


--
-- Name: claim_relations_target_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX claim_relations_target_idx ON corpus.claim_relations USING btree (scope_id, target_claim_id, relation_concept_id, known_from DESC);


--
-- Name: controversy_proceedings_relation_concept_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX controversy_proceedings_relation_concept_idx ON corpus.controversy_proceedings USING btree (relation_concept_id);


--
-- Name: corpus_scopes_private_org_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX corpus_scopes_private_org_idx ON corpus.scopes USING btree (organization_id) WHERE (visibility = 'private'::text);


--
-- Name: corpus_scopes_public_singleton_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX corpus_scopes_public_singleton_idx ON corpus.scopes USING btree (visibility) WHERE (visibility = 'public'::text);


--
-- Name: court_aliases_normalized_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX court_aliases_normalized_idx ON corpus.court_aliases USING btree (normalized_alias);


--
-- Name: court_jurisdictions_lookup_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX court_jurisdictions_lookup_idx ON corpus.court_jurisdictions USING btree (jurisdiction_code, court_id);


--
-- Name: court_organ_aliases_normalized_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX court_organ_aliases_normalized_idx ON corpus.court_organ_aliases USING btree (normalized_alias);


--
-- Name: court_organs_court_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX court_organs_court_idx ON corpus.court_organs USING btree (court_id);


--
-- Name: court_relations_from_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX court_relations_from_idx ON corpus.court_relations USING btree (from_court_id, relation_type);


--
-- Name: court_relations_to_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX court_relations_to_idx ON corpus.court_relations USING btree (to_court_id, relation_type);


--
-- Name: courts_legal_entity_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX courts_legal_entity_idx ON corpus.courts USING btree (legal_entity_id) WHERE (legal_entity_id IS NOT NULL);


--
-- Name: courts_system_type_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX courts_system_type_idx ON corpus.courts USING btree (judicial_system, court_type, active_from, active_to);


--
-- Name: decision_legal_states_current_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX decision_legal_states_current_idx ON corpus.decision_legal_states USING btree (decision_id, state_concept_id) WHERE (known_to IS NULL);


--
-- Name: decision_panel_members_case_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX decision_panel_members_case_idx ON corpus.decision_panel_members USING btree (scope_id, case_id, ordinal);


--
-- Name: disposition_arguments_action_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX disposition_arguments_action_idx ON corpus.judicial_disposition_action_arguments USING btree (scope_id, action_id, ordinal);


--
-- Name: disposition_arguments_claim_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX disposition_arguments_claim_key ON corpus.judicial_disposition_action_arguments USING btree (action_id, role_concept_id, target_claim_id) WHERE (object_type = 'claim'::text);


--
-- Name: disposition_arguments_court_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX disposition_arguments_court_key ON corpus.judicial_disposition_action_arguments USING btree (action_id, role_concept_id, target_court_id) WHERE (object_type = 'court'::text);


--
-- Name: disposition_arguments_court_organ_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX disposition_arguments_court_organ_key ON corpus.judicial_disposition_action_arguments USING btree (action_id, role_concept_id, target_court_organ_id) WHERE (object_type = 'court_organ'::text);


--
-- Name: disposition_arguments_decision_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX disposition_arguments_decision_key ON corpus.judicial_disposition_action_arguments USING btree (action_id, role_concept_id, target_decision_id) WHERE (object_type = 'decision'::text);


--
-- Name: disposition_arguments_party_role_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX disposition_arguments_party_role_key ON corpus.judicial_disposition_action_arguments USING btree (action_id, role_concept_id, target_party_role_id) WHERE (object_type = 'party_role'::text);


--
-- Name: disposition_arguments_proceeding_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX disposition_arguments_proceeding_key ON corpus.judicial_disposition_action_arguments USING btree (action_id, role_concept_id, target_proceeding_id) WHERE (object_type = 'proceeding'::text);


--
-- Name: disposition_arguments_proposition_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX disposition_arguments_proposition_key ON corpus.judicial_disposition_action_arguments USING btree (action_id, role_concept_id, target_proposition_id) WHERE (object_type = 'proposition'::text);


--
-- Name: disposition_arguments_provision_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX disposition_arguments_provision_key ON corpus.judicial_disposition_action_arguments USING btree (action_id, role_concept_id, target_provision_id) WHERE (object_type = 'provision'::text);


--
-- Name: entity_identity_assertions_candidate_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX entity_identity_assertions_candidate_idx ON corpus.entity_identity_assertions USING btree (scope_id, candidate_entity_id, known_from DESC);


--
-- Name: entity_identity_assertions_observed_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX entity_identity_assertions_observed_idx ON corpus.entity_identity_assertions USING btree (scope_id, observed_entity_id, known_from DESC);


--
-- Name: entity_identity_evidence_assertion_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX entity_identity_evidence_assertion_idx ON corpus.entity_identity_assertion_evidence USING btree (scope_id, assertion_id);


--
-- Name: entity_identity_resolutions_current_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX entity_identity_resolutions_current_idx ON corpus.entity_identity_resolutions USING btree (observed_entity_id) WHERE ((known_to IS NULL) AND (verification_status <> ALL (ARRAY['rejected'::text, 'superseded'::text])));


--
-- Name: factual_proposition_evidence_fact_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX factual_proposition_evidence_fact_idx ON corpus.factual_proposition_evidence USING btree (scope_id, factual_proposition_id);


--
-- Name: factual_propositions_scope_kind_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX factual_propositions_scope_kind_idx ON corpus.factual_propositions USING btree (scope_id, kind_concept_id, verification_status);


--
-- Name: factual_subjects_claim_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX factual_subjects_claim_key ON corpus.factual_proposition_subjects USING btree (factual_proposition_id, relation_concept_id, claim_id) WHERE (subject_type = 'claim'::text);


--
-- Name: factual_subjects_judicial_decision_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX factual_subjects_judicial_decision_key ON corpus.factual_proposition_subjects USING btree (factual_proposition_id, relation_concept_id, judicial_decision_id) WHERE (subject_type = 'judicial_decision'::text);


--
-- Name: factual_subjects_party_role_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX factual_subjects_party_role_key ON corpus.factual_proposition_subjects USING btree (factual_proposition_id, relation_concept_id, party_role_id) WHERE (subject_type = 'party_role'::text);


--
-- Name: factual_subjects_proceeding_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX factual_subjects_proceeding_key ON corpus.factual_proposition_subjects USING btree (factual_proposition_id, relation_concept_id, proceeding_id) WHERE (subject_type = 'proceeding'::text);


--
-- Name: ingestion_jobs_artifact_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX ingestion_jobs_artifact_idx ON corpus.ingestion_jobs USING btree (artifact_id, created_at DESC);


--
-- Name: ingestion_jobs_parser_version_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX ingestion_jobs_parser_version_idx ON corpus.ingestion_jobs USING btree (parser_version_id);


--
-- Name: judicial_decisions_act_type_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX judicial_decisions_act_type_idx ON corpus.judicial_decisions USING btree (act_type_concept_id, decision_date DESC);


--
-- Name: judicial_officers_legal_entity_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX judicial_officers_legal_entity_idx ON corpus.judicial_officers USING btree (legal_entity_id) WHERE (legal_entity_id IS NOT NULL);


--
-- Name: judicial_officers_name_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX judicial_officers_name_idx ON corpus.judicial_officers USING btree (scope_id, normalized_name) WHERE (normalized_name IS NOT NULL);


--
-- Name: legal_amendment_effects_source_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_amendment_effects_source_idx ON corpus.legal_amendment_effects USING btree (source_instrument_id, effective_on);


--
-- Name: legal_amendment_effects_target_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_amendment_effects_target_idx ON corpus.legal_amendment_effects USING btree (target_instrument_id, target_provision_id, effective_on);


--
-- Name: legal_authorities_legal_entity_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_authorities_legal_entity_idx ON corpus.legal_authorities USING btree (legal_entity_id) WHERE (legal_entity_id IS NOT NULL);


--
-- Name: legal_concept_aliases_lookup_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_concept_aliases_lookup_idx ON corpus.legal_concept_aliases USING btree (normalized_alias) WHERE (normalized_alias IS NOT NULL);


--
-- Name: legal_concept_edges_source_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_concept_edges_source_idx ON corpus.legal_concept_edges USING btree (source_concept_id, relation_type);


--
-- Name: legal_concept_edges_target_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_concept_edges_target_idx ON corpus.legal_concept_edges USING btree (target_concept_id, relation_type);


--
-- Name: legal_concepts_scheme_lookup_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_concepts_scheme_lookup_idx ON corpus.legal_concepts USING btree (scheme_code, jurisdiction_code, code);


--
-- Name: legal_controversies_scope_status_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_controversies_scope_status_idx ON corpus.legal_controversies USING btree (scope_id, status, opened_on DESC);


--
-- Name: legal_document_identifiers_lookup_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_document_identifiers_lookup_idx ON corpus.legal_document_identifiers USING btree (identifier_type, normalized_value) WHERE (normalized_value IS NOT NULL);


--
-- Name: legal_document_occurrence_artifact_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_document_occurrence_artifact_idx ON corpus.legal_document_artifact_occurrences USING btree (artifact_id);


--
-- Name: legal_document_provisions_document_ordinal_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_document_provisions_document_ordinal_idx ON corpus.legal_document_provisions USING btree (document_id, ordinal);


--
-- Name: legal_document_provisions_parent_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_document_provisions_parent_idx ON corpus.legal_document_provisions USING btree (parent_provision_id) WHERE (parent_provision_id IS NOT NULL);


--
-- Name: legal_document_provisions_sibling_label_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_document_provisions_sibling_label_key ON corpus.legal_document_provisions USING btree (document_id, COALESCE(parent_provision_id, '00000000-0000-0000-0000-000000000000'::uuid), normalized_label) WHERE (normalized_label IS NOT NULL);


--
-- Name: legal_document_tags_tag_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_document_tags_tag_idx ON corpus.legal_document_tags USING btree (tag_id);


--
-- Name: legal_documents_number_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_documents_number_idx ON corpus.legal_documents USING btree (document_number) WHERE (document_number IS NOT NULL);


--
-- Name: legal_documents_type_date_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_documents_type_date_idx ON corpus.legal_documents USING btree (document_type, document_date DESC);


--
-- Name: legal_instrument_events_timeline_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_instrument_events_timeline_idx ON corpus.legal_instrument_events USING btree (instrument_id, occurred_on, event_type);


--
-- Name: legal_instrument_identifiers_lookup_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_instrument_identifiers_lookup_idx ON corpus.legal_instrument_identifiers USING btree (identifier_type, normalized_value) WHERE (normalized_value IS NOT NULL);


--
-- Name: legal_instrument_version_documents_document_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_instrument_version_documents_document_idx ON corpus.legal_instrument_version_documents USING btree (scope_id, document_id);


--
-- Name: legal_instrument_version_knowledge_current_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_instrument_version_knowledge_current_idx ON corpus.legal_instrument_version_knowledge USING btree (instrument_version_id) WHERE (known_to IS NULL);


--
-- Name: legal_instrument_versions_timeline_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_instrument_versions_timeline_idx ON corpus.legal_instrument_versions USING btree (instrument_id, valid_from, valid_to);


--
-- Name: legal_instruments_lookup_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_instruments_lookup_idx ON corpus.legal_instruments USING btree (country_code, jurisdiction_code, instrument_type);


--
-- Name: legal_issue_evidence_issue_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_issue_evidence_issue_idx ON corpus.legal_issue_evidence USING btree (scope_id, issue_id);


--
-- Name: legal_issue_subjects_claim_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_issue_subjects_claim_key ON corpus.legal_issue_subjects USING btree (issue_id, relation_concept_id, claim_id) WHERE (subject_type = 'claim'::text);


--
-- Name: legal_issue_subjects_issue_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_issue_subjects_issue_idx ON corpus.legal_issue_subjects USING btree (scope_id, issue_id, ordinal);


--
-- Name: legal_issue_subjects_judicial_decision_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_issue_subjects_judicial_decision_key ON corpus.legal_issue_subjects USING btree (issue_id, relation_concept_id, judicial_decision_id) WHERE (subject_type = 'judicial_decision'::text);


--
-- Name: legal_issue_subjects_proceeding_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_issue_subjects_proceeding_key ON corpus.legal_issue_subjects USING btree (issue_id, relation_concept_id, proceeding_id) WHERE (subject_type = 'proceeding'::text);


--
-- Name: legal_issue_subjects_proposition_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_issue_subjects_proposition_key ON corpus.legal_issue_subjects USING btree (issue_id, relation_concept_id, proposition_id) WHERE (subject_type = 'proposition'::text);


--
-- Name: legal_issues_scope_status_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_issues_scope_status_idx ON corpus.legal_issues USING btree (scope_id, verification_status, created_at DESC);


--
-- Name: legal_norm_assertions_claim_history_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_norm_assertions_claim_history_key ON corpus.legal_norm_assertions USING btree (norm_claim_id, known_from);


--
-- Name: legal_norm_assertions_current_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_norm_assertions_current_idx ON corpus.legal_norm_assertions USING btree (norm_claim_id) WHERE (known_to IS NULL);


--
-- Name: legal_norm_sources_assertion_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_norm_sources_assertion_idx ON corpus.legal_norm_sources USING btree (norm_assertion_id, source_role, verification_status);


--
-- Name: legal_proceedings_originating_court_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_proceedings_originating_court_idx ON corpus.legal_proceedings USING btree (originating_court_id, filing_date DESC) WHERE (originating_court_id IS NOT NULL);


--
-- Name: legal_proceedings_scope_status_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_proceedings_scope_status_idx ON corpus.legal_proceedings USING btree (scope_id, status, filing_date DESC);


--
-- Name: legal_proposition_evidence_case_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_proposition_evidence_case_idx ON corpus.legal_proposition_evidence USING btree (scope_id, source_case_id) WHERE (source_case_id IS NOT NULL);


--
-- Name: legal_proposition_evidence_proposition_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_proposition_evidence_proposition_idx ON corpus.legal_proposition_evidence USING btree (scope_id, proposition_id);


--
-- Name: legal_proposition_relations_from_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_proposition_relations_from_idx ON corpus.legal_proposition_relations USING btree (scope_id, from_proposition_id, relation_type);


--
-- Name: legal_proposition_relations_to_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_proposition_relations_to_idx ON corpus.legal_proposition_relations USING btree (scope_id, to_proposition_id, relation_type);


--
-- Name: legal_proposition_subjects_decision_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_proposition_subjects_decision_key ON corpus.legal_proposition_subjects USING btree (proposition_id, subject_role, judicial_decision_id) WHERE (judicial_decision_id IS NOT NULL);


--
-- Name: legal_proposition_subjects_document_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_proposition_subjects_document_key ON corpus.legal_proposition_subjects USING btree (proposition_id, subject_role, legal_document_id) WHERE (legal_document_id IS NOT NULL);


--
-- Name: legal_proposition_subjects_general_law_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_proposition_subjects_general_law_key ON corpus.legal_proposition_subjects USING btree (proposition_id, subject_role) WHERE (subject_type = 'general_law'::text);


--
-- Name: legal_proposition_subjects_proceeding_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_proposition_subjects_proceeding_key ON corpus.legal_proposition_subjects USING btree (proposition_id, subject_role, proceeding_id) WHERE (proceeding_id IS NOT NULL);


--
-- Name: legal_proposition_subjects_provision_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_proposition_subjects_provision_key ON corpus.legal_proposition_subjects USING btree (proposition_id, subject_role, provision_id) WHERE (provision_id IS NOT NULL);


--
-- Name: legal_propositions_type_status_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_propositions_type_status_idx ON corpus.legal_propositions USING btree (scope_id, proposition_type, verification_status);


--
-- Name: legal_provision_version_knowledge_current_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_provision_version_knowledge_current_idx ON corpus.legal_provision_version_knowledge USING btree (provision_version_id) WHERE (known_to IS NULL);


--
-- Name: legal_provision_versions_provision_history_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_provision_versions_provision_history_idx ON corpus.legal_provision_versions USING btree (provision_id, instrument_version_id);


--
-- Name: legal_provision_versions_sibling_label_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_provision_versions_sibling_label_key ON corpus.legal_provision_versions USING btree (instrument_version_id, COALESCE(parent_provision_id, '00000000-0000-0000-0000-000000000000'::uuid), normalized_label) WHERE (normalized_label IS NOT NULL);


--
-- Name: legal_provisions_instrument_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_provisions_instrument_idx ON corpus.legal_provisions USING btree (instrument_id);


--
-- Name: legal_relation_assertions_current_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_relation_assertions_current_idx ON corpus.legal_relation_assertions USING btree (relation_identity_id) WHERE (known_to IS NULL);


--
-- Name: legal_relation_identities_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_relation_identities_key ON corpus.legal_relation_identities USING btree (source_document_id, COALESCE(source_provision_id, '00000000-0000-0000-0000-000000000000'::uuid), relation_type, target_document_id, COALESCE(target_provision_id, '00000000-0000-0000-0000-000000000000'::uuid));


--
-- Name: legal_relation_observations_evidence_page_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_relation_observations_evidence_page_idx ON corpus.legal_relation_observations USING btree (evidence_artifact_page_id) WHERE (evidence_artifact_page_id IS NOT NULL);


--
-- Name: legal_relation_observations_source_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_relation_observations_source_idx ON corpus.legal_relation_observations USING btree (source_document_id, relation_type, status);


--
-- Name: legal_relation_observations_target_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX legal_relation_observations_target_idx ON corpus.legal_relation_observations USING btree (target_document_id, relation_type, status) WHERE (target_document_id IS NOT NULL);


--
-- Name: legal_treatment_assertions_current_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX legal_treatment_assertions_current_idx ON corpus.legal_treatment_assertions USING btree (source_case_id, target_case_id, treatment_type, COALESCE(legal_issue_id, '00000000-0000-0000-0000-000000000000'::uuid), COALESCE(source_proposition_id, '00000000-0000-0000-0000-000000000000'::uuid), COALESCE(target_proposition_id, '00000000-0000-0000-0000-000000000000'::uuid)) WHERE (known_to IS NULL);


--
-- Name: participants_legal_entity_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX participants_legal_entity_idx ON corpus.participants USING btree (legal_entity_id) WHERE (legal_entity_id IS NOT NULL);


--
-- Name: participants_scope_normalized_name_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX participants_scope_normalized_name_idx ON corpus.participants USING btree (scope_id, normalized_name) WHERE (normalized_name IS NOT NULL);


--
-- Name: passages_case_page_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX passages_case_page_idx ON corpus.passages USING btree (case_id, page_start, page_end);


--
-- Name: passages_fts_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX passages_fts_idx ON corpus.passages USING gin (fts);


--
-- Name: procedural_decision_relations_source_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX procedural_decision_relations_source_idx ON corpus.procedural_decision_relations USING btree (scope_id, source_case_id, relation_type);


--
-- Name: procedural_decision_relations_target_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX procedural_decision_relations_target_idx ON corpus.procedural_decision_relations USING btree (scope_id, target_case_id, relation_type);


--
-- Name: procedural_events_timeline_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX procedural_events_timeline_idx ON corpus.procedural_events USING btree (scope_id, proceeding_id, occurred_on, sequence_number, created_at);


--
-- Name: procedural_relation_observations_source_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX procedural_relation_observations_source_idx ON corpus.procedural_decision_relation_observations USING btree (scope_id, source_case_id, relation_type, status);


--
-- Name: proceeding_decisions_proceeding_stage_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX proceeding_decisions_proceeding_stage_idx ON corpus.proceeding_decisions USING btree (scope_id, proceeding_id, procedural_stage, ordinal);


--
-- Name: proceeding_identifiers_identity_key; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX proceeding_identifiers_identity_key ON corpus.proceeding_identifiers USING btree (proceeding_id, identifier_type, raw_value, COALESCE(source_registry_id, '00000000-0000-0000-0000-000000000000'::uuid));


--
-- Name: proceeding_identifiers_lookup_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX proceeding_identifiers_lookup_idx ON corpus.proceeding_identifiers USING btree (identifier_type, normalized_value) WHERE (normalized_value IS NOT NULL);


--
-- Name: proceeding_participants_participant_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX proceeding_participants_participant_idx ON corpus.proceeding_participants USING btree (scope_id, participant_id);


--
-- Name: proceeding_participants_proceeding_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX proceeding_participants_proceeding_idx ON corpus.proceeding_participants USING btree (scope_id, proceeding_id, ordinal);


--
-- Name: proceeding_relations_current_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE UNIQUE INDEX proceeding_relations_current_idx ON corpus.proceeding_relations USING btree (source_proceeding_id, target_proceeding_id, relation_concept_id) WHERE ((known_to IS NULL) AND (verification_status <> ALL (ARRAY['rejected'::text, 'superseded'::text])));


--
-- Name: proceeding_relations_source_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX proceeding_relations_source_idx ON corpus.proceeding_relations USING btree (scope_id, source_proceeding_id, relation_concept_id, known_from DESC);


--
-- Name: proceeding_relations_target_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX proceeding_relations_target_idx ON corpus.proceeding_relations USING btree (scope_id, target_proceeding_id, relation_concept_id, known_from DESC);


--
-- Name: source_artifact_locations_artifact_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX source_artifact_locations_artifact_idx ON corpus.source_artifact_locations USING btree (artifact_id);


--
-- Name: source_artifact_locations_collection_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX source_artifact_locations_collection_idx ON corpus.source_artifact_locations USING btree (source_registry_id, source_collection) WHERE (source_collection IS NOT NULL);


--
-- Name: source_artifact_locations_locator_history_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX source_artifact_locations_locator_history_idx ON corpus.source_artifact_locations USING btree (locator_type, locator, last_seen_at DESC);


--
-- Name: source_artifact_locations_registry_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX source_artifact_locations_registry_idx ON corpus.source_artifact_locations USING btree (source_registry_id) WHERE (source_registry_id IS NOT NULL);


--
-- Name: source_artifact_locations_source_identifier_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX source_artifact_locations_source_identifier_idx ON corpus.source_artifact_locations USING btree (source_registry_id, source_identifier) WHERE (source_identifier IS NOT NULL);


--
-- Name: source_artifacts_scope_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX source_artifacts_scope_idx ON corpus.source_artifacts USING btree (scope_id);


--
-- Name: source_artifacts_source_registry_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX source_artifacts_source_registry_idx ON corpus.source_artifacts USING btree (source_registry_id);


--
-- Name: source_collections_source_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX source_collections_source_idx ON corpus.source_collections USING btree (source_registry_id, active);


--
-- Name: source_document_artifacts_artifact_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX source_document_artifacts_artifact_idx ON corpus.source_document_artifacts USING btree (artifact_id);


--
-- Name: source_document_observations_document_time_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX source_document_observations_document_time_idx ON corpus.source_document_observations USING btree (source_document_id, observed_at DESC);


--
-- Name: source_documents_current_url_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX source_documents_current_url_idx ON corpus.source_documents USING btree (current_document_url) WHERE (current_document_url IS NOT NULL);


--
-- Name: source_documents_registry_collection_idx; Type: INDEX; Schema: corpus; Owner: -
--

CREATE INDEX source_documents_registry_collection_idx ON corpus.source_documents USING btree (source_registry_id, source_collection, artifact_availability);


--
-- Name: courts courts_ensure_legal_entity; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER courts_ensure_legal_entity BEFORE INSERT ON corpus.courts FOR EACH ROW EXECUTE FUNCTION corpus.ensure_court_legal_entity();


--
-- Name: decision_legal_states decision_legal_states_no_knowledge_overlap; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER decision_legal_states_no_knowledge_overlap BEFORE INSERT OR UPDATE ON corpus.decision_legal_states FOR EACH ROW EXECUTE FUNCTION corpus.reject_decision_state_knowledge_overlap();


--
-- Name: decision_legal_states decision_legal_states_validate_concept; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER decision_legal_states_validate_concept BEFORE INSERT OR UPDATE OF state_concept_id ON corpus.decision_legal_states FOR EACH ROW EXECUTE FUNCTION corpus.validate_decision_state_concept();


--
-- Name: decision_legal_status_events decision_legal_status_no_knowledge_overlap; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER decision_legal_status_no_knowledge_overlap BEFORE INSERT OR UPDATE ON corpus.decision_legal_status_events FOR EACH ROW EXECUTE FUNCTION corpus.reject_decision_status_knowledge_overlap();


--
-- Name: judicial_disposition_action_arguments disposition_arguments_validate_context; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER disposition_arguments_validate_context BEFORE INSERT OR UPDATE ON corpus.judicial_disposition_action_arguments FOR EACH ROW EXECUTE FUNCTION corpus.validate_disposition_action_argument_context();


--
-- Name: entity_identity_resolutions entity_identity_resolutions_no_knowledge_overlap; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER entity_identity_resolutions_no_knowledge_overlap BEFORE INSERT OR UPDATE ON corpus.entity_identity_resolutions FOR EACH ROW EXECUTE FUNCTION corpus.reject_entity_resolution_knowledge_overlap();


--
-- Name: entity_identity_resolutions entity_identity_resolutions_validate_assertion; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER entity_identity_resolutions_validate_assertion BEFORE INSERT OR UPDATE OF scope_id, observed_entity_id, canonical_entity_id, supporting_assertion_id ON corpus.entity_identity_resolutions FOR EACH ROW EXECUTE FUNCTION corpus.validate_entity_identity_resolution();


--
-- Name: entity_identity_assertions entity_identity_verified_require_evidence; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE CONSTRAINT TRIGGER entity_identity_verified_require_evidence AFTER INSERT OR UPDATE OF verification_status ON corpus.entity_identity_assertions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION corpus.require_verified_entity_identity_evidence();


--
-- Name: factual_propositions factual_propositions_immutable_identity; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER factual_propositions_immutable_identity BEFORE UPDATE ON corpus.factual_propositions FOR EACH ROW EXECUTE FUNCTION corpus.reject_factual_proposition_identity_mutation();


--
-- Name: factual_propositions factual_propositions_verified_require_evidence; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE CONSTRAINT TRIGGER factual_propositions_verified_require_evidence AFTER INSERT OR UPDATE OF verification_status, verification_method ON corpus.factual_propositions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION corpus.require_verified_fact_evidence();


--
-- Name: judicial_authority_assertions judicial_authority_assertions_no_knowledge_overlap; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER judicial_authority_assertions_no_knowledge_overlap BEFORE INSERT OR UPDATE ON corpus.judicial_authority_assertions FOR EACH ROW EXECUTE FUNCTION corpus.reject_judicial_authority_knowledge_overlap();


--
-- Name: judicial_officers judicial_officers_ensure_legal_entity; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER judicial_officers_ensure_legal_entity BEFORE INSERT ON corpus.judicial_officers FOR EACH ROW EXECUTE FUNCTION corpus.ensure_officer_legal_entity();


--
-- Name: judicial_vote_stances judicial_vote_stances_validate_target; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER judicial_vote_stances_validate_target BEFORE INSERT OR UPDATE OF scope_type, proposition_id, case_id, scope_id ON corpus.judicial_vote_stances FOR EACH ROW EXECUTE FUNCTION corpus.validate_vote_stance_target();


--
-- Name: legal_authorities legal_authorities_ensure_legal_entity; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_authorities_ensure_legal_entity BEFORE INSERT ON corpus.legal_authorities FOR EACH ROW EXECUTE FUNCTION corpus.ensure_authority_legal_entity();


--
-- Name: legal_concept_edges legal_concept_edges_reject_hierarchy_cycle; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_concept_edges_reject_hierarchy_cycle BEFORE INSERT OR UPDATE ON corpus.legal_concept_edges FOR EACH ROW EXECUTE FUNCTION corpus.reject_legal_concept_hierarchy_cycle();


--
-- Name: legal_instrument_version_knowledge legal_instrument_version_knowledge_no_overlap; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_instrument_version_knowledge_no_overlap BEFORE INSERT OR UPDATE ON corpus.legal_instrument_version_knowledge FOR EACH ROW EXECUTE FUNCTION corpus.reject_instrument_knowledge_overlap();


--
-- Name: legal_issues legal_issues_immutable_identity; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_issues_immutable_identity BEFORE UPDATE ON corpus.legal_issues FOR EACH ROW EXECUTE FUNCTION corpus.reject_legal_issue_identity_mutation();


--
-- Name: legal_issues legal_issues_verified_require_evidence; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE CONSTRAINT TRIGGER legal_issues_verified_require_evidence AFTER INSERT OR UPDATE OF verification_status, verification_method ON corpus.legal_issues DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION corpus.require_verified_issue_evidence();


--
-- Name: legal_matter_concept_edges legal_matter_concept_edges_no_cycle; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_matter_concept_edges_no_cycle BEFORE INSERT OR UPDATE ON corpus.legal_matter_concept_edges FOR EACH ROW EXECUTE FUNCTION corpus.reject_matter_concept_cycle();


--
-- Name: legal_norm_assertions legal_norm_assertions_canonical_claim; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_norm_assertions_canonical_claim BEFORE INSERT OR UPDATE OF norm_claim_id, proposition_id, jurisdiction_code, norm_kind, valid_from, valid_to ON corpus.legal_norm_assertions FOR EACH ROW EXECUTE FUNCTION corpus.canonicalize_norm_claim();


--
-- Name: legal_norm_assertions legal_norm_assertions_no_knowledge_overlap; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_norm_assertions_no_knowledge_overlap BEFORE INSERT OR UPDATE ON corpus.legal_norm_assertions FOR EACH ROW EXECUTE FUNCTION corpus.reject_norm_claim_knowledge_overlap();


--
-- Name: legal_norm_assertions legal_norm_assertions_verified_sources; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_norm_assertions_verified_sources AFTER INSERT OR UPDATE OF verification_status ON corpus.legal_norm_assertions FOR EACH ROW EXECUTE FUNCTION corpus.validate_verified_norm_sources();


--
-- Name: legal_norm_sources legal_norm_sources_canonical_scope; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_norm_sources_canonical_scope BEFORE INSERT OR UPDATE OF norm_assertion_id ON corpus.legal_norm_sources FOR EACH ROW EXECUTE FUNCTION corpus.canonicalize_norm_source_scope();


--
-- Name: legal_propositions legal_propositions_immutable_identity; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_propositions_immutable_identity BEFORE UPDATE ON corpus.legal_propositions FOR EACH ROW EXECUTE FUNCTION corpus.reject_legal_proposition_identity_mutation();


--
-- Name: legal_provision_version_knowledge legal_provision_version_knowledge_no_overlap; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_provision_version_knowledge_no_overlap BEFORE INSERT OR UPDATE ON corpus.legal_provision_version_knowledge FOR EACH ROW EXECUTE FUNCTION corpus.reject_provision_knowledge_overlap();


--
-- Name: legal_relation_assertions legal_relation_assertions_canonical_scope; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_relation_assertions_canonical_scope BEFORE INSERT OR UPDATE OF relation_identity_id ON corpus.legal_relation_assertions FOR EACH ROW EXECUTE FUNCTION corpus.canonicalize_relation_assertion_scope();


--
-- Name: legal_relation_assertions legal_relation_assertions_no_knowledge_overlap; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_relation_assertions_no_knowledge_overlap BEFORE INSERT OR UPDATE ON corpus.legal_relation_assertions FOR EACH ROW EXECUTE FUNCTION corpus.reject_relation_knowledge_overlap();


--
-- Name: legal_relation_identities legal_relation_identities_canonical_scope; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_relation_identities_canonical_scope BEFORE INSERT OR UPDATE OF source_document_id ON corpus.legal_relation_identities FOR EACH ROW EXECUTE FUNCTION corpus.canonicalize_relation_identity_scope();


--
-- Name: legal_treatment_assertions legal_treatment_assertions_membership; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_treatment_assertions_membership BEFORE INSERT OR UPDATE ON corpus.legal_treatment_assertions FOR EACH ROW EXECUTE FUNCTION corpus.validate_treatment_proposition_membership();


--
-- Name: legal_treatment_assertions legal_treatment_assertions_no_knowledge_overlap; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER legal_treatment_assertions_no_knowledge_overlap BEFORE INSERT OR UPDATE ON corpus.legal_treatment_assertions FOR EACH ROW EXECUTE FUNCTION corpus.reject_treatment_knowledge_overlap();


--
-- Name: participants participants_ensure_legal_entity; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER participants_ensure_legal_entity BEFORE INSERT ON corpus.participants FOR EACH ROW EXECUTE FUNCTION corpus.ensure_participant_legal_entity();


--
-- Name: procedure_concept_edges procedure_concept_edges_no_cycle; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER procedure_concept_edges_no_cycle BEFORE INSERT OR UPDATE ON corpus.procedure_concept_edges FOR EACH ROW EXECUTE FUNCTION corpus.reject_procedure_concept_cycle();


--
-- Name: proceeding_relations proceeding_relations_validate_symmetry; Type: TRIGGER; Schema: corpus; Owner: -
--

CREATE TRIGGER proceeding_relations_validate_symmetry BEFORE INSERT OR UPDATE OF source_proceeding_id, target_proceeding_id, relation_concept_id ON corpus.proceeding_relations FOR EACH ROW EXECUTE FUNCTION corpus.validate_proceeding_relation_symmetry();


--
-- Name: acquisition_run_items acquisition_run_items_artifact_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.acquisition_run_items
    ADD CONSTRAINT acquisition_run_items_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES corpus.source_artifacts(id);


--
-- Name: acquisition_run_items acquisition_run_items_run_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.acquisition_run_items
    ADD CONSTRAINT acquisition_run_items_run_id_fkey FOREIGN KEY (run_id) REFERENCES corpus.acquisition_runs(id) ON DELETE CASCADE;


--
-- Name: acquisition_run_items acquisition_run_items_source_document_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.acquisition_run_items
    ADD CONSTRAINT acquisition_run_items_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES corpus.source_documents(id);


--
-- Name: acquisition_runs acquisition_runs_source_collection_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.acquisition_runs
    ADD CONSTRAINT acquisition_runs_source_collection_id_fkey FOREIGN KEY (source_collection_id) REFERENCES corpus.source_collections(id);


--
-- Name: adjudicative_act_type_concepts adjudicative_act_type_concepts_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.adjudicative_act_type_concepts
    ADD CONSTRAINT adjudicative_act_type_concepts_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.adjudicative_act_type_concepts(id);


--
-- Name: adjudicative_act_type_concepts adjudicative_act_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.adjudicative_act_type_concepts
    ADD CONSTRAINT adjudicative_act_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: analysis_observations analysis_observations_same_scope_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.analysis_observations
    ADD CONSTRAINT analysis_observations_same_scope_case_fkey FOREIGN KEY (scope_id, case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: analysis_observations analysis_observations_same_scope_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.analysis_observations
    ADD CONSTRAINT analysis_observations_same_scope_document_fkey FOREIGN KEY (scope_id, legal_document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: analysis_observations analysis_observations_same_scope_proceeding_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.analysis_observations
    ADD CONSTRAINT analysis_observations_same_scope_proceeding_fkey FOREIGN KEY (scope_id, proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id);


--
-- Name: analysis_observations analysis_observations_scope_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.analysis_observations
    ADD CONSTRAINT analysis_observations_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id);


--
-- Name: artifact_pages artifact_pages_artifact_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.artifact_pages
    ADD CONSTRAINT artifact_pages_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES corpus.source_artifacts(id) ON DELETE CASCADE;


--
-- Name: case_artifact_occurrences case_artifact_occurrences_artifact_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_artifact_occurrences
    ADD CONSTRAINT case_artifact_occurrences_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES corpus.source_artifacts(id) ON DELETE CASCADE;


--
-- Name: case_artifact_occurrences case_artifact_occurrences_case_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_artifact_occurrences
    ADD CONSTRAINT case_artifact_occurrences_case_id_fkey FOREIGN KEY (case_id) REFERENCES corpus.judicial_decisions(id) ON DELETE CASCADE;


--
-- Name: case_artifact_occurrences case_artifact_occurrences_same_scope_artifact_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_artifact_occurrences
    ADD CONSTRAINT case_artifact_occurrences_same_scope_artifact_fkey FOREIGN KEY (scope_id, artifact_id) REFERENCES corpus.source_artifacts(scope_id, id);


--
-- Name: case_artifact_occurrences case_artifact_occurrences_same_scope_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_artifact_occurrences
    ADD CONSTRAINT case_artifact_occurrences_same_scope_case_fkey FOREIGN KEY (scope_id, case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: judicial_decision_dispositions case_dispositions_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decision_dispositions
    ADD CONSTRAINT case_dispositions_concept_fkey FOREIGN KEY (disposition_concept_id) REFERENCES corpus.disposition_concepts(id);


--
-- Name: judicial_decision_dispositions case_dispositions_same_case_evidence_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decision_dispositions
    ADD CONSTRAINT case_dispositions_same_case_evidence_fkey FOREIGN KEY (case_id, evidence_case_page_id) REFERENCES corpus.case_pages(case_id, id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: judicial_decision_dispositions case_dispositions_same_scope_affected_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decision_dispositions
    ADD CONSTRAINT case_dispositions_same_scope_affected_case_fkey FOREIGN KEY (scope_id, affected_case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: judicial_decision_dispositions case_dispositions_same_scope_affected_proceeding_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decision_dispositions
    ADD CONSTRAINT case_dispositions_same_scope_affected_proceeding_fkey FOREIGN KEY (scope_id, affected_proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id);


--
-- Name: judicial_decision_dispositions case_dispositions_same_scope_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decision_dispositions
    ADD CONSTRAINT case_dispositions_same_scope_case_fkey FOREIGN KEY (scope_id, case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: case_identifier_type_concepts case_identifier_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_identifier_type_concepts
    ADD CONSTRAINT case_identifier_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: case_identifiers case_identifiers_case_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_identifiers
    ADD CONSTRAINT case_identifiers_case_id_fkey FOREIGN KEY (case_id) REFERENCES corpus.judicial_decisions(id) ON DELETE CASCADE;


--
-- Name: case_identifiers case_identifiers_evidence_same_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_identifiers
    ADD CONSTRAINT case_identifiers_evidence_same_case_fkey FOREIGN KEY (case_id, evidence_case_page_id) REFERENCES corpus.case_pages(case_id, id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: case_identifiers case_identifiers_identifier_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_identifiers
    ADD CONSTRAINT case_identifiers_identifier_type_concept_fkey FOREIGN KEY (identifier_type) REFERENCES corpus.case_identifier_type_concepts(code);


--
-- Name: case_metadata_observations case_metadata_observations_case_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_metadata_observations
    ADD CONSTRAINT case_metadata_observations_case_id_fkey FOREIGN KEY (case_id) REFERENCES corpus.judicial_decisions(id) ON DELETE CASCADE;


--
-- Name: case_metadata_observations case_metadata_observations_evidence_same_case_artifact_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_metadata_observations
    ADD CONSTRAINT case_metadata_observations_evidence_same_case_artifact_fkey FOREIGN KEY (case_id, evidence_case_page_id, artifact_id) REFERENCES corpus.case_pages(case_id, id, artifact_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: case_metadata_observations case_metadata_observations_job_artifact_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_metadata_observations
    ADD CONSTRAINT case_metadata_observations_job_artifact_fkey FOREIGN KEY (ingestion_job_id, artifact_id) REFERENCES corpus.ingestion_jobs(id, artifact_id) ON DELETE CASCADE;


--
-- Name: case_metadata_resolution_observations case_metadata_resolution_observations_observation_same_case_fke; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_metadata_resolution_observations
    ADD CONSTRAINT case_metadata_resolution_observations_observation_same_case_fke FOREIGN KEY (case_id, observation_id) REFERENCES corpus.case_metadata_observations(case_id, id) ON DELETE RESTRICT;


--
-- Name: case_metadata_resolution_observations case_metadata_resolution_observations_resolution_same_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_metadata_resolution_observations
    ADD CONSTRAINT case_metadata_resolution_observations_resolution_same_case_fkey FOREIGN KEY (case_id, resolution_id) REFERENCES corpus.case_metadata_resolutions(case_id, id) ON DELETE CASCADE;


--
-- Name: case_metadata_resolutions case_metadata_resolutions_case_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_metadata_resolutions
    ADD CONSTRAINT case_metadata_resolutions_case_id_fkey FOREIGN KEY (case_id) REFERENCES corpus.judicial_decisions(id) ON DELETE CASCADE;


--
-- Name: case_pages case_pages_artifact_page_same_artifact_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_pages
    ADD CONSTRAINT case_pages_artifact_page_same_artifact_fkey FOREIGN KEY (artifact_id, artifact_page_id) REFERENCES corpus.artifact_pages(artifact_id, id);


--
-- Name: case_pages case_pages_case_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_pages
    ADD CONSTRAINT case_pages_case_id_fkey FOREIGN KEY (case_id) REFERENCES corpus.judicial_decisions(id) ON DELETE CASCADE;


--
-- Name: case_pages case_pages_same_scope_artifact_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_pages
    ADD CONSTRAINT case_pages_same_scope_artifact_fkey FOREIGN KEY (scope_id, artifact_id) REFERENCES corpus.source_artifacts(scope_id, id);


--
-- Name: case_pages case_pages_same_scope_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.case_pages
    ADD CONSTRAINT case_pages_same_scope_case_fkey FOREIGN KEY (scope_id, case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: judicial_decisions cases_court_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decisions
    ADD CONSTRAINT cases_court_id_fkey FOREIGN KEY (court_id) REFERENCES corpus.courts(id);


--
-- Name: judicial_decisions cases_court_organ_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decisions
    ADD CONSTRAINT cases_court_organ_id_fkey FOREIGN KEY (court_organ_id) REFERENCES corpus.court_organs(id);


--
-- Name: judicial_decisions cases_decision_date_evidence_same_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decisions
    ADD CONSTRAINT cases_decision_date_evidence_same_case_fkey FOREIGN KEY (id, decision_date_evidence_case_page_id) REFERENCES corpus.case_pages(case_id, id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: judicial_decisions cases_legal_document_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decisions
    ADD CONSTRAINT cases_legal_document_id_fkey FOREIGN KEY (legal_document_id) REFERENCES corpus.legal_documents(id);


--
-- Name: judicial_decisions cases_scope_fk; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decisions
    ADD CONSTRAINT cases_scope_fk FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id);


--
-- Name: disposition_effect_concepts claim_effect_concepts_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.disposition_effect_concepts
    ADD CONSTRAINT claim_effect_concepts_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.disposition_effect_concepts(id);


--
-- Name: claim_relation_concepts claim_relation_concepts_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.claim_relation_concepts
    ADD CONSTRAINT claim_relation_concepts_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.claim_relation_concepts(id);


--
-- Name: claim_relation_concepts claim_relation_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.claim_relation_concepts
    ADD CONSTRAINT claim_relation_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: claim_relations claim_relations_relation_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.claim_relations
    ADD CONSTRAINT claim_relations_relation_concept_id_fkey FOREIGN KEY (relation_concept_id) REFERENCES corpus.claim_relation_concepts(id);


--
-- Name: claim_relations claim_relations_scope_id_source_claim_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.claim_relations
    ADD CONSTRAINT claim_relations_scope_id_source_claim_id_fkey FOREIGN KEY (scope_id, source_claim_id) REFERENCES corpus.legal_claims(scope_id, id) ON DELETE CASCADE;


--
-- Name: claim_relations claim_relations_scope_id_target_claim_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.claim_relations
    ADD CONSTRAINT claim_relations_scope_id_target_claim_id_fkey FOREIGN KEY (scope_id, target_claim_id) REFERENCES corpus.legal_claims(scope_id, id) ON DELETE CASCADE;


--
-- Name: controversy_membership_role_concepts controversy_membership_role_concepts_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.controversy_membership_role_concepts
    ADD CONSTRAINT controversy_membership_role_concepts_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.controversy_membership_role_concepts(id);


--
-- Name: controversy_membership_role_concepts controversy_membership_role_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.controversy_membership_role_concepts
    ADD CONSTRAINT controversy_membership_role_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: controversy_proceedings controversy_proceedings_relation_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.controversy_proceedings
    ADD CONSTRAINT controversy_proceedings_relation_concept_fkey FOREIGN KEY (relation_concept_id) REFERENCES corpus.controversy_membership_role_concepts(id);


--
-- Name: controversy_proceedings controversy_proceedings_scope_id_controversy_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.controversy_proceedings
    ADD CONSTRAINT controversy_proceedings_scope_id_controversy_id_fkey FOREIGN KEY (scope_id, controversy_id) REFERENCES corpus.legal_controversies(scope_id, id) ON DELETE CASCADE;


--
-- Name: controversy_proceedings controversy_proceedings_scope_id_proceeding_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.controversy_proceedings
    ADD CONSTRAINT controversy_proceedings_scope_id_proceeding_id_fkey FOREIGN KEY (scope_id, proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id) ON DELETE CASCADE;


--
-- Name: court_alias_kind_concepts court_alias_kind_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_alias_kind_concepts
    ADD CONSTRAINT court_alias_kind_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: court_aliases court_aliases_alias_kind_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_aliases
    ADD CONSTRAINT court_aliases_alias_kind_concept_fkey FOREIGN KEY (alias_kind) REFERENCES corpus.court_alias_kind_concepts(code);


--
-- Name: court_aliases court_aliases_court_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_aliases
    ADD CONSTRAINT court_aliases_court_id_fkey FOREIGN KEY (court_id) REFERENCES corpus.courts(id) ON DELETE CASCADE;


--
-- Name: court_aliases court_aliases_source_registry_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_aliases
    ADD CONSTRAINT court_aliases_source_registry_id_fkey FOREIGN KEY (source_registry_id) REFERENCES corpus.source_registries(id) ON DELETE CASCADE;


--
-- Name: court_function_type_concepts court_function_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_function_type_concepts
    ADD CONSTRAINT court_function_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: court_functional_competences court_functional_competences_court_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_functional_competences
    ADD CONSTRAINT court_functional_competences_court_id_fkey FOREIGN KEY (court_id) REFERENCES corpus.courts(id) ON DELETE CASCADE;


--
-- Name: court_functional_competences court_functional_competences_function_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_functional_competences
    ADD CONSTRAINT court_functional_competences_function_type_concept_fkey FOREIGN KEY (function_type) REFERENCES corpus.court_function_type_concepts(code);


--
-- Name: court_functional_competences court_functional_competences_instance_level_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_functional_competences
    ADD CONSTRAINT court_functional_competences_instance_level_concept_fkey FOREIGN KEY (instance_level) REFERENCES corpus.court_instance_level_concepts(code);


--
-- Name: court_functional_competences court_functional_competences_procedure_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_functional_competences
    ADD CONSTRAINT court_functional_competences_procedure_concept_id_fkey FOREIGN KEY (procedure_concept_id) REFERENCES corpus.procedure_concepts(id);


--
-- Name: court_instance_level_concepts court_instance_level_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_instance_level_concepts
    ADD CONSTRAINT court_instance_level_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: court_jurisdictions court_jurisdictions_court_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_jurisdictions
    ADD CONSTRAINT court_jurisdictions_court_id_fkey FOREIGN KEY (court_id) REFERENCES corpus.courts(id) ON DELETE CASCADE;


--
-- Name: court_jurisdictions court_jurisdictions_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_jurisdictions
    ADD CONSTRAINT court_jurisdictions_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: court_organ_alias_kind_concepts court_organ_alias_kind_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_organ_alias_kind_concepts
    ADD CONSTRAINT court_organ_alias_kind_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: court_organ_aliases court_organ_aliases_alias_kind_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_organ_aliases
    ADD CONSTRAINT court_organ_aliases_alias_kind_concept_fkey FOREIGN KEY (alias_kind) REFERENCES corpus.court_organ_alias_kind_concepts(code);


--
-- Name: court_organ_aliases court_organ_aliases_court_organ_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_organ_aliases
    ADD CONSTRAINT court_organ_aliases_court_organ_id_fkey FOREIGN KEY (court_organ_id) REFERENCES corpus.court_organs(id) ON DELETE CASCADE;


--
-- Name: court_organ_aliases court_organ_aliases_source_registry_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_organ_aliases
    ADD CONSTRAINT court_organ_aliases_source_registry_id_fkey FOREIGN KEY (source_registry_id) REFERENCES corpus.source_registries(id) ON DELETE CASCADE;


--
-- Name: court_organs court_organs_court_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_organs
    ADD CONSTRAINT court_organs_court_id_fkey FOREIGN KEY (court_id) REFERENCES corpus.courts(id);


--
-- Name: court_relation_type_concepts court_relation_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_relation_type_concepts
    ADD CONSTRAINT court_relation_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: court_relations court_relations_from_court_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_relations
    ADD CONSTRAINT court_relations_from_court_id_fkey FOREIGN KEY (from_court_id) REFERENCES corpus.courts(id) ON DELETE CASCADE;


--
-- Name: court_relations court_relations_relation_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_relations
    ADD CONSTRAINT court_relations_relation_type_concept_fkey FOREIGN KEY (relation_type) REFERENCES corpus.court_relation_type_concepts(code);


--
-- Name: court_relations court_relations_to_court_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_relations
    ADD CONSTRAINT court_relations_to_court_id_fkey FOREIGN KEY (to_court_id) REFERENCES corpus.courts(id) ON DELETE CASCADE;


--
-- Name: court_subject_matter_competences court_subject_matter_competences_court_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_subject_matter_competences
    ADD CONSTRAINT court_subject_matter_competences_court_id_fkey FOREIGN KEY (court_id) REFERENCES corpus.courts(id) ON DELETE CASCADE;


--
-- Name: court_subject_matter_competences court_subject_matter_competences_legal_matter_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_subject_matter_competences
    ADD CONSTRAINT court_subject_matter_competences_legal_matter_concept_id_fkey FOREIGN KEY (legal_matter_concept_id) REFERENCES corpus.legal_matter_concepts(id);


--
-- Name: court_territorial_competences court_territorial_competences_court_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_territorial_competences
    ADD CONSTRAINT court_territorial_competences_court_id_fkey FOREIGN KEY (court_id) REFERENCES corpus.courts(id) ON DELETE CASCADE;


--
-- Name: court_territorial_competences court_territorial_competences_territorial_unit_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_territorial_competences
    ADD CONSTRAINT court_territorial_competences_territorial_unit_id_fkey FOREIGN KEY (territorial_unit_id) REFERENCES corpus.territorial_units(id);


--
-- Name: court_type_concepts court_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.court_type_concepts
    ADD CONSTRAINT court_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: courts courts_court_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.courts
    ADD CONSTRAINT courts_court_type_concept_fkey FOREIGN KEY (court_type) REFERENCES corpus.court_type_concepts(code);


--
-- Name: courts courts_judicial_system_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.courts
    ADD CONSTRAINT courts_judicial_system_concept_fkey FOREIGN KEY (judicial_system) REFERENCES corpus.judicial_system_concepts(code);


--
-- Name: courts courts_legal_entity_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.courts
    ADD CONSTRAINT courts_legal_entity_id_fkey FOREIGN KEY (legal_entity_id) REFERENCES corpus.legal_entities(id);


--
-- Name: decision_legal_matters decision_legal_matters_legal_matter_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_matters
    ADD CONSTRAINT decision_legal_matters_legal_matter_concept_id_fkey FOREIGN KEY (legal_matter_concept_id) REFERENCES corpus.legal_matter_concepts(id);


--
-- Name: decision_legal_matters decision_legal_matters_relation_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_matters
    ADD CONSTRAINT decision_legal_matters_relation_type_concept_fkey FOREIGN KEY (relation_type) REFERENCES corpus.decision_matter_relation_concepts(code);


--
-- Name: decision_legal_matters decision_legal_matters_scope_id_decision_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_matters
    ADD CONSTRAINT decision_legal_matters_scope_id_decision_id_fkey FOREIGN KEY (scope_id, decision_id) REFERENCES corpus.judicial_decisions(scope_id, id) ON DELETE CASCADE;


--
-- Name: decision_legal_states decision_legal_states_decision_id_evidence_case_page_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_states
    ADD CONSTRAINT decision_legal_states_decision_id_evidence_case_page_id_fkey FOREIGN KEY (decision_id, evidence_case_page_id) REFERENCES corpus.case_pages(case_id, id);


--
-- Name: decision_legal_states decision_legal_states_scope_id_decision_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_states
    ADD CONSTRAINT decision_legal_states_scope_id_decision_id_fkey FOREIGN KEY (scope_id, decision_id) REFERENCES corpus.judicial_decisions(scope_id, id) ON DELETE CASCADE;


--
-- Name: decision_legal_states decision_legal_states_scope_id_source_document_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_states
    ADD CONSTRAINT decision_legal_states_scope_id_source_document_id_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: decision_legal_states decision_legal_states_state_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_states
    ADD CONSTRAINT decision_legal_states_state_concept_id_fkey FOREIGN KEY (state_concept_id) REFERENCES corpus.decision_state_concepts(id);


--
-- Name: decision_legal_status_events decision_legal_status_events_same_case_evidence_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_status_events
    ADD CONSTRAINT decision_legal_status_events_same_case_evidence_fkey FOREIGN KEY (case_id, evidence_case_page_id) REFERENCES corpus.case_pages(case_id, id);


--
-- Name: decision_legal_status_events decision_legal_status_events_same_scope_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_status_events
    ADD CONSTRAINT decision_legal_status_events_same_scope_case_fkey FOREIGN KEY (scope_id, case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: decision_legal_status_events decision_legal_status_events_same_scope_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_status_events
    ADD CONSTRAINT decision_legal_status_events_same_scope_document_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: decision_legal_status_events decision_legal_status_events_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_legal_status_events
    ADD CONSTRAINT decision_legal_status_events_type_concept_fkey FOREIGN KEY (event_type_concept_id) REFERENCES corpus.judicial_event_type_concepts(id);


--
-- Name: decision_matter_relation_concepts decision_matter_relation_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_matter_relation_concepts
    ADD CONSTRAINT decision_matter_relation_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: decision_panel_members decision_panel_members_panel_role_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_panel_members
    ADD CONSTRAINT decision_panel_members_panel_role_concept_fkey FOREIGN KEY (panel_role) REFERENCES corpus.panel_role_concepts(code);


--
-- Name: decision_panel_members decision_panel_members_same_case_evidence_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_panel_members
    ADD CONSTRAINT decision_panel_members_same_case_evidence_fkey FOREIGN KEY (case_id, evidence_case_page_id) REFERENCES corpus.case_pages(case_id, id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: decision_panel_members decision_panel_members_same_scope_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_panel_members
    ADD CONSTRAINT decision_panel_members_same_scope_case_fkey FOREIGN KEY (scope_id, case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: decision_panel_members decision_panel_members_same_scope_officer_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_panel_members
    ADD CONSTRAINT decision_panel_members_same_scope_officer_fkey FOREIGN KEY (scope_id, officer_id) REFERENCES corpus.judicial_officers(scope_id, id);


--
-- Name: decision_procedure_relation_concepts decision_procedure_relation_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_procedure_relation_concepts
    ADD CONSTRAINT decision_procedure_relation_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: decision_procedures decision_procedures_procedure_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_procedures
    ADD CONSTRAINT decision_procedures_procedure_concept_id_fkey FOREIGN KEY (procedure_concept_id) REFERENCES corpus.procedure_concepts(id);


--
-- Name: decision_procedures decision_procedures_relation_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_procedures
    ADD CONSTRAINT decision_procedures_relation_type_concept_fkey FOREIGN KEY (relation_type) REFERENCES corpus.decision_procedure_relation_concepts(code);


--
-- Name: decision_procedures decision_procedures_scope_id_decision_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_procedures
    ADD CONSTRAINT decision_procedures_scope_id_decision_id_fkey FOREIGN KEY (scope_id, decision_id) REFERENCES corpus.judicial_decisions(scope_id, id) ON DELETE CASCADE;


--
-- Name: decision_state_concepts decision_state_concepts_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_state_concepts
    ADD CONSTRAINT decision_state_concepts_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.decision_state_concepts(id);


--
-- Name: decision_votes decision_votes_panel_member_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_votes
    ADD CONSTRAINT decision_votes_panel_member_fkey FOREIGN KEY (case_id, officer_id) REFERENCES corpus.decision_panel_members(case_id, officer_id);


--
-- Name: decision_votes decision_votes_same_case_opinion_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_votes
    ADD CONSTRAINT decision_votes_same_case_opinion_fkey FOREIGN KEY (scope_id, case_id, opinion_id) REFERENCES corpus.judicial_opinions(scope_id, case_id, id);


--
-- Name: decision_votes decision_votes_same_scope_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_votes
    ADD CONSTRAINT decision_votes_same_scope_case_fkey FOREIGN KEY (scope_id, case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: decision_votes decision_votes_same_scope_officer_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_votes
    ADD CONSTRAINT decision_votes_same_scope_officer_fkey FOREIGN KEY (scope_id, officer_id) REFERENCES corpus.judicial_officers(scope_id, id);


--
-- Name: decision_votes decision_votes_vote_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.decision_votes
    ADD CONSTRAINT decision_votes_vote_type_concept_fkey FOREIGN KEY (vote_type) REFERENCES corpus.judicial_vote_type_concepts(code);


--
-- Name: judicial_disposition_action_arguments disposition_arguments_action_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_action_arguments
    ADD CONSTRAINT disposition_arguments_action_fkey FOREIGN KEY (scope_id, disposition_id, action_id) REFERENCES corpus.judicial_disposition_actions(scope_id, disposition_id, id) ON DELETE CASCADE;


--
-- Name: judicial_disposition_action_arguments disposition_arguments_claim_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_action_arguments
    ADD CONSTRAINT disposition_arguments_claim_fkey FOREIGN KEY (scope_id, target_claim_id) REFERENCES corpus.legal_claims(scope_id, id);


--
-- Name: judicial_disposition_action_arguments disposition_arguments_court_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_action_arguments
    ADD CONSTRAINT disposition_arguments_court_fkey FOREIGN KEY (target_court_id) REFERENCES corpus.courts(id);


--
-- Name: judicial_disposition_action_arguments disposition_arguments_court_organ_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_action_arguments
    ADD CONSTRAINT disposition_arguments_court_organ_fkey FOREIGN KEY (target_court_organ_id) REFERENCES corpus.court_organs(id);


--
-- Name: judicial_disposition_action_arguments disposition_arguments_decision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_action_arguments
    ADD CONSTRAINT disposition_arguments_decision_fkey FOREIGN KEY (scope_id, target_decision_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: judicial_disposition_action_arguments disposition_arguments_party_role_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_action_arguments
    ADD CONSTRAINT disposition_arguments_party_role_fkey FOREIGN KEY (scope_id, target_party_role_id) REFERENCES corpus.proceeding_party_roles(scope_id, id);


--
-- Name: judicial_disposition_action_arguments disposition_arguments_proceeding_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_action_arguments
    ADD CONSTRAINT disposition_arguments_proceeding_fkey FOREIGN KEY (scope_id, target_proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id);


--
-- Name: judicial_disposition_action_arguments disposition_arguments_proposition_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_action_arguments
    ADD CONSTRAINT disposition_arguments_proposition_fkey FOREIGN KEY (scope_id, target_proposition_id) REFERENCES corpus.legal_propositions(scope_id, id);


--
-- Name: judicial_disposition_action_arguments disposition_arguments_provision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_action_arguments
    ADD CONSTRAINT disposition_arguments_provision_fkey FOREIGN KEY (scope_id, target_provision_id) REFERENCES corpus.legal_provisions(scope_id, id);


--
-- Name: judicial_disposition_action_arguments disposition_arguments_role_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_action_arguments
    ADD CONSTRAINT disposition_arguments_role_fkey FOREIGN KEY (role_scheme_code, role_concept_id) REFERENCES corpus.legal_concepts(scheme_code, id);


--
-- Name: disposition_concepts disposition_concepts_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.disposition_concepts
    ADD CONSTRAINT disposition_concepts_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.disposition_concepts(id);


--
-- Name: disposition_effect_argument_rules disposition_effect_argument_rules_effect_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.disposition_effect_argument_rules
    ADD CONSTRAINT disposition_effect_argument_rules_effect_concept_id_fkey FOREIGN KEY (effect_concept_id) REFERENCES corpus.disposition_effect_concepts(id) ON DELETE CASCADE;


--
-- Name: disposition_effect_argument_rules disposition_effect_argument_rules_role_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.disposition_effect_argument_rules
    ADD CONSTRAINT disposition_effect_argument_rules_role_fkey FOREIGN KEY (role_scheme_code, role_concept_id) REFERENCES corpus.legal_concepts(scheme_code, id);


--
-- Name: entity_identity_assertion_evidence entity_identity_assertion_evi_source_document_observation__fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_assertion_evidence
    ADD CONSTRAINT entity_identity_assertion_evi_source_document_observation__fkey FOREIGN KEY (source_document_observation_id) REFERENCES corpus.source_document_observations(id) ON DELETE SET NULL;


--
-- Name: entity_identity_assertion_evidence entity_identity_assertion_evidence_artifact_page_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_assertion_evidence
    ADD CONSTRAINT entity_identity_assertion_evidence_artifact_page_id_fkey FOREIGN KEY (artifact_page_id) REFERENCES corpus.artifact_pages(id);


--
-- Name: entity_identity_assertions entity_identity_assertions_candidate_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_assertions
    ADD CONSTRAINT entity_identity_assertions_candidate_fkey FOREIGN KEY (scope_id, candidate_entity_id) REFERENCES corpus.legal_entities(scope_id, id) ON DELETE CASCADE;


--
-- Name: entity_identity_assertions entity_identity_assertions_observed_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_assertions
    ADD CONSTRAINT entity_identity_assertions_observed_fkey FOREIGN KEY (scope_id, observed_entity_id) REFERENCES corpus.legal_entities(scope_id, id) ON DELETE CASCADE;


--
-- Name: entity_identity_assertions entity_identity_assertions_relation_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_assertions
    ADD CONSTRAINT entity_identity_assertions_relation_fkey FOREIGN KEY (relation_scheme_code, relation_concept_id) REFERENCES corpus.legal_concepts(scheme_code, id);


--
-- Name: entity_identity_assertion_evidence entity_identity_evidence_assertion_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_assertion_evidence
    ADD CONSTRAINT entity_identity_evidence_assertion_fkey FOREIGN KEY (scope_id, assertion_id) REFERENCES corpus.entity_identity_assertions(scope_id, id) ON DELETE CASCADE;


--
-- Name: entity_identity_resolutions entity_identity_resolutions_assertion_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_resolutions
    ADD CONSTRAINT entity_identity_resolutions_assertion_fkey FOREIGN KEY (scope_id, supporting_assertion_id) REFERENCES corpus.entity_identity_assertions(scope_id, id);


--
-- Name: entity_identity_resolutions entity_identity_resolutions_canonical_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_resolutions
    ADD CONSTRAINT entity_identity_resolutions_canonical_fkey FOREIGN KEY (scope_id, canonical_entity_id) REFERENCES corpus.legal_entities(scope_id, id);


--
-- Name: entity_identity_resolutions entity_identity_resolutions_observed_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.entity_identity_resolutions
    ADD CONSTRAINT entity_identity_resolutions_observed_fkey FOREIGN KEY (scope_id, observed_entity_id) REFERENCES corpus.legal_entities(scope_id, id) ON DELETE CASCADE;


--
-- Name: factual_proposition_evidence factual_evidence_case_page_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_proposition_evidence
    ADD CONSTRAINT factual_evidence_case_page_fkey FOREIGN KEY (source_decision_id, case_page_id) REFERENCES corpus.case_pages(case_id, id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: factual_proposition_evidence factual_evidence_decision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_proposition_evidence
    ADD CONSTRAINT factual_evidence_decision_fkey FOREIGN KEY (scope_id, source_decision_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: factual_proposition_evidence factual_evidence_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_proposition_evidence
    ADD CONSTRAINT factual_evidence_document_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: factual_proposition_evidence factual_evidence_fact_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_proposition_evidence
    ADD CONSTRAINT factual_evidence_fact_fkey FOREIGN KEY (scope_id, factual_proposition_id) REFERENCES corpus.factual_propositions(scope_id, id) ON DELETE CASCADE;


--
-- Name: factual_proposition_evidence factual_proposition_evidence_artifact_page_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_proposition_evidence
    ADD CONSTRAINT factual_proposition_evidence_artifact_page_id_fkey FOREIGN KEY (artifact_page_id) REFERENCES corpus.artifact_pages(id);


--
-- Name: factual_propositions factual_propositions_kind_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_propositions
    ADD CONSTRAINT factual_propositions_kind_fkey FOREIGN KEY (kind_scheme_code, kind_concept_id) REFERENCES corpus.legal_concepts(scheme_code, id);


--
-- Name: factual_propositions factual_propositions_scope_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_propositions
    ADD CONSTRAINT factual_propositions_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id);


--
-- Name: factual_proposition_subjects factual_subjects_claim_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_proposition_subjects
    ADD CONSTRAINT factual_subjects_claim_fkey FOREIGN KEY (scope_id, claim_id) REFERENCES corpus.legal_claims(scope_id, id);


--
-- Name: factual_proposition_subjects factual_subjects_decision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_proposition_subjects
    ADD CONSTRAINT factual_subjects_decision_fkey FOREIGN KEY (scope_id, judicial_decision_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: factual_proposition_subjects factual_subjects_fact_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_proposition_subjects
    ADD CONSTRAINT factual_subjects_fact_fkey FOREIGN KEY (scope_id, factual_proposition_id) REFERENCES corpus.factual_propositions(scope_id, id) ON DELETE CASCADE;


--
-- Name: factual_proposition_subjects factual_subjects_party_role_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_proposition_subjects
    ADD CONSTRAINT factual_subjects_party_role_fkey FOREIGN KEY (scope_id, party_role_id) REFERENCES corpus.proceeding_party_roles(scope_id, id);


--
-- Name: factual_proposition_subjects factual_subjects_proceeding_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_proposition_subjects
    ADD CONSTRAINT factual_subjects_proceeding_fkey FOREIGN KEY (scope_id, proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id);


--
-- Name: factual_proposition_subjects factual_subjects_relation_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.factual_proposition_subjects
    ADD CONSTRAINT factual_subjects_relation_fkey FOREIGN KEY (relation_scheme_code, relation_concept_id) REFERENCES corpus.legal_concepts(scheme_code, id);


--
-- Name: ingestion_jobs ingestion_jobs_artifact_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.ingestion_jobs
    ADD CONSTRAINT ingestion_jobs_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES corpus.source_artifacts(id);


--
-- Name: ingestion_jobs ingestion_jobs_parser_version_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.ingestion_jobs
    ADD CONSTRAINT ingestion_jobs_parser_version_id_fkey FOREIGN KEY (parser_version_id) REFERENCES corpus.parser_versions(id);


--
-- Name: instrument_authority_role_concepts instrument_authority_role_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.instrument_authority_role_concepts
    ADD CONSTRAINT instrument_authority_role_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: instrument_document_role_concepts instrument_document_role_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.instrument_document_role_concepts
    ADD CONSTRAINT instrument_document_role_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: instrument_version_kind_concepts instrument_version_kind_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.instrument_version_kind_concepts
    ADD CONSTRAINT instrument_version_kind_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: judicial_authority_effect_concepts judicial_authority_effect_concepts_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_authority_effect_concepts
    ADD CONSTRAINT judicial_authority_effect_concepts_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.judicial_authority_effect_concepts(id);


--
-- Name: judicial_authority_effect_concepts judicial_authority_effect_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_authority_effect_concepts
    ADD CONSTRAINT judicial_authority_effect_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: judicial_authorship_role_concepts judicial_authorship_role_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_authorship_role_concepts
    ADD CONSTRAINT judicial_authorship_role_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: judicial_decisions judicial_decisions_act_type_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_decisions
    ADD CONSTRAINT judicial_decisions_act_type_fkey FOREIGN KEY (act_type_concept_id) REFERENCES corpus.adjudicative_act_type_concepts(id);


--
-- Name: judicial_disposition_actions judicial_disposition_actions_effect_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_actions
    ADD CONSTRAINT judicial_disposition_actions_effect_concept_id_fkey FOREIGN KEY (effect_concept_id) REFERENCES corpus.disposition_effect_concepts(id);


--
-- Name: judicial_disposition_actions judicial_disposition_actions_scope_id_disposition_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_disposition_actions
    ADD CONSTRAINT judicial_disposition_actions_scope_id_disposition_id_fkey FOREIGN KEY (scope_id, disposition_id) REFERENCES corpus.judicial_decision_dispositions(scope_id, id) ON DELETE CASCADE;


--
-- Name: judicial_event_type_concepts judicial_event_type_concepts_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_event_type_concepts
    ADD CONSTRAINT judicial_event_type_concepts_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.judicial_event_type_concepts(id);


--
-- Name: judicial_event_type_concepts judicial_event_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_event_type_concepts
    ADD CONSTRAINT judicial_event_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: judicial_officer_position_type_concepts judicial_officer_position_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_officer_position_type_concepts
    ADD CONSTRAINT judicial_officer_position_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: judicial_officer_positions judicial_officer_positions_court_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_officer_positions
    ADD CONSTRAINT judicial_officer_positions_court_id_fkey FOREIGN KEY (court_id) REFERENCES corpus.courts(id);


--
-- Name: judicial_officer_positions judicial_officer_positions_position_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_officer_positions
    ADD CONSTRAINT judicial_officer_positions_position_type_concept_fkey FOREIGN KEY (position_type) REFERENCES corpus.judicial_officer_position_type_concepts(code);


--
-- Name: judicial_officer_positions judicial_officer_positions_same_scope_officer_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_officer_positions
    ADD CONSTRAINT judicial_officer_positions_same_scope_officer_fkey FOREIGN KEY (scope_id, officer_id) REFERENCES corpus.judicial_officers(scope_id, id);


--
-- Name: judicial_officers judicial_officers_legal_entity_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_officers
    ADD CONSTRAINT judicial_officers_legal_entity_id_fkey FOREIGN KEY (legal_entity_id) REFERENCES corpus.legal_entities(id);


--
-- Name: judicial_officers judicial_officers_same_scope_legal_entity_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_officers
    ADD CONSTRAINT judicial_officers_same_scope_legal_entity_fkey FOREIGN KEY (scope_id, legal_entity_id) REFERENCES corpus.legal_entities(scope_id, id);


--
-- Name: judicial_officers judicial_officers_scope_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_officers
    ADD CONSTRAINT judicial_officers_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id);


--
-- Name: judicial_opinion_authors judicial_opinion_authors_authorship_role_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_authors
    ADD CONSTRAINT judicial_opinion_authors_authorship_role_concept_fkey FOREIGN KEY (authorship_role) REFERENCES corpus.judicial_authorship_role_concepts(code);


--
-- Name: judicial_opinion_authors judicial_opinion_authors_case_id_officer_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_authors
    ADD CONSTRAINT judicial_opinion_authors_case_id_officer_id_fkey FOREIGN KEY (case_id, officer_id) REFERENCES corpus.decision_panel_members(case_id, officer_id);


--
-- Name: judicial_opinion_authors judicial_opinion_authors_scope_id_case_id_opinion_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_authors
    ADD CONSTRAINT judicial_opinion_authors_scope_id_case_id_opinion_id_fkey FOREIGN KEY (scope_id, case_id, opinion_id) REFERENCES corpus.judicial_opinions(scope_id, case_id, id) ON DELETE CASCADE;


--
-- Name: judicial_opinion_join_type_concepts judicial_opinion_join_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_join_type_concepts
    ADD CONSTRAINT judicial_opinion_join_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: judicial_opinion_joiners judicial_opinion_joiners_join_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_joiners
    ADD CONSTRAINT judicial_opinion_joiners_join_type_concept_fkey FOREIGN KEY (join_type) REFERENCES corpus.judicial_opinion_join_type_concepts(code);


--
-- Name: judicial_opinion_joiners judicial_opinion_joiners_panel_member_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_joiners
    ADD CONSTRAINT judicial_opinion_joiners_panel_member_fkey FOREIGN KEY (case_id, officer_id) REFERENCES corpus.decision_panel_members(case_id, officer_id);


--
-- Name: judicial_opinion_joiners judicial_opinion_joiners_same_case_opinion_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_joiners
    ADD CONSTRAINT judicial_opinion_joiners_same_case_opinion_fkey FOREIGN KEY (scope_id, case_id, opinion_id) REFERENCES corpus.judicial_opinions(scope_id, case_id, id);


--
-- Name: judicial_opinion_joiners judicial_opinion_joiners_same_scope_officer_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_joiners
    ADD CONSTRAINT judicial_opinion_joiners_same_scope_officer_fkey FOREIGN KEY (scope_id, officer_id) REFERENCES corpus.judicial_officers(scope_id, id);


--
-- Name: judicial_opinion_joiners judicial_opinion_joiners_same_scope_opinion_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_joiners
    ADD CONSTRAINT judicial_opinion_joiners_same_scope_opinion_fkey FOREIGN KEY (scope_id, opinion_id) REFERENCES corpus.judicial_opinions(scope_id, id);


--
-- Name: judicial_opinion_type_concepts judicial_opinion_type_concepts_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_type_concepts
    ADD CONSTRAINT judicial_opinion_type_concepts_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.judicial_opinion_type_concepts(id);


--
-- Name: judicial_opinion_type_concepts judicial_opinion_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinion_type_concepts
    ADD CONSTRAINT judicial_opinion_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: judicial_opinions judicial_opinions_same_scope_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinions
    ADD CONSTRAINT judicial_opinions_same_scope_case_fkey FOREIGN KEY (scope_id, case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: judicial_opinions judicial_opinions_same_scope_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinions
    ADD CONSTRAINT judicial_opinions_same_scope_document_fkey FOREIGN KEY (scope_id, document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: judicial_opinions judicial_opinions_same_scope_proposition_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinions
    ADD CONSTRAINT judicial_opinions_same_scope_proposition_fkey FOREIGN KEY (scope_id, proposition_id) REFERENCES corpus.legal_propositions(scope_id, id);


--
-- Name: judicial_opinions judicial_opinions_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_opinions
    ADD CONSTRAINT judicial_opinions_type_concept_fkey FOREIGN KEY (opinion_type_concept_id) REFERENCES corpus.judicial_opinion_type_concepts(id);


--
-- Name: judicial_stance_concepts judicial_stance_concepts_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_stance_concepts
    ADD CONSTRAINT judicial_stance_concepts_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.judicial_stance_concepts(id);


--
-- Name: judicial_stance_concepts judicial_stance_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_stance_concepts
    ADD CONSTRAINT judicial_stance_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: judicial_system_concepts judicial_system_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_system_concepts
    ADD CONSTRAINT judicial_system_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: judicial_vote_stances judicial_vote_stances_case_id_disposition_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_vote_stances
    ADD CONSTRAINT judicial_vote_stances_case_id_disposition_id_fkey FOREIGN KEY (case_id, disposition_id) REFERENCES corpus.judicial_decision_dispositions(case_id, id);


--
-- Name: judicial_vote_stances judicial_vote_stances_case_id_officer_id_vote_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_vote_stances
    ADD CONSTRAINT judicial_vote_stances_case_id_officer_id_vote_id_fkey FOREIGN KEY (case_id, officer_id, vote_id) REFERENCES corpus.decision_votes(case_id, officer_id, id) ON DELETE CASCADE;


--
-- Name: judicial_vote_stances judicial_vote_stances_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_vote_stances
    ADD CONSTRAINT judicial_vote_stances_concept_fkey FOREIGN KEY (stance_concept_id) REFERENCES corpus.judicial_stance_concepts(id);


--
-- Name: judicial_vote_stances judicial_vote_stances_scope_id_case_id_opinion_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_vote_stances
    ADD CONSTRAINT judicial_vote_stances_scope_id_case_id_opinion_id_fkey FOREIGN KEY (scope_id, case_id, opinion_id) REFERENCES corpus.judicial_opinions(scope_id, case_id, id);


--
-- Name: judicial_vote_stances judicial_vote_stances_scope_id_proposition_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_vote_stances
    ADD CONSTRAINT judicial_vote_stances_scope_id_proposition_id_fkey FOREIGN KEY (scope_id, proposition_id) REFERENCES corpus.legal_propositions(scope_id, id);


--
-- Name: judicial_vote_type_concepts judicial_vote_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_vote_type_concepts
    ADD CONSTRAINT judicial_vote_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_amendment_effect_type_concepts legal_amendment_effect_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_effect_type_concepts
    ADD CONSTRAINT legal_amendment_effect_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_amendment_effects legal_amendment_effects_effect_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_effects
    ADD CONSTRAINT legal_amendment_effects_effect_type_concept_fkey FOREIGN KEY (effect_type) REFERENCES corpus.legal_amendment_effect_type_concepts(code);


--
-- Name: legal_amendment_effects legal_amendment_effects_evidence_artifact_page_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_effects
    ADD CONSTRAINT legal_amendment_effects_evidence_artifact_page_id_fkey FOREIGN KEY (evidence_artifact_page_id) REFERENCES corpus.artifact_pages(id);


--
-- Name: legal_amendment_effects legal_amendment_effects_same_scope_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_effects
    ADD CONSTRAINT legal_amendment_effects_same_scope_document_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: legal_amendment_effects legal_amendment_effects_same_scope_source_instrument_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_effects
    ADD CONSTRAINT legal_amendment_effects_same_scope_source_instrument_fkey FOREIGN KEY (scope_id, source_instrument_id) REFERENCES corpus.legal_instruments(scope_id, id);


--
-- Name: legal_amendment_effects legal_amendment_effects_same_scope_target_instrument_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_effects
    ADD CONSTRAINT legal_amendment_effects_same_scope_target_instrument_fkey FOREIGN KEY (scope_id, target_instrument_id) REFERENCES corpus.legal_instruments(scope_id, id);


--
-- Name: legal_amendment_effects legal_amendment_effects_source_version_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_effects
    ADD CONSTRAINT legal_amendment_effects_source_version_fkey FOREIGN KEY (source_instrument_id, source_version_id) REFERENCES corpus.legal_instrument_versions(instrument_id, id);


--
-- Name: legal_amendment_effects legal_amendment_effects_target_provision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_effects
    ADD CONSTRAINT legal_amendment_effects_target_provision_fkey FOREIGN KEY (target_instrument_id, target_provision_id) REFERENCES corpus.legal_provisions(instrument_id, id);


--
-- Name: legal_amendment_operation_type_concepts legal_amendment_operation_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_operation_type_concepts
    ADD CONSTRAINT legal_amendment_operation_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_amendment_operations legal_amendment_operations_amendment_effect_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_operations
    ADD CONSTRAINT legal_amendment_operations_amendment_effect_id_fkey FOREIGN KEY (amendment_effect_id) REFERENCES corpus.legal_amendment_effects(id) ON DELETE CASCADE;


--
-- Name: legal_amendment_operations legal_amendment_operations_operation_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_operations
    ADD CONSTRAINT legal_amendment_operations_operation_type_concept_fkey FOREIGN KEY (operation_type) REFERENCES corpus.legal_amendment_operation_type_concepts(code);


--
-- Name: legal_amendment_operations legal_amendment_operations_same_scope_target_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_amendment_operations
    ADD CONSTRAINT legal_amendment_operations_same_scope_target_fkey FOREIGN KEY (scope_id, target_provision_version_id) REFERENCES corpus.legal_provision_versions(scope_id, id);


--
-- Name: legal_authorities legal_authorities_authority_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_authorities
    ADD CONSTRAINT legal_authorities_authority_type_concept_fkey FOREIGN KEY (authority_type) REFERENCES corpus.legal_authority_type_concepts(code);


--
-- Name: legal_authorities legal_authorities_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_authorities
    ADD CONSTRAINT legal_authorities_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_authorities legal_authorities_legal_entity_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_authorities
    ADD CONSTRAINT legal_authorities_legal_entity_id_fkey FOREIGN KEY (legal_entity_id) REFERENCES corpus.legal_entities(id);


--
-- Name: legal_authorities legal_authorities_same_scope_legal_entity_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_authorities
    ADD CONSTRAINT legal_authorities_same_scope_legal_entity_fkey FOREIGN KEY (scope_id, legal_entity_id) REFERENCES corpus.legal_entities(scope_id, id);


--
-- Name: legal_authorities legal_authorities_scope_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_authorities
    ADD CONSTRAINT legal_authorities_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id);


--
-- Name: legal_authority_type_concepts legal_authority_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_authority_type_concepts
    ADD CONSTRAINT legal_authority_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_claim_concepts legal_claim_concepts_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_claim_concepts
    ADD CONSTRAINT legal_claim_concepts_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.legal_claim_concepts(id);


--
-- Name: legal_claim_concepts legal_claim_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_claim_concepts
    ADD CONSTRAINT legal_claim_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_claims legal_claims_claim_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_claims
    ADD CONSTRAINT legal_claims_claim_concept_id_fkey FOREIGN KEY (claim_concept_id) REFERENCES corpus.legal_claim_concepts(id);


--
-- Name: legal_claims legal_claims_parent_claim_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_claims
    ADD CONSTRAINT legal_claims_parent_claim_id_fkey FOREIGN KEY (parent_claim_id) REFERENCES corpus.legal_claims(id);


--
-- Name: legal_claims legal_claims_parent_same_proceeding_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_claims
    ADD CONSTRAINT legal_claims_parent_same_proceeding_fkey FOREIGN KEY (scope_id, proceeding_id, parent_claim_id) REFERENCES corpus.legal_claims(scope_id, proceeding_id, id);


--
-- Name: legal_claims legal_claims_party_role_same_proceeding_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_claims
    ADD CONSTRAINT legal_claims_party_role_same_proceeding_fkey FOREIGN KEY (scope_id, proceeding_id, asserted_by_party_role_id) REFERENCES corpus.proceeding_party_roles(scope_id, proceeding_id, id);


--
-- Name: legal_claims legal_claims_scope_id_asserted_by_party_role_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_claims
    ADD CONSTRAINT legal_claims_scope_id_asserted_by_party_role_id_fkey FOREIGN KEY (scope_id, asserted_by_party_role_id) REFERENCES corpus.proceeding_party_roles(scope_id, id);


--
-- Name: legal_claims legal_claims_scope_id_proceeding_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_claims
    ADD CONSTRAINT legal_claims_scope_id_proceeding_id_fkey FOREIGN KEY (scope_id, proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id) ON DELETE CASCADE;


--
-- Name: legal_concept_aliases legal_concept_aliases_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_concept_aliases
    ADD CONSTRAINT legal_concept_aliases_concept_id_fkey FOREIGN KEY (concept_id) REFERENCES corpus.legal_concepts(id) ON DELETE CASCADE;


--
-- Name: legal_concept_edges legal_concept_edges_source_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_concept_edges
    ADD CONSTRAINT legal_concept_edges_source_concept_id_fkey FOREIGN KEY (source_concept_id) REFERENCES corpus.legal_concepts(id) ON DELETE CASCADE;


--
-- Name: legal_concept_edges legal_concept_edges_target_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_concept_edges
    ADD CONSTRAINT legal_concept_edges_target_concept_id_fkey FOREIGN KEY (target_concept_id) REFERENCES corpus.legal_concepts(id) ON DELETE CASCADE;


--
-- Name: legal_concepts legal_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_concepts
    ADD CONSTRAINT legal_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_concepts legal_concepts_scheme_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_concepts
    ADD CONSTRAINT legal_concepts_scheme_code_fkey FOREIGN KEY (scheme_code) REFERENCES corpus.concept_schemes(code);


--
-- Name: legal_controversies legal_controversies_scope_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_controversies
    ADD CONSTRAINT legal_controversies_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id);


--
-- Name: legal_controversies legal_controversies_status_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_controversies
    ADD CONSTRAINT legal_controversies_status_concept_fkey FOREIGN KEY (status) REFERENCES corpus.legal_controversy_status_concepts(code);


--
-- Name: legal_controversy_status_concepts legal_controversy_status_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_controversy_status_concepts
    ADD CONSTRAINT legal_controversy_status_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_document_identifiers legal_document_identifiers_document_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_identifiers
    ADD CONSTRAINT legal_document_identifiers_document_id_fkey FOREIGN KEY (document_id) REFERENCES corpus.legal_documents(id);


--
-- Name: legal_document_identifiers legal_document_identifiers_source_registry_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_identifiers
    ADD CONSTRAINT legal_document_identifiers_source_registry_id_fkey FOREIGN KEY (source_registry_id) REFERENCES corpus.source_registries(id);


--
-- Name: legal_document_artifact_occurrences legal_document_occurrence_same_scope_artifact_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_artifact_occurrences
    ADD CONSTRAINT legal_document_occurrence_same_scope_artifact_fkey FOREIGN KEY (scope_id, artifact_id) REFERENCES corpus.source_artifacts(scope_id, id);


--
-- Name: legal_document_artifact_occurrences legal_document_occurrence_same_scope_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_artifact_occurrences
    ADD CONSTRAINT legal_document_occurrence_same_scope_document_fkey FOREIGN KEY (scope_id, document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: legal_document_provisions legal_document_provisions_document_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_provisions
    ADD CONSTRAINT legal_document_provisions_document_id_fkey FOREIGN KEY (document_id) REFERENCES corpus.legal_documents(id) ON DELETE CASCADE;


--
-- Name: legal_document_provisions legal_document_provisions_parent_same_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_provisions
    ADD CONSTRAINT legal_document_provisions_parent_same_document_fkey FOREIGN KEY (document_id, parent_provision_id) REFERENCES corpus.legal_document_provisions(document_id, id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: legal_document_provisions legal_document_provisions_provision_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_provisions
    ADD CONSTRAINT legal_document_provisions_provision_type_concept_fkey FOREIGN KEY (provision_type) REFERENCES corpus.provision_type_concepts(code);


--
-- Name: legal_document_tags legal_document_tags_document_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_tags
    ADD CONSTRAINT legal_document_tags_document_id_fkey FOREIGN KEY (document_id) REFERENCES corpus.legal_documents(id) ON DELETE CASCADE;


--
-- Name: legal_document_tags legal_document_tags_evidence_artifact_page_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_tags
    ADD CONSTRAINT legal_document_tags_evidence_artifact_page_id_fkey FOREIGN KEY (evidence_artifact_page_id) REFERENCES corpus.artifact_pages(id);


--
-- Name: legal_document_tags legal_document_tags_tag_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_tags
    ADD CONSTRAINT legal_document_tags_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES corpus.legal_tags(id) ON DELETE CASCADE;


--
-- Name: legal_document_type_concepts legal_document_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_document_type_concepts
    ADD CONSTRAINT legal_document_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_documents legal_documents_document_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_documents
    ADD CONSTRAINT legal_documents_document_type_concept_fkey FOREIGN KEY (document_type) REFERENCES corpus.legal_document_type_concepts(code);


--
-- Name: legal_documents legal_documents_scope_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_documents
    ADD CONSTRAINT legal_documents_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id);


--
-- Name: legal_entities legal_entities_scope_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_entities
    ADD CONSTRAINT legal_entities_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id);


--
-- Name: legal_instrument_authority_roles legal_instrument_authority_roles_authority_role_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_authority_roles
    ADD CONSTRAINT legal_instrument_authority_roles_authority_role_concept_fkey FOREIGN KEY (authority_role) REFERENCES corpus.instrument_authority_role_concepts(code);


--
-- Name: legal_instrument_authority_roles legal_instrument_authority_roles_same_scope_authority_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_authority_roles
    ADD CONSTRAINT legal_instrument_authority_roles_same_scope_authority_fkey FOREIGN KEY (scope_id, authority_id) REFERENCES corpus.legal_authorities(scope_id, id);


--
-- Name: legal_instrument_authority_roles legal_instrument_authority_roles_same_scope_instrument_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_authority_roles
    ADD CONSTRAINT legal_instrument_authority_roles_same_scope_instrument_fkey FOREIGN KEY (scope_id, instrument_id) REFERENCES corpus.legal_instruments(scope_id, id);


--
-- Name: legal_instrument_event_type_concepts legal_instrument_event_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_event_type_concepts
    ADD CONSTRAINT legal_instrument_event_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_instrument_events legal_instrument_events_event_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_events
    ADD CONSTRAINT legal_instrument_events_event_type_concept_fkey FOREIGN KEY (event_type) REFERENCES corpus.legal_instrument_event_type_concepts(code);


--
-- Name: legal_instrument_events legal_instrument_events_evidence_artifact_page_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_events
    ADD CONSTRAINT legal_instrument_events_evidence_artifact_page_id_fkey FOREIGN KEY (evidence_artifact_page_id) REFERENCES corpus.artifact_pages(id);


--
-- Name: legal_instrument_events legal_instrument_events_same_scope_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_events
    ADD CONSTRAINT legal_instrument_events_same_scope_document_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: legal_instrument_events legal_instrument_events_same_scope_instrument_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_events
    ADD CONSTRAINT legal_instrument_events_same_scope_instrument_fkey FOREIGN KEY (scope_id, instrument_id) REFERENCES corpus.legal_instruments(scope_id, id);


--
-- Name: legal_instrument_identifiers legal_instrument_identifiers_instrument_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_identifiers
    ADD CONSTRAINT legal_instrument_identifiers_instrument_id_fkey FOREIGN KEY (instrument_id) REFERENCES corpus.legal_instruments(id) ON DELETE CASCADE;


--
-- Name: legal_instrument_identifiers legal_instrument_identifiers_source_registry_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_identifiers
    ADD CONSTRAINT legal_instrument_identifiers_source_registry_id_fkey FOREIGN KEY (source_registry_id) REFERENCES corpus.source_registries(id);


--
-- Name: legal_instrument_type_concepts legal_instrument_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_type_concepts
    ADD CONSTRAINT legal_instrument_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_instrument_version_documents legal_instrument_version_documents_document_role_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_version_documents
    ADD CONSTRAINT legal_instrument_version_documents_document_role_concept_fkey FOREIGN KEY (document_role) REFERENCES corpus.instrument_document_role_concepts(code);


--
-- Name: legal_instrument_version_documents legal_instrument_version_documents_same_scope_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_version_documents
    ADD CONSTRAINT legal_instrument_version_documents_same_scope_document_fkey FOREIGN KEY (scope_id, document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: legal_instrument_version_documents legal_instrument_version_documents_same_scope_version_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_version_documents
    ADD CONSTRAINT legal_instrument_version_documents_same_scope_version_fkey FOREIGN KEY (scope_id, instrument_version_id) REFERENCES corpus.legal_instrument_versions(scope_id, id);


--
-- Name: legal_instrument_version_knowledge legal_instrument_version_knowledge_same_scope_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_version_knowledge
    ADD CONSTRAINT legal_instrument_version_knowledge_same_scope_document_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: legal_instrument_version_knowledge legal_instrument_version_knowledge_same_scope_version_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_version_knowledge
    ADD CONSTRAINT legal_instrument_version_knowledge_same_scope_version_fkey FOREIGN KEY (scope_id, instrument_version_id) REFERENCES corpus.legal_instrument_versions(scope_id, id);


--
-- Name: legal_instrument_versions legal_instrument_versions_same_instrument_parent_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_versions
    ADD CONSTRAINT legal_instrument_versions_same_instrument_parent_fkey FOREIGN KEY (instrument_id, derived_from_version_id) REFERENCES corpus.legal_instrument_versions(instrument_id, id);


--
-- Name: legal_instrument_versions legal_instrument_versions_same_scope_instrument_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_versions
    ADD CONSTRAINT legal_instrument_versions_same_scope_instrument_fkey FOREIGN KEY (scope_id, instrument_id) REFERENCES corpus.legal_instruments(scope_id, id);


--
-- Name: legal_instrument_versions legal_instrument_versions_version_kind_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instrument_versions
    ADD CONSTRAINT legal_instrument_versions_version_kind_concept_fkey FOREIGN KEY (version_kind) REFERENCES corpus.instrument_version_kind_concepts(code);


--
-- Name: legal_instruments legal_instruments_instrument_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instruments
    ADD CONSTRAINT legal_instruments_instrument_type_concept_fkey FOREIGN KEY (instrument_type) REFERENCES corpus.legal_instrument_type_concepts(code);


--
-- Name: legal_instruments legal_instruments_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instruments
    ADD CONSTRAINT legal_instruments_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_instruments legal_instruments_scope_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_instruments
    ADD CONSTRAINT legal_instruments_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id);


--
-- Name: legal_issue_evidence legal_issue_evidence_artifact_page_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issue_evidence
    ADD CONSTRAINT legal_issue_evidence_artifact_page_id_fkey FOREIGN KEY (artifact_page_id) REFERENCES corpus.artifact_pages(id);


--
-- Name: legal_issue_evidence legal_issue_evidence_case_page_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issue_evidence
    ADD CONSTRAINT legal_issue_evidence_case_page_fkey FOREIGN KEY (source_decision_id, case_page_id) REFERENCES corpus.case_pages(case_id, id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: legal_issue_evidence legal_issue_evidence_decision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issue_evidence
    ADD CONSTRAINT legal_issue_evidence_decision_fkey FOREIGN KEY (scope_id, source_decision_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: legal_issue_evidence legal_issue_evidence_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issue_evidence
    ADD CONSTRAINT legal_issue_evidence_document_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: legal_issue_evidence legal_issue_evidence_issue_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issue_evidence
    ADD CONSTRAINT legal_issue_evidence_issue_fkey FOREIGN KEY (scope_id, issue_id) REFERENCES corpus.legal_issues(scope_id, id) ON DELETE CASCADE;


--
-- Name: legal_issue_subjects legal_issue_subjects_claim_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issue_subjects
    ADD CONSTRAINT legal_issue_subjects_claim_fkey FOREIGN KEY (scope_id, claim_id) REFERENCES corpus.legal_claims(scope_id, id);


--
-- Name: legal_issue_subjects legal_issue_subjects_decision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issue_subjects
    ADD CONSTRAINT legal_issue_subjects_decision_fkey FOREIGN KEY (scope_id, judicial_decision_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: legal_issue_subjects legal_issue_subjects_issue_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issue_subjects
    ADD CONSTRAINT legal_issue_subjects_issue_fkey FOREIGN KEY (scope_id, issue_id) REFERENCES corpus.legal_issues(scope_id, id) ON DELETE CASCADE;


--
-- Name: legal_issue_subjects legal_issue_subjects_proceeding_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issue_subjects
    ADD CONSTRAINT legal_issue_subjects_proceeding_fkey FOREIGN KEY (scope_id, proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id);


--
-- Name: legal_issue_subjects legal_issue_subjects_proposition_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issue_subjects
    ADD CONSTRAINT legal_issue_subjects_proposition_fkey FOREIGN KEY (scope_id, proposition_id) REFERENCES corpus.legal_propositions(scope_id, id);


--
-- Name: legal_issue_subjects legal_issue_subjects_relation_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issue_subjects
    ADD CONSTRAINT legal_issue_subjects_relation_fkey FOREIGN KEY (relation_scheme_code, relation_concept_id) REFERENCES corpus.legal_concepts(scheme_code, id);


--
-- Name: legal_issues legal_issues_scope_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_issues
    ADD CONSTRAINT legal_issues_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id);


--
-- Name: legal_matter_concept_edges legal_matter_concept_edges_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_matter_concept_edges
    ADD CONSTRAINT legal_matter_concept_edges_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.legal_matter_concepts(id) ON DELETE CASCADE;


--
-- Name: legal_matter_concept_edges legal_matter_concept_edges_narrower_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_matter_concept_edges
    ADD CONSTRAINT legal_matter_concept_edges_narrower_concept_id_fkey FOREIGN KEY (narrower_concept_id) REFERENCES corpus.legal_matter_concepts(id) ON DELETE CASCADE;


--
-- Name: legal_matter_concept_edges legal_matter_concept_edges_relation_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_matter_concept_edges
    ADD CONSTRAINT legal_matter_concept_edges_relation_type_concept_fkey FOREIGN KEY (relation_type) REFERENCES corpus.matter_taxonomy_relation_concepts(code);


--
-- Name: legal_matter_concepts legal_matter_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_matter_concepts
    ADD CONSTRAINT legal_matter_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_norm_assertions legal_norm_assertions_claim_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_assertions
    ADD CONSTRAINT legal_norm_assertions_claim_fkey FOREIGN KEY (scope_id, norm_claim_id) REFERENCES corpus.legal_norm_claims(scope_id, id);


--
-- Name: legal_norm_assertions legal_norm_assertions_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_assertions
    ADD CONSTRAINT legal_norm_assertions_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_norm_assertions legal_norm_assertions_same_scope_prop_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_assertions
    ADD CONSTRAINT legal_norm_assertions_same_scope_prop_fkey FOREIGN KEY (scope_id, proposition_id) REFERENCES corpus.legal_propositions(scope_id, id);


--
-- Name: legal_norm_claims legal_norm_claims_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_claims
    ADD CONSTRAINT legal_norm_claims_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_norm_claims legal_norm_claims_legal_matter_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_claims
    ADD CONSTRAINT legal_norm_claims_legal_matter_concept_id_fkey FOREIGN KEY (legal_matter_concept_id) REFERENCES corpus.legal_matter_concepts(id);


--
-- Name: legal_norm_claims legal_norm_claims_scope_id_proposition_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_claims
    ADD CONSTRAINT legal_norm_claims_scope_id_proposition_id_fkey FOREIGN KEY (scope_id, proposition_id) REFERENCES corpus.legal_propositions(scope_id, id);


--
-- Name: legal_norm_source_role_concepts legal_norm_source_role_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_source_role_concepts
    ADD CONSTRAINT legal_norm_source_role_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_norm_sources legal_norm_sources_document_provision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_sources
    ADD CONSTRAINT legal_norm_sources_document_provision_fkey FOREIGN KEY (source_document_id, source_document_provision_id) REFERENCES corpus.legal_document_provisions(document_id, id);


--
-- Name: legal_norm_sources legal_norm_sources_evidence_artifact_page_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_sources
    ADD CONSTRAINT legal_norm_sources_evidence_artifact_page_id_fkey FOREIGN KEY (evidence_artifact_page_id) REFERENCES corpus.artifact_pages(id);


--
-- Name: legal_norm_sources legal_norm_sources_norm_assertion_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_sources
    ADD CONSTRAINT legal_norm_sources_norm_assertion_id_fkey FOREIGN KEY (norm_assertion_id) REFERENCES corpus.legal_norm_assertions(id) ON DELETE CASCADE;


--
-- Name: legal_norm_sources legal_norm_sources_same_scope_assertion_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_sources
    ADD CONSTRAINT legal_norm_sources_same_scope_assertion_fkey FOREIGN KEY (assertion_scope_id, norm_assertion_id) REFERENCES corpus.legal_norm_assertions(scope_id, id);


--
-- Name: legal_norm_sources legal_norm_sources_same_scope_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_sources
    ADD CONSTRAINT legal_norm_sources_same_scope_document_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: legal_norm_sources legal_norm_sources_source_role_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_norm_sources
    ADD CONSTRAINT legal_norm_sources_source_role_concept_fkey FOREIGN KEY (source_role) REFERENCES corpus.legal_norm_source_role_concepts(code);


--
-- Name: legal_proceeding_status_concepts legal_proceeding_status_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proceeding_status_concepts
    ADD CONSTRAINT legal_proceeding_status_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_proceedings legal_proceedings_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proceedings
    ADD CONSTRAINT legal_proceedings_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_proceedings legal_proceedings_legal_matter_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proceedings
    ADD CONSTRAINT legal_proceedings_legal_matter_concept_id_fkey FOREIGN KEY (legal_matter_concept_id) REFERENCES corpus.legal_matter_concepts(id);


--
-- Name: legal_proceedings legal_proceedings_originating_court_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proceedings
    ADD CONSTRAINT legal_proceedings_originating_court_id_fkey FOREIGN KEY (originating_court_id) REFERENCES corpus.courts(id);


--
-- Name: legal_proceedings legal_proceedings_procedure_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proceedings
    ADD CONSTRAINT legal_proceedings_procedure_concept_id_fkey FOREIGN KEY (procedure_concept_id) REFERENCES corpus.procedure_concepts(id);


--
-- Name: legal_proceedings legal_proceedings_scope_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proceedings
    ADD CONSTRAINT legal_proceedings_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id);


--
-- Name: legal_proceedings legal_proceedings_status_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proceedings
    ADD CONSTRAINT legal_proceedings_status_concept_fkey FOREIGN KEY (status) REFERENCES corpus.legal_proceeding_status_concepts(code);


--
-- Name: legal_proposition_evidence legal_proposition_evidence_artifact_page_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_evidence
    ADD CONSTRAINT legal_proposition_evidence_artifact_page_id_fkey FOREIGN KEY (artifact_page_id) REFERENCES corpus.artifact_pages(id);


--
-- Name: legal_proposition_evidence legal_proposition_evidence_evidence_role_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_evidence
    ADD CONSTRAINT legal_proposition_evidence_evidence_role_concept_fkey FOREIGN KEY (evidence_role) REFERENCES corpus.legal_proposition_evidence_role_concepts(code);


--
-- Name: legal_proposition_evidence_role_concepts legal_proposition_evidence_role_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_evidence_role_concepts
    ADD CONSTRAINT legal_proposition_evidence_role_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_proposition_evidence legal_proposition_evidence_same_case_page_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_evidence
    ADD CONSTRAINT legal_proposition_evidence_same_case_page_fkey FOREIGN KEY (source_case_id, case_page_id) REFERENCES corpus.case_pages(case_id, id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: legal_proposition_evidence legal_proposition_evidence_same_scope_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_evidence
    ADD CONSTRAINT legal_proposition_evidence_same_scope_case_fkey FOREIGN KEY (scope_id, source_case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: legal_proposition_evidence legal_proposition_evidence_same_scope_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_evidence
    ADD CONSTRAINT legal_proposition_evidence_same_scope_document_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: legal_proposition_evidence legal_proposition_evidence_same_scope_proposition_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_evidence
    ADD CONSTRAINT legal_proposition_evidence_same_scope_proposition_fkey FOREIGN KEY (scope_id, proposition_id) REFERENCES corpus.legal_propositions(scope_id, id);


--
-- Name: legal_proposition_relation_concepts legal_proposition_relation_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_relation_concepts
    ADD CONSTRAINT legal_proposition_relation_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_proposition_relations legal_proposition_relations_from_scope_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_relations
    ADD CONSTRAINT legal_proposition_relations_from_scope_fkey FOREIGN KEY (scope_id, from_proposition_id) REFERENCES corpus.legal_propositions(scope_id, id);


--
-- Name: legal_proposition_relations legal_proposition_relations_relation_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_relations
    ADD CONSTRAINT legal_proposition_relations_relation_type_concept_fkey FOREIGN KEY (relation_type) REFERENCES corpus.legal_proposition_relation_concepts(code);


--
-- Name: legal_proposition_relations legal_proposition_relations_to_scope_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_relations
    ADD CONSTRAINT legal_proposition_relations_to_scope_fkey FOREIGN KEY (scope_id, to_proposition_id) REFERENCES corpus.legal_propositions(scope_id, id);


--
-- Name: legal_proposition_subjects legal_proposition_subjects_same_scope_decision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_subjects
    ADD CONSTRAINT legal_proposition_subjects_same_scope_decision_fkey FOREIGN KEY (scope_id, judicial_decision_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: legal_proposition_subjects legal_proposition_subjects_same_scope_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_subjects
    ADD CONSTRAINT legal_proposition_subjects_same_scope_document_fkey FOREIGN KEY (scope_id, legal_document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: legal_proposition_subjects legal_proposition_subjects_same_scope_proceeding_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_subjects
    ADD CONSTRAINT legal_proposition_subjects_same_scope_proceeding_fkey FOREIGN KEY (scope_id, proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id);


--
-- Name: legal_proposition_subjects legal_proposition_subjects_same_scope_prop_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_subjects
    ADD CONSTRAINT legal_proposition_subjects_same_scope_prop_fkey FOREIGN KEY (scope_id, proposition_id) REFERENCES corpus.legal_propositions(scope_id, id);


--
-- Name: legal_proposition_subjects legal_proposition_subjects_same_scope_provision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_proposition_subjects
    ADD CONSTRAINT legal_proposition_subjects_same_scope_provision_fkey FOREIGN KEY (scope_id, provision_id) REFERENCES corpus.legal_provisions(scope_id, id);


--
-- Name: legal_propositions legal_propositions_scope_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_propositions
    ADD CONSTRAINT legal_propositions_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id);


--
-- Name: legal_provision_lineage legal_provision_lineage_amendment_effect_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_lineage
    ADD CONSTRAINT legal_provision_lineage_amendment_effect_id_fkey FOREIGN KEY (amendment_effect_id) REFERENCES corpus.legal_amendment_effects(id) ON DELETE SET NULL;


--
-- Name: legal_provision_lineage legal_provision_lineage_from_scope_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_lineage
    ADD CONSTRAINT legal_provision_lineage_from_scope_fkey FOREIGN KEY (scope_id, from_provision_id) REFERENCES corpus.legal_provisions(scope_id, id);


--
-- Name: legal_provision_lineage legal_provision_lineage_lineage_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_lineage
    ADD CONSTRAINT legal_provision_lineage_lineage_type_concept_fkey FOREIGN KEY (lineage_type) REFERENCES corpus.legal_provision_lineage_type_concepts(code);


--
-- Name: legal_provision_lineage legal_provision_lineage_to_scope_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_lineage
    ADD CONSTRAINT legal_provision_lineage_to_scope_fkey FOREIGN KEY (scope_id, to_provision_id) REFERENCES corpus.legal_provisions(scope_id, id);


--
-- Name: legal_provision_lineage_type_concepts legal_provision_lineage_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_lineage_type_concepts
    ADD CONSTRAINT legal_provision_lineage_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_provision_version_knowledge legal_provision_version_knowledge_document_provision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_version_knowledge
    ADD CONSTRAINT legal_provision_version_knowledge_document_provision_fkey FOREIGN KEY (source_document_id, source_document_provision_id) REFERENCES corpus.legal_document_provisions(document_id, id);


--
-- Name: legal_provision_version_knowledge legal_provision_version_knowledge_same_scope_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_version_knowledge
    ADD CONSTRAINT legal_provision_version_knowledge_same_scope_document_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: legal_provision_version_knowledge legal_provision_version_knowledge_same_scope_version_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_version_knowledge
    ADD CONSTRAINT legal_provision_version_knowledge_same_scope_version_fkey FOREIGN KEY (scope_id, provision_version_id) REFERENCES corpus.legal_provision_versions(scope_id, id);


--
-- Name: legal_provision_version_sources legal_provision_version_sources_document_provision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_version_sources
    ADD CONSTRAINT legal_provision_version_sources_document_provision_fkey FOREIGN KEY (source_document_id, source_document_provision_id) REFERENCES corpus.legal_document_provisions(document_id, id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: legal_provision_version_sources legal_provision_version_sources_same_scope_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_version_sources
    ADD CONSTRAINT legal_provision_version_sources_same_scope_document_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: legal_provision_version_sources legal_provision_version_sources_same_scope_version_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_version_sources
    ADD CONSTRAINT legal_provision_version_sources_same_scope_version_fkey FOREIGN KEY (scope_id, instrument_version_id) REFERENCES corpus.legal_instrument_versions(scope_id, id);


--
-- Name: legal_provision_version_sources legal_provision_version_sources_source_role_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_version_sources
    ADD CONSTRAINT legal_provision_version_sources_source_role_concept_fkey FOREIGN KEY (source_role) REFERENCES corpus.provision_source_role_concepts(code);


--
-- Name: legal_provision_version_sources legal_provision_version_sources_version_match_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_version_sources
    ADD CONSTRAINT legal_provision_version_sources_version_match_fkey FOREIGN KEY (instrument_version_id, provision_version_id) REFERENCES corpus.legal_provision_versions(instrument_version_id, id);


--
-- Name: legal_provision_versions legal_provision_versions_provision_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_versions
    ADD CONSTRAINT legal_provision_versions_provision_type_concept_fkey FOREIGN KEY (provision_type) REFERENCES corpus.provision_type_concepts(code);


--
-- Name: legal_provision_versions legal_provision_versions_same_instrument_parent_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_versions
    ADD CONSTRAINT legal_provision_versions_same_instrument_parent_fkey FOREIGN KEY (instrument_id, parent_provision_id) REFERENCES corpus.legal_provisions(instrument_id, id);


--
-- Name: legal_provision_versions legal_provision_versions_same_instrument_provision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_versions
    ADD CONSTRAINT legal_provision_versions_same_instrument_provision_fkey FOREIGN KEY (instrument_id, provision_id) REFERENCES corpus.legal_provisions(instrument_id, id);


--
-- Name: legal_provision_versions legal_provision_versions_same_instrument_version_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_versions
    ADD CONSTRAINT legal_provision_versions_same_instrument_version_fkey FOREIGN KEY (instrument_id, instrument_version_id) REFERENCES corpus.legal_instrument_versions(instrument_id, id);


--
-- Name: legal_provision_versions legal_provision_versions_same_scope_provision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provision_versions
    ADD CONSTRAINT legal_provision_versions_same_scope_provision_fkey FOREIGN KEY (scope_id, provision_id) REFERENCES corpus.legal_provisions(scope_id, id);


--
-- Name: legal_provisions legal_provisions_same_scope_instrument_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_provisions
    ADD CONSTRAINT legal_provisions_same_scope_instrument_fkey FOREIGN KEY (scope_id, instrument_id) REFERENCES corpus.legal_instruments(scope_id, id);


--
-- Name: legal_relation_assertion_evidence legal_relation_assertion_evidence_artifact_page_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_assertion_evidence
    ADD CONSTRAINT legal_relation_assertion_evidence_artifact_page_id_fkey FOREIGN KEY (artifact_page_id) REFERENCES corpus.artifact_pages(id);


--
-- Name: legal_relation_assertion_evidence legal_relation_assertion_evidence_assertion_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_assertion_evidence
    ADD CONSTRAINT legal_relation_assertion_evidence_assertion_id_fkey FOREIGN KEY (assertion_id) REFERENCES corpus.legal_relation_assertions(id) ON DELETE CASCADE;


--
-- Name: legal_relation_assertion_evidence legal_relation_assertion_evidence_observation_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_assertion_evidence
    ADD CONSTRAINT legal_relation_assertion_evidence_observation_id_fkey FOREIGN KEY (observation_id) REFERENCES corpus.legal_relation_observations(id) ON DELETE SET NULL;


--
-- Name: legal_relation_assertions legal_relation_assertions_promoted_from_observation_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_assertions
    ADD CONSTRAINT legal_relation_assertions_promoted_from_observation_id_fkey FOREIGN KEY (promoted_from_observation_id) REFERENCES corpus.legal_relation_observations(id) ON DELETE SET NULL;


--
-- Name: legal_relation_assertions legal_relation_assertions_same_scope_identity_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_assertions
    ADD CONSTRAINT legal_relation_assertions_same_scope_identity_fkey FOREIGN KEY (scope_id, relation_identity_id) REFERENCES corpus.legal_relation_identities(scope_id, id) ON DELETE CASCADE;


--
-- Name: legal_relation_identities legal_relation_identities_relation_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_identities
    ADD CONSTRAINT legal_relation_identities_relation_type_concept_fkey FOREIGN KEY (relation_type) REFERENCES corpus.legal_relation_type_concepts(code);


--
-- Name: legal_relation_identities legal_relation_identities_source_provision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_identities
    ADD CONSTRAINT legal_relation_identities_source_provision_fkey FOREIGN KEY (source_document_id, source_provision_id) REFERENCES corpus.legal_document_provisions(document_id, id);


--
-- Name: legal_relation_identities legal_relation_identities_source_scope_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_identities
    ADD CONSTRAINT legal_relation_identities_source_scope_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id) ON DELETE CASCADE;


--
-- Name: legal_relation_identities legal_relation_identities_target_provision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_identities
    ADD CONSTRAINT legal_relation_identities_target_provision_fkey FOREIGN KEY (target_document_id, target_provision_id) REFERENCES corpus.legal_document_provisions(document_id, id);


--
-- Name: legal_relation_identities legal_relation_identities_target_scope_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_identities
    ADD CONSTRAINT legal_relation_identities_target_scope_fkey FOREIGN KEY (scope_id, target_document_id) REFERENCES corpus.legal_documents(scope_id, id) ON DELETE CASCADE;


--
-- Name: legal_relation_observation_type_concepts legal_relation_observation_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_observation_type_concepts
    ADD CONSTRAINT legal_relation_observation_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_relation_observations legal_relation_observations_evidence_artifact_page_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_observations
    ADD CONSTRAINT legal_relation_observations_evidence_artifact_page_id_fkey FOREIGN KEY (evidence_artifact_page_id) REFERENCES corpus.artifact_pages(id);


--
-- Name: legal_relation_observations legal_relation_observations_ingestion_job_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_observations
    ADD CONSTRAINT legal_relation_observations_ingestion_job_id_fkey FOREIGN KEY (ingestion_job_id) REFERENCES corpus.ingestion_jobs(id) ON DELETE SET NULL;


--
-- Name: legal_relation_observations legal_relation_observations_relation_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_observations
    ADD CONSTRAINT legal_relation_observations_relation_type_concept_fkey FOREIGN KEY (relation_type) REFERENCES corpus.legal_relation_observation_type_concepts(code);


--
-- Name: legal_relation_observations legal_relation_observations_source_document_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_observations
    ADD CONSTRAINT legal_relation_observations_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES corpus.legal_documents(id) ON DELETE CASCADE;


--
-- Name: legal_relation_observations legal_relation_observations_source_provision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_observations
    ADD CONSTRAINT legal_relation_observations_source_provision_fkey FOREIGN KEY (source_document_id, source_provision_id) REFERENCES corpus.legal_document_provisions(document_id, id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: legal_relation_observations legal_relation_observations_target_document_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_observations
    ADD CONSTRAINT legal_relation_observations_target_document_id_fkey FOREIGN KEY (target_document_id) REFERENCES corpus.legal_documents(id) ON DELETE CASCADE;


--
-- Name: legal_relation_observations legal_relation_observations_target_provision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_observations
    ADD CONSTRAINT legal_relation_observations_target_provision_fkey FOREIGN KEY (target_document_id, target_provision_id) REFERENCES corpus.legal_document_provisions(document_id, id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: legal_relation_type_concepts legal_relation_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_relation_type_concepts
    ADD CONSTRAINT legal_relation_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_tag_type_concepts legal_tag_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_tag_type_concepts
    ADD CONSTRAINT legal_tag_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_tags legal_tags_tag_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_tags
    ADD CONSTRAINT legal_tags_tag_type_concept_fkey FOREIGN KEY (tag_type) REFERENCES corpus.legal_tag_type_concepts(code);


--
-- Name: legal_treatment_assertions legal_treatment_assertions_evidence_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_treatment_assertions
    ADD CONSTRAINT legal_treatment_assertions_evidence_id_fkey FOREIGN KEY (evidence_id) REFERENCES corpus.legal_proposition_evidence(id);


--
-- Name: legal_treatment_assertions legal_treatment_assertions_same_scope_evidence_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_treatment_assertions
    ADD CONSTRAINT legal_treatment_assertions_same_scope_evidence_fkey FOREIGN KEY (scope_id, evidence_id) REFERENCES corpus.legal_proposition_evidence(scope_id, id);


--
-- Name: legal_treatment_assertions legal_treatment_assertions_same_scope_issue_v4_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_treatment_assertions
    ADD CONSTRAINT legal_treatment_assertions_same_scope_issue_v4_fkey FOREIGN KEY (scope_id, legal_issue_id) REFERENCES corpus.legal_issues(scope_id, id);


--
-- Name: legal_treatment_assertions legal_treatment_assertions_same_scope_source_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_treatment_assertions
    ADD CONSTRAINT legal_treatment_assertions_same_scope_source_case_fkey FOREIGN KEY (scope_id, source_case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: legal_treatment_assertions legal_treatment_assertions_same_scope_source_prop_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_treatment_assertions
    ADD CONSTRAINT legal_treatment_assertions_same_scope_source_prop_fkey FOREIGN KEY (scope_id, source_proposition_id) REFERENCES corpus.legal_propositions(scope_id, id);


--
-- Name: legal_treatment_assertions legal_treatment_assertions_same_scope_target_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_treatment_assertions
    ADD CONSTRAINT legal_treatment_assertions_same_scope_target_case_fkey FOREIGN KEY (scope_id, target_case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: legal_treatment_assertions legal_treatment_assertions_same_scope_target_prop_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_treatment_assertions
    ADD CONSTRAINT legal_treatment_assertions_same_scope_target_prop_fkey FOREIGN KEY (scope_id, target_proposition_id) REFERENCES corpus.legal_propositions(scope_id, id);


--
-- Name: legal_treatment_assertions legal_treatment_assertions_treatment_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_treatment_assertions
    ADD CONSTRAINT legal_treatment_assertions_treatment_type_concept_fkey FOREIGN KEY (treatment_type) REFERENCES corpus.legal_treatment_type_concepts(code);


--
-- Name: legal_treatment_type_concepts legal_treatment_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_treatment_type_concepts
    ADD CONSTRAINT legal_treatment_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: legal_version_authority_assessments legal_version_authority_assessments_same_scope_document_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_version_authority_assessments
    ADD CONSTRAINT legal_version_authority_assessments_same_scope_document_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id);


--
-- Name: legal_version_authority_assessments legal_version_authority_assessments_same_scope_version_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.legal_version_authority_assessments
    ADD CONSTRAINT legal_version_authority_assessments_same_scope_version_fkey FOREIGN KEY (scope_id, instrument_version_id) REFERENCES corpus.legal_instrument_versions(scope_id, id);


--
-- Name: matter_taxonomy_relation_concepts matter_taxonomy_relation_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.matter_taxonomy_relation_concepts
    ADD CONSTRAINT matter_taxonomy_relation_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: panel_role_concepts panel_role_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.panel_role_concepts
    ADD CONSTRAINT panel_role_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: participants participants_legal_entity_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.participants
    ADD CONSTRAINT participants_legal_entity_id_fkey FOREIGN KEY (legal_entity_id) REFERENCES corpus.legal_entities(id);


--
-- Name: participants participants_same_scope_legal_entity_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.participants
    ADD CONSTRAINT participants_same_scope_legal_entity_fkey FOREIGN KEY (scope_id, legal_entity_id) REFERENCES corpus.legal_entities(scope_id, id);


--
-- Name: participants participants_scope_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.participants
    ADD CONSTRAINT participants_scope_id_fkey FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id);


--
-- Name: party_representations party_representations_representation_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.party_representations
    ADD CONSTRAINT party_representations_representation_type_concept_fkey FOREIGN KEY (representation_type) REFERENCES corpus.representation_type_concepts(code);


--
-- Name: party_representations party_representations_same_scope_representative_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.party_representations
    ADD CONSTRAINT party_representations_same_scope_representative_fkey FOREIGN KEY (scope_id, representative_participant_id) REFERENCES corpus.participants(scope_id, id);


--
-- Name: party_representations party_representations_same_scope_role_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.party_representations
    ADD CONSTRAINT party_representations_same_scope_role_fkey FOREIGN KEY (scope_id, party_role_id) REFERENCES corpus.proceeding_party_roles(scope_id, id);


--
-- Name: party_side_concepts party_side_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.party_side_concepts
    ADD CONSTRAINT party_side_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: passages passages_case_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.passages
    ADD CONSTRAINT passages_case_id_fkey FOREIGN KEY (case_id) REFERENCES corpus.judicial_decisions(id) ON DELETE CASCADE;


--
-- Name: judicial_authority_assertions precedential_authority_assertions_court_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_authority_assertions
    ADD CONSTRAINT precedential_authority_assertions_court_id_fkey FOREIGN KEY (court_id) REFERENCES corpus.courts(id);


--
-- Name: judicial_authority_assertions precedential_authority_assertions_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_authority_assertions
    ADD CONSTRAINT precedential_authority_assertions_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: judicial_authority_assertions precedential_authority_assertions_legal_matter_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_authority_assertions
    ADD CONSTRAINT precedential_authority_assertions_legal_matter_concept_id_fkey FOREIGN KEY (legal_matter_concept_id) REFERENCES corpus.legal_matter_concepts(id);


--
-- Name: judicial_authority_assertions precedential_authority_assertions_same_scope_decision_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_authority_assertions
    ADD CONSTRAINT precedential_authority_assertions_same_scope_decision_fkey FOREIGN KEY (scope_id, decision_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: judicial_authority_assertions precedential_authority_assertions_same_scope_proposition_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_authority_assertions
    ADD CONSTRAINT precedential_authority_assertions_same_scope_proposition_fkey FOREIGN KEY (scope_id, proposition_id) REFERENCES corpus.legal_propositions(scope_id, id);


--
-- Name: judicial_authority_assertions precedential_authority_effect_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.judicial_authority_assertions
    ADD CONSTRAINT precedential_authority_effect_concept_fkey FOREIGN KEY (authority_effect_concept_id) REFERENCES corpus.judicial_authority_effect_concepts(id);


--
-- Name: procedural_decision_relation_observations procedural_decision_relation_observations_relation_type_concept; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_decision_relation_observations
    ADD CONSTRAINT procedural_decision_relation_observations_relation_type_concept FOREIGN KEY (relation_type) REFERENCES corpus.procedural_decision_relation_type_concepts(code);


--
-- Name: procedural_decision_relation_type_concepts procedural_decision_relation_type_concep_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_decision_relation_type_concepts
    ADD CONSTRAINT procedural_decision_relation_type_concep_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: procedural_decision_relations procedural_decision_relations_promoted_from_observation_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_decision_relations
    ADD CONSTRAINT procedural_decision_relations_promoted_from_observation_id_fkey FOREIGN KEY (promoted_from_observation_id) REFERENCES corpus.procedural_decision_relation_observations(id) ON DELETE SET NULL;


--
-- Name: procedural_decision_relations procedural_decision_relations_relation_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_decision_relations
    ADD CONSTRAINT procedural_decision_relations_relation_type_concept_fkey FOREIGN KEY (relation_type) REFERENCES corpus.procedural_decision_relation_type_concepts(code);


--
-- Name: procedural_decision_relations procedural_decision_relations_same_scope_source_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_decision_relations
    ADD CONSTRAINT procedural_decision_relations_same_scope_source_fkey FOREIGN KEY (scope_id, source_case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: procedural_decision_relations procedural_decision_relations_same_scope_target_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_decision_relations
    ADD CONSTRAINT procedural_decision_relations_same_scope_target_fkey FOREIGN KEY (scope_id, target_case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: procedural_event_type_concepts procedural_event_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_event_type_concepts
    ADD CONSTRAINT procedural_event_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: procedural_events procedural_events_event_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_events
    ADD CONSTRAINT procedural_events_event_type_concept_fkey FOREIGN KEY (event_type) REFERENCES corpus.procedural_event_type_concepts(code);


--
-- Name: procedural_events procedural_events_evidence_case_page_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_events
    ADD CONSTRAINT procedural_events_evidence_case_page_id_fkey FOREIGN KEY (evidence_case_page_id) REFERENCES corpus.case_pages(id);


--
-- Name: procedural_events procedural_events_same_scope_proceeding_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_events
    ADD CONSTRAINT procedural_events_same_scope_proceeding_fkey FOREIGN KEY (scope_id, proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id);


--
-- Name: procedural_events procedural_events_source_document_observation_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_events
    ADD CONSTRAINT procedural_events_source_document_observation_id_fkey FOREIGN KEY (source_document_observation_id) REFERENCES corpus.source_document_observations(id) ON DELETE SET NULL;


--
-- Name: procedural_decision_relation_observations procedural_relation_observations_same_case_evidence_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_decision_relation_observations
    ADD CONSTRAINT procedural_relation_observations_same_case_evidence_fkey FOREIGN KEY (source_case_id, evidence_case_page_id) REFERENCES corpus.case_pages(case_id, id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: procedural_decision_relation_observations procedural_relation_observations_same_scope_source_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_decision_relation_observations
    ADD CONSTRAINT procedural_relation_observations_same_scope_source_fkey FOREIGN KEY (scope_id, source_case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: procedural_decision_relation_observations procedural_relation_observations_same_scope_target_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_decision_relation_observations
    ADD CONSTRAINT procedural_relation_observations_same_scope_target_fkey FOREIGN KEY (scope_id, target_case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: procedural_role_concepts procedural_role_concepts_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_role_concepts
    ADD CONSTRAINT procedural_role_concepts_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.procedural_role_concepts(id);


--
-- Name: procedural_role_concepts procedural_role_concepts_default_party_side_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedural_role_concepts
    ADD CONSTRAINT procedural_role_concepts_default_party_side_concept_fkey FOREIGN KEY (default_party_side) REFERENCES corpus.party_side_concepts(code);


--
-- Name: procedure_concept_edges procedure_concept_edges_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedure_concept_edges
    ADD CONSTRAINT procedure_concept_edges_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.procedure_concepts(id) ON DELETE CASCADE;


--
-- Name: procedure_concept_edges procedure_concept_edges_narrower_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedure_concept_edges
    ADD CONSTRAINT procedure_concept_edges_narrower_concept_id_fkey FOREIGN KEY (narrower_concept_id) REFERENCES corpus.procedure_concepts(id) ON DELETE CASCADE;


--
-- Name: procedure_concept_edges procedure_concept_edges_relation_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedure_concept_edges
    ADD CONSTRAINT procedure_concept_edges_relation_type_concept_fkey FOREIGN KEY (relation_type) REFERENCES corpus.procedure_taxonomy_relation_concepts(code);


--
-- Name: procedure_concepts procedure_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedure_concepts
    ADD CONSTRAINT procedure_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: procedure_taxonomy_relation_concepts procedure_taxonomy_relation_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.procedure_taxonomy_relation_concepts
    ADD CONSTRAINT procedure_taxonomy_relation_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: proceeding_decision_relation_concepts proceeding_decision_relation_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_decision_relation_concepts
    ADD CONSTRAINT proceeding_decision_relation_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: proceeding_decisions proceeding_decisions_relation_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_decisions
    ADD CONSTRAINT proceeding_decisions_relation_type_concept_fkey FOREIGN KEY (relation_type) REFERENCES corpus.proceeding_decision_relation_concepts(code);


--
-- Name: proceeding_decisions proceeding_decisions_same_scope_case_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_decisions
    ADD CONSTRAINT proceeding_decisions_same_scope_case_fkey FOREIGN KEY (scope_id, case_id) REFERENCES corpus.judicial_decisions(scope_id, id);


--
-- Name: proceeding_decisions proceeding_decisions_same_scope_proceeding_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_decisions
    ADD CONSTRAINT proceeding_decisions_same_scope_proceeding_fkey FOREIGN KEY (scope_id, proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id);


--
-- Name: proceeding_identifier_type_concepts proceeding_identifier_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_identifier_type_concepts
    ADD CONSTRAINT proceeding_identifier_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: proceeding_identifiers proceeding_identifiers_court_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_identifiers
    ADD CONSTRAINT proceeding_identifiers_court_id_fkey FOREIGN KEY (court_id) REFERENCES corpus.courts(id);


--
-- Name: proceeding_identifiers proceeding_identifiers_identifier_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_identifiers
    ADD CONSTRAINT proceeding_identifiers_identifier_type_concept_fkey FOREIGN KEY (identifier_type) REFERENCES corpus.proceeding_identifier_type_concepts(code);


--
-- Name: proceeding_identifiers proceeding_identifiers_proceeding_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_identifiers
    ADD CONSTRAINT proceeding_identifiers_proceeding_id_fkey FOREIGN KEY (proceeding_id) REFERENCES corpus.legal_proceedings(id) ON DELETE CASCADE;


--
-- Name: proceeding_identifiers proceeding_identifiers_source_registry_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_identifiers
    ADD CONSTRAINT proceeding_identifiers_source_registry_id_fkey FOREIGN KEY (source_registry_id) REFERENCES corpus.source_registries(id);


--
-- Name: proceeding_participants proceeding_participants_party_side_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_participants
    ADD CONSTRAINT proceeding_participants_party_side_concept_fkey FOREIGN KEY (party_side) REFERENCES corpus.party_side_concepts(code);


--
-- Name: proceeding_participants proceeding_participants_same_scope_participant_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_participants
    ADD CONSTRAINT proceeding_participants_same_scope_participant_fkey FOREIGN KEY (scope_id, participant_id) REFERENCES corpus.participants(scope_id, id);


--
-- Name: proceeding_participants proceeding_participants_same_scope_proceeding_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_participants
    ADD CONSTRAINT proceeding_participants_same_scope_proceeding_fkey FOREIGN KEY (scope_id, proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id);


--
-- Name: proceeding_participants proceeding_participants_source_document_observation_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_participants
    ADD CONSTRAINT proceeding_participants_source_document_observation_id_fkey FOREIGN KEY (source_document_observation_id) REFERENCES corpus.source_document_observations(id) ON DELETE SET NULL;


--
-- Name: proceeding_party_roles proceeding_party_roles_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_party_roles
    ADD CONSTRAINT proceeding_party_roles_concept_fkey FOREIGN KEY (role_concept_id) REFERENCES corpus.procedural_role_concepts(id);


--
-- Name: proceeding_party_roles proceeding_party_roles_party_side_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_party_roles
    ADD CONSTRAINT proceeding_party_roles_party_side_concept_fkey FOREIGN KEY (party_side) REFERENCES corpus.party_side_concepts(code);


--
-- Name: proceeding_party_roles proceeding_party_roles_same_scope_participant_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_party_roles
    ADD CONSTRAINT proceeding_party_roles_same_scope_participant_fkey FOREIGN KEY (scope_id, participant_id) REFERENCES corpus.participants(scope_id, id);


--
-- Name: proceeding_party_roles proceeding_party_roles_same_scope_proceeding_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_party_roles
    ADD CONSTRAINT proceeding_party_roles_same_scope_proceeding_fkey FOREIGN KEY (scope_id, proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id);


--
-- Name: proceeding_relation_concepts proceeding_relation_concepts_broader_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_relation_concepts
    ADD CONSTRAINT proceeding_relation_concepts_broader_concept_id_fkey FOREIGN KEY (broader_concept_id) REFERENCES corpus.proceeding_relation_concepts(id);


--
-- Name: proceeding_relation_concepts proceeding_relation_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_relation_concepts
    ADD CONSTRAINT proceeding_relation_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: proceeding_relations proceeding_relations_relation_concept_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_relations
    ADD CONSTRAINT proceeding_relations_relation_concept_id_fkey FOREIGN KEY (relation_concept_id) REFERENCES corpus.proceeding_relation_concepts(id);


--
-- Name: proceeding_relations proceeding_relations_scope_id_source_proceeding_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_relations
    ADD CONSTRAINT proceeding_relations_scope_id_source_proceeding_id_fkey FOREIGN KEY (scope_id, source_proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id) ON DELETE CASCADE;


--
-- Name: proceeding_relations proceeding_relations_scope_id_target_proceeding_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.proceeding_relations
    ADD CONSTRAINT proceeding_relations_scope_id_target_proceeding_id_fkey FOREIGN KEY (scope_id, target_proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id) ON DELETE CASCADE;


--
-- Name: provision_source_role_concepts provision_source_role_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.provision_source_role_concepts
    ADD CONSTRAINT provision_source_role_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: provision_type_concepts provision_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.provision_type_concepts
    ADD CONSTRAINT provision_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: representation_type_concepts representation_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.representation_type_concepts
    ADD CONSTRAINT representation_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: source_artifact_locations source_artifact_locations_artifact_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_artifact_locations
    ADD CONSTRAINT source_artifact_locations_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES corpus.source_artifacts(id) ON DELETE CASCADE;


--
-- Name: source_artifact_locations source_artifact_locations_source_registry_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_artifact_locations
    ADD CONSTRAINT source_artifact_locations_source_registry_id_fkey FOREIGN KEY (source_registry_id) REFERENCES corpus.source_registries(id);


--
-- Name: source_artifacts source_artifacts_scope_fk; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_artifacts
    ADD CONSTRAINT source_artifacts_scope_fk FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id);


--
-- Name: source_artifacts source_artifacts_source_registry_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_artifacts
    ADD CONSTRAINT source_artifacts_source_registry_id_fkey FOREIGN KEY (source_registry_id) REFERENCES corpus.source_registries(id);


--
-- Name: source_collections source_collections_source_registry_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_collections
    ADD CONSTRAINT source_collections_source_registry_id_fkey FOREIGN KEY (source_registry_id) REFERENCES corpus.source_registries(id) ON DELETE CASCADE;


--
-- Name: source_document_artifacts source_document_artifacts_artifact_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_document_artifacts
    ADD CONSTRAINT source_document_artifacts_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES corpus.source_artifacts(id) ON DELETE CASCADE;


--
-- Name: source_document_artifacts source_document_artifacts_source_document_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_document_artifacts
    ADD CONSTRAINT source_document_artifacts_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES corpus.source_documents(id) ON DELETE CASCADE;


--
-- Name: source_document_observations source_document_observations_source_document_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_document_observations
    ADD CONSTRAINT source_document_observations_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES corpus.source_documents(id) ON DELETE CASCADE;


--
-- Name: source_documents source_documents_source_registry_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.source_documents
    ADD CONSTRAINT source_documents_source_registry_id_fkey FOREIGN KEY (source_registry_id) REFERENCES corpus.source_registries(id);


--
-- Name: territorial_unit_type_concepts territorial_unit_type_concepts_jurisdiction_code_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.territorial_unit_type_concepts
    ADD CONSTRAINT territorial_unit_type_concepts_jurisdiction_code_fkey FOREIGN KEY (jurisdiction_code) REFERENCES corpus.jurisdictions(code);


--
-- Name: territorial_units territorial_units_parent_id_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.territorial_units
    ADD CONSTRAINT territorial_units_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES corpus.territorial_units(id);


--
-- Name: territorial_units territorial_units_unit_type_concept_fkey; Type: FK CONSTRAINT; Schema: corpus; Owner: -
--

ALTER TABLE ONLY corpus.territorial_units
    ADD CONSTRAINT territorial_units_unit_type_concept_fkey FOREIGN KEY (unit_type) REFERENCES corpus.territorial_unit_type_concepts(code);


--
-- PostgreSQL database dump complete
--


