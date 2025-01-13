#!/bin/bash

# Enable debug output
set -x

# Check required dependencies
for cmd in ffmpeg yq awk; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "Error: $cmd is not installed. Please install it first."
        exit 1
    fi
done

# Check if a directory argument is provided
if [ $# -ne 1 ]; then
    echo "Usage: $0 <directory>"
    exit 1
fi

# The main directory to process
main_dir="$1"

# Debug: Print directory being processed
echo "Processing directory: $main_dir"

# Check if the directory exists
if [ ! -d "$main_dir" ]; then
    echo "Error: Directory '$main_dir' does not exist."
    exit 1
fi

# Create a log file
log_file="conversion_log.txt"
echo "Starting conversion process at $(date)" > "$log_file"

# Debug: List all files in directory
echo "Files in directory:"
ls -la "$main_dir"

# Counter for processed files
converted=0
failed=0
skipped_dirs=0

# Look for metadata YAML and timestamps file directly in the main directory
yaml_file="$main_dir/$(basename "$main_dir")_metadata.yaml"
ts_file="$main_dir/$(basename "$main_dir")_timestamps.txt"

# Debug: Check for metadata and timestamp files
echo "Looking for metadata file: $yaml_file"
echo "Looking for timestamps file: $ts_file"

if [ ! -f "$yaml_file" ]; then
    echo "Error: Metadata file not found: $yaml_file"
    exit 1
fi

if [ ! -f "$ts_file" ]; then
    echo "Error: Timestamps file not found: $ts_file"
    exit 1
fi

echo "Found metadata and timestamps files. Processing videos..."

# Process files in the main directory
if [ -f "$yaml_file" ] && [ -f "$ts_file" ]; then
    echo "Processing directory: $main_dir"
    
    # Get target framerate from metadata
    metadata_fps=$(yq '.framerate' "$yaml_file")
    echo "Target framerate from metadata: $metadata_fps fps"
    
    # Process each chunk
    yq -r '.chunks[] | [.chunk_id, .filename, .frame_count] | @tsv' "$yaml_file" | \
    while IFS=$'\t' read -r chunk_id filename frame_count; do
        input_file="$main_dir/$filename"
        
        # Debug: Print file being processed
        echo "Looking for input file: $input_file"
        
        if [ -f "$input_file" ]; then
            echo "Processing chunk $chunk_id: $filename"
            output_file="${input_file%.h264}.mp4"
            
            # High quality conversion with optimizations
            if ffmpeg -i "$input_file" \
                -vf "scale=iw/2:ih/2:flags=lanczos,format=gray" \
                -c:v libx264 -preset veryslow -crf 1 \
                -x264-params "rc-lookahead=250:me=umh:subme=11:trellis=2:bframes=16:b-adapt=2:ref=16" \
                -pix_fmt yuv420p \
                -tune grain \
                -r "$metadata_fps" \
                -an -y "$output_file" 2>> "$log_file"; then
                
                echo "Successfully converted: $input_file"
                ((converted++))
            else
                echo "Failed to convert: $input_file"
                ((failed++))
                echo "Failed: $input_file" >> "$log_file"
            fi
        else
            echo "Missing h264 file: $input_file"
            ((failed++))
        fi
    done
else
    echo "Skipping directory: $main_dir (missing metadata or timestamps)"
    ((skipped_dirs++))
fi

# Print summary
echo -e "\nConversion complete!"
echo "Successfully converted: $converted files"
echo "Failed conversions: $failed files"
echo "Skipped directories: $skipped_dirs"
echo "Check $log_file for detailed conversion log"