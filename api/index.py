from http.server import BaseHTTPRequestHandler
import json

# Bu sınıf Vercel'in anlayacağı dildir.
class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        # 1. Başarılı (200 OK) kodu gönder
        self.send_response(200)
        
        # 2. Cevabın tipinin JSON olduğunu belirt (Header)
        self.send_header('Content-type', 'application/json')
        self.end_headers()

        # 3. Seninle tasarladığımız "İyi Tasarım" JSON verisi
        # (Şimdilik statik, yani 'Hardcoded')
        data = {
            "meta": {
                "message": "Bu veri Vercel üzerinden Python ile geliyor!",
                "status": "success"
            },
            "courses": [
                {
                    "id": "MAT101",
                    "name": "Matematik I",
                    "average": 85.0
                },
                {
                    "id": "FIZ101",
                    "name": "Fizik I",
                    "average": 70.5
                }
            ]
        }

        # 4. Veriyi JSON string'e çevirip gönder
        self.wfile.write(json.dumps(data).encode('utf-8'))
        return