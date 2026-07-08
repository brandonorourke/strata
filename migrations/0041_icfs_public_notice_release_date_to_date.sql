-- public_notice_release_date is a date-only field (ServiceNow glide_date): all 1,501
-- non-null values are at midnight UTC, zero carry a time. Same footgun as
-- action_taken_date (migration 0040) — stored as timestamptz, so SQL `::date` shifts
-- it a day in the ET session while Python `.date()` was fine. Make it a real DATE,
-- converting each stored instant in UTC (the correct calendar date) so nothing shifts.

ALTER TABLE icfs_public_notices
    ALTER COLUMN public_notice_release_date TYPE date
    USING (public_notice_release_date AT TIME ZONE 'UTC')::date;
