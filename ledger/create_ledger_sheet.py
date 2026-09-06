"""Create the Google Sheet ledger for the one month IBKR paper trading test.

Run this to build the spreadsheet from scratch:

    source /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv/bin/activate
    python /Users/mtalib/workspace_repos/personal_repo/agentic_trading/ledger/create_ledger_sheet.py

It creates a brand new spreadsheet every time it runs, then writes the new id
and URL into /Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/ledger.json.
The old sheet is left alone, so nothing is destroyed, but config/ledger.json will
point at the newest one.

Auth: the OAuth token at
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/token_personal_drive.json
(a symlink to the drive.file token for mtalib.personal@gmail.com). The sheet is
created under that personal account, so no sharing step is needed.
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

_AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from paths import config_dir, project_root, secrets_dir  # noqa: E402

TOKEN_PATH = str(secrets_dir() / "token_personal_drive.json")
PROJECT_DIR = str(project_root())
LEDGER_JSON_PATH = str(config_dir() / "ledger.json")

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE_API = "https://www.googleapis.com/drive/v3/files"
DRIVE_SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
)

SPREADSHEET_TITLE = "Agentic Trading Paper Ledger (IBKR)"
SHARE_WITH_EMAIL = "mtalib.personal@gmail.com"

# Timestamps in this ledger are New York time, so the whole spreadsheet is set
# to that timezone. Otherwise Sheets would do date maths in another timezone.
SPREADSHEET_TIMEZONE = "America/New_York"

# Styling stays plain and monochrome, two colours only.
# Light grey (off white grey) #F4F5F3, used as the header row fill.
HEADER_FILL = {"red": 244 / 255, "green": 245 / 255, "blue": 243 / 255}
# Near black #191919, used for the header row text.
HEADER_TEXT = {"red": 25 / 255, "green": 25 / 255, "blue": 25 / 255}

# Number format patterns, kept in one place so every tab matches.
FMT_DATE = ("DATE", "yyyy-mm-dd")
FMT_DATETIME = ("DATE_TIME", "yyyy-mm-dd hh:mm:ss")
FMT_MONEY = ("CURRENCY", "$#,##0.00")
# Model calls cost fractions of a cent, so their own money format keeps four
# decimal places. $#,##0.00 would round a real cost down to $0.00.
FMT_MONEY_FINE = ("CURRENCY", "$#,##0.0000")
FMT_PERCENT = ("NUMBER", "0.00%")
FMT_WHOLE = ("NUMBER", "#,##0")
FMT_DECIMAL = ("NUMBER", "0.00")

# How many Daily rows get the live formulas filled in ahead of time. A month of
# US trading is about 21 days, so 40 leaves plenty of room.
DAILY_FORMULA_ROWS = 40

# How many Trades rows get the two slippage formulas filled in ahead of time.
# 999 rows means row 2 to row 1000, which is the whole Trades tab below its
# header. The formulas have to be sitting there before a fill arrives, because
# the agent writes values into a row rather than writing formulas of its own.
TRADES_FORMULA_ROWS = 999

# The five books the eval runs side by side inside the one paper account.
# Book id, strategy, model. Every trade and every decision is stamped with the
# book that made it, so the tabs can be sliced per book at the end of the month.
BOOKS = [
    ("A", "Opening momentum", "Claude Fable 5.1"),
    ("B", "Opening momentum", "none"),
    ("C", "Insider buying", "Claude Fable 5.1"),
    ("D", "Congress trades", "Claude Fable 5.1"),
    ("E", "Opening momentum", "GPT-6 Astra"),
]

# Each book is scored as if it started with its own $100,000.
BOOK_CAPITAL = 100000

TRADES_HEADERS = [
    "Timestamp (ET)",
    "Date",
    "Symbol",
    "Side",
    "Qty",
    "Fill Price",
    "Notional",
    "Commission",
    "Order Type",
    "Order Id",
    "Strategy Signal",
    "Reason",
    "Realised P&L",
    "Notes",
    "Book",
    "Model",
    "Model Cost USD",
    "Prompt Hash",
    # The four slippage columns are appended on the end on purpose. Every
    # formula elsewhere in this sheet points at Trades columns A to R, so
    # adding these anywhere but the end would move a column out from under
    # them. Python fills in the first two, the sheet works out the last two.
    "Decision Price",
    "Decision Time (ET)",
    "Slippage $",
    "Slippage bps",
]

DAILY_HEADERS = [
    "Date",
    "Starting Equity",
    "Ending Equity",
    "Daily P&L $",
    "Daily P&L %",
    "Cumulative P&L %",
    "SPY Close",
    "SPY Daily %",
    "SPY Cumulative %",
    "Alpha vs SPY (cum)",
    "Trades Count",
    "Rules Triggered",
    "Notes",
    "Model Cost USD",
]

SUMMARY_HEADERS = ["Metric", "Value", "What it means"]
RULES_LOG_HEADERS = [
    "Timestamp",
    "Rule",
    "Detail",
    "Action Taken",
    "Book",
    "Model",
    "Model Cost USD",
    "Prompt Hash",
]
CONFIG_HEADERS = ["Setting", "Value", "Notes"]
BOOKS_HEADERS = [
    "Book",
    "Strategy",
    "Model",
    "Capital",
    "Equity",
    "Return %",
    "SPY %",
    "Alpha",
    "Max DD",
    "Trades",
    "Commissions",
    "Model Cost USD",
    "Rule Triggers",
    "Missed Ticks",
    "Slippage $",
    "Avg Slippage bps",
]

# Column widths in pixels, one entry per column, in order.
TRADES_WIDTHS = [150, 95, 80, 70, 70, 95, 110, 100, 100, 110, 150, 240, 110, 240,
                 60, 220, 125, 130, 120, 150, 100, 110]
DAILY_WIDTHS = [95, 120, 120, 110, 100, 135, 95, 105, 135, 145, 100, 170, 240, 125]
SUMMARY_WIDTHS = [190, 130, 380]
RULES_LOG_WIDTHS = [150, 170, 340, 260, 60, 220, 125, 130]
CONFIG_WIDTHS = [170, 150, 260]
BOOKS_WIDTHS = [60, 165, 150, 100, 110, 90, 90, 90, 90, 80, 115, 125, 110, 110,
                110, 130]

SPY_CLOSE_NOTE = (
    "SPY Close is typed in by the agent each day from its own price source. "
    "It is deliberately not a GOOGLEFINANCE formula, so the agent controls "
    "where the number comes from and the benchmark cannot silently change."
)

BOOKS_NOTE = (
    "Blank cells here are the numbers the sheet cannot work out on its own yet. "
    "Equity, Max DD and Missed Ticks have to be written in by the agent, because "
    "the other tabs hold one running account, not five separate equity curves. "
    "Return % and Alpha are live formulas and fill themselves in the moment "
    "Equity has a number in it."
)

CONFIG_NOTE = (
    "Mo to fill. The money and strategy settings are not decided yet, so every "
    "value below is left blank on purpose."
)

# Sheet layout: title, header row, column count, row count, column widths.
TABS = [
    {
        "id": 0,
        "title": "Trades",
        "headers": TRADES_HEADERS,
        # 1000 rows so the slippage formulas in columns U and V have a home all
        # the way down. The tab is one row per fill, so this is a month of
        # trading many times over.
        "rows": 1 + TRADES_FORMULA_ROWS,
        "widths": TRADES_WIDTHS,
    },
    {
        "id": 1,
        "title": "Daily",
        "headers": DAILY_HEADERS,
        "rows": 200,
        "widths": DAILY_WIDTHS,
    },
    {
        "id": 2,
        "title": "Summary",
        "headers": SUMMARY_HEADERS,
        "rows": 30,
        "widths": SUMMARY_WIDTHS,
    },
    {
        "id": 3,
        "title": "Rules Log",
        "headers": RULES_LOG_HEADERS,
        "rows": 300,
        "widths": RULES_LOG_WIDTHS,
    },
    {
        "id": 4,
        "title": "Config",
        "headers": CONFIG_HEADERS,
        "rows": 30,
        "widths": CONFIG_WIDTHS,
    },
    {
        "id": 5,
        "title": "Books",
        "headers": BOOKS_HEADERS,
        "rows": 20,
        "widths": BOOKS_WIDTHS,
    },
]


def load_session():
    """Open an authorised HTTP session using the existing Sheets token.

    The token file is only ever read, never written back, so a refreshed access
    token lives in memory for this run and the file on disk stays untouched.
    """
    with open(TOKEN_PATH) as handle:
        info = json.load(handle)
    creds = Credentials.from_authorized_user_info(info)
    return AuthorizedSession(creds), info.get("scopes", [])


def api(session, method, url, payload=None, attempts=5):
    """Call the Google API, retrying the errors that are worth retrying.

    Google answers with 429 when we are going too fast and 5xx when its own
    service hiccups. Both clear up on their own, so we wait a little longer
    each time rather than giving up. Anything else is a real problem and is
    raised straight away with the response body attached.
    """
    delay = 1.0
    for attempt in range(1, attempts + 1):
        response = session.request(method, url, json=payload)
        if response.ok:
            return response.json() if response.text else {}
        retryable = response.status_code == 429 or response.status_code >= 500
        if retryable and attempt < attempts:
            print(
                f"  Google returned {response.status_code}, retrying in "
                f"{delay:.0f}s (attempt {attempt} of {attempts})"
            )
            time.sleep(delay)
            delay *= 2
            continue
        raise RuntimeError(
            "Google API call failed.\n"
            "  {0} {1}\n  status {2}\n  body {3}".format(
                method, url, response.status_code, response.text[:1200]
            )
        )


def daily_formula_rows():
    """Build the live formula cells for the Daily tab, row by row.

    Every formula is guarded, so a row that is not filled in yet shows nothing
    instead of an error, and nothing is ever divided by zero or by a blank.

    Column letters on the Daily tab:
      A Date, B Starting Equity, C Ending Equity, D Daily P&L $,
      E Daily P&L %, F Cumulative P&L %, G SPY Close, H SPY Daily %,
      I SPY Cumulative %, J Alpha vs SPY (cum), K Trades Count
    """
    rows = []
    for row in range(2, 2 + DAILY_FORMULA_ROWS):
        prev = row - 1
        # Daily P&L in dollars: end of day equity minus start of day equity.
        d = f'=IF(OR($B{row}="",$C{row}=""),"",$C{row}-$B{row})'
        # Daily P&L as a percent of the equity the day started with.
        e = f'=IF(OR($B{row}="",$C{row}="",$B{row}=0),"",($C{row}-$B{row})/$B{row})'
        # Cumulative P&L percent, measured against the very first starting equity.
        f = f'=IF(OR($C{row}="",$B$2="",$B$2=0),"",$C{row}/$B$2-1)'
        # SPY move since yesterday. On the first row there is no yesterday, so
        # the ISNUMBER check keeps it blank rather than dividing by the header.
        h = (
            f'=IF(OR($G{row}="",NOT(ISNUMBER($G{prev})),$G{prev}=0),"",'
            f"$G{row}/$G{prev}-1)"
        )
        # SPY move since the first day of the test.
        i = f'=IF(OR($G{row}="",$G$2="",$G$2=0),"",$G{row}/$G$2-1)'
        # Alpha: how far ahead of SPY the account is, cumulatively.
        j = f'=IF(OR($F{row}="",$I{row}=""),"",$F{row}-$I{row})'
        # How many fills the Trades tab holds for this date.
        k = f'=IF($A{row}="","",COUNTIF(Trades!$B$2:$B,$A{row}))'
        rows.append([d, e, f, "", h, i, j, k])
    return rows


def trades_formula_rows():
    """Build the two slippage cells for the Trades tab, row by row.

    Slippage is the gap between the price the decision was made at and the
    price the order actually filled at. In plain words:

      BUY   Fill Price minus Decision Price, times the quantity. Paying more
            than we decided at is a positive number, and positive is bad.
      SELL  Decision Price minus Fill Price, times the quantity. Selling for
            less than we decided at is also positive, and also bad.

    So a positive figure in either column always means money lost to the gap.

    The cells stay blank whenever Decision Price, Fill Price or Qty is missing,
    which is most of the time: the row is pre-filled long before the fill that
    will use it arrives. ABS is used on Qty so that a quantity written as a
    negative number for a sell cannot silently flip the sign. The Side column
    is what carries the direction in this ledger, not the sign of Qty.

    Column letters on the Trades tab:
      D Side, E Qty, F Fill Price, S Decision Price, U Slippage $,
      V Slippage bps.
    """
    rows = []
    for row in range(2, 2 + TRADES_FORMULA_ROWS):
        # Slippage in dollars, direction decided by the Side column.
        u = (f'=IF(OR(NOT(ISNUMBER($S{row})),NOT(ISNUMBER($F{row})),'
             f'NOT(ISNUMBER($E{row}))),"",'
             f'IF(UPPER($D{row})="BUY",($F{row}-$S{row})*ABS($E{row}),'
             f'IF(UPPER($D{row})="SELL",($S{row}-$F{row})*ABS($E{row}),"")))')
        # The same gap as a share of what the trade was worth at the decision
        # price, in basis points, so a $5 slip on a $1,000 trade and a $50 slip
        # on a $10,000 trade read as the same 50.
        v = (f'=IF(OR(NOT(ISNUMBER($U{row})),NOT(ISNUMBER($S{row})),'
             f'NOT(ISNUMBER($E{row})),$S{row}=0,$E{row}=0),"",'
             f'$U{row}/($S{row}*ABS($E{row}))*10000)')
        rows.append([u, v])
    return rows


def summary_rows():
    """The Summary tab, one metric per row, all of it read off Daily and Trades.

    Trades columns used: A Timestamp, M Realised P&L, U Slippage $,
    V Slippage bps.
    Daily columns used: A Date, B Starting Equity, C Ending Equity,
    E Daily P&L %, G SPY Close.

    Last value lookups use INDEX with COUNT, which assumes Daily is filled in
    from the top with no gaps. That is how the agent appends rows.
    """
    return [
        [
            "Start Date",
            '=IF(COUNT(Daily!$A$2:$A)=0,"",MIN(Daily!$A$2:$A))',
            "First trading day recorded on the Daily tab.",
        ],
        [
            "End Date",
            '=IF(COUNT(Daily!$A$2:$A)=0,"",MAX(Daily!$A$2:$A))',
            "Last trading day recorded on the Daily tab.",
        ],
        [
            "Starting Equity",
            '=IF(COUNT(Daily!$B$2:$B)=0,"",INDEX(Daily!$B$2:$B,1))',
            "Account value at the start of day one.",
        ],
        [
            "Current Equity",
            '=IF(COUNT(Daily!$C$2:$C)=0,"",'
            "INDEX(Daily!$C$2:$C,COUNT(Daily!$C$2:$C)))",
            "Account value at the end of the most recent day.",
        ],
        [
            "Total Return %",
            '=IF(OR($B$4="",$B$5="",$B$4=0),"",$B$5/$B$4-1)',
            "Current equity against starting equity.",
        ],
        [
            "SPY Return %",
            '=IF(COUNT(Daily!$G$2:$G)=0,"",'
            "INDEX(Daily!$G$2:$G,COUNT(Daily!$G$2:$G))/INDEX(Daily!$G$2:$G,1)-1)",
            "What simply holding SPY would have returned over the same days.",
        ],
        [
            "Alpha",
            '=IF(OR($B$6="",$B$7=""),"",$B$6-$B$7)',
            "Total return minus the SPY return. Positive means we beat SPY.",
        ],
        [
            "Max Drawdown %",
            '=IFERROR(LET(e,FILTER(Daily!$C$2:$C,Daily!$C$2:$C<>""),'
            "m,SCAN(0,e,LAMBDA(a,x,MAX(a,x))),MIN(MAP(e,m,LAMBDA(x,y,x/y-1)))),\"\")",
            "Worst drop from a peak in account value. Shown as a negative "
            "number, so nearer zero is better.",
        ],
        [
            "Win Rate",
            '=IF(COUNT(Trades!$M$2:$M)=0,"",'
            'COUNTIF(Trades!$M$2:$M,">0")/COUNT(Trades!$M$2:$M))',
            "Share of closed trades that made money. Only fills with a "
            "realised P&L figure count.",
        ],
        [
            "Avg Win",
            '=IFERROR(AVERAGEIF(Trades!$M$2:$M,">0"),"")',
            "Average dollars made on a winning trade.",
        ],
        [
            "Avg Loss",
            '=IFERROR(AVERAGEIF(Trades!$M$2:$M,"<0"),"")',
            "Average dollars lost on a losing trade, as a negative number.",
        ],
        [
            "Number of Trades",
            "=COUNTA(Trades!$A$2:$A)",
            "Every fill logged on the Trades tab.",
        ],
        [
            "Sharpe (daily, annualised)",
            '=IFERROR(IF(COUNT(Daily!$E$2:$E)<2,"",'
            "AVERAGE(Daily!$E$2:$E)/STDEV(Daily!$E$2:$E)*SQRT(252)),\"\")",
            "Return per unit of wobble, scaled to a year. Needs at least two "
            "days before it shows anything.",
        ],
        # These two go on the end, and must stay on the end. Total Return %,
        # SPY Return % and Alpha are read by cell address ($B$4 to $B$7 here,
        # and Summary!$B$7 over on the Books tab), so a row inserted above them
        # would point every one of those formulas at the wrong number.
        [
            "Avg Slippage bps",
            '=IF(COUNT(Trades!$V$2:$V)=0,"",AVERAGE(Trades!$V$2:$V))',
            "Average gap between the price a trade was decided at and the "
            "price it filled at, in basis points. Positive is worse for us.",
        ],
        [
            "Slippage $ total",
            '=IF(COUNT(Trades!$U$2:$U)=0,"",SUM(Trades!$U$2:$U))',
            "What that gap has cost in dollars over the whole month.",
        ],
    ]


def books_rows():
    """One row per book, mostly live formulas that slice the other tabs by book.

    Every fill on the Trades tab and every line on the Rules Log now carries the
    book that made it, so the counting can be left to the spreadsheet. The
    columns those formulas read:

      Trades     H Commission, O Book, Q Model Cost USD,
                 U Slippage $, V Slippage bps
      Rules Log  B Rule, E Book, G Model Cost USD

    Books tab column letters:
      A Book, B Strategy, C Model, D Capital, E Equity, F Return %, G SPY %,
      H Alpha, I Max DD, J Trades, K Commissions, L Model Cost USD,
      M Rule Triggers, N Missed Ticks, O Slippage $, P Avg Slippage bps.

    Equity, Max DD and Missed Ticks are left blank on purpose. The Daily tab
    tracks the one paper account, not a separate equity curve per book, so
    there is nothing in this sheet to work them out from yet. Return % and
    Alpha are written as live formulas anyway, so they start working the moment
    an Equity figure is filled in.
    """
    rows = []
    for offset, (book_id, strategy, model) in enumerate(BOOKS):
        row = 2 + offset
        # Return against the book's own starting capital.
        f = f'=IF(OR($E{row}="",$D{row}="",$D{row}=0),"",$E{row}/$D{row}-1)'
        # SPY is the same benchmark for all five books, so it is read once off
        # the Summary tab rather than worked out again per book.
        g = '=IF(Summary!$B$7="","",Summary!$B$7)'
        # Alpha: this book\'s return minus what SPY did over the same days.
        h = f'=IF(OR($F{row}="",$G{row}=""),"",$F{row}-$G{row})'
        # Fills logged against this book.
        j = f"=COUNTIFS(Trades!$O$2:$O,$A{row})"
        # Commission this book paid.
        k = f"=SUMIFS(Trades!$H$2:$H,Trades!$O$2:$O,$A{row})"
        # What the model calls cost. Cost can land on either tab, so both are
        # added: a decision row on the Rules Log, a fill row on Trades.
        cost = (f"=SUMIFS(Trades!$Q$2:$Q,Trades!$O$2:$O,$A{row})"
                f"+SUMIFS('Rules Log'!$G$2:$G,'Rules Log'!$E$2:$E,$A{row})")
        # Guardrails that actually fired. The Rules Log also holds the "decision"
        # rows, which are judgements rather than a limit biting, so they are left
        # out of this count.
        m = (f"=COUNTIFS('Rules Log'!$E$2:$E,$A{row},"
             f"'Rules Log'!$B$2:$B,\"<>decision\")")
        # What this book has lost to slippage. Trades column O is the Book
        # column and Trades columns U and V are the two slippage columns, so
        # this reads "sum this book's slippage" and then "average this book's
        # slippage in basis points". AVERAGEIFS is wrapped in IFERROR because
        # a book with no fills yet has nothing to average.
        o = f"=SUMIFS(Trades!$U$2:$U,Trades!$O$2:$O,$A{row})"
        p = f'=IFERROR(AVERAGEIFS(Trades!$V$2:$V,Trades!$O$2:$O,$A{row}),"")'
        rows.append([book_id, strategy, model, BOOK_CAPITAL, "", f, g, h, "",
                     j, k, cost, m, "", o, p])
    return rows


def config_rows():
    """Config keys, deliberately left with no values yet."""
    return [
        ["Starting equity", "", "Mo to fill"],
        ["Max position %", "", "Mo to fill"],
        ["Daily loss cap %", "", "Mo to fill"],
        ["Universe", "", "Mo to fill"],
        ["Cadence", "", "Mo to fill"],
    ]


def create_spreadsheet(session):
    """Create the spreadsheet with all five tabs and a frozen header row."""
    body = {
        "properties": {
            "title": SPREADSHEET_TITLE,
            "locale": "en_US",
            "timeZone": SPREADSHEET_TIMEZONE,
        },
        "sheets": [
            {
                "properties": {
                    "sheetId": tab["id"],
                    "title": tab["title"],
                    "index": index,
                    "gridProperties": {
                        "rowCount": tab["rows"],
                        "columnCount": len(tab["headers"]),
                        "frozenRowCount": 1,
                    },
                }
            }
            for index, tab in enumerate(TABS)
        ],
    }
    return api(session, "POST", SHEETS_API, body)


def write_values(session, spreadsheet_id):
    """Put the headers, the formulas, and the Summary and Config content in place."""
    data = [
        {"range": "Trades!A1", "values": [TRADES_HEADERS]},
        {"range": "Trades!U2", "values": trades_formula_rows()},
        {"range": "Daily!A1", "values": [DAILY_HEADERS]},
        {"range": "Daily!D2", "values": daily_formula_rows()},
        {"range": "Summary!A1", "values": [SUMMARY_HEADERS]},
        {"range": "Summary!A2", "values": summary_rows()},
        {"range": "Rules Log!A1", "values": [RULES_LOG_HEADERS]},
        {"range": "Config!A1", "values": [CONFIG_HEADERS]},
        {"range": "Config!A2", "values": config_rows()},
        {"range": "Books!A1", "values": [BOOKS_HEADERS]},
        {"range": "Books!A2", "values": books_rows()},
    ]
    api(
        session,
        "POST",
        f"{SHEETS_API}/{spreadsheet_id}/values:batchUpdate",
        {"valueInputOption": "USER_ENTERED", "data": data},
    )


def header_style_request(sheet_id, column_count):
    """Bold, light grey filled, near black, clipped header row."""
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": column_count,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": HEADER_FILL,
                    "wrapStrategy": "CLIP",
                    "verticalAlignment": "MIDDLE",
                    "textFormat": {"bold": True, "foregroundColor": HEADER_TEXT},
                }
            },
            "fields": (
                "userEnteredFormat(backgroundColor,wrapStrategy,"
                "verticalAlignment,textFormat)"
            ),
        }
    }


def column_width_requests(sheet_id, widths):
    """One request per column, so each column gets its own sensible width."""
    return [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": index,
                    "endIndex": index + 1,
                },
                "properties": {"pixelSize": width},
                "fields": "pixelSize",
            }
        }
        for index, width in enumerate(widths)
    ]


def number_format_request(sheet_id, first_col, last_col, fmt, first_row=1, last_row=None):
    """Apply one number format to a block of data cells (header row excluded)."""
    number_type, pattern = fmt
    grid = {
        "sheetId": sheet_id,
        "startRowIndex": first_row,
        "startColumnIndex": first_col,
        "endColumnIndex": last_col + 1,
    }
    if last_row is not None:
        grid["endRowIndex"] = last_row
    return {
        "repeatCell": {
            "range": grid,
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": number_type, "pattern": pattern}
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    }


def note_request(sheet_id, row, column, note):
    """Attach a hover note to a single cell."""
    return {
        "updateCells": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row,
                "endRowIndex": row + 1,
                "startColumnIndex": column,
                "endColumnIndex": column + 1,
            },
            "rows": [{"values": [{"note": note}]}],
            "fields": "note",
        }
    }


def format_spreadsheet(session, spreadsheet_id):
    """Everything visual: header style, widths, number formats, cell notes."""
    requests = []

    for tab in TABS:
        requests.append(header_style_request(tab["id"], len(tab["headers"])))
        requests.extend(column_width_requests(tab["id"], tab["widths"]))

    # Trades tab number formats.
    requests += [
        number_format_request(0, 0, 0, FMT_DATETIME),  # Timestamp (ET)
        number_format_request(0, 1, 1, FMT_DATE),  # Date
        number_format_request(0, 4, 4, FMT_WHOLE),  # Qty
        number_format_request(0, 5, 7, FMT_MONEY),  # Fill Price, Notional, Commission
        number_format_request(0, 12, 12, FMT_MONEY),  # Realised P&L
        number_format_request(0, 16, 16, FMT_MONEY_FINE),  # Model Cost USD
        number_format_request(0, 18, 18, FMT_MONEY),  # Decision Price
        number_format_request(0, 19, 19, FMT_DATETIME),  # Decision Time (ET)
        number_format_request(0, 20, 20, FMT_MONEY),  # Slippage $
        number_format_request(0, 21, 21, FMT_DECIMAL),  # Slippage bps
    ]

    # Daily tab number formats.
    requests += [
        number_format_request(1, 0, 0, FMT_DATE),  # Date
        number_format_request(1, 1, 3, FMT_MONEY),  # Starting, Ending, Daily P&L $
        number_format_request(1, 4, 5, FMT_PERCENT),  # Daily P&L %, Cumulative P&L %
        number_format_request(1, 6, 6, FMT_MONEY),  # SPY Close
        number_format_request(1, 7, 9, FMT_PERCENT),  # SPY daily, SPY cum, Alpha
        number_format_request(1, 10, 10, FMT_WHOLE),  # Trades Count
        number_format_request(1, 13, 13, FMT_MONEY_FINE),  # Model Cost USD
    ]

    # Summary values are one per row, so each cell gets its own format.
    summary_formats = {
        1: FMT_DATE,  # Start Date
        2: FMT_DATE,  # End Date
        3: FMT_MONEY,  # Starting Equity
        4: FMT_MONEY,  # Current Equity
        5: FMT_PERCENT,  # Total Return %
        6: FMT_PERCENT,  # SPY Return %
        7: FMT_PERCENT,  # Alpha
        8: FMT_PERCENT,  # Max Drawdown %
        9: FMT_PERCENT,  # Win Rate
        10: FMT_MONEY,  # Avg Win
        11: FMT_MONEY,  # Avg Loss
        12: FMT_WHOLE,  # Number of Trades
        13: FMT_DECIMAL,  # Sharpe
        14: FMT_DECIMAL,  # Avg Slippage bps
        15: FMT_MONEY,  # Slippage $ total
    }
    for row_index, fmt in summary_formats.items():
        requests.append(
            number_format_request(2, 1, 1, fmt, first_row=row_index, last_row=row_index + 1)
        )

    # Rules Log timestamps and model cost.
    requests.append(number_format_request(3, 0, 0, FMT_DATETIME))
    requests.append(number_format_request(3, 6, 6, FMT_MONEY_FINE))  # Model Cost USD

    # Books tab number formats.
    requests += [
        number_format_request(5, 3, 4, FMT_MONEY),  # Capital, Equity
        number_format_request(5, 5, 8, FMT_PERCENT),  # Return %, SPY %, Alpha, Max DD
        number_format_request(5, 9, 9, FMT_WHOLE),  # Trades
        number_format_request(5, 10, 10, FMT_MONEY),  # Commissions
        number_format_request(5, 11, 11, FMT_MONEY_FINE),  # Model Cost USD
        number_format_request(5, 12, 13, FMT_WHOLE),  # Rule Triggers, Missed Ticks
        number_format_request(5, 14, 14, FMT_MONEY),  # Slippage $
        number_format_request(5, 15, 15, FMT_DECIMAL),  # Avg Slippage bps
    ]

    # Notes that explain the three things a reader would otherwise guess wrong.
    requests.append(note_request(1, 0, 6, SPY_CLOSE_NOTE))  # Daily, SPY Close header
    requests.append(note_request(4, 0, 0, CONFIG_NOTE))  # Config, first header cell
    requests.append(note_request(5, 0, 4, BOOKS_NOTE))  # Books, Equity header

    api(
        session,
        "POST",
        f"{SHEETS_API}/{spreadsheet_id}:batchUpdate",
        {"requests": requests},
    )


def try_share(session, spreadsheet_id, scopes):
    """Give mtalib.personal@gmail.com edit access, if the token allows it.

    Sharing is a Drive API job. The Sheets only token cannot do it, so this
    says so plainly instead of failing in a confusing way.
    """
    if not any(scope in DRIVE_SCOPES for scope in scopes):
        return (
            False,
            "Not shared. The token at {0} holds the Sheets scope only, and "
            "sharing needs a Drive scoped token.".format(TOKEN_PATH),
        )
    url = f"{DRIVE_API}/{spreadsheet_id}/permissions?sendNotificationEmail=false"
    try:
        api(
            session,
            "POST",
            url,
            {"role": "writer", "type": "user", "emailAddress": SHARE_WITH_EMAIL},
        )
    except RuntimeError as error:
        return False, f"Sharing failed: {error}"
    return True, f"Shared with {SHARE_WITH_EMAIL} as editor."


def write_ledger_json(spreadsheet_id, url):
    """Record where the sheet lives, so the rest of the project can find it."""
    os.makedirs(os.path.dirname(LEDGER_JSON_PATH), exist_ok=True)
    with open(LEDGER_JSON_PATH, "w") as handle:
        json.dump({"spreadsheet_id": spreadsheet_id, "url": url}, handle, indent=2)
        handle.write("\n")


def verify(session, spreadsheet_id):
    """Read the tab names and the first row of each tab back out of the sheet."""
    meta = api(
        session,
        "GET",
        f"{SHEETS_API}/{spreadsheet_id}?fields=sheets.properties(title,gridProperties)",
    )
    titles = [sheet["properties"]["title"] for sheet in meta["sheets"]]
    ranges = "&".join(
        "ranges=" + quote(f"'{title}'!1:1", safe="") for title in titles
    )
    values = api(
        session,
        "GET",
        f"{SHEETS_API}/{spreadsheet_id}/values:batchGet?{ranges}",
    )
    headers = [entry.get("values", [[]])[0] for entry in values["valueRanges"]]
    frozen = [
        sheet["properties"]["gridProperties"].get("frozenRowCount", 0)
        for sheet in meta["sheets"]
    ]
    return titles, headers, frozen


def main():
    session, scopes = load_session()

    created = create_spreadsheet(session)
    spreadsheet_id = created["spreadsheetId"]
    # Build the URL from the id rather than using the one the API hands back,
    # which carries an account specific "ouid" parameter on the end.
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"

    write_values(session, spreadsheet_id)
    format_spreadsheet(session, spreadsheet_id)
    write_ledger_json(spreadsheet_id, url)
    _shared, share_message = try_share(session, spreadsheet_id, scopes)

    titles, headers, frozen = verify(session, spreadsheet_id)

    print(f"Created: {SPREADSHEET_TITLE}")
    print(f"Id:      {spreadsheet_id}")
    print(f"URL:     {url}")
    print(f"Saved:   {LEDGER_JSON_PATH}")
    print(f"Sharing: {share_message}")
    print("Tabs read back from the API:")
    for title, header, frozen_rows in zip(titles, headers, frozen):
        print(f"  {title} (frozen rows: {frozen_rows})")
        print(f"    {header}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
