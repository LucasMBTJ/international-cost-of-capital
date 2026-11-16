# International Cost of Capital (Streamlit)

Compares a project's **cost of equity, cost of debt and WACC in USD** and in the **currency of a selected country**, using live market and tax data.

## Model

| Step | Formula |
|---|---|
| Debt-to-equity | D/E = d / (1 − d), with d = target debt share D/(D+E) |
| Levered beta | βL = βU · [1 + (1 − τ) · D/E] |
| USD cost of equity (CAPM) | Re = Rf(US 10y) + βL · ERP |
| Foreign cost of equity | (1 + Re\*) = (1 + Re) · (1 + Rf\*) / (1 + Rf) |
| USD cost of debt | Rd = Rf(US 10y) + BBB spread |
| Foreign cost of debt, override **off** | (1 + Rd\*) = (1 + Rd) · (1 + Rf\*) / (1 + Rf); implied spread = Rd\* − Rf\* |
| Foreign cost of debt, override **on** | Rd\* = Rf\* + user spread |
| WACC (both currencies) | WACC = (1 − d) · Re + d · Rd · (1 − τ) |

Rf and Rf\* are the 10-year government bond yields of the U.S. and of the selected country. Each country uses its **own** yield, so euro members do not share Germany's rate. The debt share, ERP and one project tax rate τ are used in both currencies. You choose τ with the U.S. / target-country toggle.

## Data sources

| Data | Source | How it is fetched |
|---|---|---|
| Industry unlevered beta | Damodaran, [betas.xls](https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls) | Sheet *Industry Averages*, column *Unlevered beta* (not the cash-corrected one) |
| BBB spread (USD) | Damodaran, [ratings.html](https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html) | Baa2/BBB row, table for large non-financial service firms |
| Corporate tax rate | [OECD Corporate Tax Statistics](https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/statutory-corporate-income-tax-rates_440f9286.html) | OECD SDMX feed `DSD_TAX_CIT@DF_CIT`, combined (central + sub-central) statutory rate, latest year |
| 10-year government yields | [Trading Economics – Bonds](https://tradingeconomics.com/bonds) | HTML scrape of the bond tables (no API key) |

- Data are cached for 6 hours. **🔄 Refresh data** in the sidebar clears the cache and fetches everything again.
- The *Sources & dates* table shows each source's URL, as-of date, status (Live / Snapshot) and fetch time.
- **Fallback:** if a live fetch fails, the app uses a dated built-in snapshot (betas and spread from January 2026, OECD rates for 2026, and yields captured 2026-11-15) and shows a warning. Trading Economics sometimes serves a bot check to cloud servers, so yields are the source most likely to fall back. The sidebar's *Data sources & diagnostics* panel shows why a fetch failed.
- The country list includes every country with a Trading Economics 10-year yield. If OECD has no rate for a country (e.g., Russia, Taiwan), its tax rate becomes a manual input.

## Features

- **Inputs:** industry, target country, equity risk premium and target debt share.
- **Tax toggle:** choose the U.S. or the target-country tax rate as the project tax rate.
- **Manual overrides:** unlevered beta, U.S. and foreign tax rates, USD BBB spread, and both 10-year yields. The foreign-currency BBB spread has its own override. When it is off, the app shows the auto (parity) spread.
- **Results:** USD and foreign-currency results side by side, a detailed table, and the formulas with your numbers plugged in.
- **Assumptions:** the main assumptions are explained in the app.
- **All-industry comparison:** a table and grouped bar chart of WACC or cost of equity for every industry, with the selected industry highlighted.
- **Downloads:** CSV files of the selected results (with inputs and sources) and of the all-industry comparison.
- **Model checks:** run live on your inputs:
  1. Equal 10-year yields give identical USD and foreign results (spread override off).
  2. Zero debt makes WACC equal the cost of equity.
  3. Overriding the foreign spread leaves all USD results unchanged.

**Defaults:** Software (System & Application), United States, U.S. tax rate, 6.5% ERP, 30% debt.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Put `app.py`, `requirements.txt` and `README.md` in the repository root.
2. On share.streamlit.io, choose **Create app**, then pick the repo, the branch and `app.py`.
3. Under **Advanced settings**, set Python **3.12**, then deploy.

## Worked example (verification)

Inputs: Software (System & Application), βU = 1.23, Germany vs U.S., U.S. tax rate 25.5285%, ERP 6.5%, d = 30%, U.S. 10y 5.146%, Germany 10y 3.3762%, BBB spread 1.11%.

| | USD | EUR |
|---|---|---|
| Levered beta | 1.6226 | 1.6226 |
| Cost of equity | 15.693% | 13.745% |
| Pre-tax cost of debt | 6.256% | 4.468% |
| WACC | 12.383% | 10.620% |

An independent spreadsheet built from the same formulas gives the same numbers.

## Limitations

- Trading Economics has no free API. If its page layout changes or blocks the server, the app falls back to the snapshot. You can also type the yields in manually.
- Damodaran betas are for U.S. firms. Using them abroad assumes the business risk is the same.
- No country risk premium is added. The cost of equity differs between currencies only through the parity term.
