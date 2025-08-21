import streamlit as st
from google.cloud import firestore
import google.auth
import pandas as pd
from google.cloud.firestore import FieldFilter
from io import BytesIO
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import numpy as np
import time
import zipfile
import os
import pytz
import random
from scipy import signal
from scipy.stats import skew, kurtosis
from collections import defaultdict
import matplotlib.dates as mdates
import plotly.express as px
import plotly.graph_objects as go
from google.api_core.exceptions import ResourceExhausted, RetryError
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Table, TableStyle
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Line
import tempfile
import base64
import plotly.io as pio
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import kaleido

# Set browser path for kaleido
os.environ["BROWSER_PATH"] = "/usr/bin/chromium"  
st.set_page_config(layout="wide", page_title="Trebirth Scan Report Viewer")

# Redirect to login page if not authenticated
if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
    st.warning("Please log in first.")
    st.switch_page("main4.py")

# Initialize authentication state
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "company" not in st.session_state:
    st.session_state["company"] = None

# Define company login credentials
company_credentials = {
    "Hlabs": "H2025$$",
    "Ilabs": "I2025$$",
    "PCI": "P2025$$",
    "Vlabs": "V2025$$",
    "Trebirth": "T2025$$"
}

def logout():
    """Handle logout"""
    st.session_state["authenticated"] = False
    st.session_state["company"] = None
    for key in list(st.session_state.keys()):
        if key.startswith(('selected_', 'filtered_')):
            del st.session_state[key]
    st.rerun()

# Initialize Firestore
@st.cache_resource
def init_firestore():
    try:
        return firestore.Client.from_service_account_info(st.secrets["firebase_admin"])
    except Exception:
        st.error("Firebase configuration not found in Streamlit secrets. Please check your secrets configuration.")
        st.stop()
        return None

db = init_firestore()

def exponential_backoff(retries):
    base_delay = 1
    max_delay = 60
    delay = base_delay * (2 ** retries) + random.uniform(0, 1)
    return min(delay, max_delay)

@st.cache_data
def fetch_data(company_name):
    if not db:
        return [], {}, []
    
    query = db.collection('homescan2')
    docs = query.stream()

    locations = set()
    city_to_areas = {}
    scans_data = []

    for doc in docs:
        data = doc.to_dict()
        company = data.get("CompanyName", "").strip()

        if company == company_name:
            location = data.get("City", "").strip()
            if location:
                locations.add(location)

                area = data.get("Area", "").strip()
                if area:
                    if location not in city_to_areas:
                        city_to_areas[location] = set()
                    city_to_areas[location].add(area)

            timestamp_str = data.get("timestamp")
            scan_date = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").strftime('%Y-%m-%d') if timestamp_str else "Unknown Date"
            data["scan_date"] = scan_date
            scans_data.append(data)

    return sorted(locations), city_to_areas, scans_data

def main():
    company_name = st.session_state["company"]
    
    # Custom CSS
    st.markdown(
        """
        <style>
        .main-header {
            font-size: 2.2rem;
            color: #1f4e79;
            text-align: center;
            margin-bottom: 2rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Sidebar
    with st.sidebar:
        st.title(f"Welcome, {company_name}!")
        if st.button("Logout", type="secondary"):
            logout()
        
        st.markdown("---")
        
        # Fetch data
        locations, city_to_areas, scans_data = fetch_data(company_name)

        # --- Location selection (single select) ---
        st.subheader("Filters")
        selected_location = st.selectbox("Select Report Location:", locations, key="selected_location")

        # --- Area selection (single select) ---
        filtered_areas = city_to_areas.get(selected_location, [])
        selected_area = st.selectbox("Select Report Area:", sorted(filtered_areas), key="selected_area")

        # --- Month selection ---
        scan_months = set()
        for scan in scans_data:
            if scan["City"].strip() == selected_location and scan["Area"].strip() == selected_area:
                scan_date_obj = datetime.strptime(scan.get("scan_date", "1970-01-01"), '%Y-%m-%d')
                scan_months.add(scan_date_obj.strftime("%Y-%m"))  # "YYYY-MM"

        scan_months = sorted(list(scan_months))
        selected_month = st.selectbox("Select scan month:", scan_months, key="selected_month")

    # --- Main content ---
    st.markdown('<h1 class="main-header">Trebirth Scan Report Viewer</h1>', unsafe_allow_html=True)

    if selected_location and selected_area and selected_month:
        final_scans = [
            scan for scan in scans_data 
            if scan["City"].strip() == selected_location
            and scan["Area"].strip() == selected_area
            and scan.get("scan_date", "1970-01-01").startswith(selected_month)
            and scan["CompanyName"].strip() == company_name
        ]

        if final_scans:
            st.subheader(f"All Scans for {selected_area} in {selected_month}")

            # Show as table
            col1, col2, col3 = st.columns([3, 2, 2])
            with col1: st.write("**Apartment**")
            with col2: st.write("**Date of Scan**")
            with col3: st.write("**Incharge**")
            st.markdown("---")

            for scan in final_scans:
                col1, col2, col3 = st.columns([3, 2, 2])
                with col1: st.write(scan.get("Apartment", "N/A"))
                with col2: st.write(scan.get("scan_date", "Unknown Date"))
                with col3: st.write(scan.get("Incharge", "N/A"))
                st.markdown("---")

            # CSV Export
            df = pd.DataFrame(final_scans)
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Download All Data as CSV",
                data=csv,
                file_name=f"trebirth_scans_{selected_area}_{selected_month}.csv",
                mime="text/csv"
            )
        else:
            st.warning("No scans available for the selected criteria.")
    else:
        st.info("Please make all selections in the sidebar to view available reports.")

if __name__ == "__main__":
    main()
