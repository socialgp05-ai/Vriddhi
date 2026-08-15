import streamlit as st
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
import io

# ==========================================
# 0. CONFIGURATION & STATE
# ==========================================
st.set_page_config(
    page_title="AI Finance & Growth Decision Engine",
    page_icon="📈",
    layout="wide"
)

if 'financial_data' not in st.session_state:
    st.session_state.financial_data = None
if 'company_ticker' not in st.session_state:
    st.session_state.company_ticker = "HONASA"

# Preset Indian Listed Equities (Screener.in Tickers)
POPULAR_COMPANIES = {
    "Honasa Consumer Ltd.": "HONASA",
    "Nykaa (FSN E-Commerce)": "NYKAA",
    "Tata Consumer Products": "TATACONSUM",
    "Zomato Ltd.": "ZOMATO",
    "Dabur India": "DABUR",
    "Hindustan Unilever": "HINDUNILVR"
}

# ==========================================
# 1. SCREENER.IN DATA PIPELINE (LIVE & FREE)
# ==========================================
@st.cache_data(ttl=3600)
def fetch_screener_data(ticker):
    base_url = f"https://www.screener.in/company/{ticker}/consolidated/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    
    try:
        res = requests.get(base_url, headers=headers, timeout=10)
        
        # If consolidated doesn't exist, try standalone
        if res.status_code == 404:
            base_url = f"https://www.screener.in/company/{ticker}/"
            res = requests.get(base_url, headers=headers, timeout=10)
            
        if res.status_code != 200:
            return {"status": "ERROR", "message": f"Could not connect to Screener.in for {ticker}."}

        soup = BeautifulSoup(res.text, "html.parser")
        
        def extract_table(section_id):
            section = soup.find("section", id=section_id)
            if section:
                table = section.find("table")
                if table:
                    # Parse HTML table to Pandas DataFrame
                    df = pd.read_html(io.StringIO(str(table)))[0]
                    df.set_index(df.columns[0], inplace=True)
                    return df
            return None
            
        pl = extract_table("profit-loss")
        bs = extract_table("balance-sheet")
        cf = extract_table("cash-flow")
        
        if pl is None:
            return {"status": "ERROR", "message": "Failed to parse financial tables from Screener.in"}

        return {
            "status": "SUCCESS",
            "income": pl,
            "balance": bs,
            "cashflow": cf,
            "url": base_url
        }
    except Exception as e:
        return {"status": "ERROR", "message": f"Scraping Error: {str(e)}"}

def build_evidence_ledger(data_dict, ticker):
    ledger = []
    pl = data_dict["income"]
    
    # Filter out TTM to compare full financial years
    cols = [c for c in pl.columns if "TTM" not in str(c)]
    if len(cols) < 2:
        return pd.DataFrame()
        
    latest_col = cols[-1]
    prev_col = cols[-2]
    
    def get_val(df, row_name, col):
        if df is not None:
            for idx in df.index:
                if str(idx).startswith(row_name):
                    try:
                        return float(str(df.loc[idx, col]).replace(',', ''))
                    except:
                        return None
        return None

    rev_curr = get_val(pl, "Sales", latest_col)
    rev_prev = get_val(pl, "Sales", prev_col)
    op_curr = get_val(pl, "Operating Profit", latest_col)
    pat_curr = get_val(pl, "Net Profit", latest_col)
    
    # 1. Revenue
    if rev_curr is not None:
        ledger.append({
            "Metric": "Revenue",
            "Period": latest_col,
            "Value": rev_curr,
            "Unit": "INR Crores",
            "Status": "REPORTED",
            "Source": f"Screener.in ({ticker})",
            "Doc/URL": data_dict["url"]
        })
        
    # 2. Revenue Growth
    if rev_curr and rev_prev and rev_prev != 0:
        growth = ((rev_curr - rev_prev) / rev_prev) * 100
        ledger.append({
            "Metric": "Revenue YoY Growth",
            "Period": f"{prev_col} to {latest_col}",
            "Value": growth,
            "Unit": "%",
            "Status": "DERIVED",
            "Source": "Engine Calculation",
            "Doc/URL": "Derived"
        })
        
    # 3. EBITDA (Operating Profit)
    if op_curr is not None:
        ledger.append({
            "Metric": "EBITDA",
            "Period": latest_col,
            "Value": op_curr,
            "Unit": "INR Crores",
            "Status": "REPORTED",
            "Source": f"Screener.in ({ticker})",
            "Doc/URL": data_dict["url"]
        })
        if rev_curr:
            ledger.append({
                "Metric": "EBITDA Margin",
                "Period": latest_col,
                "Value": (op_curr / rev_curr) * 100,
                "Unit": "%",
                "Status": "DERIVED",
                "Source": "Engine Calculation",
                "Doc/URL": "Derived"
            })
            
    # 4. PAT
    if pat_curr is not None:
        ledger.append({
            "Metric": "PAT (Net Profit)",
            "Period": latest_col,
            "Value": pat_curr,
            "Unit": "INR Crores",
            "Status": "REPORTED",
            "Source": f"Screener.in ({ticker})",
            "Doc/URL": data_dict["url"]
        })
        
    # 5. Non-GAAP / D2C Unit Economics Flagging
    for missing_metric in ["Gross Margin", "CAC", "LTV", "AOV"]:
        ledger.append({
            "Metric": missing_metric,
            "Period": latest_col,
            "Value": np.nan,
            "Unit": "N/A",
            "Status": "UNAVAILABLE",
            "Source": "Not separated in standard filings",
            "Doc/URL": "Requires Internal MIS Upload"
        })

    return pd.DataFrame(ledger)


# ==========================================
# 2. UI & SIDEBAR CONFIGURATION
# ==========================================
st.sidebar.title("Decision Engine (Screener.in Edition)")
st.sidebar.caption("100% Free Live Pipeline for Indian Equities")

st.sidebar.divider()

# Company Selector
selected_company_name = st.sidebar.selectbox("Select Listed Company", list(POPULAR_COMPANIES.keys()) + ["Custom Ticker"])
if selected_company_name == "Custom Ticker":
    active_ticker = st.sidebar.text_input("Enter Screener.in Ticker (e.g., ZOMATO, ITC)", value="ZOMATO").strip().upper()
else:
    active_ticker = POPULAR_COMPANIES[selected_company_name]

# Fetch Trigger
if st.sidebar.button("🔄 Fetch Live Financials", use_container_width=True) or st.session_state.financial_data is None:
    with st.spinner(f"Extracting verified tables from Screener.in for {active_ticker}..."):
        res = fetch_screener_data(active_ticker)
        if res.get("status") == "SUCCESS":
            st.session_state.financial_data = res
            st.session_state.evidence_df = build_evidence_ledger(res, active_ticker)
            st.session_state.company_ticker = active_ticker
            st.toast("Data extracted successfully from Screener.in!", icon="✅")
        else:
            st.error(res.get("message"))

menu = ["Executive Dashboard", "WHY Analysis Engine", "Scenario Engine", "Evidence Ledger"]
choice = st.sidebar.radio("Navigation", menu)

df_ledger = st.session_state.get('evidence_df', pd.DataFrame())

# ==========================================
# 3. MODULE VIEWS
# ==========================================
if choice == "Executive Dashboard":
    st.header(f"Executive Financial Overview")
    
    if df_ledger.empty:
        st.info("Click 'Fetch Live Financials' in the sidebar.")
    else:
        st.subheader(f"Target: {st.session_state.company_ticker}")
        
        def get_metric_val(metric_name):
            match = df_ledger[df_ledger['Metric'] == metric_name]
            if not match.empty and pd.notna(match['Value'].values[0]):
                return match['Value'].values[0]
            return None

        rev = get_metric_val("Revenue")
        growth = get_metric_val("Revenue YoY Growth")
        ebitda = get_metric_val("EBITDA")
        ebitda_m = get_metric_val("EBITDA Margin")
        pat = get_metric_val("PAT (Net Profit)")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Revenue (Latest FY)", f"₹{rev:,.0f} Cr" if rev else "N/A", f"{growth:+.1f}% YoY" if growth else None)
        c2.metric("EBITDA", f"₹{ebitda:,.0f} Cr" if ebitda else "N/A", f"{ebitda_m:.1f}% Margin" if ebitda_m else None)
        c3.metric("PAT (Net Profit)", f"₹{pat:,.0f} Cr" if pat else "N/A")
        c4.metric("Data Source", "Screener.in", "Verified")

        st.divider()
        st.markdown(f"**Primary Source Verification Link:** [Open {st.session_state.company_ticker} on Screener.in]({st.session_state.financial_data['url']})")

elif choice == "WHY Analysis Engine":
    st.header("The WHY Engine: Root Cause Analysis")
    st.caption("Step-by-step causality derivation grounded in verified filings.")
    
    if df_ledger.empty:
        st.warning("Please fetch live data first.")
    else:
        growth_match = df_ledger[df_ledger['Metric'] == 'Revenue YoY Growth']
        growth_val = growth_match['Value'].values[0] if not growth_match.empty else None

        st.markdown(f"""
        * **Observation (Past → Present):**
          * Reported Revenue YoY change: **{f'{growth_val:+.1f}%' if growth_val is not None else 'Insufficient Period History'}**.
        * **Driver Breakdown Request:**
          * Note: Standard Screener.in tables provide macro-level P&L. To drill down into specific price/volume drivers, the Engine requires **Management Discussion & Analysis (MD&A)** documents or internal MIS uploads.
        * **Status of Non-GAAP D2C Drivers (CAC / AOV / LTV):**
          * `INSUFFICIENT DATA — ANALYSIS NOT ESTABLISHED` (Not disclosed in statutory filings).
        """)

elif choice == "Scenario Engine":
    st.header("Scenario & Sensitivity Engine")
    st.error("ASSUMPTIONS - NOT COMPANY FORECASTS")
    
    if df_ledger.empty:
        st.warning("Fetch data first.")
    else:
        rev_val = df_ledger[df_ledger['Metric'] == 'Revenue']['Value'].values[0]
        
        col1, col2 = st.columns(2)
        with col1:
            vol_change = st.slider("Volume Growth Lever (%)", -30.0, 50.0, 10.0)
            target_margin = st.slider("Target EBITDA Margin (%)", -10.0, 40.0, 10.0)
            
        with col2:
            sim_rev = rev_val * (1 + (vol_change / 100))
            sim_ebitda = sim_rev * (target_margin / 100)
            
            st.metric("Simulated Revenue", f"₹{sim_rev:,.0f} Cr")
            st.metric("Simulated EBITDA", f"₹{sim_ebitda:,.0f} Cr")

elif choice == "Evidence Ledger":
    st.header("The Evidence Ledger")
    st.write("Automatically extracts and normalizes the statutory tables from Screener.in.")
    if df_ledger.empty:
        st.info("No active ledger.")
    else:
        st.dataframe(
            df_ledger.style.applymap(
                lambda val: 'background-color: #ffcccc' if val == 'UNAVAILABLE' 
                else ('background-color: #ccffcc' if val == 'REPORTED' 
                else ('background-color: #e6f2ff' if val == 'DERIVED' else '')),
                subset=['Status']
            ),
            use_container_width=True
        )
