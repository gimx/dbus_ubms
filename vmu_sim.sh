#!/bin/bash

# Default settings
DEFAULT_INTERFACE="can0"
INTERFACE=${1:-$DEFAULT_INTERFACE}
INITIAL_VALUE=0
INITIAL_INTERVAL=1  # Start with 1 second interval
DRY_RUN=true

# Mode descriptions
declare -A MODE_NAMES
MODE_NAMES[0]="STANDBY"
MODE_NAMES[1]="CHARGE"
MODE_NAMES[2]="DRIVE"

# Temporary files for inter-process communication
TMP_DIR=$(mktemp -d)
VALUE_FILE="$TMP_DIR/value"
INTERVAL_FILE="$TMP_DIR/interval"
DRY_RUN_FILE="$TMP_DIR/dry_run"
ACTIVE_FILE="$TMP_DIR/active"

# Initialize temp files
echo $INITIAL_VALUE > "$VALUE_FILE"
echo $INITIAL_INTERVAL > "$INTERVAL_FILE"
echo $DRY_RUN > "$DRY_RUN_FILE"
echo 1 > "$ACTIVE_FILE"

# Cleanup function
cleanup() {
    echo "Stopping background processes..."
    echo 0 > "$ACTIVE_FILE"
    wait "$SEND_PID" 2>/dev/null
    rm -rf "$TMP_DIR"
    exit 0
}

trap cleanup INT TERM EXIT

# Check dependencies
check_dependencies() {
    if ! command -v cansend &> /dev/null; then
        echo "Error: cansend command not found. Install can-utils package."
        exit 1
    fi
}

# Get mode name from value
get_mode_name() {
    echo "${MODE_NAMES[$1]}"
}

# Background sending loop
send_loop() {
    while [ $(cat "$ACTIVE_FILE") -eq 1 ]; do
        local current_value=$(cat "$VALUE_FILE")
        local current_interval=$(cat "$INTERVAL_FILE")
        local current_dry_run=$(cat "$DRY_RUN_FILE")
        local mode_name=$(get_mode_name "$current_value")
        
        local cmd="cansend $INTERFACE 440#000${current_value}0000"
        local timestamp=$(date +"%T")
        
        if [ "$current_dry_run" = "true" ]; then
            echo "[$timestamp] DRY RUN: $cmd (Mode: $mode_name)"
        else
            # Execute without printing in real mode
            if ! eval "$cmd" >/dev/null 2>&1; then
                echo "[$timestamp] Error: Failed to send message for mode $mode_name" >&2
            fi
        fi
        
        sleep "$current_interval"
    done
}

# User interface functions
show_help() {
    echo "
Available commands:
  0        : Set to STANDBY mode
  1        : Set to CHARGE mode
  2        : Set to DRIVE mode
  t <sec>  : Change send interval (1-19 seconds)
  r        : Toggle real/dry-run mode
  s        : Show current status
  h        : Show this help
  q        : Quit program
"
}

show_status() {
    local current_value=$(cat "$VALUE_FILE")
    local mode_name=$(get_mode_name "$current_value")
    
    echo "
=== Current Status ===
Interface:    $INTERFACE
Mode:         $mode_name (value: $current_value)
Interval:     $(cat "$INTERVAL_FILE") seconds
Execution:    $(cat "$DRY_RUN_FILE" | awk '{print $0 ? "Dry Run" : "Real"}')
Background:   $(ps -p $SEND_PID >/dev/null && echo "Running" || echo "Stopped")
"
}

# Main program execution
main() {
    check_dependencies
    echo "=== CAN Bus Mode Controller ==="
    echo "Starting background sender on $INTERFACE..."
    echo "Initial mode: $(get_mode_name $INITIAL_VALUE)"
    echo "Type 'h' for help, 'q' to quit"
    
    # Start background sender
    send_loop &
    SEND_PID=$!
    
    # Main input loop
    while read -p "> " input; do
        case "$input" in
            0|1|2)
                echo "$input" > "$VALUE_FILE"
                local mode_name=$(get_mode_name "$input")
                echo "Mode changed to: $mode_name (value: $input)"
                ;;
                
            t*)
                new_interval=$(awk '{print $2}' <<< "$input")
                if [[ "$new_interval" =~ ^[0-9]+$ ]] && [ "$new_interval" -ge 1 ] && [ "$new_interval" -le 19 ]; then
                    echo "$new_interval" > "$INTERVAL_FILE"
                    echo "Interval updated to: ${new_interval}s"
                else
                    echo "Invalid interval. Must be between 1 and 19 seconds."
                fi
                ;;
                
            r)
                current_mode=$(cat "$DRY_RUN_FILE")
                new_mode=$([ "$current_mode" = "true" ] && echo "false" || echo "true")
                echo "$new_mode" > "$DRY_RUN_FILE"
                echo "Execution mode changed to: $([ "$new_mode" = "true" ] && echo "Dry Run" || echo "Real")"
                ;;
                
            s)
                show_status
                ;;
                
            h)
                show_help
                ;;
                
            q)
                cleanup
                ;;
                
            *)
                echo "Unknown command. Valid modes are:"
                echo "  0: STANDBY"
                echo "  1: CHARGE"
                echo "  2: DRIVE"
                echo "Type 'h' for help."
                ;;
        esac
    done
}

# Start the program
main

