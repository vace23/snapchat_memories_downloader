#!/usr/bin/env python3
"""
Script to extract and download all Snapchat Memories from the HTML file
"""

import re
import os
import sys
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from datetime import datetime
import time
import zipfile
import io
from PIL import Image
import argparse
import subprocess
import shutil
import tempfile
import concurrent.futures
import threading


def check_ffmpeg_available():
    """
    Check whether ffmpeg is available on the system
    
    Returns:
        True if ffmpeg is available, False otherwise
    """
    return shutil.which('ffmpeg') is not None


def check_ffprobe_available():
    """
    Check whether ffprobe is available on the system

    Returns:
        True if ffprobe is available, False otherwise
    """
    return shutil.which('ffprobe') is not None


def get_video_dimensions(video_path):
    """
    Get video dimensions (width, height) using ffprobe

    Returns:
        Tuple (width, height) or None if unavailable
    """
    if not check_ffprobe_available():
        return None
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0:s=x',
            video_path
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        if not output or 'x' not in output:
            return None
        width_str, height_str = output.split('x', 1)
        width = int(width_str)
        height = int(height_str)
        return width, height
    except Exception:
        return None


def apply_overlay_to_video(video_path, overlay_path, output_path):
    """
    Apply an overlay to a video using ffmpeg
    
    Args:
        video_path: Path to the base video
        overlay_path: Path to the overlay image (PNG with transparency)
        output_path: Output path for the final video
        
    Returns:
        True on success, False otherwise
    """
    temp_overlay = None
    overlay_to_use = overlay_path
    try:
        if not check_ffmpeg_available():
            return False

        # Convert the overlay to PNG if needed for ffmpeg.
        try:
            img = Image.open(overlay_path)
            img.load()
            if img.format != 'PNG':
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                temp_overlay = temp_file.name
                temp_file.close()
                img = img.convert('RGBA')
                img.save(temp_overlay, 'PNG')
                overlay_to_use = temp_overlay
        except Exception:
            overlay_to_use = overlay_path

        # Build the filter by aligning the overlay to the video size.
        video_dims = get_video_dimensions(video_path)
        if video_dims:
            even_width = video_dims[0] - (video_dims[0] % 2)
            even_height = video_dims[1] - (video_dims[1] % 2)
            filter_complex = (
                f"[0:v]scale={even_width}:{even_height},setsar=1[base];"
                f"[1:v]scale={even_width}:{even_height},format=rgba[ovr];"
                "[base][ovr]overlay=0:0:format=auto[v]"
            )
        else:
            filter_complex = (
                "[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1[base];"
                "[1:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,format=rgba[ovr];"
                "[base][ovr]overlay=0:0:format=auto[v]"
            )

        # Robust ffmpeg command: loop the overlay image and align sizes.
        cmd = [
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'error',
            '-i', video_path,
            '-loop', '1', '-i', overlay_to_use,
            '-filter_complex',
            filter_complex,
            '-map', '[v]',
            '-map', '0:a?',
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-preset', 'medium',
            '-crf', '23',
            '-c:a', 'copy',
            '-shortest',
            '-movflags', '+faststart',
            '-y',
            output_path
        ]

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300
            )
        except subprocess.TimeoutExpired:
            print("   ⚠️  ffmpeg timed out (300s)")
            return False

        if result.returncode != 0:
            if result.stderr:
                err = result.stderr.strip()
                if err:
                    print("   ⚠️  ffmpeg error:")
                    print(err)
            return False

        # Verify the output file exists and is not empty.
        if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
            return True
        return False
    except Exception:
        return False
    finally:
        # Clean up the temporary file.
        if temp_overlay and os.path.exists(temp_overlay):
            try:
                os.remove(temp_overlay)
            except Exception:
                pass


def extract_download_links(html_file):
    """
    Extract all download links from the HTML file
    
    Args:
        html_file: Path to the HTML file
        
    Returns:
        List of dictionaries containing info for each file
    """
    print(f"📖 Reading file: {html_file}")
    
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Pattern to extract URLs from downloadMemories() calls.
    pattern = r"downloadMemories\('(https://[^']+)'"
    
    matches = re.findall(pattern, content)
    
    print(f"✅ {len(matches)} download links found\n")
    
    # Also extract metadata (date, media type).
    soup = BeautifulSoup(content, 'html.parser')
    
    memories = []
    rows = soup.find_all('tr')
    
    for row in rows:
        cells = row.find_all('td')
        if len(cells) >= 4:
            # Extract date, media type, and link.
            date_str = cells[0].get_text(strip=True)
            media_type = cells[1].get_text(strip=True)
            location = cells[2].get_text(strip=True)
            
            # Look for the link in the last cell.
            link_cell = cells[3]
            onclick = link_cell.find('a', {'onclick': True})
            if onclick:
                onclick_text = onclick.get('onclick', '')
                url_match = re.search(r"downloadMemories\('(https://[^']+)'", onclick_text)
                if url_match:
                    url = url_match.group(1)
                    memories.append({
                        'date': date_str,
                        'type': media_type,
                        'location': location,
                        'url': url
                    })
    
    return memories


def apply_overlay_to_image(base_image_path, overlay_image_path, output_path):
    """
    Apply the overlay (with caption) on the base image
    
    Args:
        base_image_path: Path to the base image
        overlay_image_path: Path to the overlay
        output_path: Output path for the merged image
        
    Returns:
        True on success, False otherwise
    """
    try:
        print(f"\n      🔧 Opening base: {os.path.basename(base_image_path)}")
        print(f"      🔧 Opening overlay: {os.path.basename(overlay_image_path)}")
        
        # Open both images.
        base = Image.open(base_image_path)
        overlay = Image.open(overlay_image_path)
        
        print(f"      📐 Base size: {base.size}, mode: {base.mode}")
        print(f"      📐 Overlay size: {overlay.size}, mode: {overlay.mode}")
        
        # Convert to RGBA for compositing.
        base = base.convert('RGBA')
        overlay = overlay.convert('RGBA')
        
        # Ensure the overlay has the same size as the base.
        if overlay.size != base.size:
            print(f"      🔄 Resizing overlay from {overlay.size} to {base.size}")
            overlay = overlay.resize(base.size, Image.Resampling.LANCZOS)
        
        # Composite the overlay onto the base.
        print(f"      🎨 Compositing images...")
        combined = Image.alpha_composite(base, overlay)
        
        # Save (convert to RGB if needed for JPEG).
        if output_path.lower().endswith(('.jpg', '.jpeg')):
            print(f"      💾 Converting to RGB for JPEG")
            combined = combined.convert('RGB')
        
        print(f"      💾 Saving to: {os.path.basename(output_path)}")
        combined.save(output_path, quality=95)
        print(f"      ✅ Success!")
        return True
    except Exception as e:
        print(f"\n⚠️  Error applying overlay: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def process_extracted_files(extract_folder, processed_folder, memory):
    """
    Process extracted files: apply the overlay and save the result
    
    Args:
        extract_folder: Folder containing the ZIP-extracted files
        processed_folder: Destination folder for the processed file
        memory: Memory metadata
        
    Returns:
        True on success, False otherwise
    """
    try:
        # List all files in the extracted folder.
        files = os.listdir(extract_folder)
        
        # Separate media and overlay files.
        media_file = None
        overlay_file = None
        
        # Look for files with -main and -overlay in their names.
        overlay_candidates = []
        overlay_exts = ('.png', '.webp', '.jpg', '.jpeg')
        for file in files:
            file_lower = file.lower()
            if '-overlay' in file_lower and file_lower.endswith(overlay_exts):
                overlay_candidates.append(file)
            elif '-main' in file_lower:
                media_file = os.path.join(extract_folder, file)

        if overlay_candidates:
            def overlay_priority(name):
                ext = os.path.splitext(name.lower())[1]
                if ext == '.png':
                    return 0
                if ext == '.webp':
                    return 1
                if ext in ('.jpg', '.jpeg'):
                    return 2
                return 99
            overlay_candidates.sort(key=overlay_priority)
            overlay_file = os.path.join(extract_folder, overlay_candidates[0])
        
        print(f"\n   📁 Files found: {files}")
        print(f"   🎬 Media: {os.path.basename(media_file) if media_file else 'Not found'}")
        print(f"   🎨 Overlay: {os.path.basename(overlay_file) if overlay_file else 'Not found'}")
        
        if not media_file:
            # No media file found.
            print(f"   ⚠️  No media file found!")
            return False
        
        # Determine the output filename from the media name.
        media_basename = os.path.basename(media_file)
        media_stem, media_ext = os.path.splitext(media_basename)
        if media_stem.endswith('-main'):
            base_id = media_stem[:-5]
        else:
            base_id = media_stem
        output_file = os.path.join(processed_folder, f"{base_id}-processed{media_ext}")
        
        # For videos, overlay is not straightforward.
        if media_file.lower().endswith(('.mp4', '.mov')):
            
            # Try applying the overlay with ffmpeg.
            if overlay_file and check_ffmpeg_available():
                print(f"   ✨ Applying overlay with ffmpeg...")
                success = apply_overlay_to_video(media_file, overlay_file, output_file)
                
                if success:
                    print(f"   ✅ Overlay applied successfully!")
                else:
                    print(f"   ⚠️  ffmpeg failed, copying without overlay")
                    # Copy without overlay.
                    with open(media_file, 'rb') as src:
                        with open(output_file, 'wb') as dst:
                            dst.write(src.read())
            else:
                # No ffmpeg or no overlay.
                if not check_ffmpeg_available() and overlay_file:
                    print(f"   ⚠️  ffmpeg not available, copying without overlay")
                
                with open(media_file, 'rb') as src:
                    with open(output_file, 'wb') as dst:
                        dst.write(src.read())
        
        # For images, apply the overlay.
        elif media_file.lower().endswith(('.jpg', '.jpeg', '.png')):
            
            if overlay_file:
                # Apply the overlay on the image.
                print(f"   ✨ Applying overlay...", end=' ')
                success = apply_overlay_to_image(media_file, overlay_file, output_file)
                if success:
                    print("✅")
                else:
                    print("❌")
                    # On failure, copy the original image.
                    with open(media_file, 'rb') as src:
                        with open(output_file, 'wb') as dst:
                            dst.write(src.read())
            else:
                # No overlay, copy the image as-is.
                with open(media_file, 'rb') as src:
                    with open(output_file, 'wb') as dst:
                        dst.write(src.read())
        
        # Set the timestamp only for the output file.
        if os.path.exists(output_file):
            apply_timestamp(output_file, memory)
        
        return True
    except Exception as e:
        print(f"\n⚠️  Error during processing: {str(e)}")
        return False


def generate_filename(memory, index):
    """
    Generate a unique filename based on metadata
    
    Args:
        memory: Dictionary with memory info
        index: File index
        
    Returns:
        Generated filename
    """
    # Extract and normalize the date.
    date_str = memory['date']
    try:
        # Format: "2025-12-22 23:03:10 UTC"
        date_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S UTC")
        date_formatted = date_obj.strftime("%Y%m%d_%H%M%S")
    except:
        date_formatted = f"memory_{index:04d}"
    
    # Determine the extension based on the media type.
    media_type = memory['type'].lower()
    if 'video' in media_type:
        extension = 'mp4'
    elif 'image' in media_type:
        extension = 'jpg'
    else:
        extension = 'dat'
    
    filename = f"{date_formatted}_{media_type}.{extension}"
    
    return filename


def apply_timestamp(file_path, memory):
    """
    Apply the memory timestamp to the given file
    """
    if not memory or not memory.get('date'):
        return
    try:
        date_obj = datetime.strptime(memory['date'], "%Y-%m-%d %H:%M:%S UTC")
        timestamp = date_obj.timestamp()
        os.utime(file_path, (timestamp, timestamp))
    except Exception:
        pass


def select_test_memories(memories, video_limit=2, image_limit=2):
    """
    Select a subset of memories for test mode

    Args:
        memories: List of memories
        video_limit: Max number of videos
        image_limit: Max number of images

    Returns:
        Filtered list of memories
    """
    selected = []
    video_count = 0
    image_count = 0

    for memory in memories:
        media_type = memory.get('type', '').lower()
        if 'video' in media_type and video_count < video_limit:
            selected.append(memory)
            video_count += 1
        elif 'image' in media_type and image_count < image_limit:
            selected.append(memory)
            image_count += 1

        if video_count >= video_limit and image_count >= image_limit:
            break

    return selected


def download_file(
    url,
    destination,
    processed_destination,
    filename,
    index,
    total,
    memory=None,
    max_retries=3,
    blocked_event=None,
    blocked_info=None
):
    """
    Download a file from a URL, extract the ZIP, and apply the overlay
    
    Args:
        url: File URL
        destination: Destination folder for temporary extracts
        processed_destination: Folder for processed files
        filename: Filename (used as folder name)
        index: Current file index
        total: Total number of files
        memory: Dictionary with memory metadata (optional)
        
    Returns:
        True on success, False otherwise
    """
    # Create a temp folder for this memory (without extension).
    folder_name = os.path.splitext(filename)[0]
    folder_path = os.path.join(destination, folder_name)
    
    # Check if already processed.
    date_str = memory.get('date', '') if memory else ''
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S UTC")
        date_formatted = date_obj.strftime("%Y%m%d_%H%M%S")
    except:
        date_formatted = f"memory_{index:04d}"
    
    # Check if files with this timestamp already exist.
    if os.path.exists(processed_destination):
        existing_files = [f for f in os.listdir(processed_destination) if f.startswith(date_formatted)]
        if existing_files:
            print(f"⏭️  [{index}/{total}] Already processed: {date_formatted}")
            return True
    
    if blocked_event and blocked_event.is_set():
        print(f"⏭️  [{index}/{total}] Block detected, skipping: {folder_name}")
        return False

    print(f"⬇️  [{index}/{total}] Downloading: {folder_name}...", end=' ', flush=True)

    attempt = 0
    while True:
        if blocked_event and blocked_event.is_set():
            print(f"⏭️  [{index}/{total}] Block detected, skipping: {folder_name}")
            return False

        try:
            # Download with a timeout.
            response = requests.get(url, timeout=30, stream=True)
            status = response.status_code
            if status in (403, 429):
                response.close()
                if blocked_event:
                    blocked_event.set()
                if blocked_info is not None and 'status' not in blocked_info:
                    blocked_info['status'] = status
                print(f"🚫 Blocked (HTTP {status})")
                return False
            if status >= 500:
                response.close()
                raise requests.exceptions.RequestException(f"HTTP {status}")
            if status >= 400:
                response.close()
                print(f"❌ HTTP error {status}")
                return False

            # Read the content.
            content = b''
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    content += chunk

            file_size = len(content) / (1024 * 1024)  # In MB

            # Check if it's a ZIP file.
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zip_file:
                    # It's a ZIP, extract to a temp folder.
                    os.makedirs(folder_path, exist_ok=True)
                    zip_file.extractall(folder_path)

                    print(f"✅ ({file_size:.2f} MB)", end=' ')

                    # Create the destination folder if it doesn't exist.
                    os.makedirs(processed_destination, exist_ok=True)
                    
                    # Process extracted files (apply overlay).
                    success = process_extracted_files(folder_path, processed_destination, memory)
                    
                    if success:
                        print("→ 🎨 Processed")
                    else:
                        print("→ ⚠️  Copied without overlay")

                    # Keep the temp folder with raw files.

            except zipfile.BadZipFile:
                # Not a ZIP, save as a single file in processed.
                os.makedirs(processed_destination, exist_ok=True)
                filepath = os.path.join(processed_destination, filename)

                with open(filepath, 'wb') as f:
                    f.write(content)

                # Set the timestamp.
                apply_timestamp(filepath, memory)

                print(f"✅ ({file_size:.2f} MB)")

            return True

        except requests.exceptions.RequestException as e:
            attempt += 1
            if attempt >= max_retries:
                print(f"❌ Error: {str(e)}")
                return False
            wait_seconds = min(2 ** (attempt - 1), 8)
            print(f"⚠️  Network error, retrying in {wait_seconds}s")
            time.sleep(wait_seconds)
        except Exception as e:
            print(f"❌ Unexpected error: {str(e)}")
            return False


def main():
    """Main function"""
    start_time_total = time.time()
    
    # Parse arguments.
    parser = argparse.ArgumentParser(
        description='Snapchat Memories downloader',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s                                    # Uses default values
  %(prog)s --html my_file.html                # Specify the HTML file
  %(prog)s --test                             # Test mode (5 files)
  %(prog)s --html file.html --test            # Combine options
        ''')
    
    parser.add_argument(
        '--html',
        default='./html/memories_history.html',
        help='Path to the Snapchat HTML file (default: ./html/memories_history.html)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test mode: limit to 4 files (2 images and 2 videos)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit the number of files to download (overrides --test)'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=1,
        help='Number of parallel downloads (default: 1)'
    )
    parser.add_argument(
        '--retries',
        type=int,
        default=3,
        help="Number of retry attempts on failure (default: 3)"
    )
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("📸 SNAPCHAT MEMORIES DOWNLOADER")
    print("=" * 70)
    print()

    # Check ffmpeg/ffprobe availability before running.
    if not check_ffmpeg_available() or not check_ffprobe_available():
        print("❌ Error: ffmpeg and ffprobe are required to run this script.")
        print("   Install ffmpeg and try again.")
        sys.exit(1)
    
    # Check that the HTML file exists.
    html_file = args.html
    if not os.path.exists(html_file):
        print(f"❌ Error: The file '{html_file}' does not exist!")
        sys.exit(1)
    
    # Extract links.
    memories = extract_download_links(html_file)
    
    if not memories:
        print("❌ No download links found in the HTML file!")
        sys.exit(1)
    
    # Print a summary.
    video_count = sum(1 for m in memories if 'video' in m['type'].lower())
    image_count = sum(1 for m in memories if 'image' in m['type'].lower())
    
    print(f"📊 Summary:")
    print(f"   • Videos: {video_count}")
    print(f"   • Images: {image_count}")
    print(f"   • Total: {len(memories)}")
    print()
    
    # Apply the limit if specified.
    if args.limit:
        memories = memories[:args.limit]
        print(f"✅ Limit applied: {len(memories)} files")
        print()
    elif args.test:
        memories = select_test_memories(memories, video_limit=2, image_limit=2)
        selected_videos = sum(1 for m in memories if 'video' in m.get('type', '').lower())
        selected_images = sum(1 for m in memories if 'image' in m.get('type', '').lower())
        print(f"✅ Test mode enabled: {len(memories)} files")
        print(f"   • Videos: {selected_videos}")
        print(f"   • Images: {selected_images}")
        print()
    
    # Destination folders.
    temp_dest = "snapchat_memories_raw"
    processed_dest = "snapchat_memories_processed"
    
    # Create folders if they don't exist.
    Path(temp_dest).mkdir(parents=True, exist_ok=True)
    Path(processed_dest).mkdir(parents=True, exist_ok=True)
    print(f"✅ Directories created/checked:")
    print(f"   • Raw: {temp_dest}")
    print(f"   • Processed: {processed_dest}")
    print()
    
    print()
    print("=" * 70)
    print("⬇️  STARTING DOWNLOAD")
    print("=" * 70)
    print()

    if args.workers < 1:
        print("❌ Error: --workers must be >= 1")
        sys.exit(1)
    if args.retries < 1:
        print("❌ Error: --retries must be >= 1")
        sys.exit(1)

    if args.workers > 1:
        print(f"⚙️  Parallel downloads: {args.workers} workers")
        print()
    
    # Download all files.
    start_time = time.time()
    results = {}

    if args.workers == 1:
        for index, memory in enumerate(memories, 1):
            filename = generate_filename(memory, index)

            ok = download_file(
                memory['url'],
                temp_dest,
                processed_dest,
                filename,
                index,
                len(memories),
                memory,
                max_retries=args.retries
            )
            results[index] = ok

            # Short pause between downloads to avoid overloading the server.
            if index < len(memories):
                time.sleep(0.5)
    else:
        blocked_event = threading.Event()
        blocked_info = {}
        total = len(memories)

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_index = {}
            for index, memory in enumerate(memories, 1):
                filename = generate_filename(memory, index)
                future = executor.submit(
                    download_file,
                    memory['url'],
                    temp_dest,
                    processed_dest,
                    filename,
                    index,
                    total,
                    memory,
                    max_retries=args.retries,
                    blocked_event=blocked_event,
                    blocked_info=blocked_info
                )
                future_to_index[future] = index
                # Slight stagger to avoid an aggressive burst.
                if index < total:
                    time.sleep(0.1)

            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    ok = future.result()
                except Exception as e:
                    print(f"❌ Unexpected error: {str(e)}")
                    ok = False
                results[index] = ok

        if blocked_event.is_set():
            status = blocked_info.get('status')
            if status:
                print(f"\n🚫 Block detected (HTTP {status}). Falling back to sequential mode.")
            else:
                print("\n🚫 Block detected. Falling back to sequential mode.")

            for index, memory in enumerate(memories, 1):
                if results.get(index):
                    continue
                filename = generate_filename(memory, index)
                ok = download_file(
                    memory['url'],
                    temp_dest,
                    processed_dest,
                    filename,
                    index,
                    len(memories),
                    memory,
                    max_retries=args.retries
                )
                results[index] = ok
                if index < len(memories):
                    time.sleep(0.5)
    
    # Final summary.
    elapsed_time = time.time() - start_time
    total_elapsed_time = time.time() - start_time_total
    for index in range(1, len(memories) + 1):
        results.setdefault(index, False)

    success_count = sum(1 for ok in results.values() if ok)
    failed_count = len(memories) - success_count

    print()
    print("=" * 70)
    print("✅ DOWNLOAD COMPLETE")
    print("=" * 70)
    print(f"✅ Successful: {success_count}/{len(memories)}")
    if failed_count > 0:
        print(f"❌ Failed: {failed_count}/{len(memories)}")
    print(f"⏱️  Download time: {elapsed_time:.1f} seconds")
    print(f"⏱️  Total time: {total_elapsed_time:.1f} seconds")
    print(f"📁 Processed files in: {os.path.abspath(processed_dest)}")
    print(f"📁 Raw files in: {os.path.abspath(temp_dest)}")
    print()
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Download interrupted by the user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {str(e)}")
        sys.exit(1)
