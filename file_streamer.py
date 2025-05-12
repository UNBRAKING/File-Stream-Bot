#!/usr/bin/env python3
# Telegram File Streamer with Channel Storage Support

import os
import asyncio
from pyrogram import Client
from pyrogram.types import Message
from aiohttp import web
import logging
import mimetypes
import re
from datetime import datetime
from io import BytesIO

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
API_ID = "26614080"  # Get from api.telegram.org
API_HASH = "7d2c9a5628814e1430b30a1f0dc0165b"  # Get from api.telegram.org
BOT_TOKEN = "7652972740:AAEyD1ogQW4wYSrW6KKa_x8IX2ze7UYvCCQ"  # Your bot token
STORAGE_CHANNEL_ID = -1001234567890  # Your private channel ID (make bot admin)
HOST = "0.0.0.0"  # Vercel will handle the domain
PORT = int(os.environ.get("PORT", 8080))  # Vercel provides PORT environment variable

# Telegram client
app = Client("file_streamer", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# File cache - stores file metadata and channel message IDs
file_cache = {}

# Web server routes
routes = web.RouteTableDef()

@routes.get('/')
async def index(request):
    return web.Response(text="Telegram File Streamer is running!")

@routes.get('/api/stream/{file_id}')
async def stream_media(request):
    """Stream media files directly from Telegram channel with support for seeking"""
    file_id = request.match_info['file_id']
    
    if file_id not in file_cache:
        return web.Response(text="File not found", status=404)
    
    file_meta = file_cache[file_id]
    file_name = file_meta['name']
    channel_message_id = file_meta['channel_msg_id']
    file_size = file_meta['size']
    
    # Get file mime type
    mime_type, _ = mimetypes.guess_type(file_name)
    if not mime_type:
        mime_type = 'application/octet-stream'
    
    # Handle range requests for streaming
    range_header = request.headers.get('Range', '')
    
    # Default values
    start = 0
    end = file_size - 1
    
    # Parse range header if present
    if range_header:
        match = re.search(r'bytes=(\d+)-(\d*)', range_header)
        if match:
            start = int(match.group(1))
            end_group = match.group(2)
            if end_group:
                end = min(int(end_group), file_size - 1)
    
    # Calculate content length
    content_length = end - start + 1
    
    # Create response headers
    headers = {
        'Content-Type': mime_type,
        'Accept-Ranges': 'bytes',
        'Content-Range': f'bytes {start}-{end}/{file_size}',
        'Content-Length': str(content_length),
        'Content-Disposition': f'inline; filename="{file_name}"',
        'Last-Modified': datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT'),
    }
    
    # Return 206 Partial Content for range requests
    status = 206 if range_header else 200
    
    # Create response
    response = web.StreamResponse(status=status, headers=headers)
    await response.prepare(request)
    
    # Stream the file directly from Telegram channel
    try:
        # Download the file in chunks
        chunk_size = 8192  # 8KB chunks
        offset = start
        remaining = content_length
        
        while remaining > 0:
            # Calculate current chunk size
            current_chunk = min(chunk_size, remaining)
            
            # Download chunk from Telegram channel
            downloaded = await app.download_media(
                channel_message_id,
                in_memory=True,
                file_name=file_name,
                progress=None,
                block=False
            )
            
            if isinstance(downloaded, BytesIO):
                downloaded.seek(offset)
                chunk = downloaded.read(current_chunk)
                if not chunk:
                    break
                await response.write(chunk)
                offset += len(chunk)
                remaining -= len(chunk)
            else:
                break
    
    except Exception as e:
        logger.error(f"Error streaming file: {e}")
        return web.Response(text="Error streaming file", status=500)
    
    await response.write_eof()
    return response

@routes.get('/api/download/{file_id}')
async def download_file(request):
    """Download the complete file from Telegram channel"""
    file_id = request.match_info['file_id']
    
    if file_id not in file_cache:
        return web.Response(text="File not found", status=404)
    
    file_meta = file_cache[file_id]
    file_name = file_meta['name']
    channel_message_id = file_meta['channel_msg_id']
    
    # Get file mime type
    mime_type, _ = mimetypes.guess_type(file_name)
    if not mime_type:
        mime_type = 'application/octet-stream'
    
    headers = {
        'Content-Disposition': f'attachment; filename="{file_name}"',
        'Content-Type': mime_type
    }
    
    # Create a streaming response
    response = web.StreamResponse(headers=headers)
    await response.prepare(request)
    
    # Download and stream the file directly from Telegram channel
    try:
        downloaded = await app.download_media(
            channel_message_id,
            in_memory=True,
            file_name=file_name,
            progress=None,
            block=False
        )
        
        if isinstance(downloaded, BytesIO):
            downloaded.seek(0)
            while True:
                chunk = downloaded.read(8192)
                if not chunk:
                    break
                await response.write(chunk)
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        return web.Response(text="Error downloading file", status=500)
    
    await response.write_eof()
    return response

@routes.get('/api/view/{file_id}')
async def view_media(request):
    """Generate HTML page with embedded media player"""
    file_id = request.match_info['file_id']
    
    if file_id not in file_cache:
        return web.Response(text="File not found", status=404)
    
    file_meta = file_cache[file_id]
    file_name = file_meta['name']
    mime_type, _ = mimetypes.guess_type(file_name)
    is_video = mime_type and mime_type.startswith('video/')
    is_audio = mime_type and mime_type.startswith('audio/')
    
    # Generate streaming URL
    stream_url = f"/api/stream/{file_id}"
    download_url = f"/api/download/{file_id}"
    
    # Create HTML with appropriate player based on file type
    if is_video:
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Stream: {file_name}</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ margin: 0; padding: 20px; font-family: Arial, sans-serif; }}
                .container {{ max-width: 800px; margin: 0 auto; }}
                h1 {{ font-size: 24px; }}
                video {{ width: 100%; max-width: 800px; }}
                .info {{ margin: 15px 0; }}
                .download-btn {{ display: inline-block; background: #4CAF50; color: white; padding: 10px 15px; 
                              text-decoration: none; border-radius: 4px; margin-top: 10px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>{file_name}</h1>
                <video controls autoplay>
                    <source src="{stream_url}" type="{mime_type}">
                    Your browser does not support the video element.
                </video>
                <div class="info">
                    <p>Streaming: <strong>{file_name}</strong></p>
                    <a href="{download_url}" class="download-btn">Download File</a>
                </div>
            </div>
        </body>
        </html>
        """
    elif is_audio:
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Stream: {file_name}</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ margin: 0; padding: 20px; font-family: Arial, sans-serif; }}
                .container {{ max-width: 800px; margin: 0 auto; }}
                h1 {{ font-size: 24px; }}
                audio {{ width: 100%; max-width: 800px; }}
                .info {{ margin: 15px 0; }}
                .download-btn {{ display: inline-block; background: #4CAF50; color: white; padding: 10px 15px; 
                              text-decoration: none; border-radius: 4px; margin-top: 10px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>{file_name}</h1>
                <audio controls autoplay>
                    <source src="{stream_url}" type="{mime_type}">
                    Your browser does not support the audio element.
                </audio>
                <div class="info">
                    <p>Streaming: <strong>{file_name}</strong></p>
                    <a href="{download_url}" class="download-btn">Download File</a>
                </div>
            </div>
        </body>
        </html>
        """
    else:
        # For other file types, provide a direct download link
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>File: {file_name}</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ margin: 0; padding: 20px; font-family: Arial, sans-serif; }}
                .container {{ max-width: 800px; margin: 0 auto; }}
                h1 {{ font-size: 24px; }}
                .info {{ margin: 15px 0; }}
                .download-btn {{ display: inline-block; background: #4CAF50; color: white; padding: 10px 15px; 
                              text-decoration: none; border-radius: 4px; margin-top: 10px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>{file_name}</h1>
                <div class="info">
                    <p>This file type cannot be streamed directly in the browser.</p>
                    <a href="{download_url}" class="download-btn">Download File</a>
                    <p>Or try to <a href="{stream_url}">stream anyway</a>.</p>
                </div>
            </div>
        </body>
        </html>
        """
    
    return web.Response(text=html, content_type='text/html')

async def handle_message(client, message: Message):
    if not message.document and not message.video and not message.audio and not message.photo:
        await message.reply("Please send a file!")
        return
    
    try:
        # Send a message that we're processing the file
        status_message = await message.reply("Processing your file...")
        
        # Get file information
        if message.document:
            file_obj = message.document
            file_type = "document"
        elif message.video:
            file_obj = message.video
            file_type = "video"
        elif message.audio:
            file_obj = message.audio
            file_type = "audio"
        elif message.photo:
            file_obj = message.photo[-1]  # Get the largest photo
            file_type = "photo"
        
        file_id = file_obj.file_id
        file_name = getattr(file_obj, 'file_name', f"{file_type}_{file_id}.{file_type}")
        file_size = file_obj.file_size
        
        # Create a safe filename for display
        safe_filename = "".join([c if c.isalnum() or c in "._- " else "_" for c in file_name]).strip()
        
        # Forward the file to storage channel
        forwarded_msg = await app.forward_messages(
            chat_id=STORAGE_CHANNEL_ID,
            from_chat_id=message.chat.id,
            message_ids=message.id
        )
        
        # Store file metadata in cache
        file_cache[file_id] = {
            'name': safe_filename,
            'size': file_size,
            'channel_msg_id': forwarded_msg.id
        }
        
        # Create URLs with Vercel's domain
        domain = os.environ.get('VERCEL_URL', 'your-app-name.vercel.app')
        view_url = f"https://{domain}/api/view/{file_id}"
        download_url = f"https://{domain}/api/download/{file_id}"
        
        await status_message.edit_text(
            f"File is ready!\n\n"
            f"📁 Name: {safe_filename}\n"
            f"💾 Size: {file_size/1024/1024:.2f} MB\n\n"
            f"🎬 View URL: {view_url}\n"
            f"📥 Direct Download: {download_url}"
        )
        
    except Exception as e:
        logger.error(f"Error processing file: {e}")
        await status_message.edit_text(f"Error: {e}")

async def start_bot():
    await app.start()
    logger.info("Telegram client started")
    
    # Set message handler
    app.add_handler(app.on_message()(handle_message))
    
    # Run infinite loop to keep bot running
    await asyncio.Event().wait()

async def start_web_server():
    web_app = web.Application()
    web_app.add_routes(routes)
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    
    logger.info(f"Web server started on port {PORT}")

async def main():
    await asyncio.gather(
        start_bot(),
        start_web_server()
    )

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        loop.close()