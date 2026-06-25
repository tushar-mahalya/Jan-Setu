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
