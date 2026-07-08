-- action_taken_date is a date-only field. Evidence: all 11,761 non-null values are at
-- exactly midnight UTC, zero carry a time (ServiceNow returns it as a glide_date,
-- "YYYY-MM-DD"). Storing it as `timestamptz` invited off-by-one bugs: Postgres casts
-- a timestamptz using the SESSION timezone (America/New_York here), so
-- `action_taken_date::date` shifts a midnight-UTC value back a day. Python `.date()`
-- (asyncpg returns UTC) was correct, SQL `::date` was not — a confusing split that
-- caused three off-by-one confusions in one day.
--
-- Fix: make the column a real DATE. The USING clause reads each stored instant in UTC
-- (the correct FCC calendar date) before casting, so no value shifts. After this, tz
-- is out of the picture entirely — `::date`, comparisons, and `.date()` all agree.
--
-- submission_date is intentionally left as timestamptz: 13,144/13,145 carry real times.
-- Both places action_taken_date lives (the filing + its action history) are date-only.

ALTER TABLE icfs_filings
    ALTER COLUMN action_taken_date TYPE date
    USING (action_taken_date AT TIME ZONE 'UTC')::date;

ALTER TABLE icfs_filing_action_history
    ALTER COLUMN action_taken_date TYPE date
    USING (action_taken_date AT TIME ZONE 'UTC')::date;
