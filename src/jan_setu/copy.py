"""Bilingual (Hindi + English) message copy for the conversation engine.

All citizen-facing strings live here so wording and translations are reviewed in
one place. WhatsApp limits: interactive body text <= 1024 chars, reply button
title <= 20 chars (so the bilingual titles below stay short).
"""

# Stable reply-button IDs. Branch on these, never on the displayed title text.
CONFIRM_YES_ID = "loc_confirm_yes"
CONFIRM_NO_ID = "loc_confirm_no"

GREETING = (
    "नमस्ते! जन सेतु में आपका स्वागत है। आपकी शिकायत दर्ज करने के लिए हमें आपका "
    "स्थान चाहिए।\n\n"
    "Hello! Welcome to Jan Setu. To register your grievance we need your location."
)

# Body shown alongside the native "Send location" button.
LOCATION_REQUEST = (
    "कृपया नीचे दिए गए बटन से अपना वर्तमान स्थान साझा करें।\n\n"
    "Please share your current location using the button below."
)

# Sent when we expected a location but got something else.
LOCATION_REPROMPT = (
    "हम आपके सटीक स्थान के बिना आगे नहीं बढ़ सकते। कृपया बटन से अपना स्थान साझा करें।\n\n"
    "We cannot proceed without your exact location. Please share it using the button."
)

# Buttons (titles must be <= 20 characters).
CONFIRM_YES_TITLE = "हाँ / Yes"
CONFIRM_NO_TITLE = "नहीं / No"

# Body for the Yes/No confirmation. Format with the resolved address (or raw
# coordinates when geocoding failed).
CONFIRM_LOCATION = (
    "क्या यह आपका वर्तमान स्थान है?\n{address}\n\nIs this your current location?\n{address}"
)

# Shown when geocoding fails — we still confirm using raw coordinates.
RAW_COORDINATES = "अक्षांश/Lat {lat:.5f}, देशांतर/Lon {lon:.5f}"

# Entry point of the next slice (issue capture). Sent on confirmed location.
ASK_ISSUE = (
    "धन्यवाद! अब कृपया अपनी समस्या बताएं — आप टेक्स्ट या वॉइस मैसेज भेज सकते हैं।\n\n"
    "Thank you! Now please describe your issue — you can send a text or a voice message."
)

# --- Issue capture (Slice 2) ---------------------------------------------------

# "Done" button shown with ASK_ISSUE. The citizen may send several text/voice
# messages, then taps Done to finish.
ISSUE_DONE_ID = "issue_done"
ISSUE_DONE_TITLE = "हो गया / Done"

# Sent if the user taps Done before describing anything — guards empty tickets.
ISSUE_EMPTY = (
    "कृपया पहले अपनी समस्या बताएं, फिर 'हो गया' दबाएं।\n\n"
    "Please describe your issue first, then tap 'Done'."
)

# Acknowledgement merged into the photo prompt (one message to keep order).
ISSUE_RECEIVED = "हमें आपके संदेश मिल गए हैं।\n\nWe have received your messages."

# Photo prompt with two buttons. Camera-only capture needs WhatsApp Flows +
# business verification (out of scope), so we request a live photo but cannot
# enforce the camera.
PHOTO_PROMPT = (
    "क्या आप घटना की एक लाइव फ़ोटो साझा करना चाहते हैं ताकि अधिकारी उसे आसानी से "
    "पहचान सकें?\n\n"
    "Would you like to share a live photo of the incident so authorities can "
    "identify it easily?"
)
PHOTO_SHARE_ID = "photo_share"
PHOTO_SHARE_TITLE = "फ़ोटो भेजें/Photo"
PHOTO_SKIP_ID = "photo_skip"
PHOTO_SKIP_TITLE = "नहीं / Skip"

# Sent after the user taps "share a photo": ask them to take a live photo now.
PHOTO_INSTRUCTION = (
    "कृपया अभी घटना की एक लाइव फ़ोटो लें और भेजें।\n\n"
    "Please take a live photo of the incident now and send it."
)

# Final registration confirmation. Format with the human-readable grievance id.
REGISTERED = (
    "आपकी शिकायत जन सेतु में दर्ज हो गई है।\nपंजीकरण क्रमांक: {grievance_id}\n"
    "हम आपको पुष्टिकरण रिपोर्ट भेजेंगे।\n\n"
    "Your complaint is registered with Jan Setu.\nReference ID: {grievance_id}\n"
    "We will send you a confirmation report."
)
