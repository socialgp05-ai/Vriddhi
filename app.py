import re
import pdfplumber
import pandas as pd
import numpy as np

def parse_indas_pdf(pdf_bytes):
    """
    Robust Ind-AS Consolidated P&L Extractor:
    - Eliminates the 'Note No.' column trap (Notes 23, 27, 28, 29, 30).
    - Detects reporting unit (Millions vs Lakhs vs Crores) and normalizes to INR Crores.
    - Captures both periods accurately.
    """
    with pdfplumber.open(pdf_bytes) as pdf:
        target_page = None
        target_text = ""
        unit_multiplier = 1.0  # Default: In Crores (1.0)
        
        # Step 1: Scan for the Consolidated P&L Page
        for page in pdf.pages:
            text = page.extract_text() or ""
            text_lower = text.lower()
            
            if ("statement of profit and loss" in text_lower or "profit and loss statement" in text_lower) and \
               ("revenue from operations" in text_lower or "total income" in text_lower):
                target_page = page
                target_text = text
                
                # Detect Unit Scale from header
                if "in million" in text_lower or "in mn" in text_lower or "₹ in million" in text_lower:
                    unit_multiplier = 0.1  # 1 Million = 0.1 Crore (divide by 10)
                elif "in lakh" in text_lower or "in lac" in text_lower or "₹ in lakhs" in text_lower:
                    unit_multiplier = 0.01 # 1 Lakh = 0.01 Crore (divide by 100)
                elif "in crore" in text_lower or "₹ in crore" in text_lower:
                    unit_multiplier = 1.0
                break
                
        if not target_page:
            return None, None

        # Step 2: Line-by-Line Token Analysis (handling Note Column)
        lines = target_text.split("\n")
        
        # Identify Year Headers (e.g. 2025 and 2024 or FY25 and FY24)
        found_years = re.findall(r'(?:20\d{2}|FY\d{2})', target_text)
        unique_years = [y for i, y in enumerate(found_years) if y not in found_years[:i]]
        
        if len(unique_years) >= 2:
            # P&L headers in India are: [Current Year (e.g. 2025), Previous Year (e.g. 2024)]
            curr_year = unique_years[0]
            prev_year = unique_years[1]
        else:
            curr_year, prev_year = "FY25", "FY24"
            
        periods = [prev_year, curr_year]

        # Key Ind-AS line items to search
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
                    # Extract all numbers from this line
                    raw_numbers = re.findall(r'\(?[\d,]+\.\d+\)?|\(?[\d,]+\)?', line)
                    cleaned_nums = []
                    
                    for num in raw_numbers:
                        # Clean parentheses (negative numbers) and commas
                        n_str = num.replace(',', '').replace('(', '-').replace(')', '').strip()
                        try:
                            val = float(n_str)
                            cleaned_nums.append(val)
                        except ValueError:
                            continue
                    
                    if not cleaned_nums:
                        continue
                        
                    # CRUCIAL: Remove Note number if present
                    # If 3 numbers exist: [Note No (1-2 digits, integer-like), Current Year Val, Previous Year Val]
                    if len(cleaned_nums) >= 3:
                        val_curr = cleaned_nums[1] * unit_multiplier
                        val_prev = cleaned_nums[2] * unit_multiplier
                    elif len(cleaned_nums) == 2:
                        val_curr = cleaned_nums[0] * unit_multiplier
                        val_prev = cleaned_nums[1] * unit_multiplier
                    else:
                        continue
                        
                    # Cumulative addition for COGS (materials + stock in trade + inventory changes)
                    if field == "COGS":
                        extracted_raw[field][0] += val_prev
                        extracted_raw[field][1] += val_curr
                    else:
                        if extracted_raw[field] == [0.0, 0.0]:
                            extracted_raw[field] = [val_prev, val_curr]
                    break

        # Step 3: Build Standard Ind-AS DataFrame in INR Crores
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
            
            # Derived EBITDA = Gross Profit - Employee Exp - Other Opex
            ebitda = gp - emp - oth if (emp > 0 or oth > 0) else (extracted_raw["PBT"][p_idx] + extracted_raw["Depreciation"][p_idx] + extracted_raw["Finance Cost"][p_idx])
            dep = extracted_raw["Depreciation"][p_idx]
            fin = extracted_raw["Finance Cost"][p_idx]
            pbt = extracted_raw["PBT"][p_idx]
            pat = extracted_raw["PAT"][p_idx]
            
            df[p_name] = [rev, cogs, gp, emp, oth, ebitda, dep, fin, pbt, pat]

        return df, periods
