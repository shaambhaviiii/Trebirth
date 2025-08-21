import streamlit as st
from google.cloud import firestore
import pandas as pd
from datetime import datetime
import numpy as np
import os
import random
import tempfile

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Table, TableStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

os.environ["BROWSER_PATH"] = "/usr/bin/chromium"  
st.set_page_config(layout="wide", page_title="Trebirth Scan Report Viewer")

if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
    st.warning("Please log in first.")
    st.switch_page("main4.py")

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "company" not in st.session_state:
    st.session_state["company"] = None

company_credentials = {
    "Hlabs": "H2025$$",
    "Ilabs": "I2025$$",
    "PCI": "P2025$$",
    "Vlabs": "V2025$$",
    "Trebirth": "T2025$$"
}

def logout():
    st.session_state["authenticated"] = False
    st.session_state["company"] = None
    for key in list(st.session_state.keys()):
        if key.startswith(('selected_', 'filtered_')):
            del st.session_state[key]
    st.rerun()

@st.cache_resource
def init_firestore():
    try:
        return firestore.Client.from_service_account_info(st.secrets["firebase_admin"])
    except Exception:
        st.error("Firebase configuration not found in Streamlit secrets. Please check your secrets configuration.")
        st.stop()
        return None

db = init_firestore()

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

def preprocess_radar_data(radar_raw):
    df_radar = pd.DataFrame(radar_raw, columns=['Radar'])
    df_radar.dropna(inplace=True)
    df_radar.fillna(df_radar.mean(), inplace=True)
    return df_radar

def plot_time_domain(preprocessed_scan, device_name, timestamp, scan_duration, sampling_rate=100):
    import plotly.graph_objects as go
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

def generate_pdf_for_apartment(apartment_scans, company_name):
    import plotly.io as pio
    import os
    pdf_path = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf").name
    
    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    styles = getSampleStyleSheet()

    try:
        pdfmetrics.registerFont(TTFont('ARLRDBD', 'Report_Generation_Customer_WebApp/ARLRDBD.TTF'))
        pdfmetrics.registerFont(TTFont('ARIAL', 'Report_Generation_Customer_WebApp/ARIAL.TTF'))
        styles["Heading1"].fontName = 'ARLRDBD'
        styles["Normal"].fontName = 'ARIAL'
    except:
        pass

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

                    try:
                        os.remove(img_path)
                    except:
                        pass

    doc.build(elements)
    return pdf_path

def main():
    company_name = st.session_state["company"]

    # Custom CSS for table and spacing
    st.markdown(
        """
        <style>
        .main-header { font-size: 2.4rem; color: #1f4e79; text-align: center; margin-bottom: 2rem; }
        .custom-table th { background-color: #20242f; color: white; padding: 12px; text-align: left; font-size: 1.05em; }
        .custom-table td { background-color: #232735; color: #ebeff6; padding: 11px; border-top: 1px solid #2d3241;}
        .custom-table { width: 95%; margin: 0 auto 2em auto; border-collapse: collapse;}
        .gap-above-table { height: 30px; }
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

        locations, city_to_areas, scans_data = fetch_data(company_name)

        selected_location = st.selectbox("Select Report Location:", locations, key="selected_location")

        filtered_areas = city_to_areas.get(selected_location, [])
        selected_area = st.selectbox("Select Report Area:", sorted(filtered_areas), key="selected_area")

        scan_months = set()
        for scan in scans_data:
            if scan["City"].strip() == selected_location and scan["Area"].strip() == selected_area:
                scan_date_obj = datetime.strptime(scan.get("scan_date", "1970-01-01"), '%Y-%m-%d')
                scan_months.add(scan_date_obj.strftime("%Y-%m"))
        scan_months = sorted(list(scan_months))
        selected_month = st.selectbox("Select scan month:", scan_months, key="selected_month")

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
            st.markdown("<div class='gap-above-table'></div>", unsafe_allow_html=True)

            apartments = {}
            for scan in final_scans:
                apt = scan.get("Apartment", "N/A")
                if apt not in apartments:
                    apartments[apt] = []
                apartments[apt].append(scan)

            # Build HTML table
            table_html = """
            <table class="custom-table">
                <thead>
                    <tr>
                        <th>Apartment</th>
                        <th>Date of Scan</th>
                        <th>Incharge</th>
                        <th>Download PDF</th>
                    </tr>
                </thead>
                <tbody>
            """
            for apartment, scans in apartments.items():
                first_scan = scans[0]
                table_html += f"""
                    <tr>
                        <td>{apartment}</td>
                        <td>{first_scan.get("scan_date", "Unknown Date")}</td>
                        <td>{first_scan.get("Incharge", "N/A")}</td>
                        <td>""" + f"""<form action="" method="post">{'<input type="submit" value="Download PDF" />'}</form></td>
                    </tr>
                """
            table_html += """
                </tbody>
            </table>
            """

            st.markdown(table_html, unsafe_allow_html=True)

            # Render download buttons below the table per apartment for actual downloads
            for apartment, scans in apartments.items():
                # Only one button per apartment, not inside the HTML table.
                st.markdown(f"<div style='margin-bottom:10px'></div>", unsafe_allow_html=True)
                if st.button(f"Download PDF: {apartment}", key=f"pdf_{apartment}_{selected_month}_{selected_area}"):
                    with st.spinner(f"Generating PDF for {apartment}..."):
                        try:
                            pdf_file = generate_pdf_for_apartment(scans, company_name)
                            with open(pdf_file, "rb") as file:
                                st.download_button(
                                    label=f"Download {apartment} Report",
                                    data=file,
                                    file_name=f"Trebirth_Report_{apartment}_{selected_month}.pdf",
                                    mime="application/pdf",
                                    key=f"download_{apartment}_{selected_month}_{selected_area}"
                                )
                            os.remove(pdf_file)
                        except Exception as e:
                            st.error(f"Error generating PDF: {str(e)}")

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
