# SignConnect User Coaching System Documentation

## Overview

The **User Coaching System** is a real-time feedback mechanism that guides users to improve gesture detection accuracy and overall experience on the Translator page. It works like a smart assistant, providing contextual messages based on:

- **Hand detection** (present/absent in frame)
- **Confidence scores** (model certainty level)
- **Gesture stability** (smooth vs. jittery movements)
- **System state** (cooling down, committing words)

---

## 🎯 Features

### ✅ Real-Time Feedback
- Updates dynamically as the user performs gestures
- Debounced to prevent message flickering (350ms delay)
- Smooth fade-in animations

### ✅ Smart Message Priority
- **Error** (Highest Priority): Hand out of frame, gesture not recognized
- **Warning**: Unstable gesture, low confidence, need to steady hand
- **Info**: Helpful hints for medium confidence gestures
- **Success** (Lowest Priority): Good detection, auto-hides after 2 seconds

### ✅ Non-Intrusive Design
- Notification-style container below video feed
- Subtle colors and animations
- Only shows one message at a time
- Automatically hides when not needed

### ✅ Responsive Layout
- Desktop: Positioned below camera panel
- Mobile: Adapts to smaller screens

---

## 📍 Component Location

The coaching component is placed directly below the video feed in the Translator page:

```html
<!-- ── User Coaching System ── -->
<div id="coaching-container" class="coaching-container hidden">
  <div id="coaching-message" class="coaching-message">
    <span id="coaching-icon" class="coaching-icon">ℹ️</span>
    <span id="coaching-text" class="coaching-text">Coaching feedback will appear here</span>
  </div>
</div>
```

---

## 💬 Message Types

### Error Messages (Red)
| Message | Trigger |
|---------|---------|
| ❌ "Move your hand into the frame" | No gesture detected |
| ❌ "Gesture not recognized" | Confidence < 50% |

### Warning Messages (Yellow)
| Message | Trigger |
|---------|---------|
| ⚠️ "Hold gesture steady" | Confidence 50-70% |
| ⚠️ "Avoid quick movement" | High gesture instability |
| ⚠️ "Center your hand" | Hand position feedback |
| ⚠️ "Adjust distance from camera" | Distance optimization |

### Info Messages (Blue)
| Message | Trigger |
|---------|---------|
| ℹ️ "Keep hand steady to confirm" | Confidence 70-85% |

### Success Messages (Green)
| Message | Trigger |
|---------|---------|
| ✅ "Good detection!" | Confidence ≥ 85% |
| ✅ "Gesture captured successfully" | Word committed (cooling down) |

---

## 🎨 Styling

### Colors & States
```css
/* INFO state (neutral, helpful hint) */
.coaching-message.info {
  background: rgba(79, 70, 229, 0.12);
  color: #93C5FD;
  border: 1px solid rgba(79, 70, 229, 0.25);
}

/* WARNING state (yellow, stability issue) */
.coaching-message.warning {
  background: rgba(245, 158, 11, 0.12);
  color: #FCD34D;
  border: 1px solid rgba(245, 158, 11, 0.25);
}

/* ERROR state (red, serious issue) */
.coaching-message.error {
  background: rgba(239, 68, 68, 0.12);
  color: #FCA5A5;
  border: 1px solid rgba(239, 68, 68, 0.25);
}

/* SUCCESS state (green, positive feedback) */
.coaching-message.success {
  background: rgba(16, 185, 129, 0.12);
  color: #86EFAC;
  border: 1px solid rgba(16, 185, 129, 0.25);
}
```

### Animations
- **Fade-in**: 150ms smooth entrance
- **Icon pulse**: Continuous subtle pulse (2s cycle)
- **Success pulse**: Single 500ms celebration pulse

---

## ⚡ Configuration

Customize behavior in `static/js/app.js`:

```javascript
const COACHING_CONFIG = {
  DEBOUNCE_MS: 350,           // Delay before updating message (avoid flicker)
  SUCCESS_TIMEOUT_MS: 2000,   // Duration to show success message
  STABILITY_THRESHOLD: 0.15,  // Confidence variance threshold for stability
};
```

### Key Parameters

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `DEBOUNCE_MS` | 350ms | Prevents flickering by delaying message updates |
| `SUCCESS_TIMEOUT_MS` | 2000ms | Auto-hide success messages after this duration |
| `STABILITY_THRESHOLD` | 0.15 | Standard deviation of recent confidence values (>0.15 = unstable) |

---

## 🧠 Logic Flow

### 1. Confidence Tracking
```javascript
// Maintains a sliding window of last 10 confidence scores
coachingState.confidenceHistory.push(confidence);
if (coachingState.confidenceHistory.length > 10) {
  coachingState.confidenceHistory.shift();
}
```

### 2. Stability Detection
```javascript
// Calculates standard deviation of recent confidence
const stdDev = Math.sqrt(variance);
const isUnstable = stdDev > STABILITY_THRESHOLD;
```

### 3. Message Priority Resolution
```
IF no hand → ERROR: "Move your hand into the frame"
ELSE IF confidence < 0.5 → ERROR: "Gesture not recognized"
ELSE IF unstable AND confidence < 0.8 → WARNING: "Avoid quick movement"
ELSE IF confidence < 0.7 → WARNING: "Hold gesture steady"
ELSE IF confidence < 0.85 → INFO: "Keep hand steady to confirm"
ELSE IF cooling_down → SUCCESS: "Gesture captured successfully"
ELSE IF confidence ≥ 0.85 → SUCCESS: "Good detection!"
ELSE → NO MESSAGE
```

### 4. Debouncing & Timeouts
- Message updates are delayed by 350ms to prevent flickering
- Success messages auto-hide after 2 seconds
- Timer cleanup on stream pause or new message

---

## 🔧 Customization Guide

### Add a New Message Type

1. Add to `COACHING_MESSAGES` in `app.js`:
```javascript
new_type: {
  state: "warning",      // info, warning, error, success
  icon: "⚠️",            // Any emoji
  text: "Your message",
  priority: 2,           // 1=highest, 4=lowest
},
```

2. Add trigger in `determineCoachingMessage()`:
```javascript
if (someCondition) {
  return COACHING_MESSAGES.new_type;
}
```

### Customize Colors

Edit CSS in `static/css/style.css`:
```css
.coaching-message.custom-state {
  background: rgba(R, G, B, 0.12);
  color: #RRGGBB;
  border: 1px solid rgba(R, G, B, 0.25);
}
```

### Adjust Thresholds

Edit `COACHING_CONFIG` in `app.js`:
```javascript
const COACHING_CONFIG = {
  DEBOUNCE_MS: 500,              // Slower updates
  SUCCESS_TIMEOUT_MS: 3000,      // Longer success messages
  STABILITY_THRESHOLD: 0.10,     // Stricter stability check
};
```

### Change Confidence Thresholds

Edit conditions in `determineCoachingMessage()`:
```javascript
// Modify these thresholds
if (confidence < 0.60) { /* Changed from 0.5 */ }
if (confidence < 0.75) { /* Changed from 0.7 */ }
if (confidence >= 0.90) { /* Changed from 0.85 */ }
```

---

## 📱 Responsive Behavior

The coaching system automatically adapts:

**Desktop (>768px)**
- Positioned below video feed
- Full width of video panel
- Standard message display

**Tablet (480px-768px)**
- Adapts to smaller video
- Message text remains readable
- Smooth scaling

**Mobile (<480px)**
- Compact vertical layout
- Smaller icon and font sizes
- Above controls for visibility

---

## 🚫 Edge Cases Handled

✅ **Stream Paused**: Coaching hidden, state reset  
✅ **No Data**: Coaching hidden gracefully  
✅ **Rapid Confidence Changes**: Debouncing prevents flicker  
✅ **Multiple Timers**: Cleared before new messages  
✅ **Gesture Transition**: Handles gesture label changes  
✅ **Low Confidence**: Distinguishes between no-hand and low-confidence  

---

## 🧪 Testing Checklist

- [ ] Start stream → coaching hidden
- [ ] Move hand out → "Move hand into frame"
- [ ] Low confidence gesture → "Gesture not recognized"
- [ ] Hold unstable gesture → "Avoid quick movement"
- [ ] Hold steady gesture (70-85% confidence) → "Keep hand steady"
- [ ] High confidence gesture → "Good detection!"
- [ ] Commit word (cooling down) → "Gesture captured!" (auto-hides)
- [ ] Pause stream → coaching hidden
- [ ] Resize window → responsive layout maintained

---

## 🔗 Integration Points

| File | Changes |
|------|---------|
| `templates/translator.html` | Added coaching container HTML |
| `static/css/style.css` | Added coaching styling & animations |
| `static/js/app.js` | Added coaching logic & state management |

---

## 💡 Best Practices

1. **Keep Messages Short**: 1-2 words optimal (e.g., "Hold steady")
2. **Use Consistent Tone**: Friendly, encouraging, non-threatening
3. **Icon Priority**: Make icons visually distinct by state
4. **Animation Balance**: Subtle enough to not distract, noticeable enough to catch attention
5. **Timeout Strategy**: Success messages should hide before next gesture starts

---

## 📊 Performance Notes

- Debouncing prevents excessive DOM updates
- Confidence history limited to 10 values (minimal memory)
- Timer cleanup prevents memory leaks
- CSS animations use GPU acceleration (transform)
- Smooth 60fps transitions

---

## 🤝 Support & Feedback

For issues or feature requests:
1. Check the message trigger logic in `determineCoachingMessage()`
2. Verify configuration thresholds in `COACHING_CONFIG`
3. Test with different confidence threshold sliders
4. Monitor browser console for any JavaScript errors

---

**Last Updated**: 2026-04-16  
**Version**: 1.0  
**Status**: Production Ready ✅
