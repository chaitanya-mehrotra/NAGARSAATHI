CREATE OR REPLACE FUNCTION check_admitted_report_link() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target uuid; targets uuid[];
BEGIN
    IF TG_TABLE_NAME = 'issues' THEN
        SELECT array_agg(report_id) INTO targets FROM issue_report_links WHERE issue_id = NEW.id;
    ELSIF TG_TABLE_NAME = 'reports' THEN
        IF TG_OP = 'INSERT' THEN targets := ARRAY[NEW.id];
        ELSIF TG_OP = 'DELETE' THEN targets := ARRAY[OLD.id];
        ELSE targets := ARRAY[NEW.id, OLD.id]; END IF;
    ELSE
        IF TG_OP = 'INSERT' THEN targets := ARRAY[NEW.report_id];
        ELSIF TG_OP = 'DELETE' THEN targets := ARRAY[OLD.report_id];
        ELSE targets := ARRAY[NEW.report_id, OLD.report_id]; END IF;
    END IF;
    FOREACH target IN ARRAY COALESCE(targets, ARRAY[]::uuid[]) LOOP
        IF EXISTS (SELECT 1 FROM reports WHERE id = target AND state = 'admitted')
           AND NOT EXISTS (SELECT 1 FROM issue_report_links WHERE report_id = target) THEN
            RAISE EXCEPTION 'admitted report requires an issue link' USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1 FROM issue_report_links l JOIN reports r ON r.id = l.report_id
            JOIN issues i ON i.id = l.issue_id
            WHERE l.report_id = target AND l.active AND
                (r.state <> 'admitted' OR r.canonical_category IS DISTINCT FROM i.category_code)
        ) THEN
            RAISE EXCEPTION 'active issue link requires an admitted compatible report'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER issues_link_integrity AFTER UPDATE ON issues
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_admitted_report_link();

CREATE FUNCTION check_boundary_ownership() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version text; owner uuid;
BEGIN
    SELECT boundary_version INTO version FROM pilots WHERE id = NEW.pilot_id;
    IF NEW.boundary_version IS DISTINCT FROM version THEN
        RAISE EXCEPTION 'boundary version does not match pilot' USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'issues' THEN
        SELECT id INTO owner FROM areas
        WHERE pilot_id = NEW.pilot_id AND boundary_version = version AND effective_to IS NULL
          AND ST_Covers(geom, NEW.geom::geometry)
        ORDER BY code COLLATE "C" LIMIT 1;
        IF owner IS NULL OR owner IS DISTINCT FROM NEW.area_id THEN
            RAISE EXCEPTION 'issue must use the deterministic owning area' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER areas_boundary_version BEFORE INSERT OR UPDATE ON areas
    FOR EACH ROW EXECUTE FUNCTION check_boundary_ownership();
CREATE TRIGGER issues_boundary_ownership
    BEFORE INSERT OR UPDATE OF pilot_id, area_id, geom, boundary_version ON issues
    FOR EACH ROW EXECUTE FUNCTION check_boundary_ownership();
