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

def login_sidebar():
    """Handle login in sidebar"""
    with st.sidebar:
        st.title("Login")
        company = st.text_input("Company Name")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            if company in company_credentials and company_credentials[company] == password:
                st.session_state["authenticated"] = True
                st.session_state["company"] = company
                st.success(f"Welcome, {company}!")
                st.rerun()
            else:
                st.error("Invalid credentials")

def logout():
    """Handle logout"""
    st.session_state["authenticated"] = False
    st.session_state["company"] = None
    # Clear any selection states
    for key in list(st.session_state.keys()):
        if key.startswith(('selected_', 'filtered_')):
            del st.session_state[key]
    st.rerun()

# Initialize Firestore
@st.cache_resource
def init_firestore():
    try:
        return firestore.Client.from_service_account_info(st.secrets["firebase_admin"])
    except Exception as e:
        st.error("Firebase configuration not found in Streamlit secrets. Please check your secrets configuration.")
        st.stop()
        return None

db = init_firestore()

def exponential_backoff(retries):
    base_delay = 1
    max_delay = 60
    delay = base_delay * (2 ** retries) + random.uniform(0, 1)
    return min(delay, max_delay)

def get_firestore_data(query):
    retries = 0
    max_retries = 10
    while retries < max_retries:
        try:
            results = query.stream()
            return list(results)
        except ResourceExhausted as e:
            st.warning(f"Quota exceeded, retrying... (attempt {retries + 1})")
            time.sleep(exponential_backoff(retries))
            retries += 1
        except RetryError as e:
            st.warning(f"Retry error: {e}, retrying... (attempt {retries + 1})")
            time.sleep(exponential_backoff(retries))
            retries += 1
        except Exception as e:
            st.error(f"An error occurred: {e}")
            break
    raise Exception("Max retries exceeded")

def convert_to_local_time(timestamp, timezone='Asia/Kolkata'):
    local_tz = pytz.timezone(timezone)
    return timestamp.astimezone(local_tz)

def preprocess_radar_data(radar_raw):
    df_radar = pd.DataFrame(radar_raw, columns=['Radar'])
    df_radar.dropna(inplace=True)
    df_radar.fillna(df_radar.mean(), inplace=True)
    return df_radar

def plot_time_domain(preprocessed_scan, device_name, timestamp, scan_duration, sampling_rate=100):
    fig = go.Figure()
    
    time_seconds = np.arange(len(preprocessed_scan)) / sampling_rate
    fig.add_trace(go.Scatter(
        x=time_seconds,
        y=preprocessed_scan['Radar'],
        mode='lines',
        name=f"{device_name} - Unknown Timestamp",
        line=dict(color='blue')
    ))

    fig.update_layout(
        template='plotly_white',
        xaxis_title=None,
        yaxis_title=None,
        xaxis=dict(showticklabels=False),
        yaxis=dict(showticklabels=False),
        legend_title="Scan",
        font=dict(color="black"),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=100, r=100, t=100, b=100),
        shapes=[dict(
            type='rect',
            x0=0,
            y0=0,
            x1=1,
            y1=1,
            xref='paper',
            yref='paper',
            line=dict(
                color="black",
                width=2
            )
        )]
    )
    return fig

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

def generate_pdf_for_apartment(apartment_scans, company_name):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmpfile:
        pdf_path = tmpfile.name
    
    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    styles = getSampleStyleSheet()

    # Apply fonts
    try:
        pdfmetrics.registerFont(TTFont('ARLRDBD', 'Report_Generation_Customer_WebApp/ARLRDBD.TTF'))
        pdfmetrics.registerFont(TTFont('ARIAL', 'Report_Generation_Customer_WebApp/ARIAL.TTF'))
        styles["Heading1"].fontName = 'ARLRDBD'
        styles["Normal"].fontName = 'ARIAL'
    except:
        pass  # Use default fonts if custom fonts not available
    
    heading_style_centered = ParagraphStyle(
        "HeadingStyleCentered", parent=styles["Heading1"], fontSize=20, textColor=colors.darkblue,
        alignment=1, spaceAfter=10, underline=True, bold=True,
    )

    heading_style_left = ParagraphStyle(
        "HeadingStyleLeft", parent=styles["Heading1"], fontSize=20, textColor=colors.darkblue,
        alignment=0, spaceAfter=10, underline=True, bold=True,
    )

    heading_style_sub = ParagraphStyle(
        "HeadingStyleLeft", parent=styles["Heading1"], fontSize=16, textColor=colors.black,
        alignment=0, spaceAfter=10, underline=True, bold=True,
    )
    
    body_style = styles["Normal"]
    body_style.fontSize = 12
    
    elements = []
    elements.append(Paragraph("TREBIRTH TEST REPORT", heading_style_centered))
    elements.append(Spacer(1, 16))
    
    desc_lines = [
        "This Trebirth test report is a supplementary report only and is only a record of the test findings."
    ]
    
    for line in desc_lines:
        elements.append(Paragraph(line, body_style))
        elements.append(Spacer(1, 6))

    elements.append(Spacer(1, 20))
   
    if not apartment_scans:
        elements.append(Paragraph("No data found.", body_style))
    else:
        first_scan = apartment_scans[0]
        test_by = first_scan["CompanyName"]
        report_loc = first_scan["City"]
        apartment_name = first_scan["Apartment"]
        report_date = first_scan["scan_date"]
        
        data = [
            ["Tests were carried out by:", test_by],
            ["Date:", report_date],
            ["Report for location at:", report_loc],
            ["Name of the building/apartment:", apartment_name]
        ]

        table = Table(data, colWidths=[2.5 * inch, 3.5 * inch])
        table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
            ('TEXTCOLOR', (1, 0), (1, -1), colors.darkblue),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black)
        ]))

        elements.append(table)
        elements.append(PageBreak())

        area_scans = {}
        for scan in apartment_scans:
            area = scan.get("Room", "Unknown Area")
            if area not in area_scans:
                area_scans[area] = []
            area_scans[area].append(scan)
                
        for i, (area, scans) in enumerate(area_scans.items(), start=1):
            elements.append(Paragraph(f"{i} {area.upper()}", heading_style_left))
            
            for j, scan in enumerate(scans, start=1):
                elements.append(Paragraph(f"{i}.{j} Radar Scan", heading_style_sub))
                
                radar_raw = scan.get('RadarRaw', [])
                if radar_raw:
                    processed_scan = preprocess_radar_data(radar_raw)
                    device_name = scan.get('Devicename', 'Unknown Device')
                    timestamp = scan.get('timestamp', datetime.now())
                    scan_duration = scan.get("ScanDuration", "Unknown")
                    
                    fig = plot_time_domain(processed_scan, device_name, timestamp, scan_duration)
                
                    img_path = f"{tempfile.gettempdir()}/time_domain_plot_{i}_{j}.png"
                    pio.write_image(fig, img_path, format="png")

                    elements.append(Image(img_path, width=400, height=300))
                    elements.append(Spacer(1, 12))

                    elements.append(Paragraph(f"Device Name: {device_name}", body_style))
                    elements.append(Spacer(1, 3))
                    elements.append(Paragraph(f"Timestamp: {datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')}", body_style))
                    elements.append(Spacer(1, 3))
                    elements.append(Paragraph(f"Scan Duration: {scan_duration}", body_style))
                    elements.append(Spacer(1, 12))
                
                    data = [
                        ["Scan Location:", scan.get("Room", "N/A")],
                        ["Device was:", scan.get("Positioned", "N/A")],
                        ["Damage Visible:", scan.get("DamageVisible", "N/A")],
                    ]
                    table = Table(data, colWidths=[2.5 * inch, 3.5 * inch])
                    table.setStyle(TableStyle([
                        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                        ('ALIGN', (1, 0), (-1, -1), 'LEFT'),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                    ]))

                    elements.append(table)
                    elements.append(Spacer(1, 20))
                    
                    # Clean up temporary image file
                    try:
                        os.remove(img_path)
                    except:
                        pass
    
    doc.build(elements)
    return pdf_path

def main():
    company_name = st.session_state["company"]
    
    # Custom CSS
    st.markdown(
        """
        <style>
        .reportview-container {
            background-color: white;
        }
        .main-header {
            font-size: 2.5rem;
            color: #1f4e79;
            text-align: center;
            margin-bottom: 2rem;
        }
        .data-table {
            margin-top: 2rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Sidebar for authenticated users
    with st.sidebar:
        st.title(f"Welcome, {company_name}!")
        
        if st.button("Logout", type="secondary"):
            logout()
        
        st.markdown("---")
        
        # Fetch data
        locations, city_to_areas, scans_data = fetch_data(company_name)
        
        # Location selection
        st.subheader("Filters")
        selected_locations = st.selectbox("Select Report Location:", locations, key="selected_locations")
        
        # Area selection
        filtered_areas = set()
        for loc in selected_locations:
            if loc in city_to_areas:
                filtered_areas.update(city_to_areas[loc])
        
        selected_areas = st.selectbox("Select Report Area:", sorted(filtered_areas), key="selected_areas")
        
        # Date selection
        selected_date = st.date_input("Select scan date:", key="selected_date")
        selected_date_str = selected_date.strftime("%Y-%m-%d") if selected_date else None
        
        # Filter scans based on selections
        filtered_scans = [
            scan for scan in scans_data 
            if (not selected_locations or scan["City"].strip() in selected_locations)
            and (not selected_areas or scan["Area"].strip() in selected_areas)
            and (not selected_date_str or scan.get("scan_date", "Unknown Date") == selected_date_str)
            and scan["CompanyName"].strip() == company_name
        ]
        
        # Apartment selection
        apartments_info = {}
        if filtered_scans:
            for scan in filtered_scans:
                apartment = scan.get("Apartment", "").strip()
                incharge = scan.get("Incharge", "").strip()
                if apartment:
                    apartments_info[apartment] = incharge
        
        if apartments_info:
            st.subheader("Select Apartments")
            selected_apartments = st.selectbox(
                "Choose apartments:",
                options=list(apartments_info.keys()),
                format_func=lambda x: f"{x} (Incharge: {apartments_info[x]})",
                key="selected_apartments"
            )
        else:
            selected_apartments = []

    # Main content area
    st.markdown('<h1 class="main-header">Trebirth Scan Report Viewer</h1>', unsafe_allow_html=True)
    
    if selected_locations and selected_areas and selected_date and selected_apartments:
        # Filter final scans based on selected apartments
        final_scans = [
            scan for scan in filtered_scans
            if scan.get("Apartment", "").strip() in selected_apartments
        ]
        
        if final_scans:
            st.markdown('<div class="data-table">', unsafe_allow_html=True)
            st.subheader("Available Reports")
            
            # Group scans by apartment for table display
            apartment_data = {}
            for scan in final_scans:
                apartment = scan.get("Apartment", "").strip()
                if apartment not in apartment_data:
                    apartment_data[apartment] = {
                        'apartment': apartment,
                        'date': scan.get("scan_date", "Unknown Date"),
                        'incharge': scan.get("Incharge", "N/A"),
                        'scans': []
                    }
                apartment_data[apartment]['scans'].append(scan)
            
            # Create table header
            col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
            with col1:
                st.write("**Apartment Name**")
            with col2:
                st.write("**Date of Scan**")
            with col3:
                st.write("**Incharge Name**")
            with col4:
                st.write("**Download PDF**")
            
            st.markdown("---")
            
            # Create table rows
            for apartment, data in apartment_data.items():
                col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
                
                with col1:
                    st.write(data['apartment'])
                with col2:
                    st.write(data['date'])
                with col3:
                    st.write(data['incharge'])
                with col4:
                    if st.button(f"Download PDF", key=f"pdf_{apartment}"):
                        with st.spinner(f"Generating PDF for {apartment}..."):
                            try:
                                pdf_file = generate_pdf_for_apartment(data['scans'], company_name)
                                
                                with open(pdf_file, "rb") as file:
                                    st.download_button(
                                        label=f"Download {apartment} Report",
                                        data=file,
                                        file_name=f"Trebirth_Report_{apartment}_{data['date']}.pdf",
                                        mime="application/pdf",
                                        key=f"download_{apartment}"
                                    )
                                
                                # Clean up temporary PDF file
                                try:
                                    os.remove(pdf_file)
                                except:
                                    pass
                                    
                            except Exception as e:
                                st.error(f"Error generating PDF: {str(e)}")
                
                st.markdown("---")
            
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Option to download CSV of all selected data
            if len(final_scans) > 0:
                st.subheader("Export Data")
                df = pd.DataFrame(final_scans)
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Download All Data as CSV",
                    data=csv,
                    file_name=f"trebirth_scans_{selected_date_str}.csv",
                    mime="text/csv"
                )
        else:
            st.warning("No scans available for the selected criteria.")
    else:
        st.info("Please make all selections in the sidebar to view available reports.")
        if not selected_locations:
            st.write("• Select at least one location")
        if not selected_areas:
            st.write("• Select at least one area")
        if not selected_date:
            st.write("• Select a scan date")
        if not selected_apartments:
            st.write("• Select at least one apartment")

if __name__ == "__main__":
    main()
