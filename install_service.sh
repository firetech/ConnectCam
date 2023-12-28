#!/bin/sh -e

[ $(id -u) != "0" ] || {
  echo "Don't run this as root!" >&2
  exit 1
}

[ -x "$(which systemctl)" ] || {
  echo "systemctl not found. Are you not using Systemd?" >&2
  exit 1
}

dir=$(dirname $(realpath $0))
config=
[ -z $1 ] || {
  config=$(realpath $1)
}

echo "# Installing service file for ConnectCam..."

sudo tee /etc/systemd/system/connectcam.service > /dev/null << EOF
[Unit]
Description=Minimalistic webcam manager for Prusa Connect
After=network-online.target

[Service]
User=$(id -u)
Group=$(id -g)
WorkingDirectory=$dir
ExecStart=/usr/bin/python3 $dir/connectcam.py $config

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable connectcam.service

echo "# Starting ConnectCam service..."
sudo systemctl start connectcam.service
