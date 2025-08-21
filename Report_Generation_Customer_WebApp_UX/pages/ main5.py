import streamlit as st
from google.cloud import firestore
import pandas as pd
from datetime import datetime
from dateutil import parser  # pip install python-dateutil
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
from google.api_core.exceptions import RetryError, ResourceExhausted

# Set browser path for kaleido
os.environ["BROWSER_PATH"] = "/usr/bin/chromium"

st.set_page_config(layout="wide", page_title="Trebirth Scan Viewer")

if "authenticated" not in st.session_state or not st.session_state.get("authenticated", False):
    st.warning("Please log in first")
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
    "Trebirth": "T2025$$",
}

def logout():
    st.session_state["authenticated"] = False
    st.session_state["company"] = None
    for k in list(st.session_state.keys()):
        if k.startswith(("selected_", "filtered_")):
            del st.session_state[k]
    st.experimental_rerun()

@st.cache_resource
def init_firestore():
    try:
        return firestore.Client.from_service_account_info(st.secrets["firebase"])
    except Exception:
        st.error("Firebase configuration missing")
        st.stop()
        return None

db = init_firestore()

@st.cache_data
def fetch_data(company):
    if not db:
        return [], {}, []

    query = db.collection("pestcontrolindia")
    docs = query.stream()
    locs = set()
    city_areas = {}
    scans = []

    for doc in docs:
        d = doc.to_dict()
        if d.get("CompanyName", "").strip() == company:
            city = d.get("City", "").strip()
            area = d.get("Area", "").strip()
            if city:
                locs.add(city)
                if area:
                    if city not in city_areas:
                        city_areas[city] = set()
                    city_areas[city].add(area)
            ts_str = d.get("timestamp")
            scan_date = "Unknown"
            if ts_str:
                try:
                    dt = parser.parse(str(ts_str))
                    scan_date = dt.strftime("%Y-%m-%d")
                except:
                    pass
            d["scan_date"] = scan_date
            scans.append(d)
    return sorted(locs), city_areas, scans

def preprocess_radar_data(raw):
    import pandas as pd
    df = pd.DataFrame(raw, columns=["Radar"])
    df.dropna(inplace=True)
    df.fillna(df.mean(), inplace=True)
    return df

def plot_time_domain(scan_df, device_name, timestamp, scan_duration, sampling_rate=100):
    import plotly.graph_objects as go
    fig = go.Figure()
    t = np.arange(len(scan_df)) / sampling_rate
    fig.add_trace(go.Scatter(x=t, y=scan_df["Radar"], mode="lines", name=device_name, line=dict(color="blue")))
    fig.update_layout(
        template="plotly_white", xaxis={"showticklabels": False}, yaxis={"showticklabels": False},
        legend_title="Scan", font={"color": "black"},
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=100, r=100, t=100, b=100),
        shapes=[dict(type="rect", x0=0, y0=0, x1=1, y1=1, xref="paper", yref="paper", line=dict(color="black", width=2))]
    )
    return fig

def generate_pdf(apartment_scans, company_name):
    import plotly.io as pio
    import os
    import tempfile
    import time

    pdf_path = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf").name

    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    styles = getSampleStyleSheet()

    try:
        pdfmetrics.registerFont(TTFont("Helvetica-bold", "Helvetica-bold.ttf"))
        styles["Heading1"].fontName = "Helvetica-bold"
    except:
        pass

    heading_center = ParagraphStyle("HeadingCenter", parent=styles["Heading1"], alignment=1, fontSize=20, textColor=colors.darkblue)
    heading_left = ParagraphStyle("HeadingLeft", parent=styles["Heading1"], alignment=0, fontSize=18, textColor=colors.darkblue)
    heading_sub = ParagraphStyle("HeadingSub", parent=styles["Heading1"], fontSize=16)

    elements = []
    elements.append(Paragraph("TREBIRTH SCAN REPORT", heading_center))
    elements.append(Spacer(1, 20))

    if not apartment_scans:
        elements.append(Paragraph("No data found.", styles["Normal"]))
    else:
        first = apartment_scans[0]
        header_data = [
            ["Company", first["CompanyName"]],
            ["Date", first["scan_date"]],
            ["Location", first["City"]],
            ["Apartment", first["Apartment"]]
        ]
        t = Table(header_data, colWidths=[100, 350])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("GRID", (0, 0), (-1, -1), 1, colors.black)]))
        elements.append(t)
        elements.append(PageBreak())

        areas = {}
        for scan in apartment_scans:
            areas.setdefault(scan.get("Room", "Unknown Room"), []).append(scan)

        img_paths = []

        for i, (area, scans) in enumerate(areas.items(), 1):
            elements.append(Paragraph(f"{i}. {area.upper()}", heading_left))

            for j, scan in enumerate(scans, 1):
                elements.append(Paragraph(f"{i}.{j} - Radar Scan", heading_sub))

                raw_data = scan.get("RadarRaw", [])
                if raw_data:
                    df = preprocess_radar_data(raw_data)
                    fig = plot_time_domain(df, scan.get("Devicename", "Unknown Device"), scan.get("timestamp", ""), scan.get("ScanDuration", ""))
                    img_path = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
                    pio.write_image(fig, img_path)
                    time.sleep(0.2)
                    if os.path.exists(img_path):
                        elements.append(Image(img_path, width=400, height=300))
                        img_paths.append(img_path)

                    elements.append(Paragraph(f"Device: {scan.get('Devicename', '')}", styles["Normal"]))
                    elements.append(Paragraph(f"Timestamp: {scan.get('timestamp', '')}", styles["Normal"]))
                    elements.append(Paragraph(f"Scan Duration: {scan.get('ScanDuration', '')}", styles["Normal"]))
                    elements.append(Spacer(1, 10))

                    details = [
                        ["Location", scan.get("Room", "")],
                        ["Position", scan.get("Positioned", "")],
                        ["Damage", scan.get("DamageVisible", "")]
                    ]
                    dt = Table(details, colWidths=[150, 200])
                    dt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
                    elements.append(dt)
                    elements.append(Spacer(1, 10))

        doc.build(elements)

        for img in img_paths:
            try:
                os.remove(img)
            except:
                pass

    return pdf_path

def main():
    company_name = st.session_state["company"]

    st.markdown("""
        <style>
            .main-header {
                font-size: 2.5rem;
                color: #1f4e79;
                text-align: center;
                margin-bottom: 2rem;
            }
        </style>
        """, unsafe_allow_html=True
    )

    with st.sidebar:
        st.title(f"Welcome, {company_name}")
        if st.button("Logout"):
            logout()
        st.markdown("---")
        locations, city_areas, scans = fetch_data(company_name)

        selected_location = st.selectbox("Select Location", locations)
        areas = city_areas.get(selected_location, [])
        selected_area = st.selectbox("Select Area", sorted(areas))

        months = set()
        for scan in scans:
            if scan.get("City") == selected_location and scan.get("Area") == selected_area:
                try:
                    dt = datetime.strptime(scan.get("scan_date"), '%Y-%m-%d')
                    months.add(dt.strftime('%Y-%m'))
                except:
                    continue
        months = sorted(list(months))
        selected_month = st.selectbox("Select Month", months)

    if all([selected_location, selected_area, selected_month]):
        st.markdown(f"# Trebirth Scan Report Viewer")
        st.subheader(f"All Scans for {selected_area} in {datetime.strptime(selected_month, '%Y-%m').strftime('%B %Y').upper()}")
        st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)

        filtered = [sc for sc in scans if sc.get("City") == selected_location and sc.get("Area") == selected_area and sc.get("scan_date", "").startswith(selected_month) and sc.get("CompanyName") == company_name]

        apartments = {}
        for f in filtered:
            apartments.setdefault(f.get("Apartment", "Unknown"), []).append(f)

        col1, col2, col3, col4 = st.columns([3,2,2,2])
        col1.write("Apartment")
        col2.write("Date")
        col3.write("Incharge")
        col4.write("Download PDF")
        st.markdown("---")

        for apt, scans_list in apartments.items():
            first_scan = scans_list[0]
            cols = st.columns([3,2,2,2])
            cols.write(apt)
            cols[1].write(first_scan.get("scan_date",""))
            cols.write(first_scan.get("Incharge",""))
            if cols.button("Download PDF", key=apt):
                pdf_file = generate_pdf(scans_list, company_name)
                with open(pdf_file, "rb") as f:
                    st.download_button("Click to download", f.read(), file_name=f"Trebirth_{apt}_{selected_month}.pdf", mime="application/pdf")
                os.remove(pdf_file)

if __name__ == "__main__":
    main()
