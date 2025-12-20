# BandScan API

Unified API for the BandScan school band management app. Handles images, push notifications, device tokens, and operational data with SQLite storage and bearer token authentication.

## Features

- **Image Management**: Upload, retrieve, and organize inventory images with automatic thumbnailing
- **Push Notifications**: Send targeted notifications to students via FCM (Android) and APNs (iOS)
- **Device Tokens**: Register and manage student device tokens for push delivery
- **Student Requests**: Queue and process student data changes with Google Sheets integration
- **Offline Queue**: Automatic retry for failed operations

## Quick Start

### 1. Clone and configure

```bash
# If cloning the standalone repo
git clone https://github.com/rubano-enterprises/bandscan-api.git
cd bandscan-api

# Configure environment
cp .env.example .env
```

Edit `.env` with your settings:

```env
# Generate a secure token:
# python3 -c "import secrets; print(secrets.token_urlsafe(32))"
BANDSCAN_API_TOKEN=your-secure-token-here

# Your server's public URL (no trailing slash)
BASE_URL=https://api.yourdomain.com

# FCM for Android notifications
FCM_SERVER_KEY=your-fcm-server-key

# APNs for iOS notifications (optional - requires additional setup)
# APNS_KEY_ID=your-key-id
# APNS_TEAM_ID=your-team-id
# APNS_BUNDLE_ID=com.yourcompany.bandscan
# APNS_KEY_FILE=/data/AuthKey.p8
```

### 2. Start the service

```bash
docker-compose up -d
```

The API will be available at `http://localhost:8000`.

### 3. Verify it's running

```bash
curl http://localhost:8000/health
# {"status":"healthy","version":"2.0.0"}
```

## API Endpoints

All endpoints (except `/health`) require `Authorization: Bearer <token>` header.

### Health & Info
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check (no auth) |
| GET | `/` | API info and docs link |

### Images
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/items/{item_id}/images` | Upload image (multipart form) |
| GET | `/items/{item_id}/images` | List images for item |
| GET | `/images/{image_id}` | Get full image |
| GET | `/images/{image_id}/thumbnail` | Get thumbnail (300x300) |
| GET | `/images/{image_id}?width=800` | Get resized image |
| DELETE | `/images/{image_id}` | Delete image |
| PUT | `/items/{item_id}/images/order` | Reorder images |
| POST | `/items/{item_id}/images/{image_id}/primary` | Set primary image |

### Device Tokens
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/tokens/register` | Register device token for push |
| DELETE | `/tokens/{token}` | Unregister device token |
| POST | `/tokens/{token}/ping` | Update last_seen timestamp |

### Notifications
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/notifications/send` | Send notification to students |
| GET | `/notifications/{band_id}` | List notifications for band |
| GET | `/notifications/{band_id}/{notification_id}` | Get notification details |

### Students (Queue)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/students/requests` | Queue student data change |
| GET | `/students/queue/stats` | Get queue statistics |

## Usage Examples

### Upload an image

```bash
curl -X POST "http://localhost:8000/items/INV-123/images" \
  -H "Authorization: Bearer your-token" \
  -F "file=@photo.jpg" \
  -F "description=Front view"
```

### Register a device token

```bash
curl -X POST "http://localhost:8000/tokens/register" \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "student_uid": "12345",
    "band_id": "band1",
    "token": "fcm-or-apns-device-token",
    "platform": "android"
  }'
```

### Send a notification

```bash
curl -X POST "http://localhost:8000/notifications/send" \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "band_id": "band1",
    "sender_email": "admin@school.edu",
    "title": "Bus Departure",
    "body": "Please board Bus 3 now",
    "recipient_uids": ["12345", "67890", "11111"]
  }'
```

### List notifications

```bash
curl "http://localhost:8000/notifications/band1?limit=20&offset=0" \
  -H "Authorization: Bearer your-token"
```

## Data Storage

Data is persisted in a Docker volume (`bandscan_data`):

```
/data/
  images/       # Image files (sharded by ID prefix)
  database/     # SQLite database (bandscan.db)
```

### Database Schema

**images** - Inventory item photos
**student_requests_queue** - Queued Google Sheets updates
**device_tokens** - Student device tokens for push
**notifications** - Notification history

### Backup

```bash
# Create backup
docker run --rm -v bandscan-api_bandscan_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/bandscan-backup.tar.gz /data

# Restore backup
docker run --rm -v bandscan-api_bandscan_data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/bandscan-backup.tar.gz -C /
```

## Push Notification Setup

### Firebase Cloud Messaging (Android)

1. Go to [Firebase Console](https://console.firebase.google.com)
2. Create or select your project
3. Go to Project Settings > Cloud Messaging
4. Copy the "Server key" to `FCM_SERVER_KEY` in `.env`

### Apple Push Notifications (iOS)

1. Go to [Apple Developer](https://developer.apple.com/account/resources/authkeys/list)
2. Create a new key with "Apple Push Notifications service (APNs)" enabled
3. Download the `.p8` file and note the Key ID and Team ID
4. Mount the .p8 file to the container and set paths in `.env`

**Note**: APNs requires HTTP/2 and JWT authentication. Full implementation requires additional dependencies.

## Production Setup with Nginx

For HTTPS, use nginx as a reverse proxy:

```nginx
server {
    listen 443 ssl;
    server_name api.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    client_max_body_size 20M;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Flutter App Configuration

In your Flutter app, pass the API credentials via dart-define:

```bash
flutter run \
  --dart-define=BANDSCAN_API_URL=https://api.yourdomain.com \
  --dart-define=BANDSCAN_API_TOKEN=your-token
```

For release builds:

```bash
flutter build apk --release \
  --dart-define=BANDSCAN_API_URL=https://api.yourdomain.com \
  --dart-define=BANDSCAN_API_TOKEN=your-token
```

## Management Commands

```bash
# View logs
docker-compose logs -f

# Restart service
docker-compose restart

# Stop service
docker-compose down

# Update to latest
git pull
docker-compose build
docker-compose up -d
```

## Development

### Running locally without Docker

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### API Documentation

Once running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Troubleshooting

**Container won't start:**
```bash
docker-compose logs bandscan-api
```

**Permission errors:**
```bash
# Fix volume permissions
docker-compose down
docker volume rm bandscan-api_bandscan_data
docker-compose up -d
```

**Test authentication:**
```bash
curl -I "http://localhost:8000/items/test/images" \
  -H "Authorization: Bearer your-token"
# Should return 200, not 401
```

**Notifications not sending:**
- Check FCM_SERVER_KEY is correct
- Verify device tokens are registered
- Check logs: `docker-compose logs -f`

## Architecture

```
Flutter App (Student) → Register device token → BandScan API → SQLite
                                                      ↓
Flutter App (Admin) → Select students + compose → BandScan API
                                                      ↓
                                        Get tokens for students
                                                      ↓
                                    Send via FCM (Android) / APNs (iOS)
                                                      ↓
                                              Student Devices
```

## License

Proprietary - Rubano Enterprises
