"""
AI Prompts Module for Video Analysis
Contains standardized prompts for frame-by-frame and summary analysis
"""

def get_frame_analysis_prompt(player_names):
    """
    Frame-level analysis prompt for individual video frames.
    Returns tag + description for each frame with detected players.
    
    Args:
        player_names: List of player names detected in the frame (can be empty)
    
    Returns:
        str: Formatted prompt for Gemini AI
    """
    if not player_names:
        # No players detected - analyze the frame without player context
        prompt = f"""
This is a cricket video frame with no detected players.

Analyze the frame and provide a TWO-PART analysis:

**TAG:** (5 words maximum, title case)
Format: [Activity/Scene Description]
Examples:
- "Cricket Field Empty"
- "Training Equipment Setup"
- "Stadium View"

**DESCRIPTION:** (20-30 words)
Describe what is visible in this frame:
- The scene or setting
- Any equipment, field, or environment visible
- General context of the cricket-related content
- Any notable features

Format your response exactly as:
TAG: [your 5-word tag]
DESCRIPTION: [your 20-30 word description]

Example:
TAG: Cricket Field Empty
DESCRIPTION: Empty cricket field with pitch visible in center. Training equipment scattered around boundary. Stadium stands visible in background under clear sky.
"""
    else:
        players_str = ", ".join(player_names)
        prompt = f"""
Detected players in this cricket frame: {players_str}

You see the image with bounding boxes around each detected player.

Provide a TWO-PART analysis:

**TAG:** (5 words maximum, title case)
Format: [Player Names] + [Activity/Action]
Examples:
- "Dhoni, Raina Nets Interaction"
- "Rayudu Batting Practice"
- "Kohli, Sharma Catching Drill"

**DESCRIPTION:** (20-30 words)
Describe the specific activity visible in this frame:
- What each player is doing
- The type of drill or practice
- Equipment being used (bat, ball, pads, etc.)
- Setting (nets, field, indoor)
- Any notable technique or interaction

Format your response exactly as:
TAG: [your 5-word tag]
DESCRIPTION: [your 20-30 word description]

Example:
TAG: Dhoni, Raina Nets Interaction
DESCRIPTION: Dhoni and Raina engaged in batting practice at the nets. Dhoni demonstrating forward defense technique while Raina observes. Both wearing full batting gear with coach providing feedback.
"""
    return prompt


def get_final_summary_prompt(frame_analyses, all_detected_players, is_unknown_faces=False):
    """
    Generate comprehensive video summary from frame analyses.
    
    Args:
        frame_analyses: List of dicts with keys: frame, timestamp, players, analysis
        all_detected_players: List of all unique players detected in video (can be empty)
        is_unknown_faces: If True, limit summary to 15 words
    
    Returns:
        str: Formatted prompt for final summary generation
    """
    analysis_context = ""
    for analysis_data in frame_analyses:
        frame_num = analysis_data['frame']
        timestamp = analysis_data['timestamp']
        players = ", ".join(analysis_data['players']) if analysis_data.get('players') else "No players"
        analysis = analysis_data['analysis']
       
        analysis_context += f"Frame {frame_num} ({timestamp:.1f}s) - {players}: {analysis}\n"
   
    if all_detected_players:
        players_str = ", ".join(all_detected_players)
        players_context = f"featuring: {players_str}"
    else:
        players_context = "with no detected players"

    prompt = f"""You analyzed multiple frames from a cricket video {players_context}

Frame-by-frame observations:
{analysis_context}

Create a STRUCTURED VIDEO SUMMARY with these sections.
Keep the language SIMPLE and PLAIN, like a short news photo caption. No fancy or commentary-style words.

**PRIMARY TAG:** (simple caption, 15 words maximum)
One short, simple phrase saying who is doing what, and where.
Return ONE line only — no alternatives, no bullet list, no quotes.
{"Do NOT invent player names. Use a generic subject (e.g., 'Player', 'Players')." if not all_detected_players else f"USE EXACTLY THESE NAMES for the players: {players_str}."}
Examples:
{"- Player batting at nets" if not all_detected_players else "- Dhoni playing at nets"}
{"- Players doing catching drill" if not all_detected_players else "- Dhoni and Raina batting at nets"}
{"- Players warming up on the ground" if not all_detected_players else "- Jadeja bowling during practice"}

**VIDEO SUMMARY:** (one simple sentence, 15 words maximum)
Say simply who is in the video and what they are doing.
Return ONE line only — no alternatives, no bullet list, no quotes.
{"Do NOT invent player names. Use a generic subject (e.g., 'A player', 'Players')." if not all_detected_players else f"USE EXACTLY THESE NAMES for the players: {players_str}."}
Examples:
{"- A player practicing batting at the nets." if not all_detected_players else "- Dhoni practicing batting at the nets."}
{"- Players taking part in a training session." if not all_detected_players else "- Dhoni and Gaikwad batting during a training session."}

**SEARCHABLE KEYWORDS:**
Provide 8-10 relevant keywords for categorization:
[keyword1], [keyword2], [keyword3], etc.

Format your response with clear section headers as shown above.
"""
   
    return prompt