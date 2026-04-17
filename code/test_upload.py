import requests
import os

url = "https://puristic-filmily-bula.ngrok-free.dev/api/upload/single"
test_file = "test.mp3"  # Create a small test MP3 file first

# Create a small test MP3 if it doesn't exist
if not os.path.exists(test_file):
    # Download a sample MP3
    import urllib.request
    urllib.request.urlretrieve("https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3", test_file)

with open(test_file, 'rb') as f:
    response = requests.post(
        url,
        files={'file': (test_file, f, 'audio/mpeg')},
        data={
            'title': 'Test Song',
            'artist': 'Test Artist',
            'stem_type': 'Acapella',
            'bpm': 120,
            'key': 'C',
            'genre': 'Hip Hop'
        }
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")