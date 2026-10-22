-- Schema and seed for the mock Acme ERP. Applied by scripts/init_db.py (idempotent).
CREATE TABLE IF NOT EXISTS inventory (
  item        TEXT PRIMARY KEY,
  stock       INTEGER NOT NULL CHECK (stock >= 0),
  unit_price  REAL,              -- catalog price in USD, NULL when unknown
  category    TEXT
);

CREATE TABLE IF NOT EXISTS vendors (
  name         TEXT PRIMARY KEY,
  aliases      TEXT NOT NULL DEFAULT '[]',   -- JSON array
  address      TEXT,
  approved     INTEGER NOT NULL DEFAULT 1,
  bank_on_file INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS invoices (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_number TEXT,
  revision       TEXT,
  vendor         TEXT,
  total          REAL,
  currency       TEXT,
  source_file    TEXT,
  fingerprint    TEXT UNIQUE,
  status         TEXT,
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payments (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_number  TEXT NOT NULL,
  vendor          TEXT NOT NULL,
  amount          REAL NOT NULL,
  currency        TEXT NOT NULL DEFAULT 'USD',
  idempotency_key TEXT NOT NULL UNIQUE,
  status          TEXT NOT NULL,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS review_queue (     -- human-in-the-loop queue (PENDING_HUMAN)
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_number TEXT,
  vendor         TEXT,
  source_file    TEXT,
  fingerprint    TEXT NOT NULL UNIQUE,
  reason         TEXT,
  state_json     TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected
  reviewer_note  TEXT,
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  decided_at     TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  ts             TEXT NOT NULL DEFAULT (datetime('now')),
  invoice_number TEXT,
  agent          TEXT NOT NULL,
  event          TEXT NOT NULL,
  detail         TEXT            -- JSON
);

-- Minimum seed from the case brief. Prices are the prices that appear most often
-- across the sample invoices (WidgetA $250, WidgetB $500, GadgetX $750).
-- FakeItem has no trustworthy price, so it is NULL.
INSERT INTO inventory (item, stock, unit_price, category) VALUES
  ('WidgetA', 15, 250.00, 'widget'),
  ('WidgetB', 10, 500.00, 'widget'),
  ('GadgetX',  5, 750.00, 'gadget'),
  ('FakeItem', 0, NULL,   'unverified')
ON CONFLICT(item) DO UPDATE SET
  stock = excluded.stock, unit_price = excluded.unit_price, category = excluded.category;

-- Mock vendor master (an assumption, documented in the README). Vendors that appear on the
-- samples with no red flags are on file. Fraudster LLC, NoProd Industries and
-- Global Supply Chain Partners are deliberately not on file. QuickShip Distributers is
-- not on file under its new name; its former name FastShip Ltd. is.
INSERT INTO vendors (name, aliases, address, approved, bank_on_file) VALUES
  ('Widgets Inc.',                '[]', '100 Main St, Chicago, IL 60601', 1, 1),
  ('Gadgets Co.',                 '[]', NULL, 1, 1),
  ('Precision Parts Ltd.',        '[]', '742 Evergreen Terrace, Springfield, IL 62704', 1, 1),
  ('Acme Industrial Supplies',    '[]', NULL, 1, 1),
  ('MegaWidgets Corp',            '[]', NULL, 1, 1),
  ('Consolidated Materials Group','[]', NULL, 1, 1),
  ('Summit Manufacturing Co.',    '[]', NULL, 1, 1),
  ('FastShip Ltd.',               '[]', NULL, 1, 1),
  ('Atlas Industrial Supply',     '[]', '500 Commerce Blvd, Detroit, MI 48201', 1, 1),
  ('TechParts International',     '[]', NULL, 1, 1),
  ('Reliable Components Inc.',    '[]', NULL, 1, 1)
ON CONFLICT(name) DO UPDATE SET
  aliases = excluded.aliases, address = excluded.address,
  approved = excluded.approved, bank_on_file = excluded.bank_on_file;
