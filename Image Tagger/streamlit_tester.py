import streamlit as st
import cv2
from PIL import Image
import numpy as np
import tempfile
import os
import time
from dotenv import load_dotenv

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from modules import frozen_config as FROZEN
import modules.image_processing as ip
from modules.video_processor import VideoProcessor
from local_pipeline import DummyVideoDB

st.set_page_config(page_title="Mac Prototype Tester", layout="wide")
st.title("dY?? SuperSearch Mac Prototype - Tuning Tester")

load_dotenv()
api_keys = [k.strip() for k in os.getenv('GEMINI_API_KEYS', os.getenv('GEMINI_API_KEY', '')).split(',') if k.strip()]

# ----------------- SIDEBAR CONTROLS -----------------
st.sidebar.header("sT,? Detection Settings")
FROZEN.FACE_COSINE_THRESHOLD = st.sidebar.slider(
    "Cosine Similarity Threshold", 0.0, 1.0, float(FROZEN.FACE_COSINE_THRESHOLD), 0.01
)
FROZEN.FACE_MIN_SHARPNESS = st.sidebar.slider(
    "Min Sharpness", 0, 100, int(FROZEN.FACE_MIN_SHARPNESS), 1
)
FROZEN.FACE_MIN_SIZE = st.sidebar.slider(
    "Min Face Size (px)", 0, 200, int(FROZEN.FACE_MIN_SIZE), 1
)
FROZEN.FACE_MAX_FACES = st.sidebar.number_input(
    "Max Faces Per Image/Frame", min_value=1, max_value=100, value=int(FROZEN.FACE_MAX_FACES)
)

show_bounding_box = st.sidebar.checkbox("Show Bounding Boxes", value=True)
show_confidence = st.sidebar.checkbox("Show Confidence Score", value=True)

st.sidebar.header("dYZ Video Settings")
FROZEN.VIDEO_FPS_EXTRACT = st.sidebar.slider("Extract Frames Per Second", 0.1, 5.0, 1.0, 0.1)
enable_ai_analysis = st.sidebar.checkbox("Enable AI Frame Analysis (Gemini)", value=True)
parallel_workers = st.sidebar.slider("Parallel Workers (LLM)", 1, 8, 4, 1)

st.sidebar.markdown("---")
st.sidebar.header("dYZ Video Temporal Consensus")
FROZEN.VIDEO_PLAYER_MIN_FRAMES = st.sidebar.slider(
    "Absolute Min Frames", 1, 20, int(getattr(FROZEN, 'VIDEO_PLAYER_MIN_FRAMES', 2)), 1
)
FROZEN.VIDEO_PLAYER_MIN_FRAMES_RATIO = st.sidebar.slider(
    "Min Frame Ratio", 0.0, 0.5, float(getattr(FROZEN, 'VIDEO_PLAYER_MIN_FRAMES_RATIO', 0.05)), 0.01
)


# ----------------- MAIN UI -----------------
upload_mode = st.radio("Select Upload Mode:", ["Images", "Video"], horizontal=True)
uploaded_file = st.file_uploader("Upload Media", type=["jpg", "png", "jpeg"] if upload_mode == "Images" else ["mp4", "mov"])

if uploaded_file is not None:
    if upload_mode == "Images":
        image = Image.open(uploaded_file)
        image_np = np.array(image.convert("RGB"))
        
        with st.spinner("Processing image through Mac Prototype pipeline..."):
            results, face_count, skip_reason, orientation, rotation_applied = ip.process_image(image_np)
            
            annotated = image_np.copy()
            for (x1, y1, x2, y2, name, confidence) in results:
                color = (0, 0, 255) if name.lower() == "unknown" else (0, 255, 0)
                if show_bounding_box:
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 3)
                
                label = f"{name}"
                if show_confidence:
                    label += f" ({confidence:.1f})"
                
                if show_bounding_box or show_confidence:
                    cv2.putText(annotated, label, (x1, max(y1 - 10, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            
            col1, col2 = st.columns([2, 1])
            with col1:
                st.image(annotated, caption="Annotated Result")
            with col2:
                st.write("### Analysis Results")
                st.write(f"**Total Faces Detected:** {face_count}")
                st.write(f"**Skip Reason:** {skip_reason or 'None'}")
                st.write(f"**Orientation:** {orientation}")
                
                st.write("### Detailed Player Tags")
                if results:
                    for r in results:
                        st.write(f"- **{r[4]}** (Score: {r[5]:.2f})")
                else:
                    st.write("No confident players found.")
                    
    elif upload_mode == "Video":
        pipeline_start = time.time()
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(uploaded_file.read())
            tmp_path = tmp.name
        
        os.environ['VIDEO_FPS_EXTRACT'] = str(FROZEN.VIDEO_FPS_EXTRACT)
        
        if not api_keys:
            st.error("No GEMINI_API_KEYS found in .env!")
        else:
            vp = VideoProcessor(api_keys=api_keys, db_manager=DummyVideoDB(), max_workers=parallel_workers)
            
            st.markdown("### dYZz,? Step 1: FFmpeg Frame Extraction")
            step1_start = time.time()
            with st.spinner("Extracting frames via FFmpeg..."):
                frame_paths = vp.extract_frames_ffmpeg(tmp_path)
            step1_time = time.time() - step1_start
            
            if not frame_paths:
                st.error("?O No frames extracted.")
            else:
                st.info(f"?,? Extraction time: {step1_time:.2f}s (Extracted {len(frame_paths)} frames)")
                
                st.markdown("### dY`  Step 2: Face Detection")
                step2_start = time.time()
                with st.spinner("Running open-set facial recognition on frames..."):
                    all_results, frames_with_players = vp.detect_faces_sequential(frame_paths)
                step2_time = time.time() - step2_start
                st.info(f"?,? Detection time: {step2_time:.2f}s (Found {len(frames_with_players)} frames with players)")
                
                import collections
                player_counts = collections.Counter()
                
                if frames_with_players:
                    st.write("#### Frames with detected players:")
                    cols = st.columns(3)
                    for i, frame in enumerate(frames_with_players):
                        col = cols[i % 3]
                        img = cv2.imread(frame['frame_info']['path'])
                        if img is not None:
                            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                            caption_parts = []
                            for det in frame['detections']:
                                x1, y1, x2, y2 = det['bbox']
                                name = det['name']
                                player_counts[name] += 1
                                if show_bounding_box:
                                    cv2.rectangle(img, (x1, y1), (x2, y2), (0,255,0), 3)
                                label = name
                                if show_confidence:
                                    label += f" ({det.get('confidence', 0):.1f})"
                                if show_bounding_box or show_confidence:
                                    cv2.putText(img, label, (x1, max(y1-10, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)
                                caption_parts.append(name)
                            col.image(img, caption=f"Sec {frame['frame_info'].get('second', 0)}: {', '.join(caption_parts)}", use_container_width=True)
                
                # Temporal consensus calculation
                st.markdown("### dY - Step 3: Temporal Consensus Filter")
                min_frames_abs = FROZEN.VIDEO_PLAYER_MIN_FRAMES
                min_frames_ratio = FROZEN.VIDEO_PLAYER_MIN_FRAMES_RATIO
                threshold = max(min_frames_abs, int(len(frame_paths) * min_frames_ratio))
                
                st.write(f"**Requirement:** Player must appear in at least **{threshold}** frames to be verified.")
                
                final_players = []
                for p, count in player_counts.items():
                    if count >= threshold:
                        final_players.append(p)
                        st.success(f"aœ? **{p}**: {count} frames (Included)")
                    else:
                        st.error(f"a C **{p}**: {count} frames (Filtered out as false positive)")
                
                llm_analyses = []
                step4_start = time.time()
                if enable_ai_analysis and final_players:
                    st.markdown("### Step 4: Parallel AI Analysis")
                    with st.spinner(f"Running Gemini AI analysis across {parallel_workers} workers..."):
                        llm_analyses = vp.parallel_llm_analysis(frames_with_players)
                    
                    st.info(f"?,? LLM analysis time: {(time.time() - step4_start):.2f}s")
                    
                    # Frame-by-frame LLM results (like playerStreamlit)
                    if llm_analyses:
                        st.write("#### Frame-by-frame AI Analysis:")
                        for idx, analysis in enumerate(llm_analyses):
                            st.markdown(f"**Frame @ {analysis.get('second', 0)}s** - Players: *{', '.join(analysis.get('players', []))}*")
                            st.info(analysis.get('description', ''))
                            st.markdown("---")
                            
                    st.markdown("### Step 5: Generating Final Summary")
                    final_summary = vp.generate_final_summary(llm_analyses, final_players, is_unknown_faces=False)
                    st.write("#### Final Video Tag Data:")
                    st.json({
                        "Final Players": final_players,
                        "Caption": final_summary.get('caption', ''),
                        "Action": final_summary.get('action', ''),
                        "Event": final_summary.get('event', ''),
                        "Mood": final_summary.get('mood', '')
                    })
                elif not enable_ai_analysis:
                    st.info("AI Analysis disabled. Only structural tags generated.")
                    st.json({
                        "Final Players": final_players
                    })
                else:
                    st.warning("No players passed the consensus filter, AI analysis skipped.")
                    
                total_time = time.time() - pipeline_start
                st.info(f"**Total pipeline time:** {total_time:.2f}s")
        
        # Cleanup
        try:
            os.remove(tmp_path)
            for f in frame_paths:
                if os.path.exists(f['path']):
                    os.remove(f['path'])
        except:
            pass
