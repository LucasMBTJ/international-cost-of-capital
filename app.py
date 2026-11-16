"""
International Cost of Capital  -  Streamlit app (Python 3.12)

Compares a project's cost of equity, cost of debt and WACC in USD and in the
currency of a selected country.

    Levered beta        bL  = bU * [1 + (1 - t) * D/E],      D/E = d / (1 - d)
    USD cost of equity  Re  = Rf_US + bL * ERP                (CAPM)
    Foreign cost of eq. 1 + Re* = (1 + Re) * (1 + Rf*) / (1 + Rf_US)
    USD cost of debt    Rd  = Rf_US + BBB spread (USD)
    Foreign cost of debt (override OFF, parity):
                        1 + Rd* = (1 + Rd) * (1 + Rf*) / (1 + Rf_US)
                        (override ON):  Rd* = Rf* + foreign BBB spread
    WACC                = (1 - d) * Re + d * Rd * (1 - t)     (same d, t, ERP in both currencies)

Data
    Industry unlevered betas : Damodaran, betas.xls (sheet "Industry Averages", column "Unlevered beta")
    BBB spread (USD)         : Damodaran, ratings.html (large non-financial service firms, Baa2/BBB)
    Corporate tax rates      : OECD Corporate Tax Statistics, combined statutory CIT rate (SDMX feed)
    10-year govt yields      : Trading Economics, /bonds
Every source falls back to a dated built-in snapshot if the live fetch fails.
"""
from __future__ import annotations

import datetime as dt
import io
import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from bs4 import BeautifulSoup

# =============================================================================
# Sources
# =============================================================================
BETAS_URLS = [
    "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls",
    "https://pages.stern.nyu.edu/adamodar/pc/datasets/betas.xls",
]
RATINGS_URLS = [
    "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html",
    "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html",
]
OECD_REPORT_URL = (
    "https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/"
    "statutory-corporate-income-tax-rates_440f9286.html#chapter-d1e2342-08e74a33fb"
)
OECD_SDMX_URL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,/all"
    "?startPeriod={start}&dimensionAtObservation=AllDimensions&format=csvfilewithlabels"
)
TE_URLS = [
    "https://tradingeconomics.com/bonds",
    "https://tradingeconomics.com/bonds?partial=markets",
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 30
CACHE_TTL = 6 * 3600

DEFAULT_INDUSTRY = "Software (System & Application)"
DEFAULT_COUNTRY = "united-states"
DEFAULT_ERP = 6.5
DEFAULT_DEBT = 30

# =============================================================================
# Built-in snapshots (used only when a live fetch fails)
# =============================================================================
SNAPSHOT_BETAS_DATE = "January 2026 (Damodaran update)"
SNAPSHOT_BETAS = """Industry|Unlevered beta
Advertising|0.93
Aerospace/Defense|0.85
Air Transport|0.70
Apparel|0.76
Auto & Truck|1.27
Auto Parts|1.02
Bank (Money Center)|0.34
Banks (Regional)|0.29
Beverage (Alcoholic)|0.61
Beverage (Soft)|0.56
Broadcasting|0.29
Brokerage & Investment Banking|0.58
Building Materials|0.93
Business & Consumer Services|0.77
Cable TV|0.35
Chemical (Basic)|0.58
Chemical (Diversified)|0.37
Chemical (Specialty)|0.79
Coal & Related Energy|1.02
Computer Services|0.92
Computers/Peripherals|1.31
Construction Supplies|1.02
Diversified|0.79
Drugs (Biotechnology)|1.03
Drugs (Pharmaceutical)|0.89
Education|0.66
Electrical Equipment|1.15
Electronics (Consumer & Office)|0.83
Electronics (General)|0.90
Engineering/Construction|1.09
Entertainment|0.74
Environmental & Waste Services|0.81
Farming/Agriculture|0.81
Financial Svcs. (Non-bank & Insurance)|0.32
Food Processing|0.46
Food Wholesalers|0.64
Furn/Home Furnishings|0.62
Green & Renewable Energy|0.46
Healthcare Products|0.83
Healthcare Support Services|0.69
Heathcare Information and Technology|0.99
Homebuilding|0.78
Hospitals/Healthcare Facilities|0.55
Hotel/Gaming|0.83
Household Products|0.72
Information Services|0.74
Insurance (General)|0.56
Insurance (Life)|0.43
Insurance (Prop/Cas.)|0.44
Investments & Asset Management|0.53
Machinery|0.87
Metals & Mining|0.96
Office Equipment & Services|0.98
Oil/Gas (Integrated)|0.27
Oil/Gas (Production and Exploration)|0.56
Oil/Gas Distribution|0.47
Oilfield Svcs/Equip.|0.74
Packaging & Container|0.72
Paper/Forest Products|0.72
Power|0.31
Precious Metals|0.79
Publishing & Newspapers|0.48
R.E.I.T.|0.39
Real Estate (Development)|0.48
Real Estate (General/Diversified)|0.58
Real Estate (Operations & Services)|0.81
Recreation|0.70
Reinsurance|0.44
Restaurant/Dining|0.77
Retail (Automotive)|0.70
Retail (Building Supply)|1.31
Retail (Distributors)|0.78
Retail (General)|0.76
Retail (Grocery and Food)|0.80
Retail (REITs)|0.44
Retail (Special Lines)|0.95
Rubber& Tires|0.14
Semiconductor|1.49
Semiconductor Equip|1.35
Shipbuilding & Marine|0.64
Shoe|0.93
Software (Entertainment)|1.01
Software (Internet)|1.55
Software (System & Application)|1.23
Steel|0.90
Telecom (Wireless)|0.39
Telecom. Equipment|0.86
Telecom. Services|0.37
Tobacco|0.68
Transportation|0.68
Transportation (Railroads)|0.81
Trucking|0.85
Utility (General)|0.15
Utility (Water)|0.28
Total Market|0.72
Total Market (without financials)|0.88"""

SNAPSHOT_BBB = 1.11  # % , Baa2/BBB, large non-financial service firms
SNAPSHOT_BBB_DATE = "January 2026"

# OECD combined (central + sub-central) statutory CIT rate, latest year available.
SNAPSHOT_TAX_DATE = "OECD Corporate Tax Statistics, retrieved 2026-11-15"
SNAPSHOT_TAX = """ISO3|Country|Year|Rate
ALB|Albania|2026|15
AND|Andorra|2026|10
AGO|Angola|2026|25
AIA|Anguilla|2026|0
ATG|Antigua and Barbuda|2026|25
ARG|Argentina|2026|35
ARM|Armenia|2026|18
ABW|Aruba|2026|22
AUS|Australia|2026|30
AUT|Austria|2026|23
AZE|Azerbaijan|2026|20
BHS|Bahamas|2026|0
BHR|Bahrain|2026|0
BRB|Barbados|2026|9
BEL|Belgium|2026|25
BLZ|Belize|2026|0
BEN|Benin|2026|30
BMU|Bermuda|2026|0
BIH|Bosnia and Herzegovina|2026|10
BWA|Botswana|2026|22
BRA|Brazil|2026|34
VGB|British Virgin Islands|2026|0
BRN|Brunei Darussalam|2026|18.5
BGR|Bulgaria|2026|10
BFA|Burkina Faso|2026|27.5
CPV|Cabo Verde|2026|20.4
CMR|Cameroon|2026|33
CAN|Canada|2026|26
CYM|Cayman Islands|2026|0
CHL|Chile|2026|27
CHN|China (People's Republic of)|2026|25
COL|Colombia|2025|35
COG|Congo|2026|28
COK|Cook Islands|2026|20
CRI|Costa Rica|2026|30
CIV|Cote d'Ivoire|2026|25
HRV|Croatia|2026|18
CUW|Curacao|2026|15
CZE|Czechia|2026|21
COD|Democratic Republic of the Congo|2026|30
DNK|Denmark|2026|22
DJI|Djibouti|2026|25
DMA|Dominica|2026|25
DOM|Dominican Republic|2026|27
EGY|Egypt|2026|22.5
EST|Estonia|2026|22
SWZ|Eswatini|2026|25
FRO|Faroe Islands|2026|18
FJI|Fiji|2026|25
FIN|Finland|2026|20
FRA|France|2026|36.13
GAB|Gabon|2026|30
GEO|Georgia|2026|15
DEU|Germany|2026|30.13
GIB|Gibraltar|2026|15
GRC|Greece|2026|22
GRL|Greenland|2026|26.5
GRD|Grenada|2026|28
GTM|Guatemala|2026|25
GGY|Guernsey|2026|0
HTI|Haiti|2026|30
HND|Honduras|2026|25
HKG|Hong Kong (China)|2026|16.5
HUN|Hungary|2026|9
ISL|Iceland|2026|20
IND|India|2026|25.17
IDN|Indonesia|2026|22
IRL|Ireland|2026|12.5
IMN|Isle of Man|2026|0
ISR|Israel|2025|23
ITA|Italy|2026|27.81
JAM|Jamaica|2026|25
JPN|Japan|2026|29.74
JEY|Jersey|2026|0
JOR|Jordan|2026|20
KAZ|Kazakhstan|2026|20
KEN|Kenya|2026|30
KOR|Korea|2026|27.5
KWT|Kuwait|2026|15
LVA|Latvia|2026|20
LBR|Liberia|2026|25
LIE|Liechtenstein|2026|12.5
LTU|Lithuania|2026|17
LUX|Luxembourg|2026|23.87
MAC|Macau (China)|2026|12
MYS|Malaysia|2026|24
MDV|Maldives|2026|15
MLT|Malta|2026|35
MRT|Mauritania|2026|25
MUS|Mauritius|2026|15
MEX|Mexico|2026|30
MDA|Moldova|2026|12
MCO|Monaco|2026|25
MNG|Mongolia|2026|25
MNE|Montenegro|2026|15
MSR|Montserrat|2026|30
MAR|Morocco|2026|35
NAM|Namibia|2026|32
NLD|Netherlands|2026|25.8
NZL|New Zealand|2026|28
NGA|Nigeria|2026|30
MKD|North Macedonia|2026|10
NOR|Norway|2026|22
OMN|Oman|2026|15
PAK|Pakistan|2026|29
PAN|Panama|2026|25
PNG|Papua New Guinea|2026|30
PRY|Paraguay|2026|10
PER|Peru|2026|29.5
PHL|Philippines|2026|25
POL|Poland|2026|19
PRT|Portugal|2026|29.5
QAT|Qatar|2026|10
ROU|Romania|2026|16
KNA|Saint Kitts and Nevis|2026|25
LCA|Saint Lucia|2026|30
VCT|Saint Vincent and the Grenadines|2026|28
WSM|Samoa|2026|27
SMR|San Marino|2026|18
SAU|Saudi Arabia|2026|20
SEN|Senegal|2026|30
SRB|Serbia|2026|15
SYC|Seychelles|2026|25
SLE|Sierra Leone|2026|25
SGP|Singapore|2026|17
SVK|Slovak Republic|2026|24
SVN|Slovenia|2026|22
ZAF|South Africa|2026|27
ESP|Spain|2026|25
LKA|Sri Lanka|2026|30
SWE|Sweden|2026|20.6
CHE|Switzerland|2026|19.47
THA|Thailand|2026|20
TGO|Togo|2026|27
TTO|Trinidad and Tobago|2026|30
TUN|Tunisia|2026|20
TUR|Turkiye|2025|25
TCA|Turks and Caicos Islands|2026|0
UKR|Ukraine|2026|18
ARE|United Arab Emirates|2026|9
GBR|United Kingdom|2026|25
USA|United States|2026|25.53
URY|Uruguay|2026|25
UZB|Uzbekistan|2026|15
VNM|Viet Nam|2026|20
ZMB|Zambia|2026|30"""

# Trading Economics 10-year yields, captured 2026-11-15 (US evening).
SNAPSHOT_YIELDS_DATE = "Trading Economics, captured 2026-11-15"
SNAPSHOT_YIELDS = """slug|Country|Yield|Date
united-states|United States|5.1460|2026-11-16
united-kingdom|United Kingdom|5.3377|2026-11-13
japan|Japan|2.8780|2026-11-16
australia|Australia|5.1350|2026-11-16
germany|Germany|3.3762|2026-11-13
brazil|Brazil|15.3350|2026-11-13
russia|Russia|16.7400|2026-11-13
india|India|7.3120|2026-11-13
canada|Canada|3.8560|2026-11-13
italy|Italy|4.4370|2026-11-13
france|France|4.9210|2026-11-13
south-africa|South Africa|8.6750|2026-11-13
china|China|1.6263|2026-11-16
switzerland|Switzerland|0.5626|2026-11-13
mexico|Mexico|9.3080|2026-11-13
netherlands|Netherlands|3.4768|2026-11-13
new-zealand|New Zealand|4.7680|2026-11-16
portugal|Portugal|3.8186|2026-11-13
south-korea|South Korea|3.9850|2026-11-16
spain|Spain|3.9442|2026-11-13
greece|Greece|4.2636|2026-11-13
turkey|Turkey|33.5200|2026-11-13
finland|Finland|3.7611|2026-11-13
lithuania|Lithuania|4.3250|2026-11-13
norway|Norway|4.3842|2026-11-13
poland|Poland|6.3350|2026-11-13
romania|Romania|7.1200|2026-11-13
slovakia|Slovakia|4.3050|2026-11-13
slovenia|Slovenia|3.9140|2026-11-13
sweden|Sweden|3.0980|2026-11-13
hungary|Hungary|5.5249|2026-11-13
iceland|Iceland|6.8100|2026-11-13
ireland|Ireland|3.5391|2026-11-13
austria|Austria|3.6100|2026-11-13
belgium|Belgium|4.3545|2026-11-13
croatia|Croatia|3.8668|2026-11-13
czech-republic|Czech Republic|5.2222|2026-11-13
denmark|Denmark|3.1690|2026-11-15
peru|Peru|6.2414|2026-11-13
chile|Chile|6.0100|2026-11-13
colombia|Colombia|12.6980|2026-11-13
singapore|Singapore|2.3230|2026-11-16
taiwan|Taiwan|1.8600|2026-11-16
thailand|Thailand|1.9950|2026-11-16
vietnam|Vietnam|4.5726|2026-11-16
hong-kong|Hong Kong|3.9941|2026-11-16
indonesia|Indonesia|7.6070|2026-11-13
israel|Israel|4.1830|2026-11-13
malaysia|Malaysia|3.8647|2026-11-15
pakistan|Pakistan|12.6040|2026-11-13
philippines|Philippines|7.7670|2026-11-16
zambia|Zambia|14.7400|2026-11-13
kenya|Kenya|12.5000|2026-11-13
nigeria|Nigeria|16.5980|2026-11-13"""

# Trading Economics slug -> (ISO3, currency code)
COUNTRY_INFO = {
    "united-states": ("USA", "USD"), "united-kingdom": ("GBR", "GBP"), "japan": ("JPN", "JPY"),
    "australia": ("AUS", "AUD"), "germany": ("DEU", "EUR"), "brazil": ("BRA", "BRL"),
    "russia": ("RUS", "RUB"), "india": ("IND", "INR"), "canada": ("CAN", "CAD"),
    "italy": ("ITA", "EUR"), "france": ("FRA", "EUR"), "south-africa": ("ZAF", "ZAR"),
    "china": ("CHN", "CNY"), "switzerland": ("CHE", "CHF"), "mexico": ("MEX", "MXN"),
    "netherlands": ("NLD", "EUR"), "new-zealand": ("NZL", "NZD"), "portugal": ("PRT", "EUR"),
    "south-korea": ("KOR", "KRW"), "spain": ("ESP", "EUR"), "greece": ("GRC", "EUR"),
    "turkey": ("TUR", "TRY"), "finland": ("FIN", "EUR"), "lithuania": ("LTU", "EUR"),
    "norway": ("NOR", "NOK"), "poland": ("POL", "PLN"), "romania": ("ROU", "RON"),
    "slovakia": ("SVK", "EUR"), "slovenia": ("SVN", "EUR"), "sweden": ("SWE", "SEK"),
    "hungary": ("HUN", "HUF"), "iceland": ("ISL", "ISK"), "ireland": ("IRL", "EUR"),
    "austria": ("AUT", "EUR"), "belgium": ("BEL", "EUR"), "croatia": ("HRV", "EUR"),
    "czech-republic": ("CZE", "CZK"), "denmark": ("DNK", "DKK"), "peru": ("PER", "PEN"),
    "chile": ("CHL", "CLP"), "colombia": ("COL", "COP"), "singapore": ("SGP", "SGD"),
    "taiwan": ("TWN", "TWD"), "thailand": ("THA", "THB"), "vietnam": ("VNM", "VND"),
    "hong-kong": ("HKG", "HKD"), "indonesia": ("IDN", "IDR"), "israel": ("ISR", "ILS"),
    "malaysia": ("MYS", "MYR"), "pakistan": ("PAK", "PKR"), "philippines": ("PHL", "PHP"),
    "zambia": ("ZMB", "ZMW"), "kenya": ("KEN", "KES"), "nigeria": ("NGA", "NGN"),
    "estonia": ("EST", "EUR"), "latvia": ("LVA", "EUR"), "luxembourg": ("LUX", "EUR"),
    "cyprus": ("CYP", "EUR"), "malta": ("MLT", "EUR"), "bulgaria": ("BGR", "BGN"),
    "serbia": ("SRB", "RSD"), "ukraine": ("UKR", "UAH"), "argentina": ("ARG", "ARS"),
    "egypt": ("EGY", "EGP"), "morocco": ("MAR", "MAD"), "namibia": ("NAM", "NAD"),
    "botswana": ("BWA", "BWP"), "uganda": ("UGA", "UGX"), "mauritius": ("MUS", "MUR"),
    "bangladesh": ("BGD", "BDT"), "sri-lanka": ("LKA", "LKR"), "qatar": ("QAT", "QAR"),
    "saudi-arabia": ("SAU", "SAR"), "jordan": ("JOR", "JOD"), "kazakhstan": ("KAZ", "KZT"),
    "costa-rica": ("CRI", "CRC"), "uruguay": ("URY", "UYU"), "panama": ("PAN", "USD"),
    "dominican-republic": ("DOM", "DOP"), "jamaica": ("JAM", "JMD"), "georgia": ("GEO", "GEL"),
    "armenia": ("ARM", "AMD"), "bahrain": ("BHR", "BHD"), "oman": ("OMN", "OMR"),
    "united-arab-emirates": ("ARE", "AED"), "macau": ("MAC", "MOP"),
}
EXCLUDE_SLUGS = {"euro-area"}  # aggregates, not countries


# =============================================================================
# Parsers (pure functions: no Streamlit calls, unit-testable)
# =============================================================================
def _now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _cell_str(x) -> str:
    return "" if x is None or (isinstance(x, float) and np.isnan(x)) else str(x).strip()


def _format_excel_date(v) -> str:
    if isinstance(v, (pd.Timestamp, dt.datetime, dt.date)):
        return pd.Timestamp(v).strftime("%B %d, %Y")
    try:
        f = float(v)
        if 20000 < f < 80000:  # Excel serial date
            return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=f)).strftime("%B %d, %Y")
    except (TypeError, ValueError):
        pass
    return _cell_str(v)


def parse_betas_frames(frames: dict) -> tuple[pd.DataFrame, str | None]:
    """frames = {sheet_name: DataFrame read with header=None}. Returns (df, date)."""
    order = sorted(frames, key=lambda s: 0 if "industry" in str(s).lower() else 1)
    for name in order:
        raw = frames[name]
        if raw is None or raw.empty:
            continue
        cells = raw.map(_cell_str) if hasattr(raw, "map") else raw.applymap(_cell_str)
        low = cells.apply(lambda c: c.str.lower())
        hdr_rows = [i for i in range(len(low))
                    if (low.iloc[i] == "industry name").any() and (low.iloc[i] == "unlevered beta").any()]
        if not hdr_rows:
            continue
        h = hdr_rows[0]
        ind_col = int(np.where(low.iloc[h].values == "industry name")[0][0])
        ub_col = int(np.where(low.iloc[h].values == "unlevered beta")[0][0])
        rows = []
        for i in range(h + 1, len(cells)):
            ind = cells.iat[i, ind_col]
            if not ind:
                if rows:
                    break
                continue
            ub = pd.to_numeric(raw.iat[i, ub_col], errors="coerce")
            if pd.notna(ub):
                rows.append((ind, float(ub)))
        if not rows:
            continue
        # "Date updated:" label -> next non-empty cell to the right (or below)
        date = None
        for i in range(len(low)):
            hits = np.where(low.iloc[i].str.startswith("date updated").values)[0]
            if len(hits):
                j = int(hits[0])
                for k in range(j + 1, raw.shape[1]):
                    if _cell_str(raw.iat[i, k]):
                        date = _format_excel_date(raw.iat[i, k])
                        break
                if date is None and i + 1 < len(raw) and _cell_str(raw.iat[i + 1, j]):
                    date = _format_excel_date(raw.iat[i + 1, j])
                break
        df = pd.DataFrame(rows, columns=["Industry", "Unlevered beta"]).drop_duplicates("Industry")
        return df.reset_index(drop=True), date
    raise ValueError("No sheet with 'Industry Name' and 'Unlevered beta' headers found")


def parse_bbb_spread(html: str) -> tuple[float, str | None]:
    """Returns (spread in %, date of analysis). Uses the left block = large non-financial firms."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    if "non-financial" not in text.lower():
        raise ValueError("Table for large non-financial service firms not found")
    m = re.search(r"Date of Analysis\W*([A-Za-z]+\.?\s+\d{4})", text)
    date = m.group(1) if m else None
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        for i, c in enumerate(cells):
            if re.fullmatch(r"Baa2\s*/\s*BBB", c):
                for nxt in cells[i + 1:]:
                    p = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*%", nxt)
                    if p:
                        return float(p.group(1)), date
    raise ValueError("Baa2/BBB row not found")


def parse_oecd_csv(text: str) -> pd.DataFrame:
    """Latest combined statutory CIT rate per jurisdiction -> ISO3, Country, Year, Rate (%)."""
    df = pd.read_csv(io.StringIO(text))
    need = {"REF_AREA", "MEASURE", "TARGETING", "TIME_PERIOD", "OBS_VALUE"}
    if not need.issubset(df.columns):
        raise ValueError(f"Unexpected OECD columns: {list(df.columns)[:12]}")
    df = df[(df["MEASURE"] == "CIT_C") & (df["TARGETING"] == "ST")].copy()
    df["OBS_VALUE"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    df["TIME_PERIOD"] = pd.to_numeric(df["TIME_PERIOD"], errors="coerce")
    df = df.dropna(subset=["OBS_VALUE", "TIME_PERIOD"])
    if df.empty:
        raise ValueError("No combined statutory CIT observations in OECD response")
    df = df.sort_values("TIME_PERIOD").groupby("REF_AREA", as_index=False).last()
    name_col = "Reference area" if "Reference area" in df.columns else "REF_AREA"
    out = pd.DataFrame({
        "ISO3": df["REF_AREA"], "Country": df[name_col],
        "Year": df["TIME_PERIOD"].astype(int), "Rate": df["OBS_VALUE"].astype(float),
    })
    return out.sort_values("Country").reset_index(drop=True)


def te_date_to_iso(s: str, today: dt.date | None = None) -> str:
    """Trading Economics shows 'Nov/13' for past days and 'HH:MM' for today."""
    today = today or dt.date.today()
    s = (s or "").strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", s):
        return today.isoformat()
    m = re.fullmatch(r"([A-Za-z]{3})/(\d{1,2})", s)
    if m:
        try:
            d = dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {today.year}", "%b %d %Y").date()
            if d > today + dt.timedelta(days=2):
                d = d.replace(year=today.year - 1)
            return d.isoformat()
        except ValueError:
            pass
    return s


def parse_te_bonds(html: str, today: dt.date | None = None) -> pd.DataFrame:
    """Rows of the Trading Economics /bonds tables -> slug, Country, Yield (%), Date."""
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=re.compile(r"/government-bond-yield"))
        if a is None:
            continue
        slug = a["href"].strip("/").split("/")[0]
        if slug in seen or slug in EXCLUDE_SLUGS:
            continue
        tds = tr.find_all("td")
        ytd = tr.find("td", id="p")
        txt = ytd.get_text(strip=True) if ytd else None
        if txt is None:  # generic fallback: first numeric cell after the name
            for td in tds:
                t = td.get_text(strip=True)
                if re.fullmatch(r"-?\d+(\.\d+)?", t):
                    txt = t
                    break
        y = pd.to_numeric(txt, errors="coerce")
        if pd.isna(y):
            continue
        date = te_date_to_iso(tds[-1].get_text(strip=True) if tds else "", today)
        seen.add(slug)
        out.append((slug, " ".join(a.get_text(" ", strip=True).split()), float(y), date))
    if not out:
        raise ValueError("No bond rows found (page may be a bot-check or rendered by JavaScript)")
    return pd.DataFrame(out, columns=["slug", "Country", "Yield", "Date"])


# =============================================================================
# Fetchers (cached; each returns a dict with data + provenance)
# =============================================================================
def _get(url: str) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def fetch_betas() -> dict:
    log = []
    for url in BETAS_URLS:
        try:
            r = _get(url)
            frames = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None)
            df, date = parse_betas_frames(frames)
            if date is None:
                date = r.headers.get("Last-Modified", "date not shown in file")
            return dict(data=df, status="Live", as_of=date, url=url, fetched=_now_utc(), log=log)
        except Exception as e:  # noqa: BLE001
            log.append(f"{url}: {type(e).__name__}: {e}")
    df = pd.read_csv(io.StringIO(SNAPSHOT_BETAS), sep="|")
    return dict(data=df, status="Snapshot", as_of=SNAPSHOT_BETAS_DATE, url=BETAS_URLS[0],
                fetched=_now_utc(), log=log)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def fetch_bbb() -> dict:
    log = []
    for url in RATINGS_URLS:
        try:
            spread, date = parse_bbb_spread(_get(url).text)
            return dict(data=spread, status="Live", as_of=date or "date not shown", url=url,
                        fetched=_now_utc(), log=log)
        except Exception as e:  # noqa: BLE001
            log.append(f"{url}: {type(e).__name__}: {e}")
    return dict(data=SNAPSHOT_BBB, status="Snapshot", as_of=SNAPSHOT_BBB_DATE, url=RATINGS_URLS[0],
                fetched=_now_utc(), log=log)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def fetch_tax() -> dict:
    log = []
    url = OECD_SDMX_URL.format(start=dt.date.today().year - 5)
    try:
        df = parse_oecd_csv(_get(url).text)
        return dict(data=df, status="Live", as_of=f"Tax years up to {int(df['Year'].max())}",
                    url=url, fetched=_now_utc(), log=log)
    except Exception as e:  # noqa: BLE001
        log.append(f"{url}: {type(e).__name__}: {e}")
    df = pd.read_csv(io.StringIO(SNAPSHOT_TAX), sep="|")
    return dict(data=df, status="Snapshot", as_of=SNAPSHOT_TAX_DATE, url=url, fetched=_now_utc(), log=log)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def fetch_yields() -> dict:
    log = []
    for url in TE_URLS:
        try:
            df = parse_te_bonds(_get(url).text)
            if "united-states" not in set(df["slug"]):
                raise ValueError("United States row missing")
            return dict(data=df, status="Live", as_of=f"Latest quotes, up to {df['Date'].max()}",
                        url=url, fetched=_now_utc(), log=log)
        except Exception as e:  # noqa: BLE001
            log.append(f"{url}: {type(e).__name__}: {e}")
    df = pd.read_csv(io.StringIO(SNAPSHOT_YIELDS), sep="|")
    return dict(data=df, status="Snapshot", as_of=SNAPSHOT_YIELDS_DATE, url=TE_URLS[0],
                fetched=_now_utc(), log=log)


# =============================================================================
# Model (all rates as decimals)
# =============================================================================
def levered_beta(beta_u: float, tax: float, d: float) -> float:
    """Hamada: bL = bU * [1 + (1 - t) * D/E], with D/E = d / (1 - d)."""
    if not 0 <= d < 1:
        raise ValueError("Debt share must be in [0, 1)")
    return beta_u * (1 + (1 - tax) * d / (1 - d))


def parity(r_usd: float, rf_us: float, rf_f: float) -> float:
    """(1 + r*) = (1 + r) * (1 + Rf*) / (1 + Rf)."""
    return (1 + r_usd) * (1 + rf_f) / (1 + rf_us) - 1


def compute(beta_u, erp, d, tax, rf_us, rf_f, spread_usd, spread_f_override=None) -> dict:
    bl = levered_beta(beta_u, tax, d)
    re_usd = rf_us + bl * erp
    re_f = parity(re_usd, rf_us, rf_f)
    rd_usd = rf_us + spread_usd
    if spread_f_override is None:
        rd_f = parity(rd_usd, rf_us, rf_f)
        spread_f, f_mode = rd_f - rf_f, "Auto (parity)"
    else:
        spread_f, f_mode = spread_f_override, "Manual override"
        rd_f = rf_f + spread_f
    wacc_usd = (1 - d) * re_usd + d * rd_usd * (1 - tax)
    wacc_f = (1 - d) * re_f + d * rd_f * (1 - tax)
    return dict(
        beta_u=beta_u, beta_l=bl, erp=erp, d=d, de=d / (1 - d), tax=tax,
        rf_usd=rf_us, rf_f=rf_f,
        re_usd=re_usd, re_f=re_f,
        spread_usd=spread_usd, spread_f=spread_f, spread_f_mode=f_mode,
        rd_usd=rd_usd, rd_f=rd_f,
        rd_at_usd=rd_usd * (1 - tax), rd_at_f=rd_f * (1 - tax),
        wacc_usd=wacc_usd, wacc_f=wacc_f,
    )


def all_industries(betas: pd.DataFrame, **kw) -> pd.DataFrame:
    rows = []
    for ind, bu in zip(betas["Industry"], betas["Unlevered beta"]):
        r = compute(beta_u=float(bu), **kw)
        rows.append({
            "Industry": ind, "Unlevered beta": r["beta_u"], "Levered beta": r["beta_l"],
            "Cost of equity USD": r["re_usd"], "Cost of equity FX": r["re_f"],
            "WACC USD": r["wacc_usd"], "WACC FX": r["wacc_f"],
        })
    return pd.DataFrame(rows)


def model_checks(base: dict) -> list[tuple[str, bool, str]]:
    """The three required sanity checks, run on the current inputs."""
    k = dict(beta_u=base["beta_u"], erp=base["erp"], d=base["d"], tax=base["tax"],
             rf_us=base["rf_usd"], spread_usd=base["spread_usd"])
    out = []
    eq = compute(rf_f=base["rf_usd"], **k)
    ok = all(np.isclose(eq[a], eq[b], atol=1e-12) for a, b in
             [("re_usd", "re_f"), ("rd_usd", "rd_f"), ("wacc_usd", "wacc_f")])
    out.append(("Equal 10y yields -> identical USD and foreign results (spread override off)", ok,
                f"WACC {eq['wacc_usd']:.4%} vs {eq['wacc_f']:.4%}"))
    z = compute(rf_f=base["rf_f"], **{**k, "d": 0.0})
    ok = np.isclose(z["wacc_usd"], z["re_usd"]) and np.isclose(z["wacc_f"], z["re_f"])
    out.append(("Zero debt -> WACC equals cost of equity (both currencies)", ok,
                f"USD {z['wacc_usd']:.4%} = {z['re_usd']:.4%}; FX {z['wacc_f']:.4%} = {z['re_f']:.4%}"))
    a = compute(rf_f=base["rf_f"], **k)
    b = compute(rf_f=base["rf_f"], spread_f_override=a["spread_f"] + 0.02, **k)
    keys = ["beta_l", "re_usd", "rd_usd", "rd_at_usd", "wacc_usd"]
    ok = all(a[x] == b[x] for x in keys)
    out.append(("Foreign spread override (+2pp) leaves all USD results unchanged", bool(ok),
                f"USD WACC {a['wacc_usd']:.4%} -> {b['wacc_usd']:.4%}; FX WACC {a['wacc_f']:.4%} -> {b['wacc_f']:.4%}"))
    return out


# =============================================================================
# UI helpers
# =============================================================================
def pct(x, n=2):
    return "n/a" if x is None or pd.isna(x) else f"{x * 100:.{n}f}%"


def show_df(df, **kw):
    try:
        st.dataframe(df, width="stretch", **kw)
    except TypeError:
        st.dataframe(df, use_container_width=True, **kw)


def show_chart(fig):
    try:
        st.plotly_chart(fig, width="stretch")
    except TypeError:
        st.plotly_chart(fig, use_container_width=True)


def override_input(label, fetched, key, *, unit="%", fmt="%.2f", step=0.05, minv=None, maxv=None,
                   force=False, help=None):
    """Checkbox + number input. Returns (value, overridden?). Values in display units."""
    c1, c2 = st.columns([1, 1.3])
    on = c1.checkbox(label, key=f"ovr_{key}", value=force, disabled=force, help=help)
    default = float(fetched) if fetched is not None and not pd.isna(fetched) else 0.0
    val = c2.number_input(f"{label} value ({unit})" if unit else f"{label} value", value=default,
                          step=step, format=fmt, key=f"val_{key}", disabled=not on,
                          min_value=minv, max_value=maxv, label_visibility="collapsed")
    return (val if on else fetched), on


# =============================================================================
# App
# =============================================================================
def main():
    st.set_page_config(page_title="International Cost of Capital", page_icon="🌐", layout="wide")
    st.title("🌐 International Cost of Capital")
    st.caption("A project's cost of equity, cost of debt and WACC in USD and in a selected "
               "country's currency.")

    with st.sidebar:
        if st.button("🔄 Refresh data", help="Clear the cache and fetch all sources again"):
            st.cache_data.clear()
            st.rerun()

    with st.spinner("Fetching Damodaran, OECD and Trading Economics data..."):
        B, S, T, Y = fetch_betas(), fetch_bbb(), fetch_tax(), fetch_yields()

    betas = B["data"]
    taxes = T["data"].set_index("ISO3")
    yields = Y["data"].copy()
    yields = yields[~yields["slug"].isin(EXCLUDE_SLUGS)].drop_duplicates("slug").set_index("slug")

    def country_meta(slug):
        iso3, ccy = COUNTRY_INFO.get(slug, (None, "LCY"))
        name = yields.loc[slug, "Country"] if slug in yields.index else slug.replace("-", " ").title()
        return name, iso3, ccy

    slugs = sorted(yields.index, key=lambda s: (s != "united-states", country_meta(s)[0]))
    us_tax_fetched = float(taxes.loc["USA", "Rate"]) if "USA" in taxes.index else None

    # ---------------- sidebar inputs ----------------
    with st.sidebar:
        st.header("Project inputs")
        industries = list(betas["Industry"])
        ind = st.selectbox("Industry (Damodaran, U.S.)", industries,
                           index=industries.index(DEFAULT_INDUSTRY) if DEFAULT_INDUSTRY in industries else 0)
        slug = st.selectbox(
            "Target country", slugs,
            index=slugs.index(DEFAULT_COUNTRY) if DEFAULT_COUNTRY in slugs else 0,
            format_func=lambda s: f"{country_meta(s)[0]} ({country_meta(s)[2]})")
        cname, iso3, ccy = country_meta(slug)
        erp_pct = st.number_input("Equity risk premium (%)", 0.0, 20.0, DEFAULT_ERP, 0.1, format="%.2f")
        d_pct = st.slider("Target debt share D/(D+E) (%)", 0, 90, DEFAULT_DEBT, 1)
        tax_choice = st.radio("Project tax rate (used in both currencies)",
                              ["U.S. rate", "Target-country rate"], horizontal=True,
                              help=f"Target country: {cname}")

        st.header("Manual overrides")
        st.caption("Tick a box to replace the fetched value. All values in %, except beta.")
        bu_f = float(betas.loc[betas["Industry"] == ind, "Unlevered beta"].iloc[0])
        bu, bu_on = override_input("Unlevered beta", bu_f, f"bu_{ind}", unit="", fmt="%.3f",
                                   step=0.01, minv=0.0)
        tax_us_pct, tax_us_on = override_input("U.S. tax rate", us_tax_fetched, "tax_usa",
                                               step=0.5, minv=0.0, maxv=99.0,
                                               force=us_tax_fetched is None)
        f_tax_fetched = float(taxes.loc[iso3, "Rate"]) if iso3 in taxes.index else None
        if slug == "united-states":
            tax_f_pct, tax_f_on = tax_us_pct, tax_us_on
        else:
            tax_f_pct, tax_f_on = override_input(
                f"{cname} tax rate", f_tax_fetched if f_tax_fetched is not None else 25.0,
                f"tax_{slug}", step=0.5, minv=0.0, maxv=99.0, force=f_tax_fetched is None,
                help="No OECD rate for this country: enter one manually." if f_tax_fetched is None else None)
        spread_pct, spread_on = override_input("USD BBB spread", S["data"], "bbb_usd",
                                               step=0.05, minv=-5.0, maxv=30.0)
        rf_us_fetched = float(yields.loc["united-states", "Yield"]) if "united-states" in yields.index else None
        rf_us_pct, rf_us_on = override_input("U.S. 10y yield", rf_us_fetched, "rf_usa",
                                             step=0.05, minv=-5.0, maxv=100.0,
                                             force=rf_us_fetched is None)
        rf_f_fetched = float(yields.loc[slug, "Yield"])
        if slug == "united-states":
            rf_f_pct, rf_f_on = rf_us_pct, rf_us_on
        else:
            rf_f_pct, rf_f_on = override_input(f"{cname} 10y yield", rf_f_fetched, f"rf_{slug}",
                                               step=0.05, minv=-5.0, maxv=100.0)

    tax_us, tax_f = tax_us_pct / 100, tax_f_pct / 100
    tax = tax_us if tax_choice == "U.S. rate" else tax_f
    kw = dict(beta_u=bu, erp=erp_pct / 100, d=d_pct / 100, tax=tax,
              rf_us=rf_us_pct / 100, rf_f=rf_f_pct / 100, spread_usd=spread_pct / 100)
    auto = compute(**kw)

    with st.sidebar:
        on = st.checkbox(f"{ccy} BBB spread override", key=f"ovr_fspread_{slug}",
                         help="Off: the foreign cost of debt is the USD cost of debt converted "
                              "with the same parity formula as equity.")
        if on:
            fs_pct = st.number_input(f"{ccy} BBB spread (%)", value=round(auto["spread_f"] * 100, 2),
                                     step=0.05, format="%.2f", key=f"val_fspread_{slug}")
        else:
            st.caption(f"Auto (parity) {ccy} BBB spread: **{pct(auto['spread_f'])}**")
        with st.expander("Data sources & diagnostics"):
            for nm, src in [("Betas", B), ("BBB spread", S), ("Tax rates", T), ("10y yields", Y)]:
                st.markdown(f"**{nm}**: {src['status']} · {src['as_of']}")
                for line in src["log"]:
                    st.code(line, language=None)

    res = compute(**kw, spread_f_override=(fs_pct / 100) if on else None)

    # ---------------- data status ----------------
    snaps = [n for n, s in [("Damodaran betas", B), ("Damodaran BBB spread", S),
                            ("OECD tax rates", T), ("Trading Economics yields", Y)] if s["status"] != "Live"]
    if snaps:
        st.warning("Live fetch failed for: " + ", ".join(snaps) + ". Using the dated built-in snapshot "
                   "(see *Sources & dates*). You can overwrite any value in the sidebar.")
    if f_tax_fetched is None and slug != "united-states":
        st.info(f"OECD has no statutory rate for {cname}: the {cname} tax rate is a manual input.")

    # ---------------- headline results ----------------
    st.subheader(f"{ind} · USD vs {ccy} ({cname})")
    st.caption(f"Debt share {d_pct}% · ERP {erp_pct:.2f}% · project tax rate "
               f"{pct(tax)} ({'U.S.' if tax_choice == 'U.S. rate' else cname})")
    c1, c2 = st.columns(2)
    for col, cur, re_, rd, rdat, w in [
        (c1, "USD", res["re_usd"], res["rd_usd"], res["rd_at_usd"], res["wacc_usd"]),
        (c2, ccy, res["re_f"], res["rd_f"], res["rd_at_f"], res["wacc_f"]),
    ]:
        with col:
            with st.container(border=True):
                st.markdown(f"### {cur}")
                m1, m2, m3 = st.columns(3)
                m1.metric("Cost of equity", pct(re_))
                m2.metric("Cost of debt (pre-tax)", pct(rd), f"after-tax {pct(rdat)}", delta_color="off")
                m3.metric("WACC", pct(w))

    def row(item, usd, fx, fmt=pct, src=""):
        return {"Item": item, "USD": fmt(usd), ccy if ccy != "USD" else "USD (selected)": fmt(fx), "Source / rule": src}

    f2 = lambda x: f"{x:.3f}"  # noqa: E731
    table = pd.DataFrame([
        row("10-year government yield (Rf)", res["rf_usd"], res["rf_f"],
            src=f"Trading Economics{' (override)' if rf_us_on or rf_f_on else ''}"),
        row("Unlevered beta", res["beta_u"], res["beta_u"], f2, f"Damodaran{' (override)' if bu_on else ''}"),
        row("D/E", res["de"], res["de"], f2, "d / (1 − d)"),
        row("Levered beta", res["beta_l"], res["beta_l"], f2, "βU·[1 + (1 − τ)·D/E]"),
        row("Equity risk premium", res["erp"], np.nan, src="Input; foreign Re via parity"),
        row("Cost of equity", res["re_usd"], res["re_f"], src="USD: Rf + βL·ERP · FX: parity"),
        row("BBB spread", res["spread_usd"], res["spread_f"],
            src=f"USD: Damodaran{' (override)' if spread_on else ''} · FX: {res['spread_f_mode']}"),
        row("Pre-tax cost of debt", res["rd_usd"], res["rd_f"], src="Rf + spread"),
        row("Project tax rate", res["tax"], res["tax"], src=f"OECD · {tax_choice}"),
        row("After-tax cost of debt", res["rd_at_usd"], res["rd_at_f"], src="Rd·(1 − τ)"),
        row("Debt share d", res["d"], res["d"], src="Input"),
        row("WACC", res["wacc_usd"], res["wacc_f"], src="(1 − d)·Re + d·Rd·(1 − τ)"),
    ])
    show_df(table, hide_index=True)

    with st.expander("How the numbers are built (with your inputs)", expanded=False):
        st.latex(r"\beta_L=\beta_U\left[1+(1-\tau)\tfrac{D}{E}\right]=%.3f\times[1+(1-%.4f)\times%.4f]=%.4f"
                 % (res["beta_u"], res["tax"], res["de"], res["beta_l"]))
        st.latex(r"R_e^{USD}=R_f+\beta_L\cdot ERP=%.4f+%.4f\times%.4f=%.4f"
                 % (res["rf_usd"], res["beta_l"], res["erp"], res["re_usd"]))
        st.latex(r"1+R_e^{*}=(1+R_e)\frac{1+R_f^{*}}{1+R_f}=%.4f\times\frac{%.4f}{%.4f}\Rightarrow R_e^{*}=%.4f"
                 % (1 + res["re_usd"], 1 + res["rf_f"], 1 + res["rf_usd"], res["re_f"]))
        st.latex(r"R_d^{USD}=R_f+s_{BBB}=%.4f+%.4f=%.4f" % (res["rf_usd"], res["spread_usd"], res["rd_usd"]))
        if res["spread_f_mode"].startswith("Auto"):
            st.latex(r"1+R_d^{*}=(1+R_d)\frac{1+R_f^{*}}{1+R_f}\Rightarrow R_d^{*}=%.4f" % res["rd_f"])
        else:
            st.latex(r"R_d^{*}=R_f^{*}+s^{*}_{BBB}=%.4f+%.4f=%.4f" % (res["rf_f"], res["spread_f"], res["rd_f"]))
        st.latex(r"WACC=(1-d)R_e+d\,R_d(1-\tau)\;\Rightarrow\;USD\;%.4f,\;\;%s\;%.4f"
                 % (res["wacc_usd"], ccy, res["wacc_f"]))

    with st.expander("Main assumptions", expanded=False):
        st.markdown(f"""
- **Risk-free rates** are the 10-year government bond yields of the U.S. and of {cname} (its own
  sovereign yield, so for euro members it includes that government's credit spread).
- **Beta**: Damodaran's U.S. industry *Unlevered beta* (not the cash-corrected one), relevered with
  Hamada's formula at the target debt share; D/E = d/(1 − d).
- **USD cost of equity** is CAPM with the chosen ERP; no separate country risk premium is added.
- **Foreign cost of equity** converts the USD rate with the interest-rate-parity relation
  (1 + R*ₑ) = (1 + Rₑ)(1 + R*f)/(1 + Rf), so differences in expected inflation are priced in.
- **USD cost of debt** = U.S. 10y + Damodaran's Baa2/BBB spread for large non-financial firms.
  With the override **off**, the foreign cost of debt is converted with the same parity formula
  (implied {ccy} spread = R*d − R*f). With it **on**, R*d = R*f + your spread; USD results do not change.
- **Taxes**: one project tax rate (U.S. or {cname}, toggle in the sidebar) is used for relevering
  beta and for the debt tax shield in both currencies. OECD rate = combined central + sub-central
  statutory CIT rate, latest year available.
- Debt share, ERP and tax rate are identical in both currencies, so any difference in results comes
  only from the two 10-year yields (and the foreign spread override, if on).
""")

    # ---------------- all-industry comparison ----------------
    st.subheader("All-industry comparison")
    betas_cmp = betas.copy()
    if bu_on:
        betas_cmp.loc[betas_cmp["Industry"] == ind, "Unlevered beta"] = bu
    comp = all_industries(betas_cmp, erp=kw["erp"], d=kw["d"], tax=kw["tax"], rf_us=kw["rf_us"],
                          rf_f=kw["rf_f"], spread_usd=kw["spread_usd"],
                          spread_f_override=res["spread_f"] if on else None)
    fx_lbl = ccy if ccy != "USD" else "USD (selected)"
    comp = comp.rename(columns={"Cost of equity FX": f"Cost of equity {fx_lbl}", "WACC FX": f"WACC {fx_lbl}"})
    fx_eq, fx_w = comp.columns[4], comp.columns[6]
    metric = st.radio("Chart metric", ["WACC", "Cost of equity"], horizontal=True)
    a_col, b_col = ("WACC USD", fx_w) if metric == "WACC" else ("Cost of equity USD", fx_eq)
    chart = comp.sort_values(a_col)
    fig = go.Figure()
    fig.add_bar(y=chart["Industry"], x=chart[a_col] * 100, name=f"{metric} USD", orientation="h",
                marker_color="#2563EB", hovertemplate="%{y}: %{x:.2f}%<extra>USD</extra>")
    fig.add_bar(y=chart["Industry"], x=chart[b_col] * 100, name=f"{metric} {ccy}", orientation="h",
                marker_color="#EA580C", hovertemplate=f"%{{y}}: %{{x:.2f}}%<extra>{ccy}</extra>")
    fig.update_layout(barmode="group", height=max(600, 22 * len(chart)), template="plotly_white",
                      margin=dict(l=10, r=10, t=30, b=10), xaxis_title=f"{metric} (%)",
                      legend=dict(orientation="h", y=1.01, x=0, yanchor="bottom"))
    fig.update_yaxes(tickfont=dict(size=10))
    sel = chart["Industry"].tolist().index(ind) if ind in chart["Industry"].tolist() else None
    if sel is not None:
        fig.add_hrect(y0=sel - 0.5, y1=sel + 0.5, fillcolor="#FDE68A", opacity=0.4, line_width=0)
    with st.expander("Chart (selected industry highlighted)", expanded=True):
        show_chart(fig)
    disp = comp.copy()
    for c in disp.columns[3:]:
        disp[c] = disp[c] * 100
    show_df(disp.style.format({c: "{:.2f}%" for c in disp.columns[3:]} |
                              {"Unlevered beta": "{:.2f}", "Levered beta": "{:.3f}"}), hide_index=True)

    # ---------------- downloads ----------------
    st.subheader("Downloads")
    stamp = dt.date.today().isoformat()
    sel_out = pd.DataFrame([
        ("Industry", ind), ("Target country", cname), ("Currency", ccy),
        ("Equity risk premium", res["erp"]), ("Debt share d", res["d"]), ("D/E", res["de"]),
        ("Project tax rate", res["tax"]), ("Tax rate choice", tax_choice),
        ("U.S. tax rate", tax_us), (f"{cname} tax rate", tax_f),
        ("Unlevered beta", res["beta_u"]), ("Levered beta", res["beta_l"]),
        ("Rf USD (U.S. 10y)", res["rf_usd"]), (f"Rf {ccy} ({cname} 10y)", res["rf_f"]),
        ("Cost of equity USD", res["re_usd"]), (f"Cost of equity {ccy}", res["re_f"]),
        ("BBB spread USD", res["spread_usd"]), (f"BBB spread {ccy}", res["spread_f"]),
        (f"{ccy} spread mode", res["spread_f_mode"]),
        ("Pre-tax cost of debt USD", res["rd_usd"]), (f"Pre-tax cost of debt {ccy}", res["rd_f"]),
        ("After-tax cost of debt USD", res["rd_at_usd"]), (f"After-tax cost of debt {ccy}", res["rd_at_f"]),
        ("WACC USD", res["wacc_usd"]), (f"WACC {ccy}", res["wacc_f"]),
        ("Betas source", f"{B['status']} · {B['as_of']}"), ("BBB source", f"{S['status']} · {S['as_of']}"),
        ("Tax source", f"{T['status']} · {T['as_of']}"), ("Yield source", f"{Y['status']} · {Y['as_of']}"),
    ], columns=["Item", "Value"])
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Selected results (CSV)", sel_out.to_csv(index=False).encode("utf-8"),
                       file_name=f"coc_{iso3 or slug}_{stamp}.csv", mime="text/csv")
    d2.download_button("⬇️ All-industry comparison (CSV)", comp.to_csv(index=False).encode("utf-8"),
                       file_name=f"coc_all_industries_{iso3 or slug}_{stamp}.csv", mime="text/csv")

    # ---------------- checks ----------------
    with st.expander("Model checks (run on your current inputs)"):
        for name, ok, detail in model_checks(res):
            (st.success if ok else st.error)(f"{'✅' if ok else '❌'} {name} — {detail}")

    # ---------------- sources ----------------
    st.subheader("Sources & dates")
    us_tax_year = int(taxes.loc["USA", "Year"]) if "USA" in taxes.index else None
    f_tax_year = int(taxes.loc[iso3, "Year"]) if iso3 in taxes.index else None
    srcs = pd.DataFrame([
        ("Industry unlevered beta", "Aswath Damodaran (NYU Stern), betas.xls", B["url"], B["as_of"], B["status"], B["fetched"]),
        ("BBB spread (Baa2/BBB, large non-financial firms)", "Aswath Damodaran, ratings.html", S["url"], S["as_of"], S["status"], S["fetched"]),
        ("Corporate tax rates (combined statutory)", "OECD Corporate Tax Statistics (SDMX feed behind the report)", OECD_REPORT_URL,
         f"{T['as_of']}; U.S. {us_tax_year or 'n/a'}, {cname} {f_tax_year or 'n/a'}", T["status"], T["fetched"]),
        ("10-year government bond yields", "Trading Economics, Bonds", Y["url"],
         f"U.S. {yields.loc['united-states', 'Date'] if 'united-states' in yields.index else 'n/a'}; "
         f"{cname} {yields.loc[slug, 'Date']}", Y["status"], Y["fetched"]),
    ], columns=["Data", "Source", "URL", "As of", "Status", "Fetched"])
    try:
        st.dataframe(srcs, hide_index=True, width="stretch",
                     column_config={"URL": st.column_config.LinkColumn("URL")})
    except TypeError:
        st.dataframe(srcs, hide_index=True, use_container_width=True,
                     column_config={"URL": st.column_config.LinkColumn("URL")})
    st.caption("Overrides in the sidebar replace fetched values for this session only. "
               "Data are cached for 6 hours; use **Refresh data** to fetch again.")


if __name__ == "__main__":
    main()
