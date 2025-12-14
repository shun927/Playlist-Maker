import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials
from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
import json
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_COOKIE_NAME'] = 'Spotify Cookie'

# -- Configuration --
SPOTIPY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIPY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')
SPOTIPY_REDIRECT_URI = os.getenv('SPOTIPY_REDIRECT_URI')

# Simple in-memory storage for requests. 
# In a production app, use a database (SQLite/PostgreSQL).
# Format: [{'artist': 'Artist', 'song': 'Song', 'uri': 'spotify:track:xxx', 'image_url': 'http...', 'id': 1}, ...]
SONG_REQUESTS = []
REQUEST_ID_COUNTER = 1

def create_spotify_oauth():
    return SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope="playlist-modify-public playlist-modify-private"
    )

def get_client_credentials_token():
    auth_manager = SpotifyClientCredentials(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET)
    return spotipy.Spotify(auth_manager=auth_manager)

@app.route('/api/search')
def search_tracks():
    query = request.args.get('q')
    if not query:
        return jsonify([])
    
    sp = get_client_credentials_token()
    results = sp.search(q=query, type='track', limit=10, market='JP')
    
    tracks = []
    for item in results['tracks']['items']:
        tracks.append({
            'name': item['name'],
            'artist': item['artists'][0]['name'],
            'uri': item['uri'],
            'image_url': item['album']['images'][-1]['url'] if item['album']['images'] else None
        })
    return jsonify(tracks)

@app.route('/', methods=['GET', 'POST'])
def index():
    global REQUEST_ID_COUNTER
    if request.method == 'POST':
        artist = request.form.get('artist')
        song = request.form.get('song')
        uri = request.form.get('uri')
        image_url = request.form.get('image_url')

        if uri:
            SONG_REQUESTS.append({
                'id': REQUEST_ID_COUNTER,
                'artist': artist,
                'song': song,
                'uri': uri,
                'image_url': image_url,
                'status': 'pending'  # pending, imported, not_found
            })
            REQUEST_ID_COUNTER += 1
            flash('リクエストを受け付けました！', 'success')
        else:
            flash('曲を選択してください', 'error')
        return redirect(url_for('index'))
    
    # Show last 10 requests to avoid duplicates (optional visual cue)
    recent_requests = list(reversed(SONG_REQUESTS))[:10]
    return render_template('index.html', recent_requests=recent_requests)

@app.route('/admin')
def admin():
    token_info = session.get('token_info', None)
    is_logged_in = False
    if token_info:
        is_logged_in = True
    return render_template('admin.html', requests=SONG_REQUESTS, is_logged_in=is_logged_in)

@app.route('/login')
def login():
    sp_oauth = create_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/callback')
def callback():
    sp_oauth = create_spotify_oauth()
    session.clear()
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)
    session['token_info'] = token_info
    return redirect(url_for('admin'))

@app.route('/import', methods=['POST'])
def import_playlist():
    token_info = session.get('token_info', None)
    if not token_info:
        return redirect(url_for('login'))

    sp = spotipy.Spotify(auth=token_info['access_token'])
    user_id = sp.current_user()['id']
    
    # Create a new playlist
    playlist_name = "Imported Web Requests"
    playlist_description = "Collaborative playlist created from web requests"
    playlist = sp.user_playlist_create(user_id, playlist_name, public=True, description=playlist_description)
    playlist_id = playlist['id']

    track_uris = []
    log_messages = []

    for req in SONG_REQUESTS:
        if req['status'] == 'imported': # Skip already imported
            continue
            
        # If we have a URI, use it directly (from new search flow)
        if 'uri' in req and req['uri']:
             track_uris.append(req['uri'])
             req['status'] = 'imported'
             log_messages.append(f"Added: {req['artist']} - {req['song']}")
             continue

        # Fallback for old text-based requests (if any)
        query = f"artist:{req['artist']} track:{req['song']}"
        results = sp.search(q=query, type='track', limit=1)
        
        if results['tracks']['items']:
            track = results['tracks']['items'][0]
            track_uris.append(track['uri'])
            req['status'] = 'imported'
            log_messages.append(f"Found: {req['artist']} - {req['song']} -> {track['name']}")
        else:
            req['status'] = 'not_found'
            log_messages.append(f"Not Found: {req['artist']} - {req['song']}")

    if track_uris:
        # Spotify API allows max 100 tracks per request, simplistic implementation here
        sp.playlist_add_items(playlist_id, track_uris)
        flash(f"プレイリスト '{playlist_name}' に {len(track_uris)} 曲を追加しました！", 'success')
    else:
        flash("追加できる曲がありませんでした。", 'warning')

    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
