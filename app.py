import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import requests
import io
import re
from bs4 import BeautifulSoup
import pdfplumber

# ==============================================================================
# AI FINANCE & GROWTH DECISION ENGINE (v4.0 ENTERPRISE DOCUMENT INTELLIGENCE)
# ==============================================================================
# 1. PRIMARY SOURCE ONLY: Fetches directly from Company IR websites.
# 2. ALGORITHMIC EXTRACTION: Parses Ind-AS PDFs dynamically (adapts to FY26+).
# 3. FULL ANALYTICAL SUITE: Scenarios, Gap Analysis, and WHY Engine scale dynamically.
# ==============================================================================

st.set_page_config(page_title="AI Finance Engine v4.0", layout="wide")

st.markdown("""
<style>
    .main-header { font-size: 26px; font-weight: 700; color: #0F172A; }
    .status-badge { padding: 4px 10px; border-radius: 4px; font-weight: 600; font-size: 12px; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. PRIMARY SOURCE FETCHER (IR WEBSITE SCRAPER)
# ==============================================================================
def scrape_ir_website(url):
    # Scrapes the official company IR page to locate the latest financial PDFs
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        pdf_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            # Look for PDF links related to results or financials
            if '.pdf' in href.lower() and any(kw in href.lower() for kw in ['result', 'financial', 'earnings', 'presentation', 'q4', 'fy26']):
                link_text = a.text.strip() or href.split('/')[-1]
                if not href.startswith('http'):
                    # Handle relative URLs
                    base = '/'.join(url.split('/')[:3])
                    href = base + href if href.startswith('/') else base + '/' + href
                pdf_links.append({"Document Name": link_text, "URL": href})
        
        # Deduplicate
        unique_links = {v['URL']:v for v in pdf_links}.values()
        return list(unique_links)
    except Exception as e:
        return str(e)

# ==============================================================================
# 2. IND-AS ALGORITHMIC PDF PARSER (NO HARDCODING)
# ==============================================================================
def parse_indas_pdf(pdf_bytes):
    """
    Intelligently searches the entire Annual Report (200+ pages)
    for the Consolidated Statement of Profit and Loss.
    """
    extracted_data = {}
    periods = []
    target_page_idx = None
    
    with pdfplumber.open(pdf_bytes) as pdf:
        total_pages = len(pdf.pages)
        
        # Step 1: Scan all pages to find the exact Consolidated P&L statement
        for idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            text_lower = text.lower()
            
            # Target Ind-AS Consolidated Statement of Profit and Loss
            if ("statement of profit and loss" in text_lower or "profit and loss account" in text_lower) and \
               ("revenue from operations" in text_lower or "total income" in text_lower):
                # Prioritize Consolidated if present
                if "consolidated" in text_lower:
                    target_page_idx = idx
                    break
                elif target_page_idx is None:
                    target_page_idx = idx
        
        if target_page_idx is None:
            return None, None

        # Step 2: Extract text and tables from the target P&L page (+ next page if spilled over)
        target_pages = [pdf.pages[target_page_idx]]
        if target_page_idx + 1 < total_pages:
            target_pages.append(pdf.pages[target_page_idx + 1])
            
        full_text = "\n".join([p.extract_text() or "" for p in target_pages])
        
        # Step 3: Identify Period Headers (e.g., Year ended March 31, 2026 / 2025)
        found_years = re.findall(r'(?:20\d{2}|FY\d{2})', full_text)
        unique_years = []
        for y in found_years:
            if y not in unique_years:
                unique_years.append(y)
        
        if len(unique_years) >= 2:
            periods = [unique_years[1], unique_years[0]]  # [Prior Year, Latest Year]
        else:
            periods = ["Prior Period", "Latest Period"]

        # Step 4: Extract Standard Ind-AS Metrics using regex across the P&L text
        metric_patterns = {
            "Revenue": [r'revenue from operations[^\d\n\-]*([\d,\.\(\)]+)[^\d\n\-]+([\d,\.\(\)]+)',
                        r'total income[^\d\n\-]*([\d,\.\(\)]+)[^\d\n\-]+([\d,\.\(\)]+)'],
            "COGS": [r'cost of materials consumed[^\d\n\-]*([\d,\.\(\)]+)[^\d\n\-]+([\d,\.\(\)]+)',
                     r'purchases of stock-in-trade[^\d\n\-]*([\d,\.\(\)]+)[^\d\n\-]+([\d,\.\(\)]+)'],
            "Employee Expense": [r'employee benefits? expense[^\d\n\-]*([\d,\.\(\)]+)[^\d\n\-]+([\d,\.\(\)]+)'],
            "Other Expenses": [r'other expenses[^\d\n\-]*([\d,\.\(\)]+)[^\d\n\-]+([\d,\.\(\)]+)'],
            "Depreciation": [r'depreciation and amortisation[^\d\n\-]*([\d,\.\(\)]+)[^\d\n\-]+([\d,\.\(\)]+)'],
            "Finance Cost": [r'finance costs?[^\d\n\-]*([\d,\.\(\)]+)[^\d\n\-]+([\d,\.\(\)]+)'],
            "PBT": [r'profit before tax[^\d\n\-]*([\d,\.\(\)]+)[^\d\n\-]+([\d,\.\(\)]+)'],
            "PAT": [r'profit for the (?:year|period)[^\d\n\-]*([\d,\.\(\)]+)[^\d\n\-]+([\d,\.\(\)]+)',
                    r'total comprehensive income[^\d\n\-]*([\d,\.\(\)]+)[^\d\n\-]+([\d,\.\(\)]+)']
        }

        def clean_val(raw_str):
            cleaned = str(raw_str).replace(',', '').replace('(', '-').replace(')', '').strip()
            try:
                return float(cleaned)
            except:
                return 0.0

        parsed_metrics = {}
        for metric, patterns in metric_patterns.items():
            for pat in patterns:
                match = re.search(pat, full_text, re.IGNORECASE)
                if match:
                    val_latest = clean_val(match.group(1))
                    val_prior = clean_val(match.group(2))
                    parsed_metrics[metric] = [val_prior, val_latest]
                    break

        if "Revenue" not in parsed_metrics:
            return None, None

        # Build Standardized P&L DataFrame
        final_df = pd.DataFrame(index=[
            "Revenue", "COGS", "Employee Expense", "Other Expenses", 
            "EBITDA", "Depreciation", "Finance Cost", "PBT", "PAT"
        ])
        
        for p_idx, p_name in enumerate(periods):
            rev = parsed_metrics.get("Revenue", [0, 0])[p_idx]
            cogs = abs(parsed_metrics.get("COGS", [0, 0])[p_idx])
            emp = abs(parsed_metrics.get("Employee Expense", [0, 0])[p_idx])
            oth = abs(parsed_metrics.get("Other Expenses", [0, 0])[p_idx])
            dep = abs(parsed_metrics.get("Depreciation", [0, 0])[p_idx])
            fin = abs(parsed_metrics.get("Finance Cost", [0, 0])[p_idx])
            pat = parsed_metrics.get("PAT", [0, 0])[p_idx]
            pbt = parsed_metrics.get("PBT", [0, 0])[p_idx]
            
            # Derive EBITDA
            ebitda = rev - cogs - emp - oth if (cogs or emp or oth) else (pbt + dep + fin)
            
            final_df[p_name] = [rev, cogs, emp, oth, ebitda, dep, fin, pbt, pat]

        return final_df, periods
# ==============================================================================
# 3. SIDEBAR: DYNAMIC DATA INGESTION
# ==============================================================================
st.sidebar.title("AI Decision Engine v4.0")
st.sidebar.caption("Primary Source & Document Intelligence")
st.sidebar.divider()

input_mode = st.sidebar.radio("Data Ingestion Mode", ["1. Scan IR Website (Auto-Fetch)", "2. Upload Official PDF / MIS"])

if input_mode == "1. Scan IR Website (Auto-Fetch)":
    ir_url = st.sidebar.text_input("Enter Company IR URL", value="https://honasa.in/investor-relations/")
    if st.sidebar.button("Scan for Latest Documents"):
        with st.spinner("Scraping official website for latest filings..."):
            links = scrape_ir_website(ir_url)
            if isinstance(links, list) and links:
                st.session_state.pdf_links = links
                st.sidebar.success(f"Found {len(links)} documents.")
            else:
                st.sidebar.error("Could not locate PDF filings. Try uploading manually.")
                
    if 'pdf_links' in st.session_state:
        selected_pdf = st.sidebar.selectbox("Select Document to Parse", [doc['Document Name'] for doc in st.session_state.pdf_links])
        if st.sidebar.button("Extract Financials"):
            doc_url = next(item['URL'] for item in st.session_state.pdf_links if item['Document Name'] == selected_pdf)
            with st.spinner(f"Downloading & Parsing {selected_pdf}..."):
                try:
                    res = requests.get(doc_url, headers={'User-Agent': 'Mozilla/5.0'})
                    pdf_bytes = io.BytesIO(res.content)
                    df, periods = parse_indas_pdf(pdf_bytes)
                    if df is not None:
                        st.session_state.live_df = df
                        st.session_state.periods = periods
                        st.session_state.source_doc = doc_url
                        st.sidebar.success("Extraction Successful.")
                    else:
                        st.sidebar.error("Failed to map Ind-AS table structures. Please upload a standard CSV/MIS.")
                except Exception as e:
                    st.sidebar.error(f"Error parsing PDF: {e}")

elif input_mode == "2. Upload Official PDF / MIS":
    uploaded_file = st.sidebar.file_uploader("Upload Primary PDF / CSV", type=["pdf", "csv"])
    if uploaded_file and st.sidebar.button("Process Upload"):
        with st.spinner("Executing document parsing algorithms..."):
            if uploaded_file.name.endswith('.pdf'):
                df, periods = parse_indas_pdf(uploaded_file)
                if df is not None:
                    st.session_state.live_df = df
                    st.session_state.periods = periods
                    st.session_state.source_doc = "USER PROVIDED — NOT INDEPENDENTLY VERIFIED"
                    st.sidebar.success("Extraction Successful.")
                else:
                    st.sidebar.error("Table mapping failed. Ensure PDF contains standard financial schedules.")
            else:
                # Handle CSV fallback
                df = pd.read_csv(uploaded_file, index_col=0)
                st.session_state.live_df = df
                st.session_state.periods = df.columns.tolist()
                st.session_state.source_doc = "USER PROVIDED — NOT INDEPENDENTLY VERIFIED"
                st.sidebar.success("CSV Uploaded.")

st.sidebar.divider()
nav_module = st.sidebar.radio("Executive Modules", [
    "1. Executive Financial Overview",
    "2. The WHY Engine (Root Cause)",
    "3. Growth & Gap Analysis",
    "4. Scenario Decision Simulator",
    "5. Evidence & Source Ledger"
])

# ==============================================================================
# 4. CORE ANALYTICAL MODULES (DYNAMIC)
# ==============================================================================
if 'live_df' not in st.session_state:
    st.info("👈 Please execute a data ingestion method in the sidebar to initialize the AI Engine.")
else:
    df = st.session_state.live_df
    periods = st.session_state.periods
    curr_col = periods[-1]
    prev_col = periods[0]
    
    # Calculate baseline metrics dynamically
    rev_curr = df.loc["Revenue", curr_col]
    rev_prev = df.loc["Revenue", prev_col]
    rev_yoy = ((rev_curr - rev_prev) / rev_prev) * 100 if rev_prev else 0
    
    ebitda_curr = df.loc["EBITDA", curr_col]
    ebitda_prev = df.loc["EBITDA", prev_col]
    ebitda_margin_curr = (ebitda_curr / rev_curr) * 100 if rev_curr else 0
    ebitda_margin_prev = (ebitda_prev / rev_prev) * 100 if rev_prev else 0
    
    if nav_module == "1. Executive Financial Overview":
        st.markdown('<p class="main-header">Dynamic Executive Dashboard</p>', unsafe_allow_html=True)
        st.markdown(f"**Primary Source:** [{st.session_state.source_doc}]({st.session_state.source_doc})")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"Revenue ({curr_col})", f"{rev_curr:,.2f}", f"{rev_yoy:+.1f}% YoY")
        c2.metric(f"EBITDA ({curr_col})", f"{ebitda_curr:,.2f}", f"Margin: {ebitda_margin_curr:.1f}%")
        c3.metric(f"PAT ({curr_col})", f"{df.loc['PAT', curr_col]:,.2f}")
        c4.metric(f"COGS Intensity", f"{(df.loc['COGS', curr_col]/rev_curr)*100:.1f}% of Rev")
        
        st.divider()
        st.subheader("Extracted Multi-Period Financial Matrix")
        display_df = df.copy()
        display_df["Variance (Abs)"] = display_df[curr_col] - display_df[prev_col]
        display_df["Variance (%)"] = (display_df["Variance (Abs)"] / abs(display_df[prev_col])) * 100
        display_df = display_df.fillna(0)
        st.dataframe(display_df.style.format("{:.2f}"), use_container_width=True)

    elif nav_module == "2. The WHY Engine (Root Cause)":
        st.markdown('<p class="main-header">The WHY Engine: Variance Attribution</p>', unsafe_allow_html=True)
        st.markdown("Causality derivation grounded exactly in the extracted numbers. No assumptions.")
        
        st.subheader("Observation Matrix")
        st.markdown(f"""
        * **Top-Line:** Revenue shifted by {rev_yoy:+.1f}%.
        * **Operating Profit:** EBITDA margin moved from {ebitda_margin_prev:.2f}% to {ebitda_margin_curr:.2f}%.
        """)
        
        st.subheader("Cost Driver Decomposition")
        cost_df = pd.DataFrame({
            "Cost Element": ["COGS", "Employee Expense", "Other Expenses"],
            f"{prev_col} (% of Rev)": [(df.loc["COGS", prev_col]/rev_prev)*100 if rev_prev else 0, (df.loc["Employee Expense", prev_col]/rev_prev)*100 if rev_prev else 0, (df.loc["Other Expenses", prev_col]/rev_prev)*100 if rev_prev else 0],
            f"{curr_col} (% of Rev)": [(df.loc["COGS", curr_col]/rev_curr)*100 if rev_curr else 0, (df.loc["Employee Expense", curr_col]/rev_curr)*100 if rev_curr else 0, (df.loc["Other Expenses", curr_col]/rev_curr)*100 if rev_curr else 0]
        })
        cost_df["Margin Impact (bps)"] = (cost_df[f"{prev_col} (% of Rev)"] - cost_df[f"{curr_col} (% of Rev)"]) * 100
        st.dataframe(cost_df, use_container_width=True)
        
        st.info("**Engine Finding:** A positive Margin Impact (bps) indicates cost efficiency (the cost shrank relative to revenue), directly bridging the EBITDA delta.")

    elif nav_module == "3. Growth & Gap Analysis":
        st.markdown('<p class="main-header">Gap Analysis & Non-GAAP Metrics</p>', unsafe_allow_html=True)
        
        st.subheader("Identifiable Gaps (Actual vs Extracted History)")
        gap_data = [
            {"Metric": "Revenue Trajectory", "Latest Actual": f"{rev_yoy:+.1f}%", "Historical Baseline": "Requires Multi-Year Input", "Status": "DERIVED"},
            {"Metric": "EBITDA Margin", "Latest Actual": f"{ebitda_margin_curr:.1f}%", "Historical Baseline": f"{ebitda_margin_prev:.1f}%", "Status": "DERIVED"}
        ]
        st.dataframe(pd.DataFrame(gap_data), use_container_width=True)
        
        st.subheader("D2C Unit Economics (CAC, LTV, AOV, Conversion)")
        st.error("INSUFFICIENT DATA — ANALYSIS NOT ESTABLISHED. These metrics are not disclosed in standard Ind-AS filings extracted above. Please upload internal MIS via CSV to unlock this module.")

    elif nav_module == "4. Scenario Decision Simulator":
        st.markdown('<p class="main-header">Scenario Engine: Strategic Modeling</p>', unsafe_allow_html=True)
        st.error("STRICT GOVERNANCE: ALL SIMULATIONS BELOW ARE USER-DEFINED ASSUMPTIONS, NOT OFFICIAL FORECASTS.")
        
        c1, c2 = st.columns(2)
        with c1:
            st.subheader(f"Strategic Levers (Base: {curr_col})")
            vol_growth = st.slider("Revenue Volume Growth (%)", -20.0, 50.0, 10.0)
            cogs_eff = st.slider("COGS Efficiency (bps improvement)", -300, 300, 50)
            opex_eff = st.slider("Other Opex Efficiency (bps improvement)", -300, 300, 0)
            
        with c2:
            st.subheader("Simulated P&L Impact")
            sim_rev = rev_curr * (1 + (vol_growth/100))
            
            base_cogs_pct = df.loc["COGS", curr_col] / rev_curr
            sim_cogs = sim_rev * (base_cogs_pct - (cogs_eff/10000))
            
            base_emp_pct = df.loc["Employee Expense", curr_col] / rev_curr
            sim_emp = sim_rev * base_emp_pct
            
            base_opex_pct = df.loc["Other Expenses", curr_col] / rev_curr
            sim_opex = sim_rev * (base_opex_pct - (opex_eff/10000))
            
            sim_ebitda = sim_rev - sim_cogs - sim_emp - sim_opex
            sim_ebitda_margin = (sim_ebitda / sim_rev) * 100
            
            st.metric("Simulated Revenue", f"{sim_rev:,.2f}", f"{sim_rev - rev_curr:+,.2f} vs Base")
            st.metric("Simulated EBITDA", f"{sim_ebitda:,.2f}", f"Margin: {sim_ebitda_margin:.2f}%")

    elif nav_module == "5. Evidence & Source Ledger":
        st.markdown('<p class="main-header">Evidence Ledger & Source Traceability</p>', unsafe_allow_html=True)
        st.write(f"All data actively derived from: **{st.session_state.source_doc}**")
        
        ledger_data = []
        for index, row in df.iterrows():
            ledger_data.append({
                "Metric": index,
                "Value Extracted": row[curr_col],
                "Period": curr_col,
                "Status": "DERIVED" if index == "EBITDA" else "REPORTED",
                "Extraction Provenance": "Algorithmic Ind-AS Parse (pdfplumber)"
            })
            
        st.dataframe(pd.DataFrame(ledger_data), use_container_width=True)
