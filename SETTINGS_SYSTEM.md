# Minimal Settings System Documentation

A production-ready, lightweight settings system for web apps with theme switching, localStorage persistence, and smooth transitions.

## Features

✅ **Theme Toggle** - Dark/Light mode switching  
✅ **localStorage Persistence** - Settings survive page reloads  
✅ **Smooth Transitions** - CSS animations between themes  
✅ **FOUC Prevention** - No flash of unstyled content on load  
✅ **Event System** - Dispatch events when settings change  
✅ **Zero Dependencies** - Pure vanilla JavaScript and CSS  
✅ **Accessibility** - ARIA labels and semantic HTML  
✅ **Responsive** - Mobile-friendly UI  

## Quick Start

### 1. Include Files

```html
<!DOCTYPE html>
<html lang="en" data-theme="dark">
  <head>
    <link rel="stylesheet" href="static/css/settings.css">
  </head>
  <body>
    <header>
      <button id="theme-toggle" type="button">🌙</button>
    </header>
    
    <main>
      <!-- Your content here -->
    </main>

    <script src="static/js/settings.js"></script>
  </body>
</html>
```

### 2. Use CSS Variables

```css
body {
  background-color: var(--bg-primary);
  color: var(--text-primary);
  transition: background-color 0.3s ease;
}

button {
  background-color: var(--accent);
  transition: background-color 0.3s ease;
}
```

### 3. Done!

The system auto-initializes. Users can toggle the theme, and it persists across sessions.

## JavaScript API

### Methods

#### `Settings.init()`
Initializes the settings system. Called automatically on page load.
```javascript
Settings.init();
```

#### `Settings.toggleTheme()`
Toggle between dark and light themes.
```javascript
Settings.toggleTheme();
```

#### `Settings.getTheme()`
Get the current theme.
```javascript
const theme = Settings.getTheme();  // Returns 'dark' or 'light'
```

#### `Settings.setSetting(key, value)`
Set a setting value and persist to localStorage.
```javascript
Settings.setSetting('theme', 'light');
```

#### `Settings.getSetting(key)`
Get a setting value.
```javascript
const theme = Settings.getSetting('theme');
```

#### `Settings.getAll()`
Get all current settings.
```javascript
const settings = Settings.getAll();
// Returns: { theme: 'dark' }
```

#### `Settings.reset()`
Reset all settings to defaults and re-apply.
```javascript
Settings.reset();
```

### Constants

```javascript
Settings.THEME_DARK   // 'dark'
Settings.THEME_LIGHT  // 'light'
```

### Events

Listen for theme changes:
```javascript
window.addEventListener('themeChanged', (event) => {
  console.log('Theme changed to:', event.detail.theme);
});
```

## CSS Variables Available

### Dark Theme
```css
:root[data-theme="dark"] {
  --bg-primary: #0B0F19;
  --bg-secondary: #111827;
  --surface: #1F2937;
  --surface-hover: #2D3748;
  --border: #374151;
  --text-primary: #E5E7EB;
  --text-secondary: #9CA3AF;
  --text-muted: #6B7280;
  --accent: #4F46E5;
  --accent-hover: #4338CA;
  --success: #10B981;
  --warning: #F59E0B;
  --error: #EF4444;
}
```

### Light Theme
```css
:root[data-theme="light"] {
  --bg-primary: #FFFFFF;
  --bg-secondary: #F9FAFB;
  --surface: #F3F4F6;
  --surface-hover: #E5E7EB;
  --border: #D1D5DB;
  --text-primary: #1F2937;
  --text-secondary: #4B5563;
  --text-muted: #6B7280;
  --accent: #4F46E5;
  --accent-hover: #4338CA;
  --success: #059669;
  --warning: #D97706;
  --error: #DC2626;
}
```

## Extending the System

### Adding New Settings

1. **Update defaults in settings.js:**
```javascript
const defaults = {
  theme: THEME_DARK,
  fontSize: 'medium',
  language: 'en'
};
```

2. **Add CSS variables for new settings:**
```css
:root[data-font-size="small"] {
  --text-base: 14px;
  --text-lg: 16px;
}

:root[data-font-size="medium"] {
  --text-base: 16px;
  --text-lg: 18px;
}
```

3. **Use in your code:**
```javascript
Settings.setSetting('fontSize', 'large');
const size = Settings.getSetting('fontSize');
```

### Custom Theme Colors

Edit the CSS variables in `static/css/settings.css`:

```css
:root[data-theme="dark"] {
  --accent: #YOUR_COLOR;
  --success: #YOUR_COLOR;
  /* ... etc */
}
```

## Integration Examples

### With React

```jsx
import { useEffect, useState } from 'react';

function ThemeToggle() {
  const [theme, setTheme] = useState(Settings.getTheme());

  useEffect(() => {
    const handleThemeChange = (e) => {
      setTheme(e.detail.theme);
    };

    window.addEventListener('themeChanged', handleThemeChange);
    return () => window.removeEventListener('themeChanged', handleThemeChange);
  }, []);

  return (
    <button onClick={() => Settings.toggleTheme()}>
      {theme === 'dark' ? '☀️' : '🌙'}
    </button>
  );
}
```

### With Vue

```vue
<template>
  <button @click="Settings.toggleTheme()">
    {{ Settings.getTheme() === 'dark' ? '☀️' : '🌙' }}
  </button>
</template>

<script>
export default {
  data() {
    return {
      Settings
    };
  }
};
</script>
```

### With Alpine.js

```html
<div x-data="{ theme: 'dark' }" @theme-changed="theme = $event.detail.theme">
  <button @click="Settings.toggleTheme()">
    <span x-show="theme === 'dark'">☀️</span>
    <span x-show="theme === 'light'">🌙</span>
  </button>
</div>
```

## Customization

### Change Toggle Button Appearance

```html
<!-- Custom emoji -->
<button id="theme-toggle">🌗</button>

<!-- Or custom SVG icon -->
<button id="theme-toggle">
  <svg width="24" height="24"><!-- icon SVG --></svg>
</button>

<!-- Or text -->
<button id="theme-toggle">Toggle Theme</button>
```

### Custom Storage Key

Edit in `settings.js`:
```javascript
const STORAGE_KEY = "my_app_settings";  // Change this
```

### Disable Smooth Transitions on Load

Remove or comment out the `setupTransitions()` call in `init()`.

## Browser Compatibility

- ✅ Chrome/Edge 49+
- ✅ Firefox 31+
- ✅ Safari 9.1+
- ✅ iOS Safari 9.3+
- ✅ Android 5+

CSS Variables (custom properties) are required. For IE11 support, provide fallback colors.

## Performance

**File Sizes:**
- `settings.js`: ~2.5 KB (uncompressed), ~1 KB (gzipped)
- `settings.css`: ~3 KB (uncompressed), ~1.2 KB (gzipped)

**Runtime Performance:**
- No layout shifts or repaints during initialization
- Smooth 60 FPS transitions
- No JavaScript framework overhead
- Minimal DOM manipulation

## Troubleshooting

### Theme not persisting
- Check browser's localStorage is enabled
- Verify `STORAGE_KEY` is not shared with other apps
- Check browser console for errors: `Settings.getAll()`

### FOUC (Flash of Unstyled Content) visible
- Ensure `settings.js` is loaded before rendering content
- Check that `html.prevent-transitions` CSS rule exists
- Verify requestAnimationFrame is supported

### Toggle button not working
- Check button has id="theme-toggle"
- Verify settings.js is loaded and initialized
- Check browser console for JavaScript errors

## License

This settings system is provided as-is for production use.

## See Also

- [SETTINGS_DEMO.html](SETTINGS_DEMO.html) - Interactive demo with examples
- [static/js/settings.js](static/js/settings.js) - Source code
- [static/css/settings.css](static/css/settings.css) - CSS variables and styling
