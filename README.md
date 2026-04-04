# Multitrack Recorder for Behringer X32 (And probably other consoles)

This project is still in development so may not work as expected.  
Inspired by https://github.com/jajito/X32-Recorder/tree/main

**Multitrack-Recorder-Behringer-X32** is a Python-based wrapper around FFmpeg for Linux.  
It allows recording and playback of 16-channel audio from a Behringer X32 (or any other console acting as a multichannel audio interface) with a simple **Web UI** by Flask.

This project was primarily created to enable devices like **Odroid** or **Raspberry Pi** to stay connected to a X32 console, record live shows, or play multitrack `.wav` files for virtual soundcheck.


### System Dependencies
- `ffmpeg` 
- `alsa-utils` 
- Python 3 (Tested on 3.9)
### Python Dependencies
- `flask`

## To start
Run web.py and open `http://<device_ip>:5000` in browser

