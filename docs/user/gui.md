# GUI

> **In development.** The GUI is not released yet. This page describes the
> behaviour being built (issues #18, #19, and #28) and will be completed
> when it ships.

- The window opens when the program starts.
- **Start/Stop** streams the scope to N1MM+ using the settings in the window,
  which are saved automatically.
- **Close (X)** asks whether to *keep streaming in the system tray* or *exit*,
  with a **Remember my choice** option (setting `on_close`).
- **Minimize** hides the window to the system tray, and streaming continues.
- **Tray icon:** the tooltip shows the status; the menu has Show window,
  Start/Stop streaming, and Exit; double-click shows the window.
