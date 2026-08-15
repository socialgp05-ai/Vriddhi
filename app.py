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

st.set_page_config(page_title="AI Finance Engine v4.1", layout="wide")

st.markdown('''
<style>
    .main-header { font-size: 26px; font-weight: 700; color: #0F172A; }
</style>
''', unsafe_allow_html=True)

def scrape_ir_website(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        pdf_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '.pdf' in href.lower() and any(kw in href.lower() for kw in ['result', 'financial', 'earnings', 'presentation', 'q4', 'fy26']):
                link_text = a.text.strip() or href.split('/')[-1]
                if not href.startswith('http'):
                    base = '/'.join(url.split('/')[:3])
                    href = base + href if href.startswith('/') else base + '/' + href
                pdf_links.append({"Document Name": link_text, "URL": href})
        unique_links = {v['URL']:v for v in pdf_links}.values()
        return list(unique_links)
    except Exception as e:
        return str(e)

def parse_indas_pdf(pdf_bytes):
    with pdfplumber.open(pdf_bytes) as pdf:
        target_page = None
        target_text = ""
        unit_multiplier = 1.0
        
        for page in pdf.pages:
            text = page.extract_text() or ""
            text_lower = text.lower()
            if ("statement of profit and loss" in text_lower or "profit and loss statement" in text_lower) and                ("revenue from operations" in text_lower or "total income" in text_lower):
                target_page = page
                target_text = text
                if "in million" in text_lower or "in mn" in text_lower or "₹ in million" in text_lower:
                    unit_multiplier = 0.1
                elif "in lakh" in text_lower or "in lac" in text_lower or "₹ in lakhs" in text_lower:
                    unit_multiplier = 0.01
                elif "in crore" in text_lower or "₹ in crore" in text_lower:
                    unit_multiplier = 1.0
                break
                
        if not target_page:
            return None, None

        lines = target_text.split("\n")
        found_years = re.findall(r'(?:20\d{2}|FY\d{2})', target_text)
        unique_years = []
        for y in found_years:
            if y not in unique_years:
                unique_years.append(y)
                
        if len(unique_years) >= 2:
            curr_year = unique_years[0]
            prev_year = unique_years[1]
        else:
            curr_year, prev_year = "FY25", "FY24"
            
        periods = [prev_year, curr_year]

        field_keywords = {
            "Revenue": ["revenue from operations", "sale of products"],
            "COGS": ["cost of materials consumed", "purchases of stock-in-trade", "changes in inventories"],
            "Employee Expense": ["employee benefits expense", "employee benefit expenses"],
            "Other Expenses": ["other expenses"],
            "Depreciation": ["depreciation and amortisation", "depreciation and amortization"],
            "Finance Cost": ["finance costs", "finance cost"],
            "PBT": ["profit before tax", "profit before exceptional"],
            "PAT": ["profit for the year", "profit for the period", "total comprehensive income"]
        }

        extracted_raw = {k: [0.0, 0.0] for k in field_keywords}
        
        for line in lines:
            line_clean = line.strip().lower()
            for field, kw_list in field_keywords.items():
                if any(kw in line_clean for kw in kw_list):
                    raw_numbers = re.findall(r'\(?\[\d,\]+\.\d+\)?|\(?\[\d,\]+\)?', line)
                    cleaned_nums = []
                    for num in raw_numbers:
                        n_str = num.replace(',', '').replace('(', '-').replace(')', '').strip()
                        try:
                            val = float(n_str)
                            cleaned_nums.append(val)
                        except ValueError:
                            continue
                    
                    if not cleaned_nums:
                        continue
                        
                    if len(cleaned_nums) >= 3:
                        val_curr = cleaned_nums[1] * unit_multiplier
                        val_prev = cleaned_nums[2] * unit_multiplier
                    elif len(cleaned_nums) == 2:
                        val_curr = cleaned_nums[0] * unit_multiplier
                        val_prev = cleaned_nums[1] * unit_multiplier
                    else:
                        continue
                        
                    if field == "COGS":
                        extracted_raw[field][0] += val_prev
                        extracted_raw[field][1] += val_curr
                    else:
                        if extracted_raw[field] == [0.0, 0.0]:
                            extracted_raw[field] = [val_prev, val_curr]
                    break

        df = pd.DataFrame(index=[
            "Revenue", "COGS", "Gross Profit", "Employee Expense", 
            "Other Expenses", "EBITDA", "Depreciation", "Finance Cost", "PBT", "PAT"
        ])
        
        for p_idx, p_name in enumerate(periods):
            rev = extracted_raw["Revenue"][p_idx]
            cogs = extracted_raw["COGS"][p_idx]
            gp = rev - cogs if rev > 0 else 0.0
            emp = extracted_raw["Employee Expense"][p_idx]
            oth = extracted_raw["Other Expenses"][p_idx]
            
            ebitda = gp - emp - oth if (emp > 0 or oth > 0) else (extracted_raw["PBT"][p_idx] + extracted_raw["Depreciation"][p_idx] + extracted_raw["Finance Cost"][p_idx])
            dep = extracted_raw["Depreciation"][p_idx]
            fin = extracted_raw["Finance Cost"][p_idx]
            pbt = extracted_raw["PBT"][p_idx]
            pat = extracted_raw["PAT"][p_idx]
            
            df[p_name] = [rev, cogs, gp, emp, oth, ebitda, dep, fin, pbt, pat]

        return df, periods

st.sidebar.title("AI Decision Engine v4.1")
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
                        st.sidebar.error("Failed to map Ind-AS table structures.")
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
                    st.session_state.source_doc = "USER PROVIDED"
                    st.sidebar.success("Extraction Successful.")
                else:
                    st.sidebar.error("Table mapping failed. Ensure PDF contains standard financial schedules.")
            else:
                df = pd.read_csv(uploaded_file, index_col=0)
                st.session_state.live_df = df
                st.session_state.periods = df.columns.tolist()
                st.session_state.source_doc = "USER PROVIDED"
                st.sidebar.success("CSV Uploaded.")

st.sidebar.divider()
nav_module = st.sidebar.radio("Executive Modules", [
    "1. Executive Financial Overview",
    "2. The WHY Engine (Root Cause)",
    "3. Scenario Decision Simulator"
])

if 'live_df' in st.session_state:
    df = st.session_state.live_df
    periods = st.session_state.periods
    curr_col = periods[-1]
    prev_col = periods[0]
    
    rev_curr = df.loc["Revenue", curr_col]
    rev_prev = df.loc["Revenue", prev_col]
    rev_yoy = ((rev_curr - rev_prev) / rev_prev) * 100 if rev_prev else 0
    
    ebitda_curr = df.loc["EBITDA", curr_col]
    ebitda_margin_curr = (ebitda_curr / rev_curr) * 100 if rev_curr else 0
    
    if nav_module == "1. Executive Financial Overview":
        st.markdown('<p class="main-header">Dynamic Executive Dashboard</p>', unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"Revenue ({curr_col})", f"{rev_curr:,.2f}", f"{rev_yoy:+.1f}% YoY")
        c2.metric(f"EBITDA ({curr_col})", f"{ebitda_curr:,.2f}", f"Margin: {ebitda_margin_curr:.1f}%")
        c3.metric(f"PAT ({curr_col})", f"{df.loc['PAT', curr_col]:,.2f}")
        c4.metric(f"COGS Intensity", f"{(df.loc['COGS', curr_col]/rev_curr)*100:.1f}% of Rev" if rev_curr else "N/A")
        
        st.divider()
        st.dataframe(df.style.format("{:.2f}"), use_container_width=True)

    elif nav_module == "2. The WHY Engine (Root Cause)":
        st.markdown('<p class="main-header">The WHY Engine: Variance Attribution</p>', unsafe_allow_html=True)
        st.subheader("Cost Driver Decomposition")
        cost_df = pd.DataFrame({
            "Cost Element": ["COGS", "Employee Expense", "Other Expenses"],
            f"{prev_col} (% of Rev)": [(df.loc["COGS", prev_col]/rev_prev)*100 if rev_prev else 0, (df.loc["Employee Expense", prev_col]/rev_prev)*100 if rev_prev else 0, (df.loc["Other Expenses", prev_col]/rev_prev)*100 if rev_prev else 0],
            f"{curr_col} (% of Rev)": [(df.loc["COGS", curr_col]/rev_curr)*100 if rev_curr else 0, (df.loc["Employee Expense", curr_col]/rev_curr)*100 if rev_curr else 0, (df.loc["Other Expenses", curr_col]/rev_curr)*100 if rev_curr else 0]
        })
        cost_df["Margin Impact (bps)"] = (cost_df[f"{prev_col} (% of Rev)"] - cost_df[f"{curr_col} (% of Rev)"]) * 100
        st.dataframe(cost_df, use_container_width=True)
        st.info("**Engine Finding:** A positive Margin Impact (bps) indicates cost efficiency, directly bridging the EBITDA delta.")

    elif nav_module == "4. Scenario Decision Simulator" or nav_module == "3. Scenario Decision Simulator":
        st.markdown('<p class="main-header">Scenario Engine: Strategic Modeling</p>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader(f"Strategic Levers (Base: {curr_col})")
            vol_growth = st.slider("Revenue Volume Growth (%)", -20.0, 50.0, 10.0)
            cogs_eff = st.slider("COGS Efficiency (bps improvement)", -300, 300, 50)
            opex_eff = st.slider("Other Opex Efficiency (bps improvement)", -300, 300, 0)
            
        with c2:
            st.subheader("Simulated P&L Impact")
            sim_rev = rev_curr * (1 + (vol_growth/100))
            base_cogs_pct = (df.loc["COGS", curr_col] / rev_curr) if rev_curr else 0
            sim_cogs = sim_rev * (base_cogs_pct - (cogs_eff/10000))
            base_emp_pct = (df.loc["Employee Expense", curr_col] / rev_curr) if rev_curr else 0
            sim_emp = sim_rev * base_emp_pct
            base_opex_pct = (df.loc["Other Expenses", curr_col] / rev_curr) if rev_curr else 0
            sim_opex = sim_rev * (base_opex_pct - (opex_eff/10000))
            
            sim_ebitda = sim_rev - sim_cogs - sim_emp - sim_opex
            sim_ebitda_margin = (sim_ebitda / sim_rev) * 100 if sim_rev else 0
            
            st.metric("Simulated Revenue", f"{sim_rev:,.2f}", f"{sim_rev - rev_curr:+,.2f} vs Base")
            st.metric("Simulated EBITDA", f"{sim_ebitda:,.2f}", f"Margin: {sim_ebitda_margin:.2f}%")
