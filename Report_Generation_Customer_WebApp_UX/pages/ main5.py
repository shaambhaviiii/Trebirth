import streamlit as st
from google.cloud import firestore
import pandas as pd
from datetime import datetime
import numpy as np
import time
import os
import random
import tempfile
import plotly.io as pio
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image,
    PageBreak,
    Table,
    TableStyle,
)
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from google.api_core.exceptions import ResourceExhausted, RetryError

# Set browser path for kaleido (used for plotly image export)
os.environ["BROWSER_PATH"] = "/usr/bin/chromium"

# Configure Streamlit page layout and title
st.set_page_config(layout="wide", page_title="Trebirth Scan Report Viewer")

# Redirect to login page if user is not authenticated
if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
    st.warning("Please log in first.")
    st.switch_page("main4.py")

# Initialize authentication and company state variables if not set
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "company" not in st.session_state:
    st.session_state["company"] = None

# Predefined company credentials (used elsewhere)
company_credentials = {
    "Hlabs": "H2025$$",
    "Ilabs": "I2025$$",
    "PCI": "P2025$$",
    "Vlabs": "V2025$$",
    "Trebirth": "T2025$$",
}

def logout():
    # Clear authentication and company from session state and relevant selections
    st.session_state["authenticated"] = False
    st.session_state["company"] = None
    for key in list(st.session_state.keys()):
        if key.startswith(("selected_", "filtered_")):
            del st.session_state[key]
    st.rerun()

@st.cache_resource
def init_firestore():
    # Initialize Firestore client using secrets from Streamlit
    try:
        return firestore.Client.from_service_account_info(st.secrets["firebase_admin"])
    except Exception:
        st.error("Firebase config not found in secrets, check configuration.")
        st.stop()
        return None

# Firestore client instance
db = init_firestore()

def exponential_backoff(retries):
    # Exponential backoff with jitter to delay retries upon failures
    base_delay = 1
    max_delay = 60
    delay = base_delay * (2 ** retries) + random.uniform(0, 1)
    return min(delay, max_delay)

@st.cache_data
def fetch_data(company_name):
    # Fetch scan data from Firestore filtered by company name
    if not db:
        return [], {}, []
    query = db.collection("pestcontrolindia")
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

            # Parse timestamp to create a formatted scan_date string
            timestamp_str = data.get("timestamp")
            scan_date = (
                datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
                if timestamp_str
                else "Unknown Date"
            )
            data["scan_date"] = scan_date
            scans_data.append(data)

    return sorted(locations), city_to_areas, scans_data

def preprocess_radar_data(radar_raw):
    # Convert radar raw data list into pandas DataFrame,
    # drop missing data and substitute missing values with mean
    import pandas as pd

    df_radar = pd.DataFrame(radar_raw, columns=["Radar"])
    df_radar.dropna(inplace=True)
    df_radar.fillna(df_radar.mean(), inplace=True)
    return df_radar

def plot_time_domain(preprocessed_scan, device_name, timestamp, scan_duration, sampling_rate=100):
    # Create Plotly line chart for radar scan signal over time
    import plotly.graph_objects as go

    fig = go.Figure()
    time_seconds = np.arange(len(preprocessed_scan)) / sampling_rate
    fig.add_trace(
        go.Scatter(
            x=time_seconds,
            y=preprocessed_scan["Radar"],
            mode="lines",
            name=f"{device_name} - Unknown Timestamp",
            line=dict(color="blue"),
        )
    )
    # Customize plot layout to hide axis labels and add border
    fig.update_layout(
        template="plotly_white",
        xaxis_title=None,
        yaxis_title=None,
        xaxis=dict(showticklabels=False),
        yaxis=dict(showticklabels=False),
        legend_title="Scan",
        font=dict(color="black"),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=100, r=100, t=100, b=100),
        shapes=[
            dict(
                type="rect",
                x0=0,
                y0=0,
                x1=1,
                y1=1,
                xref="paper",
                yref="paper",
                line=dict(color="black", width=2),
            )
        ],
    )
    return fig

def generate_pdf_for_apartment(apartment_scans, company_name):
    # Generate a PDF report for an apartment with scan details and charts
    import plotly.io as pio
    import os
    import tempfile
    import time

    pdf_path = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf").name

    # Setup PDF document and styles
    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    styles = getSampleStyleSheet()

    try:
        # Register custom fonts if available
        pdfmetrics.registerFont(TTFont("ARLRDBD", "Report_Generation_Customer_WebApp/ARLRDBD.TTF"))
        pdfmetrics.registerFont(TTFont("ARIAL", "Report_Generation_Customer_WebApp/ARIAL.TTF"))
        styles["Heading1"].fontName = "ARLRDBD"
        styles["Normal"].fontName = "ARIAL"
    except:
        # Fallback to default fonts
        pass

    # Define paragraph styles for headings and body
    heading_style_centered = ParagraphStyle(
        "HeadingStyleCentered",
        parent=styles["Heading1"],
        fontSize=20,
        textColor=colors.darkblue,
        alignment=1,
        spaceAfter=10,
        underline=True,
        bold=True,
    )

    heading_style_left = ParagraphStyle(
        "HeadingStyleLeft",
        parent=styles["Heading1"],
        fontSize=20,
        textColor=colors.darkblue,
        alignment=0,
        spaceAfter=10,
        underline=True,
        bold=True,
    )

    heading_style_sub = ParagraphStyle(
        "HeadingStyleLeft",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.black,
        alignment=0,
        spaceAfter=10,
        underline=True,
        bold=True,
    )

    # Body text style
    body_style = styles["Normal"]
    body_style.fontSize = 12

    elements = []
    # Add main report title and spacing
    elements.append(Paragraph("TREBIRTH TEST REPORT", heading_style_centered))
    elements.append(Spacer(1, 16))

    # Add report description lines
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

        # Add summary info table at the start of report
        data = [
            ["Tests were carried out by:", test_by],
            ["Date:", report_date],
            ["Report for location at:", report_loc],
            ["Name of the building/apartment:", apartment_name],
        ]
        table = Table(data, colWidths=[2.5 * inch, 3.5 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.black),
                    ("TEXTCOLOR", (1, 0), (1, -1), colors.darkblue),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ]
            )
        )
        elements.append(table)
        elements.append(PageBreak())

        # Organize scans grouped by room/area in the apartment
        area_scans = {}
        for scan in apartment_scans:
            area = scan.get("Room", "Unknown Area")
            if area not in area_scans:
                area_scans[area] = []
            area_scans[area].append(scan)

        img_paths_to_delete = []  # Track temp images for later cleanup

        # Add radar scan data and images per area and scan
        for i, (area, scans) in enumerate(area_scans.items(), start=1):
            elements.append(Paragraph(f"{i} {area.upper()}", heading_style_left))
            for j, scan in enumerate(scans, start=1):
                elements.append(Paragraph(f"{i}.{j} Radar Scan", heading_style_sub))

                radar_raw = scan.get("RadarRaw", [])
                if radar_raw:
                    processed_scan = preprocess_radar_data(radar_raw)
                    device_name = scan.get("Devicename", "Unknown Device")
                    timestamp = scan.get("timestamp", datetime.now())
                    scan_duration = scan.get("ScanDuration", "Unknown")
                    fig = plot_time_domain(processed_scan, device_name, timestamp, scan_duration)
                    
                    # Export plot as PNG image in temp directory
                    img_path = f"{tempfile.gettempdir()}/time_domain_plot_{i}_{j}.png"
                    pio.write_image(fig, img_path, format="png")
                    time.sleep(0.2)  # Wait to ensure file is written

                    # Add image to PDF if file exists
                    if os.path.isfile(img_path):
                        elements.append(Image(img_path, width=400, height=300))
                        img_paths_to_delete.append(img_path)
                    else:
                        st.error(f"Image file not found: {img_path}")

                    # Add scan metadata to report under image
                    elements.append(Spacer(1, 12))
                    elements.append(Paragraph(f"Device Name: {device_name}", body_style))
                    elements.append(Spacer(1, 3))
                    try:
                        ts_obj = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        ts_obj = timestamp
                    elements.append(Paragraph(f"Timestamp: {ts_obj}", body_style))
                    elements.append(Spacer(1, 3))
                    elements.append(Paragraph(f"Scan Duration: {scan_duration}", body_style))
                    elements.append(Spacer(1, 12))

                    # Additional scanning details table
                    data = [
                        ["Scan Location:", scan.get("Room", "N/A")],
                        ["Device was:", scan.get("Positioned", "N/A")],
                        ["Damage Visible:", scan.get("DamageVisible", "N/A")],
                    ]
                    table = Table(data, colWidths=[2.5 * inch, 3.5 * inch])
                    table.setStyle(
                        TableStyle(
                            [
                                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                                ("ALIGN", (1, 0), (-1, -1), "LEFT"),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                            ]
                        )
                    )
                    elements.append(table)
                    elements.append(Spacer(1, 20))

        # Build PDF document
        doc.build(elements)

        # Clean up temporary images after PDF creation
        for path in img_paths_to_delete:
            try:
                os.remove(path)
            except Exception:
                pass

    # Return file path for use in download button
    return pdf_path

def main():
    """
    Main Streamlit app function:
    - Shows sidebar filters and logout
    - Loads and filters scan data
    - Displays filtered scan reports table with download options
    """
    company_name = st.session_state["company"]

    # Custom CSS for page header
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

    # Sidebar components
    with st.sidebar:
        st.title(f"Welcome, {company_name}!")

        # Logout button triggers session clearing and rerun
        if st.button("Logout", type="secondary"):
            logout()

        st.markdown("---")

        # Fetch data for the logged-in company
        locations, city_to_areas, scans_data = fetch_data(company_name)

        # Sidebar: Select report location (single select)
        selected_location = st.selectbox("Select Report Location:", locations, key="selected_location")

        # Sidebar: Select report area (filtered by location)
        filtered_areas = city_to_areas.get(selected_location, [])
        selected_area = st.selectbox("Select Report Area:", sorted(filtered_areas), key="selected_area")

        # Sidebar: Collect available months of scans for selected location/area
        scan_months = set()
        for scan in scans_data:
            if (
                scan["City"].strip() == selected_location
                and scan["Area"].strip() == selected_area
            ):
                scan_date_obj = datetime.strptime(scan.get("scan_date", "1970-01-01"), "%Y-%m-%d")
                scan_months.add(scan_date_obj.strftime("%Y-%m"))

        # Sidebar: Select scan month (single select)
        scan_months = sorted(list(scan_months))
        selected_month = st.selectbox("Select scan month:", scan_months, key="selected_month")

    # Convert selected scan month to pretty format ("MONTH YEAR", e.g. "MARCH 2025")
    if selected_month:
        month_dt = datetime.strptime(selected_month, "%Y-%m")
        pretty_month_label = month_dt.strftime("%B %Y").upper()
    else:
        pretty_month_label = ""

    # Main page title
    st.markdown(f'<h1 class="main-header">Trebirth Scan Report Viewer</h1>', unsafe_allow_html=True)

    # Check that all filters are selected before displaying data
    if selected_location and selected_area and selected_month:
        # Filter scan data based on selections
        final_scans = [
            scan
            for scan in scans_data
            if scan["City"].strip() == selected_location
            and scan["Area"].strip() == selected_area
            and scan.get("scan_date", "1970-01-01").startswith(selected_month)
            and scan["CompanyName"].strip() == company_name
        ]

        if final_scans:
            # Show header with gap before table
            st.subheader(f"All Scans for {selected_area} in {pretty_month_label}")
            st.markdown("<div style='height:25px;'></div>", unsafe_allow_html=True)

            # Group scans by apartment for display and PDF generation
            apartments = {}
            for scan in final_scans:
                apt = scan.get("Apartment", "N/A")
                if apt not in apartments:
                    apartments[apt] = []
                apartments[apt].append(scan)

            # Display table headers
            col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
            with col1:
                st.write("**Apartment**")
            with col2:
                st.write("**Date of Scan**")
            with col3:
                st.write("**Incharge**")
            with col4:
                st.write("**Download PDF**")
            st.markdown("---")

            # Display each apartment's data row and download button
            for apartment, scans in apartments.items():
                first_scan = scans[0]
                col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
                with col1:
                    st.write(apartment)
                with col2:
                    st.write(first_scan.get("scan_date", "Unknown Date"))
                with col3:
                    st.write(first_scan.get("Incharge", "N/A"))
                with col4:
                    # Download PDF button triggers PDF generation and download
                    if st.button("Download PDF", key=f"pdf_{apartment}_{selected_month}_{selected_area}"):
                        with st.spinner(f"Generating PDF for {apartment}..."):
                            try:
                                pdf_file = generate_pdf_for_apartment(scans, company_name)
                                with open(pdf_file, "rb") as file:
                                    st.download_button(
                                        label=f"Download {apartment} Report",
                                        data=file,
                                        file_name=f"Trebirth_Report_{apartment}_{selected_month}.pdf",
                                        mime="application/pdf",
                                        key=f"download_{apartment}_{selected_month}_{selected_area}",
                                    )
                                os.remove(pdf_file)
                            except Exception as e:
                                st.error(f"Error generating PDF: {str(e)}")
                st.markdown("---")

            # Provide CSV download for all filtered scans combined
            df = pd.DataFrame(final_scans)
            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download All Data as CSV",
                data=csv,
                file_name=f"trebirth_scans_{selected_area}_{selected_month}.csv",
                mime="text/csv",
            )
        else:
            # Show warning if no scans matched the filter criteria
            st.warning("No scans available for the selected criteria.")
    else:
        # Inform the user to finish selecting filters before displaying scans
        st.info("Please make all selections in the sidebar to view available reports.")


if __name__ == "__main__":
    main()
