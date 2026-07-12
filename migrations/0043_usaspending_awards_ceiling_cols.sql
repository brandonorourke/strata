-- Add ceiling / obligation / order-expiry columns to usaspending_awards.
--   ceiling          — base_and_all_options from the award DETAIL endpoint (the true
--                      contract ceiling; NOT available in spending_by_award). Populated
--                      by a later per-IDV detail-fetch pass — NULL until that's built.
--   total_obligation — detail-endpoint total_obligation (same later pass). NULL for now.
--   last_order_date  — IDV "Last Date to Order": when the vehicle stops accepting orders
--                      (latent-capacity expiry). Comes from the IDV search field itself,
--                      so it IS populated on pull.
-- LOCAL-ONLY for now (matches 0042) — do NOT run on prod yet.

ALTER TABLE usaspending_awards
    ADD COLUMN ceiling          NUMERIC,
    ADD COLUMN total_obligation NUMERIC,
    ADD COLUMN last_order_date  DATE;
