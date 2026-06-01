#!/bin/bash
Xvfb :1 -screen 0 1280x800x24 &
XVFB_PID=$!
sleep 1
DISPLAY=:1 python main.py
kill $XVFB_PID 2>/dev/null
