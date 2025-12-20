# Shadow Path Mobile

**Shadow Path** is an asymmetric tactical turn-based stealth game.
(1 Seeker vs 1 Hider)

> **Version**: 7.2 (Balanced Edition)
> **Platform**: Windows / Linux / Android
> **Networking**: Global Multiplayer via MQTT (No port forwarding required)

## 🎮 How to Play

### Roles
*   **Hider (Red)**: Survive for 30 turns or fool the Seeker.
    *   **Phase (Q)**: Walk through walls (CD: 6).
    *   **Decoy (1)**: Generate a fake heat signature (CD: 4).
    *   **Silent (2)**: Move without leaving heat traces (CD: 5).
*   **Seeker (Blue)**: Catch the Hider using scanning tools.
    *   **Probe**: Click any cell to get distance to target.
    *   **Radar (R)**: Scan a 7x7 area (CD: 3).
    *   **Catch**: Draw a green path and confirm to catch.

## 🚀 Running on PC

1.  Install Python 3.x.
2.  Install dependencies:
    ```bash
    pip install pygame paho-mqtt
    ```
3.  Run the game:
    ```bash
    python main.py
    ```

## 📱 Android Build

This repository includes a GitHub Action to automatically build the APK.

1.  Fork or Push this repository to GitHub.
2.  Go to the **Actions** tab.
3.  Wait for the "Build Android APK" workflow to finish.
4.  Download the **package** artifact and install on your phone.

## 🛠 Tech Stack

*   **Engine**: Pygame
*   **Network**: Paho-MQTT (Websockets/TCP)
*   **Build Tool**: Buildozer (for Android)
