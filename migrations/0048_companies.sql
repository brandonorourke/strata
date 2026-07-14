-- 0048_companies.sql
-- Canonical company lookup table. Supersedes the hardcoded DISPLAY_NAMES map in
-- apps/api/main.py and gives idiq_recipients a real FK to key mapping/confirm off of.
-- `aliases` exists because a single name isn't enough to match subsidiaries: e.g. SAIC
-- subs appear as both "SAIC …" (ticker) and "Science Applications International …".
-- Deliberately minimal: is_prime/is_public/kind deferred to the universe/competitive-field
-- work (#4/#5) — append them when a consumer needs them. This table is the intended
-- replacement for the company-directory role of canonical_entities (news table, to be
-- dropped later once the news pipeline is retired).

BEGIN;

CREATE TABLE companies (
    id         serial PRIMARY KEY,
    slug       text NOT NULL UNIQUE,
    name       text NOT NULL,
    ticker     text UNIQUE,                    -- nullable: privates have no ticker
    aliases    text[] NOT NULL DEFAULT '{}',   -- extra match names beyond `name`
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Seed: the 20 confirmed watchlist companies (original 10 + batch2 10).
-- `name` = official exchange-registered name (NASDAQ/NYSE, verified against SEC filings).
-- aliases left empty: the official name's brand tokens + the ticker cover subsidiary
-- matching; populate an alias only if a divergent operating brand shows up in review.
INSERT INTO companies (slug, name, ticker, aliases) VALUES
    ('viasat',              'Viasat, Inc.',                                  'VSAT', '{}'),
    ('aerovironment',       'AeroVironment, Inc.',                           'AVAV', '{}'),
    ('kratos',              'Kratos Defense & Security Solutions, Inc.',     'KTOS', '{}'),
    ('mercury-systems',     'Mercury Systems, Inc.',                         'MRCY', '{}'),
    ('comtech',             'Comtech Telecommunications Corp.',              'CMTL', '{}'),
    ('leonardo-drs',        'Leonardo DRS, Inc.',                            'DRS',  '{}'),
    ('intuitive-machines',  'Intuitive Machines, Inc.',                      'LUNR', '{}'),
    ('rocket-lab',          'Rocket Lab Corporation',                        'RKLB', '{}'),
    ('redwire',             'Redwire Corporation',                           'RDW',  '{}'),
    ('blacksky',            'BlackSky Technology Inc.',                      'BKSY', '{}'),
    ('booz-allen-hamilton', 'Booz Allen Hamilton Holding Corporation',       'BAH',  '{}'),
    ('bwx-technologies',    'BWX Technologies, Inc.',                        'BWXT', '{}'),
    ('caci',                'CACI International Inc',                         'CACI', '{}'),
    ('curtiss-wright',      'Curtiss-Wright Corporation',                    'CW',   '{}'),
    ('iridium',             'Iridium Communications Inc.',                   'IRDM', '{}'),
    ('leidos',              'Leidos Holdings, Inc.',                         'LDOS', '{}'),
    ('osi-systems',         'OSI Systems, Inc.',                             'OSIS', '{}'),
    ('planet-labs',         'Planet Labs PBC',                               'PL',   '{}'),
    ('parsons',             'Parsons Corporation',                           'PSN',  '{}'),
    ('saic',                'Science Applications International Corporation', 'SAIC', '{}');

-- FK from the UEI directory to its company.
ALTER TABLE idiq_recipients ADD COLUMN company_id integer REFERENCES companies(id);
CREATE INDEX idx_idiq_recipients_company_id ON idiq_recipients (company_id);

-- Backfill by ticker match (every current recipient carries a ticker).
UPDATE idiq_recipients ir
   SET company_id = c.id
  FROM companies c
 WHERE ir.ticker = c.ticker;

COMMIT;
