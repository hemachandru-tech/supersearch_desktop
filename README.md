# SuperSearch Desktop Application

This package contains the complete SuperSearch application, divided into two main components:

## 1. Image Tagger (Mac Prototype)
This is the core AI-powered tagging backend and its native Desktop/Mac UI interface. It handles massive batch processing of images and videos using Open-Set facial recognition, Temporal Consensus filtering, and Gemini AI analysis.

### How to use:
- **Windows users:** Double click `run_desktop.py` (or run it via terminal) to open the native desktop window.
- **Mac users:** Run `Install SuperSearch.command` once, and then `Launch SuperSearch.command` to start the app.
- **To test the logic and fine-tune thresholds:** Run `python -m streamlit run streamlit_tester.py` from your terminal to open the tuning interface.

### Requirements:
To install dependencies for this module, navigate into the `Image Tagger` folder and run:
`pip install -r requirements_desktop.txt`

---

## 2. Player Streamlit (Legacy / Ultra-Fast Pipeline)
This is the original standalone Streamlit interface designed for ultra-fast processing using the closed-set SVM model. 

### How to use:
Navigate into the `Player Streamlit` directory in your terminal and run:
`python -m streamlit run appvi.py`

### Requirements:
To install dependencies for this module, navigate into the `Player Streamlit` folder and run:
`pip install -r requirements.txt`

---
*Note: Both applications rely on API keys. Ensure your `.env` file is properly configured with your `GEMINI_API_KEY` (or `GEMINI_API_KEYS` comma-separated).*
