#!/bin/bash

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

# Check if the directory exists
if [ ! -d "$main_dir" ]; then
    echo "Error: Directory '$main_dir' does not exist."
    exit 1
fi

# Create a log file
log_file="conversion_log.txt"
echo "Starting conversion process at $(date)" > "$log_file"

# Counter for processed files
converted=0
failed=0
skipped_dirs=0

# Function to calculate frame ranges and analyze timestamps for a chunk
analyze_chunk_timestamps() {
    local ts_file="$1"
    local start_frame="$2"
    local frame_count="$3"
    local chunk_id="$4"
    local analysis_file="$5"
    
    echo "Analyzing timestamps for chunk $chunk_id (frames $start_frame to $((start_frame + frame_count - 1)))"
    
    awk -F, -v start="$start_frame" -v count="$frame_count" -v chunk="$chunk_id" '
    BEGIN {
        expected_frame = start
        end_frame = start + count - 1
        found_frames = 0
        missing_frames = 0
        total_time = 0
        first_ts = -1
        last_ts = -1
        gap_threshold = 1.0/15.0  # Allow up to 1/15 sec between frames
    }
    
    NR > 1 && $1 >= start && $1 <= end_frame {
        frame_num = $1
        ts = $2
        
        # Track first and last timestamp
        if (first_ts == -1) {
            first_ts = ts
            prev_ts = ts
            prev_frame = frame_num
        }
        
        # Check for frame gaps
        if (frame_num != expected_frame) {
            printf "Missing frames %d to %d\n", expected_frame, frame_num - 1
            missing_frames += frame_num - expected_frame
        }
        
        # Check for timestamp gaps
        gap = ts - prev_ts
        if (gap > gap_threshold) {
            printf "Timing gap of %.3f seconds between frames %d and %d\n", \
                gap, prev_frame, frame_num
        }
        
        found_frames++
        last_ts = ts
        prev_ts = ts
        prev_frame = frame_num
        expected_frame = frame_num + 1
    }
    
    END {
        duration = last_ts - first_ts
        actual_fps = (found_frames - 1) / duration
        
        printf "\nChunk %d Analysis:\n", chunk
        printf "Expected frames: %d\n", count
        printf "Found frames: %d\n", found_frames
        printf "Missing frames: %d\n", missing_frames
        printf "Duration: %.3f seconds\n", duration
        printf "Actual frame rate: %.2f fps\n", actual_fps
    }
    ' "$ts_file" > "$analysis_file"
    
    # Extract the actual fps for ffmpeg
    actual_fps=$(awk '/Actual frame rate:/ {print $4}' "$analysis_file")
    echo "$actual_fps"
}

# Function to get frame range start for a chunk
get_chunk_start_frame() {
    local chunk_id="$1"
    local yaml_file="$2"
    
    # Calculate starting frame based on previous chunks' frame counts
    local start_frame=0
    for ((i=1; i<chunk_id; i++)); do
        local prev_count=$(yq ".chunks[] | select(.chunk_id == $i) | .frame_count" "$yaml_file")
        start_frame=$((start_frame + prev_count))
    done
    echo "$start_frame"
}

# Process directories
find "$main_dir" -type d | while read -r dir; do
    # Skip the root directory
    if [ "$dir" = "$main_dir" ]; then
        continue
    fi
    
    # Look for metadata YAML and timestamps file
    yaml_file=$(find "$dir" -maxdepth 1 -type f -name "*_metadata.yaml" | head -n 1)
    ts_file=$(find "$dir" -maxdepth 1 -type f -name "*_timestamps.txt" | head -n 1)
    
    if [ -f "$yaml_file" ] && [ -f "$ts_file" ]; then
        echo "Processing directory: $dir"
        
        # Get target framerate from metadata
        target_fps=$(yq '.framerate' "$yaml_file")
        echo "Target framerate: $target_fps fps"
        
        # Process each chunk
        yq -r '.chunks[] | [.chunk_id, .filename, .frame_count] | @tsv' "$yaml_file" | \
        while IFS=$'\t' read -r chunk_id filename frame_count; do
            input_file="$dir/$filename"
            
            if [ -f "$input_file" ]; then
                echo "Processing chunk $chunk_id: $filename"
                output_file="${input_file%.h264}.mp4"
                
                # Get starting frame for this chunk
                start_frame=$(get_chunk_start_frame "$chunk_id" "$yaml_file")
                
                # Analyze timestamps for this chunk
                analysis_file="${input_file%.h264}_analysis.txt"
                actual_fps=$(analyze_chunk_timestamps "$ts_file" "$start_frame" "$frame_count" \
                    "$chunk_id" "$analysis_file")
                
                # Use the detected fps, or fall back to target fps if detection fails
                fps_to_use=${actual_fps:-$target_fps}
                echo "Converting with frame rate: $fps_to_use fps"
                
                # Convert to grayscale MP4
                # Get frame rate from metadata
                metadata_fps=$(yq '.framerate' "$yaml_file")
                
                # High quality conversion with optimizations for file size
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
        echo "Skipping directory: $dir (missing metadata or timestamps)"
        ((skipped_dirs++))
    fi
done

# Print summary
echo -e "\nConversion complete!"
echo "Successfully converted: $converted files"
echo "Failed conversions: $failed files"
echo "Skipped directories: $skipped_dirs"
echo "Check $log_file for detailed conversion log"