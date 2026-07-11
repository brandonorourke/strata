-- The uei→ticker mapping now lives in idiq_recipients (migration 0046). The
-- denormalized ticker column on usaspending_awards is redundant — awards roll up
-- to a ticker via recipient_uei → idiq_recipients (confirmed only). Drop it.
-- LOCAL-ONLY for now.

ALTER TABLE usaspending_awards DROP COLUMN ticker;
