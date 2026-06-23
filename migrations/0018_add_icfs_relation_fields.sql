-- file_number on Pleadings & Comments is a structural join key back to icfs_filings
-- (same file_number format) — lets us know which company a pleading is about with
-- zero ambiguity, no LLM/name-matching needed.
ALTER TABLE icfs_pleadings_and_comments ADD COLUMN IF NOT EXISTS file_number TEXT;
CREATE INDEX IF NOT EXISTS ix_icfs_pleadings_file_number ON icfs_pleadings_and_comments (file_number);

-- url is a real, working citation link to FCC's EDOCS search for the notice.
-- da_number is the "Daily Action" number some notices key their url off of instead of number.
ALTER TABLE icfs_public_notices ADD COLUMN IF NOT EXISTS url TEXT;
ALTER TABLE icfs_public_notices ADD COLUMN IF NOT EXISTS da_number TEXT;
