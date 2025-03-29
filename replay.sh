#!/bin/bash

# Check if both arguments are provided
if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <candump logfile to replay> <interface used in logfile>"
    exit 1
fi

filename="$1"
interface="$2"

# Verify the file exists
if [ ! -f "$filename" ]; then
    echo "Error: File '$filename' does not exist"
    exit 1
fi

ifconfig vcan0 up  

# Replay the file indefinitely on the specified interface
canplayer -I "$filename" -l i vcan0="$interface"

