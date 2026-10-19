E.D.I.T.H - the satellite for the Echo VR lobby
================================================
Even Dead I'm The Hero (a joke from Spider-Man: Far From Home).

Install
  1. Extract this whole zip somewhere (not inside the game folder).
  2. Close Echo VR.
  3. Run install.bat. It finds Echo VR through Spark's settings and asks you to confirm,
     or asks you to drag the Echo VR folder into its window.
  4. Start Echo VR and go to the lobby.

What it installs (into <Echo VR>\bin\win10\plugins)
  EDITH.dll            all of her: behaviour, voice, her lobby data and settings in one file
  With nEVR: nothing else. nEVR keeps working; the installer turns on nEVR's local plugins
    (x-local-plugins: true in _local\config.yaml) so the launcher loads her.
  Without nEVR: if the game has no plugin loader (bin\win10\dbgcore.dll) yet, it installs that too.
  Files from older E.D.I.T.H releases (plugins\EDITH\, plugins\EdithVoice\) are removed.

Talking to her
  She listens through your microphone (your default recording device). Once you've spawned in her
  lobby and while you're not muted on Echo's voice chat, what you say is sent to her server, where
  it's turned into text so she can answer; nothing is sent while you're muted or away from her
  lobby. Say "Edith" to get her attention. With nEVR, her settings can be changed from the
  launcher's Options for her (for example mic = off).

Uninstall
  Run uninstall.bat. It removes E.D.I.T.H but not the plugin loader, which your other mods may use.
