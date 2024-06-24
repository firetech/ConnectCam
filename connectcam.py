#!/usr/bin/env python3

# ConnectCam - Minimialistic webcam manager for Prusa Connect
# Copyright (C) 2023  Joakim Tufvegren
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import os
import re
import sys
import mmap
import time
import v4l2
import toml
import errno
import fcntl
import base64
import select
import signal
import requests
import threading

CAMERA_WAIT_TIMEOUT = 10
DEFAULT_URL = 'https://connect.prusa3d.com/c/snapshot'

verbose = False


def verbose_print(*args, **kwargs):
    if verbose:
        print(*args, **kwargs)


def load_config(config_file = None):
    if config_file is None:
        path = os.path.dirname(os.path.realpath(__file__))
        config_file = os.path.join(path, 'config.toml')
    verbose_print("Loading '{}'...".format(config_file))
    config = toml.load(config_file)
    if not 'camera' in config or len(config['camera']) < 1:
        if 'cameras' in config and len(config['cameras']) >= 1:
            config['camera'] = config['cameras']
        else:
            raise ValueError("No cameras in config!")
    if not 'refresh_rate' in config:
        config['refresh_rate'] = 30
    return config


def get_device(camera_name):
    dev = None
    for f in os.listdir("/sys/class/video4linux"):
        real_file = os.path.realpath(
            '/sys/class/video4linux/{}/name'.format(f))
        with open(real_file, "rt") as name_file:
            name = name_file.read().rstrip()
        if camera_name in name:
            if dev is None or f < dev:
                dev = f
    return '/dev/{}'.format(dev)


def init(vd, config = {}):
    verbose_print("Initializing '{}' ({})".format(config['name'], vd.name))
    # Check video capture capability
    cp = v4l2.v4l2_capability()
    fcntl.ioctl(vd, v4l2.VIDIOC_QUERYCAP, cp)
    if v4l2.V4L2_CAP_VIDEO_CAPTURE & cp.capabilities == 0:
        raise ValueError

    # Set specified (or max) resolution
    config_res = config['resolution'] if 'resolution' in config else None
    if config_res is not None:
        c_width, c_height = map(int, config_res.split('x'))
        config_res_found = False
    fmt = v4l2.v4l2_format()
    fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
    fmt.fmt.pix.pixelformat = v4l2.V4L2_PIX_FMT_MJPEG
    max_pixels = 0
    size = v4l2.v4l2_frmsizeenum()
    size.pixel_format = fmt.fmt.pix.pixelformat
    size.index = 0
    while True:
        try:
            fcntl.ioctl(vd, v4l2.VIDIOC_ENUM_FRAMESIZES, size)
        except OSError:
            break
        if size.type == v4l2.V4L2_FRMSIZE_TYPE_DISCRETE:
            width = size.discrete.width
            height = size.discrete.height
            curr_pixels = width * height
            match = (config_res is not None and
                    c_width == width and
                    c_height == height)
            if match or curr_pixels >= max_pixels:
                fmt.fmt.pix.width = width
                fmt.fmt.pix.height = height
                max_pixels = curr_pixels
                if match:
                    config_res_found = True
                    break
        size.index += 1
    if config_res is not None and not config_res_found:
        print("Warning: Resolution '{}' not supported by '{}', " \
                "using max instead".format(
                    config_res,
                    config['name']),
                file=sys.stderr)
    verbose_print("Setting resolution {}x{}".format(
                fmt.fmt.pix.width,
                fmt.fmt.pix.height))
    fcntl.ioctl(vd, v4l2.VIDIOC_S_FMT, fmt)

    # Request and set up capture buffer
    req = v4l2.v4l2_requestbuffers()
    req.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
    req.memory = v4l2.V4L2_MEMORY_MMAP
    req.count = 1
    fcntl.ioctl(vd, v4l2.VIDIOC_REQBUFS, req)
    buf = v4l2.v4l2_buffer()
    buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
    buf.memory = v4l2.V4L2_MEMORY_MMAP
    buf.index = 0
    fcntl.ioctl(vd, v4l2.VIDIOC_QUERYBUF, buf)
    mm = mmap.mmap(vd.fileno(),
        buf.length,
        mmap.MAP_SHARED,
        mmap.PROT_READ | mmap.PROT_WRITE,
        offset=buf.m.offset)

    # Start streaming
    fcntl.ioctl(vd, v4l2.VIDIOC_STREAMON,
            v4l2.v4l2_buf_type(v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE))

    return buf, mm


# Adapted from https://stackoverflow.com/a/29838711
class MMapStreamer(object):
    def __init__(self, mmap, total, block=65535):
        self.mmap = mmap
        self.remaining = total
        self.block = block

        # So that requests doesn't try to chunk the upload but will instead
        # stream it:
        self.len = total

    def read(self, amount=-1):
        if self.remaining <= 0:
            return b''
        if amount < 0:
            amount = self.total
        data = self.mmap.read(min(self.block, self.remaining, amount))
        self.remaining -= len(data)
        return data


def capture(vd, buf, mm, config):
    # Grab a frame
    fcntl.ioctl(vd, v4l2.VIDIOC_QBUF, buf)
    events, *_ = select.select((vd,), (), (), CAMERA_WAIT_TIMEOUT)
    if not events:
        raise TimeoutError("Timeout getting frame for '{}'".format(
                    config['name']))
    fcntl.ioctl(vd, v4l2.VIDIOC_DQBUF, buf)
    verbose_print("Captured frame for '{}'".format(config['name']))
    # At this point, the `mm` mmap contains the frame data

    # And send it to Prusa Connect
    response = requests.put(
        config['url'],
        headers={
            'Content-Type': 'image/jpg',
            'Fingerprint': config['fingerprint'],
            'Token': config['token'],
        },
        data=MMapStreamer(mm, buf.bytesused)
    )
    mm.seek(0)
    response.raise_for_status()
    verbose_print("Updated frame for '{}'".format(config['name']))


stop = threading.Event()
def capture_thread(vd, buf, mm, config, rate = 30):
    try:
        while not stop.wait(timeout=rate):
            try:
                capture(vd, buf, mm, config)
            except Exception as err:
                print("Error updating frame for '{}': {}".format(
                            config['name'],
                            err
                        ),
                        file=sys.stderr)
    finally:
        vd.close()


def _signal_handler(sig, frame):
    verbose_print('Exiting...')
    stop.set()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
            description='Send webcam snapshots to Prusa Connect')
    parser.add_argument('-v', '--verbose',
            action='store_true',
            help='Output diagnostic info')
    parser.add_argument('-o', '--oneshot',
            action='store_true',
            help='Only send one shapshot per camera, then exit')
    parser.add_argument('config',
            nargs='?',
            help='Config file to use (default config.toml in directory of ' \
                 'script)')

    args = parser.parse_args()

    verbose = args.verbose
    config = load_config(args.config)
    rate = config['refresh_rate']
    threads = []
    for cam_config in config['camera']:
        if not 'name' in cam_config:
            raise ValueError("Camera config missing name!")
        if not 'token' in cam_config:
            raise ValueError("Camera '{}' missing token!".format(
                    cam_config['name']))
        if not 'fingerprint' in cam_config:
            b64 = base64.b64encode(bytes(cam_config['name'], 'utf8'))
            fprint = b64.decode('ascii').ljust(16, '.')
            cam_config['fingerprint'] = fprint[0:64]
        if not 'url' in cam_config:
            cam_config['url'] = DEFAULT_URL
        try:
            vd = None
            if 'dev' in cam_config:
                dev = cam_config['dev']
            else:
                dev = get_device(cam_config['name'])
                if dev is None:
                    raise
            vd = open(dev, 'rb+', buffering=0)
            buf, mm = init(vd, cam_config)
            capture(vd, buf, mm, cam_config)
            if args.oneshot:
                vd.close()
            else:
                threads.append(threading.Thread(
                            target=capture_thread,
                            args=(vd, buf, mm, cam_config, rate)))
        except Exception as e:
            raise RuntimeError("Failed to initialize '{}'".format(
                    cam_config['name']))

    if not args.oneshot:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        for t in threads:
            t.start()

        for t in threads:
            t.join()
