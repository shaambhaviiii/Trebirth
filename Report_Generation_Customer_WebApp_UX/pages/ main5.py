import streamlit as st
from google.cloud import firestore
import pandas as pd
from datetime import datetime
from dateutil import parser  # pip install python-dateutil
import numpy as np
import time
import os
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

# Set browser path for kaleido (for plotly image export)
os.environ["BROWSER_PATH"] = "/usr/bin/chromium"

st.set_page_config(layout="wide", page_title="Trebirth Scan Viewer")

def logout():
    st.session_state["authenticated"] = False
    st.session_state["company"] = None
    for key in list(st.session_state.keys()):
        if key.startswith(("selected_", "filtered_")):
            del st.session_state[key]
    st.experimental_rerun()

@st.cache_resource
def init_firestore():
    try:
        return firestore.Client.from_service_account_info(st.secrets["firebase_admin"])
    except Exception:
        st.error("Firebase configuration missing")
        st.stop()
        return None

db = init_firestore()

@st.cache_data
def fetch_data(company_name):
    if not db:
        return [], {}, []
    query = db.collection("pestcontrolindia")
    docs = query.stream()

    locations = set()
    city_areas = {}
    scans = []
    for doc in docs:
        d = doc.to_dict()
        if d.get("CompanyName", "").strip() != company_name:
            continue
        
        city = d.get("City", "").strip()
        area = d.get("Area", "").strip()
        if city:
            locations.add(city)
            if area:
                city_areas.setdefault(city, set()).add(area)
        ts = d.get("timestamp")
        scan_date = "Unknown"
        if ts:
            try:
                parsed_dt = parser.parse(str(ts))
                scan_date = parsed_dt.strftime("%Y-%m-%d")
            except Exception:
                pass
        d["scan_date"] = scan_date
        scans.append(d)
    return sorted(locations), city_areas, scans

def preprocess_radar_data(raw):
    import pandas as pd
    df = pd.DataFrame(raw, columns=["Radar"])
    df.dropna(inplace=True)
    df.fillna(df.mean(), inplace=True)
    return df

def plot_time_domain(df, device_name, timestamp, scan_duration, sampling_rate=100):
    import plotly.graph_objects as go
    fig = go.Figure()
    t = np.arange(len(df)) / sampling_rate
    fig.add_trace(go.Scatter(x=t, y=df["Radar"], mode="lines", name=device_name, line=dict(color='blue')))
    fig.update_layout(
        template='plotly_white', xaxis={'showticklabels':False}, yaxis={'showticklabels':False},
        legend_title='Scan', font={'color':'black'},
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=100, r=100, t=100, b=100),
        shapes=[dict(type='rect', x0=0, y0=0, x1=1, y1=1, xref='paper', yref='paper', line=dict(color='black', width=2))]
    )
    return fig

def generate_pdf(apartment_scans, company_name):
    import plotly.io as pio
    import tempfile
    import os
    import time

    pdf_path = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf").name
    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    styles = getSampleStyleSheet()

    try:
        pdfmetrics.registerFont(TTFont('Helvetica-Bold', 'Helvetica-Bold.ttf'))
        styles['Heading1'].fontName = 'Helvetica-Bold'
    except:
        pass

    heading_center = ParagraphStyle('heading_center', parent=styles['Heading1'], fontSize=20, alignment=1, textColor=colors.darkblue)
    heading_left = ParagraphStyle('heading_left', parent=styles['Heading1'], fontSize=18, alignment=0, textColor=colors.darkblue)
    heading_sub = ParagraphStyle('heading_sub', parent=styles['Heading2'], fontSize=16, alignment=0)
    body = styles['Normal']
    body.fontSize = 12

    elements = []
    elements.append(Paragraph("TREBIRTH SCAN REPORT", heading_center))
    elements.append(Spacer(1,16))
    elements.append(Paragraph("This Treborth scan report is supplementary and only for record.", body))
    elements.append(Spacer(1,20))

    if not apartment_scans:
        elements.append(Paragraph("No data available.", body))
    else:
        first = apartment_scans[0]
        info = [
            ["Company", first.get("CompanyName","")],
            ["Date", first.get("scan_date","")],
            ["Location", first.get("City","")],
            ["Apartment", first.get("Apartment","")]
        ]
        t = Table(info, colWidths=[120,350])
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.lightgrey),
            ('GRID',(0,0),(-1,-1),0.5,colors.black)
        ]))
        elements.append(t)
        elements.append(PageBreak())

        area_dict = {}
        for scan in apartment_scans:
            area_dict.setdefault(scan.get("Room","Unknown"),[]).append(scan)

        img_files = []
        for i, (area, scans) in enumerate(area_dict.items(),1):
            elements.append(Paragraph(f"{i} {area.upper()}", heading_left))
            for j, scan in enumerate(scans,1):
                elements.append(Paragraph(f"{i}.{j} Radar Scan", heading_sub))
                
                radar_raw = scan.get("RadarRaw",[])
                if radar_raw:
                    df_radar = preprocess_radar_data(radar_raw)
                    fig = plot_time_domain(df_radar, scan.get("Devicename","Unknown"), scan.get("timestamp",""), scan.get("ScanDuration",""))
                    img_file = tempfile.NamedTemporaryFile(delete=False,suffix=".png").name
                    pio.write_image(fig, img_file)
                    time.sleep(0.2)
                    if os.path.isfile(img_file):
                        elements.append(Image(img_file, width=400, height=300))
                        img_files.append(img_file)
                    
                    elements.append(Spacer(1,12))
                    elements.append(Paragraph(f"Device: {scan.get('Devicename','')}", body))
                    elements.append(Paragraph(f"Timestamp: {scan.get('timestamp','')}", body))
                    elements.append(Paragraph(f"Duration: {scan.get('ScanDuration','')}", body))

                    details = [
                        ["Location", scan.get("Room","")],
                        ["Position", scan.get("Positioned","")],
                        ["Damage", scan.get("DamageVisible","")]
                    ]
                    detail_table = Table(details, colWidths=[120,350])
                    detail_table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.black)]))
                    elements.append(detail_table)
                    elements.append(Spacer(1,20))
        
        doc.build(elements)
        for f in img_files:
            try:
                os.remove(f)
            except:
                pass
    return pdf_path

def main():
    if not st.session_state.get("authenticated", False):
        st.warning("Please log in")
        st.stop()

    company_name = st.session_state.get("company")
    locations, city_areas, scans = fetch_data(company_name)

    st.sidebar.title(f"Welcome, {company_name}")
    if st.sidebar.button("Logout"):
        logout()

    selected_location = st.sidebar.selectbox("Select Location", locations)
    areas = city_areas.get(selected_location, [])
    selected_area = st.sidebar.selectbox("Select Area", sorted(areas))

    month_set = set()
    for scan in scans:
        if scan.get("City") == selected_location and scan.get("Area") == selected_area:
            try:
                dt = datetime.strptime(scan.get("scan_date"), "%Y-%m-%d")
                month_set.add(dt.strftime("%Y-%m"))
            except:
                pass
    months = sorted(list(month_set))
    selected_month = st.sidebar.selectbox("Select Month", months)

    st.markdown("# Treborth Scan Viewer")

    if selected_location and selected_area and selected_month:
        pretty_month = datetime.strptime(selected_month, "%Y-%m").strftime("%B %Y").upper()
        st.subheader(f"All Scans for {selected_area} in {pretty_month}")
        st.markdown("<div style='height:25px'></div>", unsafe_allow_html=True)

        filtered_scans = [s for s in scans if s.get("City") == selected_location and
                          s.get("Area") == selected_area and
                          s.get("scan_date").startswith(selected_month)]
        
        apartments = {}
        for fscan in filtered_scans:
            apartments.setdefault(fscan.get("Apartment","Unknown"), []).append(fscan)

        cols = st.columns([3,2,2,2])
        cols[0].write("Apartment")
        cols[1].write("Date")
        cols[2].write("Incharge")
        cols[3].write("Download PDF")
        st.markdown("---")

        for apt, apt_scans in apartments.items():
            c = st.columns([3,2,2,2])
            c.write(apt)
            c[1].write(apt_scans.get("scan_date",""))
            c[2].write(apt_scans.get("Incharge",""))
            if c[3].button("Download PDF", key=apt):
                pdf_path = generate_pdf(apt_scans, company_name)
                with open(pdf_path, "rb") as f:
                    st.download_button(label="Download PDF", data=f.read(),
                                       file_name=f"Treborth_{apt}_{selected_month}.pdf",
                                       mime="application/pdf")
                os.remove(pdf_path)
    else:
        st.info("Please select Location, Area, and Month")

if __name__ == "__main__":
    main()
