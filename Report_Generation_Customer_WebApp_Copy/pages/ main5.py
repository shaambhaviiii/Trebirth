import streamlit as st
from google.cloud import firestore
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

# Configure page
st.set_page_config(page_title="Customer Report Viewer", layout="wide")

# Initialize session state
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "company" not in st.session_state:
    st.session_state["company"] = None
if "selected_location" not in st.session_state:
    st.session_state["selected_location"] = None
if "selected_area" not in st.session_state:
    st.session_state["selected_area"] = None
if "selected_date" not in st.session_state:
    st.session_state["selected_date"] = None
if "selected_apartments" not in st.session_state:
    st.session_state["selected_apartments"] = []

# Company credentials
company_credentials = {
    "Hlabs": "H2025$$",
    "Ilabs": "I2025$$",
    "PCI": "P2025$$",
    "Vlabs": "V2025$$",
    "Trebirth": "T2025$$"
}

# Initialize Firestore
db = firestore.Client.from_service_account_info(st.secrets["firebase_admin"])
query = db.collection("homescan2")

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

def fetch_data(company_name):
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

                Area = data.get("Area", "").strip()
                if Area:
                    if location not in city_to_areas:
                        city_to_areas[location] = set()
                    city_to_areas[location].add(Area)

            timestamp_str = data.get("timestamp")
            scan_date = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").strftime('%Y-%m-%d') if timestamp_str else "Unknown Date"
            data["scan_date"] = scan_date
            scans_data.append(data)

    return sorted(locations), city_to_areas, scans_data

def login_form():
    st.sidebar.title("Login")
    company = st.sidebar.text_input("Company Name")
    password = st.sidebar.text_input("Password", type="password")

    if st.sidebar.button("Login"):
        if company in company_credentials and company_credentials[company] == password:
            st.session_state["authenticated"] = True
            st.session_state["company"] = company
            st.sidebar.success(f"Login successful! Welcome, {company}.")
            st.rerun()
        else:
            st.sidebar.error("Invalid company name or password")

def logout():
    if st.sidebar.button("Logout"):
        st.session_state["authenticated"] = False
        st.session_state["company"] = None
        st.session_state["selected_location"] = None
        st.session_state["selected_area"] = None
        st.session_state["selected_date"] = None
        st.session_state["selected_apartments"] = []
        st.rerun()

def sidebar_filters():
    st.sidebar.title("Filters")
    
    # Fetch data for the logged-in company
    locations, city_to_areas, scans_data = fetch_data(st.session_state["company"])
    
    # Location selection
    selected_location = st.sidebar.selectbox(
        "Select Report Location:",
        ["All"] + locations,
        index=0 if st.session_state["selected_location"] is None else 
              ["All"] + locations.index(st.session_state["selected_location"]) + 1
    )
    
    if selected_location != "All":
        st.session_state["selected_location"] = selected_location
    else:
        st.session_state["selected_location"] = None
    
    # Area selection based on selected location
    filtered_areas = set()
    if st.session_state["selected_location"]:
        if st.session_state["selected_location"] in city_to_areas:
            filtered_areas.update(city_to_areas[st.session_state["selected_location"]])
    else:
        for loc in locations:
            if loc in city_to_areas:
                filtered_areas.update(city_to_areas[loc])
    
    selected_area = st.sidebar.selectbox(
        "Select Report Area:",
        ["All"] + sorted(filtered_areas),
        index=0 if st.session_state["selected_area"] is None else 
              ["All"] + sorted(filtered_areas).index(st.session_state["selected_area"]) + 1
    )
    
    if selected_area != "All":
        st.session_state["selected_area"] = selected_area
    else:
        st.session_state["selected_area"] = None
    
    # Date selection
    selected_date = st.sidebar.date_input(
        "Select scan date:",
        value=st.session_state["selected_date"] if st.session_state["selected_date"] else None
    )
    st.session_state["selected_date"] = selected_date
    
    # Filter scans based on selections
    filtered_scans = [
        scan for scan in scans_data 
        if (not st.session_state["selected_location"] or scan["City"].strip() == st.session_state["selected_location"])
        and (not st.session_state["selected_area"] or scan["Area"].strip() == st.session_state["selected_area"])
        and (not st.session_state["selected_date"] or scan.get("scan_date", "Unknown Date") == st.session_state["selected_date"].strftime("%Y-%m-%d"))
        and scan["CompanyName"].strip() == st.session_state["company"]
    ]
    
    # Apartment selection
    apartments_info = {}
    for scan in filtered_scans:
        apartment = scan.get("Apartment", "").strip()
        incharge = scan.get("Incharge", "").strip()
        if apartment:
            apartments_info[apartment] = incharge
    
    if apartments_info:
        st.sidebar.markdown("### Select Apartment(s):")
        selected_apartments = []
        for apt, incharge in apartments_info.items():
            if st.sidebar.checkbox(f"{apt} (Incharge: {incharge})", key=f"apt_{apt}"):
                selected_apartments.append(apt)
        
        st.session_state["selected_apartments"] = selected_apartments
    
    return filtered_scans

def generate_pdf_for_apartment(apartment_name, scans_data):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmpfile:
        pdf_path = tmpfile.name
    
    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    styles = getSampleStyleSheet()

    # Apply fonts
    pdfmetrics.registerFont(TTFont('ARLRDBD', 'ARLRDBD.TTF'))
    pdfmetrics.registerFont(TTFont('ARIAL', 'ARIAL.TTF'))
    styles["Heading1"].fontName = 'ARLRDBD'
    styles["Normal"].fontName = 'ARIAL'
    
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
    bold_style = ParagraphStyle("BoldStyle", parent=body_style, fontSize=12, fontName="ARLRDBD")

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
    
    # Filter scans for this apartment
    apartment_scans = [scan for scan in scans_data if scan.get("Apartment", "").strip() == apartment_name]
    
    if apartment_scans:
        test_by = apartment_scans[0]["CompanyName"]
        report_loc = apartment_scans[0]["City"]
        report_date = apartment_scans[0]["scan_date"]
        
        data = [
            ["Tests were carried out by:", test_by],
            ["Date:", report_date],
            ["Report for location at:", report_loc],
            ["Name of the building/apartment:", apartment_name]
        ]

        table = Table(data, colWidths=[2.5 * inch, 3.5 * inch])
        table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'ARIAL'),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
            ('TEXTCOLOR', (1, 0), (1, -1), colors.darkblue),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black)
        ]))

        elements.append(table)
        elements.append(PageBreak())

        # Process scans for this apartment
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
                    # Process radar data and generate plots
                    df_radar = pd.DataFrame(radar_raw, columns=['Radar'])
                    df_radar.dropna(inplace=True)
                    df_radar.fillna(df_radar.mean(), inplace=True)
                    
                    device_name = scan.get('Devicename', 'Unknown Device')
                    timestamp = scan.get('timestamp', datetime.now())
                    scan_duration = scan.get("ScanDuration", "Unknown")
                    
                    # Generate plot
                    fig = go.Figure()
                    time_seconds = np.arange(len(df_radar)) / 100
                    fig.add_trace(go.Scatter(
                        x=time_seconds,
                        y=df_radar['Radar'],
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
                            line=dict(color="black", width=2)
                        )]
                    )
                    
                    # Save plot as image
                    img_path = f"{tempfile.gettempdir()}/time_domain_plot_{apartment_name}_{i}_{j}.png"
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
                        ('FONTNAME', (0, 0), (-1, -1), 'ARLRDBD'),
                        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                        ('ALIGN', (1, 0), (-1, -1), 'LEFT'),
                        ('FONTNAME', (1, 0), (-1, -1), 'ARIAL'),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                    ]))

                    elements.append(table)
                    elements.append(Spacer(1, 20))
    
    doc.build(elements)
    return pdf_path

def main_content():
    st.title(f"{st.session_state['company']} Scan Report Viewer")
    
    # Check if all required selections are made
    if (st.session_state["selected_location"] is None and 
        st.session_state["selected_area"] is None and 
        st.session_state["selected_date"] is None and 
        not st.session_state["selected_apartments"]):
        st.info("Please make selections in the sidebar to view data.")
        return
    
    # Fetch filtered data
    filtered_scans = sidebar_filters()
    
    if not filtered_scans:
        st.warning("No data found for the selected criteria.")
        return
    
    # Create table data
    table_data = []
    unique_apartments = set()
    
    for scan in filtered_scans:
        apartment = scan.get("Apartment", "").strip()
        if apartment in st.session_state["selected_apartments"]:
            unique_apartments.add(apartment)
    
    # Create table for unique apartments
    for apartment in unique_apartments:
        # Find the first scan for this apartment to get basic info
        apartment_scan = next((scan for scan in filtered_scans if scan.get("Apartment", "").strip() == apartment), None)
        
        if apartment_scan:
            scan_date = apartment_scan.get("scan_date", "Unknown Date")
            incharge = apartment_scan.get("Incharge", "").strip()
            
            table_data.append({
                "Apartment Name": apartment,
                "Date of Scan": scan_date,
                "Incharge Name": incharge,
                "Download PDF": "Download button below"
            })
    
    if table_data:
        # Display the table
        df = pd.DataFrame(table_data)
        st.dataframe(df, use_container_width=True)
        
        # Display download buttons below the table
        st.markdown("### Download Reports")
        for apartment in unique_apartments:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"**{apartment}**")
            with col2:
                # Generate PDF and create download button
                pdf_path = generate_pdf_for_apartment(apartment, filtered_scans)
                with open(pdf_path, "rb") as file:
                    pdf_data = file.read()
                os.unlink(pdf_path)  # Clean up the temporary file
                
                st.download_button(
                    label="Download PDF",
                    data=pdf_data,
                    file_name=f"Trebirth_Test_Report_{apartment}.pdf",
                    mime="application/pdf",
                    key=f"download_btn_{apartment}"
                )
    else:
        st.info("No apartments selected. Please select at least one apartment in the sidebar.")

# Main application logic
if not st.session_state["authenticated"]:
    # Show login form in sidebar
    login_form()
    st.title("Welcome to Customer Report Viewer")
    st.info("Please log in using the sidebar to access the report viewer.")
else:
    # Show logout button in sidebar
    logout()
    
    # Show filters in sidebar
    sidebar_filters()
    
    # Show main content
    main_content()
