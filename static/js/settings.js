/**
 * Minimal Settings System
 * Handles theme persistence and smooth transitions
 * Production-ready with zero dependencies
 */

const Settings = (function () {
    "use strict";

    // Configuration
    const STORAGE_KEY = "app_settings";
    const THEME_DARK = "dark";
    const THEME_LIGHT = "light";

    // Default settings
    const defaults = {
        theme: THEME_DARK
    };

    // Current state
    let state = { ...defaults };

    /**
     * Initialize settings system
     */
    function init() {
        loadSettings();
        applyTheme(state.theme);
        setupThemeToggle();
        setupTransitions();
    }

    /**
     * Load settings from localStorage
     */
    function loadSettings() {
        try {
            const stored = localStorage.getItem(STORAGE_KEY);
            if (stored) {
                const parsed = JSON.parse(stored);
                state = { ...defaults, ...parsed };
            }
        } catch (error) {
            console.error("Failed to load settings:", error);
            state = { ...defaults };
        }
    }

    /**
     * Save settings to localStorage
     */
    function saveSettings() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
        } catch (error) {
            console.error("Failed to save settings:", error);
        }
    }

    /**
     * Apply theme to document
     */
    function applyTheme(theme) {
        const isValid = [THEME_DARK, THEME_LIGHT].includes(theme);
        const themeToApply = isValid ? theme : THEME_DARK;

        document.documentElement.setAttribute("data-theme", themeToApply);
        state.theme = themeToApply;
        saveSettings();

        // Dispatch event for other listeners
        window.dispatchEvent(
            new CustomEvent("themeChanged", {
                detail: { theme: themeToApply }
            })
        );
    }

    /**
     * Get current theme
     */
    function getTheme() {
        return state.theme;
    }

    /**
     * Toggle between dark and light theme
     */
    function toggleTheme() {
        const newTheme = state.theme === THEME_DARK ? THEME_LIGHT : THEME_DARK;
        applyTheme(newTheme);
    }

    /**
     * Set a setting value
     */
    function setSetting(key, value) {
        if (key in defaults) {
            state[key] = value;
            saveSettings();
            return true;
        }
        console.warn(`Setting "${key}" does not exist`);
        return false;
    }

    /**
     * Get a setting value
     */
    function getSetting(key) {
        return key in state ? state[key] : defaults[key];
    }

    /**
     * Get all settings
     */
    function getAll() {
        return { ...state };
    }

    /**
     * Reset to defaults
     */
    function reset() {
        state = { ...defaults };
        saveSettings();
        applyTheme(defaults.theme);
    }

    /**
     * Setup theme toggle button
     */
    function setupThemeToggle() {
        const toggleBtn = document.getElementById("theme-toggle");
        if (!toggleBtn) return;

        // Update button state
        updateToggleButton();

        // Toggle on click
        toggleBtn.addEventListener("click", () => {
            toggleTheme();
            updateToggleButton();
        });
    }

    /**
     * Update toggle button appearance and label
     */
    function updateToggleButton() {
        const toggleBtn = document.getElementById("theme-toggle");
        if (!toggleBtn) return;

        const isDark = state.theme === THEME_DARK;
        toggleBtn.setAttribute("aria-pressed", String(!isDark));
        toggleBtn.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
        toggleBtn.textContent = isDark ? "☀️" : "🌙";
    }

    /**
     * Enable smooth CSS transitions
     */
    function setupTransitions() {
        // Prevent transitions on initial load
        const style = document.createElement("style");
        style.textContent = `
      html.prevent-transitions,
      html.prevent-transitions * {
        transition: none !important;
      }
    `;
        document.head.appendChild(style);

        // Remove prevent-transitions class after initial paint
        document.documentElement.classList.add("prevent-transitions");
        requestAnimationFrame(() => {
            document.documentElement.classList.remove("prevent-transitions");
        });
    }

    /**
     * Public API
     */
    return {
        init,
        toggleTheme,
        getTheme,
        setSetting,
        getSetting,
        getAll,
        reset,
        THEME_DARK,
        THEME_LIGHT
    };
})();

// Auto-initialize when DOM is ready
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => Settings.init());
} else {
    Settings.init();
}
