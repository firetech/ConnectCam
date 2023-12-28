ConnectCam - Minimialistic webcam manager for Prusa Connect
===========================================================
Upgrading from a Prusa i3 MK3S+ to a Prusa MK4, I lost the great feature of
connecting USB web cameras to the Raspberry Pi Zero I had running PrusaLink.
This utility aims to be a solution to that problem.

Simply take your old PrusaLink-Pi, give it a fresh installation of Raspberry Pi
OS Lite, connect your webcam(s), install ConnectCam, and your cameras are back
in Prusa Connect!

Requirements
------------
* A Linux-based OS, like Raspberry Pi OS (ConnectCam is using
  [V4L2](https://en.wikipedia.org/wiki/Video4Linux) for basically everything)
* Python (3.1+)
* Python libraries:
  - On **Raspberry Pi OS**, these apt packages:  
    `sudo apt install python3-toml python3-requests python3-v4l2`  
    (All of these are installed by default in Raspberry Pi OS Lite.)
  - On **other** OS, these pip packages:  
    `pip install toml requests v4l2-python3`

Installation
------------
1. Run `v4l2-ctl --list-devices` to find your connected cameras.  
   **Example:**
   ```
   UVC Camera (046d:0825) (usb-20980000.usb-1.1):
           /dev/video0
           /dev/video1
           /dev/media0

   Full HD webcam: Full HD webcam (usb-20980000.usb-1.3):
           /dev/video2
           /dev/video3
           /dev/media1
   ```
2. Copy `config.toml.example` to `config.toml` and edit to your needs, adding
   your cameras to Prusa Connect to generate the needed tokens.  
   **Example:**
   ```
   refresh_rate = 10 # Seconds between each snapshot

   [[cameras]]
   name = "Full HD webcam: Full HD webcam"
   token = "T0k3n0N3"

   [[cameras]]
   name = "UVC Camera (046d:0825)"
   token = "T0k3n7W0"
   ```
   (There are more settings available, see [config.toml.example](
   https://github.com/firetech/ConnectCam/blob/master/config.toml.example) for
   more info.)
3. Run `./connectcam.py -vo config.toml` to make sure your config works.
4. Run `./install_service.sh config.toml` to install ConnectCam as a system
   service, starting automatically on boot.
5. Done!

Limitations
-----------
To keep the code small, and required libraries to the minimum, ConnectCam
(currently) only supports MJPEG capable web cameras (unlike Prusa Link, which
also supports YUYV). This works for my two cameras (Logitech C270 and Trust
Trino HD). Experiments with YUYV just seemed to hang for some unknown reason
when trying to speak to more than one camera at a time, so I gave that up quite
quickly.

Since I don't own any Pi Camera, I am unsure how this limitation affects them.
Pull Requests are more than welcome, though! :)
