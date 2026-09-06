-- 0001_initial.sql
--
-- The first and, so far, only migration. It builds the whole system of record
-- from nothing. The runner that applies it is
-- scripts/migrate_db.py, and the helpers that write into it are agent/db.py.
--
-- data/schema.sql holds the same tables in one readable piece. That file is a
-- snapshot for a human to read, this one is what actually runs, and
-- tests/test_db.py compares the two so they cannot quietly drift apart.
--
-- Conventions used everywhere below.
--
--   ts        A timestamp as text, New York local time, written
--             "YYYY-MM-DD HH:MM:SS". The same shape the Google Sheet shows,
--             so a row can go straight from here into the sheet with no
--             conversion and no timezone argument.
--   date      Just the day part, "YYYY-MM-DD", New York.
--   booleans  Stored as 0 or 1 in an INTEGER, because SQLite has no boolean.
--             Every one of them has a CHECK so a stray 2 cannot get in.
--   json      Stored as text holding JSON. CHECK json_valid() means a
--             half-written blob is refused at the door rather than found
--             three weeks later by whoever is reading the month back.
--
-- Every id is "INTEGER PRIMARY KEY", which in SQLite is the row's own rowid,
-- so it costs nothing and counts up on its own.

-- ---------------------------------------------------------------- versioning

-- Which migration files have already been applied. The runner reads this,
-- skips anything named here, and adds a row for anything it runs. That is the
-- whole of the idempotency: run the runner ten times, the ninth and tenth do
-- nothing.
CREATE TABLE IF NOT EXISTS schema_version (
    filename    TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

-- -------------------------------------------------------------------- ticks

-- One row every time the loop wakes up, for every book, whether or not
-- anything happened. This is the attendance register: a tick that never ran
-- leaves a hole here, and a hole is what "missed ticks" on the Books tab
-- counts. Nothing else in the project can answer that question.
CREATE TABLE IF NOT EXISTS ticks (
    id           INTEGER PRIMARY KEY,
    ts           TEXT NOT NULL,
    book_id      TEXT,
    phase        TEXT,
    mode         TEXT,
    rules_commit TEXT,
    duration_ms  INTEGER,
    outcome      TEXT,
    notes        TEXT
);
CREATE INDEX IF NOT EXISTS ix_ticks_ts      ON ticks (ts);
CREATE INDEX IF NOT EXISTS ix_ticks_book_ts ON ticks (book_id, ts);

-- -------------------------------------------------------------------- scans

-- One row per run of a scanner. source says which scanner: the momentum
-- scanner, the insider sweep, the congress sweep. stage_counts is how many
-- names survived each filter, which is the thing to read when a scan comes
-- back empty and nobody knows which filter ate everything.
CREATE TABLE IF NOT EXISTS scans (
    id               INTEGER PRIMARY KEY,
    ts               TEXT NOT NULL,
    source           TEXT,
    scan_codes       TEXT,
    stage_counts     TEXT CHECK (stage_counts IS NULL OR json_valid(stage_counts)),
    diagnostics      TEXT CHECK (diagnostics  IS NULL OR json_valid(diagnostics)),
    market_data_type TEXT
);
CREATE INDEX IF NOT EXISTS ix_scans_ts     ON scans (ts);
CREATE INDEX IF NOT EXISTS ix_scans_source ON scans (source, ts);

-- The names one scan actually produced, one row each, in the order the
-- scanner ranked them. traded is filled in later, once it is known whether
-- anything was ever bought off the back of this line, so a month later the
-- question "did the shortlist find anything we used" has an answer.
CREATE TABLE IF NOT EXISTS shortlist_entries (
    id            INTEGER PRIMARY KEY,
    scan_id       INTEGER NOT NULL REFERENCES scans (id) ON DELETE CASCADE,
    rank          INTEGER,
    symbol        TEXT NOT NULL,
    direction     TEXT,
    score         REAL,
    rel_volume    REAL,
    dollar_volume REAL,
    tags          TEXT CHECK (tags    IS NULL OR json_valid(tags)),
    reasons       TEXT CHECK (reasons IS NULL OR json_valid(reasons)),
    traded        INTEGER NOT NULL DEFAULT 0 CHECK (traded IN (0, 1))
);
CREATE INDEX IF NOT EXISTS ix_shortlist_scan   ON shortlist_entries (scan_id);
CREATE INDEX IF NOT EXISTS ix_shortlist_symbol ON shortlist_entries (symbol);

-- ---------------------------------------------------------------- decisions

-- Every judgement call, including every "do nothing". That is the strategy's
-- own rule: each choice gets a written reason, so a month later the review
-- can read why a name was skipped, not only why one was bought.
--
-- shape is how the call was made: model, rules, or hybrid. It is the column
-- that separates book B, which asks nobody, from books A and E, which ask a
-- model. prompt_hash and packet_hash fingerprint what the model was shown, so
-- a prompt edited halfway through the month is visible here rather than
-- quietly changing the experiment underneath everyone.
--
-- rejected covers the calls that were made and then refused, by a guardrail
-- or by the parser. reject_reason says which.
CREATE TABLE IF NOT EXISTS decisions (
    id            INTEGER PRIMARY KEY,
    ts            TEXT NOT NULL,
    book_id       TEXT,
    shape         TEXT,
    model         TEXT,
    prompt_hash   TEXT,
    packet_hash   TEXT,
    rules_commit  TEXT,
    symbol        TEXT,
    action        TEXT,
    side          TEXT,
    entry         REAL,
    stop          REAL,
    target        REAL,
    qty           INTEGER,
    confidence    REAL,
    rationale     TEXT,
    latency_ms    INTEGER,
    tokens_in     INTEGER,
    tokens_out    INTEGER,
    cost_usd      REAL,
    rejected      INTEGER NOT NULL DEFAULT 0 CHECK (rejected IN (0, 1)),
    reject_reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_decisions_ts      ON decisions (ts);
CREATE INDEX IF NOT EXISTS ix_decisions_book_ts ON decisions (book_id, ts);
CREATE INDEX IF NOT EXISTS ix_decisions_symbol  ON decisions (symbol, ts);
CREATE INDEX IF NOT EXISTS ix_decisions_date    ON decisions (substr(ts, 1, 10));

-- ------------------------------------------------------------------- orders

-- One row per order sent, or that would have been sent in dry run. order_ref
-- is the book's tag, BOOK_A to BOOK_E, which is what makes a fill traceable
-- back to the book that asked for it once five books share one account.
--
-- parent_order_id and oca_group are how a bracket hangs together: the entry
-- is the parent, the stop and the target are its children and share an OCA
-- group so that filling one cancels the other. purpose says which of the
-- three a row is.
--
-- broker_order_id is deliberately not unique. IBKR order ids restart, and a
-- unique index on them would refuse a perfectly good order weeks later.
CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY,
    ts              TEXT NOT NULL,
    book_id         TEXT,
    order_ref       TEXT,
    broker_order_id TEXT,
    parent_order_id TEXT,
    oca_group       TEXT,
    symbol          TEXT,
    side            TEXT,
    qty             INTEGER,
    order_type      TEXT,
    limit_price     REAL,
    stop_price      REAL,
    tif             TEXT,
    purpose         TEXT,
    status          TEXT,
    decision_id     INTEGER REFERENCES decisions (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_orders_ts       ON orders (ts);
CREATE INDEX IF NOT EXISTS ix_orders_book_ts  ON orders (book_id, ts);
CREATE INDEX IF NOT EXISTS ix_orders_symbol   ON orders (symbol, ts);
CREATE INDEX IF NOT EXISTS ix_orders_broker   ON orders (broker_order_id);
CREATE INDEX IF NOT EXISTS ix_orders_decision ON orders (decision_id);

-- -------------------------------------------------------------------- fills

-- One row per execution. exec_id is IBKR's own id for the execution and is
-- unique, which is what stops the same fill being counted twice when the
-- reconciler reads the day's executions again after a restart.
--
-- decision_price is what the decision was made at. slippage_usd and
-- slippage_bps are worked out from it at write time, by the same arithmetic
-- the Google Sheet uses in columns U and V, so the two can never disagree.
-- All three stay NULL when the decision price is not known, which is the
-- honest answer rather than a zero that would drag the month's average down.
CREATE TABLE IF NOT EXISTS fills (
    id             INTEGER PRIMARY KEY,
    ts             TEXT NOT NULL,
    order_id       INTEGER REFERENCES orders (id) ON DELETE SET NULL,
    exec_id        TEXT UNIQUE,
    symbol         TEXT,
    side           TEXT,
    qty            INTEGER,
    price          REAL,
    commission     REAL,
    decision_price REAL,
    slippage_usd   REAL,
    slippage_bps   REAL
);
CREATE INDEX IF NOT EXISTS ix_fills_ts     ON fills (ts);
CREATE INDEX IF NOT EXISTS ix_fills_symbol ON fills (symbol, ts);
CREATE INDEX IF NOT EXISTS ix_fills_order  ON fills (order_id);
CREATE INDEX IF NOT EXISTS ix_fills_date   ON fills (substr(ts, 1, 10));

-- -------------------------------------------------------- position snapshots

-- What each book was holding at one moment. Written every tick and at the
-- close, so the day can be replayed afterwards rather than guessed at from
-- the fills. stop and target are the levels resting at the broker, recorded
-- here so that a stop that quietly went missing is visible in the history.
CREATE TABLE IF NOT EXISTS position_snapshots (
    id             INTEGER PRIMARY KEY,
    ts             TEXT NOT NULL,
    book_id        TEXT,
    symbol         TEXT,
    qty            INTEGER,
    avg_cost       REAL,
    market_price   REAL,
    market_value   REAL,
    unrealized_pnl REAL,
    stop           REAL,
    target         REAL
);
CREATE INDEX IF NOT EXISTS ix_snapshots_ts      ON position_snapshots (ts);
CREATE INDEX IF NOT EXISTS ix_snapshots_book_ts ON position_snapshots (book_id, ts);
CREATE INDEX IF NOT EXISTS ix_snapshots_symbol  ON position_snapshots (symbol, ts);

-- ------------------------------------------------------------------- alerts

-- Every alert raised, with where it was sent. Keeping them here means the
-- morning question "did anything shout overnight" is a query rather than a
-- scroll through a log file, and it means an alert that failed to send is
-- still on the record.
CREATE TABLE IF NOT EXISTS alerts (
    id       INTEGER PRIMARY KEY,
    ts       TEXT NOT NULL,
    level    TEXT,
    title    TEXT,
    body     TEXT,
    channels TEXT CHECK (channels IS NULL OR json_valid(channels))
);
CREATE INDEX IF NOT EXISTS ix_alerts_ts    ON alerts (ts);
CREATE INDEX IF NOT EXISTS ix_alerts_level ON alerts (level, ts);
CREATE INDEX IF NOT EXISTS ix_alerts_date  ON alerts (substr(ts, 1, 10));

-- ---------------------------------------------------------------- pre-flight

-- One row per pre-flight check per day. The pair (date, check_name) is
-- unique, so running the pre-flight twice in a morning updates the row rather
-- than adding a second opinion. verdict is the check's own word for what it
-- decided, and detail is whatever it wants to keep.
CREATE TABLE IF NOT EXISTS preflight_results (
    id         INTEGER PRIMARY KEY,
    date       TEXT NOT NULL,
    check_name TEXT NOT NULL,
    ts         TEXT,
    passed     INTEGER CHECK (passed IS NULL OR passed IN (0, 1)),
    detail     TEXT CHECK (detail IS NULL OR json_valid(detail)),
    verdict    TEXT,
    UNIQUE (date, check_name)
);
CREATE INDEX IF NOT EXISTS ix_preflight_date ON preflight_results (date);

-- ----------------------------------------------------------------- watchdog

-- One row every time the watchdog looks at something. Unlike the pre-flight
-- these are kept in full rather than one per day, because the watchdog runs
-- all day and the interesting question is usually "when did this start
-- failing", which needs every check, not the latest one.
CREATE TABLE IF NOT EXISTS watchdog_checks (
    id           INTEGER PRIMARY KEY,
    ts           TEXT NOT NULL,
    check_name   TEXT NOT NULL,
    ok           INTEGER CHECK (ok IS NULL OR ok IN (0, 1)),
    detail       TEXT,
    action_taken TEXT
);
CREATE INDEX IF NOT EXISTS ix_watchdog_ts   ON watchdog_checks (ts);
CREATE INDEX IF NOT EXISTS ix_watchdog_name ON watchdog_checks (check_name, ts);
CREATE INDEX IF NOT EXISTS ix_watchdog_date ON watchdog_checks (substr(ts, 1, 10));

-- ------------------------------------------------------------- day trade PDT

-- The pattern day trader count, one row per book per day. count_5d is how
-- many day trades that book has made in the rolling five business days.
-- would_have_blocked counts the trades the rule stopped, which is the figure
-- that says whether the PDT limit is actually costing this experiment
-- anything. regime records which rule set was in force that day, because the
-- answer changes with the account's margin regime.
CREATE TABLE IF NOT EXISTS day_trade_counters (
    id                  INTEGER PRIMARY KEY,
    date                TEXT NOT NULL,
    book_id             TEXT NOT NULL,
    count_5d            INTEGER,
    would_have_blocked  INTEGER NOT NULL DEFAULT 0,
    regime              TEXT,
    ts                  TEXT,
    UNIQUE (date, book_id)
);
CREATE INDEX IF NOT EXISTS ix_pdt_date ON day_trade_counters (date);
CREATE INDEX IF NOT EXISTS ix_pdt_book ON day_trade_counters (book_id, date);

-- ------------------------------------------------------------ margin regime

-- Which margin regime the account was in on a given day, and what made us
-- think so. One row per account per day. evidence holds the raw figures the
-- decision was based on, so a regime that flips unexpectedly can be argued
-- with rather than just believed.
CREATE TABLE IF NOT EXISTS regime_flags (
    id         INTEGER PRIMARY KEY,
    date       TEXT NOT NULL,
    account_id TEXT NOT NULL,
    regime     TEXT,
    evidence   TEXT CHECK (evidence IS NULL OR json_valid(evidence)),
    ts         TEXT,
    UNIQUE (date, account_id)
);
CREATE INDEX IF NOT EXISTS ix_regime_date ON regime_flags (date);

-- ------------------------------------------------------- daily book summary

-- One row per book per trading day: the scoreboard. This is the table the
-- Books tab and the Daily tab are both built from, and the one to read at the
-- end of the month.
--
-- It exists because the Google Sheet cannot work these out. The Daily tab
-- follows the one paper account that all five books share, so it has no way
-- to give each book its own equity curve, its own drawdown, or a count of the
-- ticks it missed. Those three are exactly the blank columns on the Books tab
-- today. Here they are just columns.
CREATE TABLE IF NOT EXISTS daily_book_summaries (
    id               INTEGER PRIMARY KEY,
    date             TEXT NOT NULL,
    book_id          TEXT NOT NULL,
    start_equity     REAL,
    end_equity       REAL,
    pnl_usd          REAL,
    pnl_pct          REAL,
    spy_close        REAL,
    trades           INTEGER,
    commissions      REAL,
    model_cost_usd   REAL,
    rule_triggers    INTEGER,
    missed_ticks     INTEGER,
    max_drawdown_pct REAL,
    notes            TEXT,
    updated_at       TEXT,
    UNIQUE (date, book_id)
);
CREATE INDEX IF NOT EXISTS ix_summaries_date ON daily_book_summaries (date);
CREATE INDEX IF NOT EXISTS ix_summaries_book ON daily_book_summaries (book_id, date);
