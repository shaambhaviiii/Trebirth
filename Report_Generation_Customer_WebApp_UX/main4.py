import streamlit as st

st.set_page_config(page_title="Trebirth - Login", layout="wide")

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

def main():
    # Custom CSS for better styling
    st.markdown(
        """
        <style>
        .main-container {
            max-width: 500px;
            margin: 0 auto;
            padding: 2rem;
        }
        .login-header {
            text-align: center;
            color: #1f4e79;
            font-size: 2.5rem;
            margin-bottom: 2rem;
        }
        .login-form {
            background: #f8f9fa;
            padding: 2rem;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    
    # Check if already authenticated
    if st.session_state["authenticated"]:
        st.switch_page("pages/main5.py")
    
    # Main login interface
    st.markdown('<div class="main-container">', unsafe_allow_html=True)
    st.markdown('<h1 class="login-header">Trebirth Scan Report System</h1>', unsafe_allow_html=True)
    
    with st.container():
        st.markdown('<div class="login-form">', unsafe_allow_html=True)
        
        st.subheader("Login")
        
        company = st.text_input("Company Name", placeholder="Enter your company name")
        password = st.text_input("Password", type="password", placeholder="Enter your password")
        
        col1, col2, col3 = st.columns([1, 1, 1])
        
        with col2:
            login_button = st.button("Login", type="primary", use_container_width=True)
        
        if login_button:
            if company in company_credentials and company_credentials[company] == password:
                st.session_state["authenticated"] = True
                st.session_state["company"] = company
                st.success(f"Login successful! Welcome, {company}")
                st.balloons()
                
                # Add a small delay for better UX
                import time
                time.sleep(1)
                st.rerun()
            else:
                st.error("Invalid company name or password. Please try again.")
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Footer information
    st.markdown("---")
    st.markdown(
        """
        <div style='text-align: center; color: #666; font-size: 0.9rem;'>
        <p>Trebirth Scan Report System | Secure Access Portal</p>
        <p>For technical support, please contact your system administrator.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

if __name__ == "__main__":
    main()
